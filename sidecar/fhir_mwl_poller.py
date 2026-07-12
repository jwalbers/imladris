"""
fhir_mwl_poller.py — Synthesizes DICOM MWL from AdvaPACS FHIR ServiceRequests.

Periodically queries AdvaPACS FHIR R5 for status=draft,active ServiceRequests and
writes one .wl file per order into the shared worklist folder.  When an order
leaves draft/active status (completed, cancelled) the corresponding .wl file is removed.

The study UID from the FHIR ServiceRequest (sent via ZDS in the original ORM)
is written into StudyInstanceUID so that the modality tags acquired DICOM with
the correct UID, linking it to the existing study in AdvaPACS.

Disabled automatically when FHIR_KEY_ID or FHIR_KEY_SECRET is unset.

Environment variables
---------------------
FHIR_BASE_URL       https://usa1.api.integration.advapacs.com/fhir/R5
FHIR_KEY_ID         AdvaPACS API key ID  (same credential as ADVAPACS_KEY_ID)
FHIR_KEY_SECRET     AdvaPACS API secret  (same credential as ADVAPACS_SECRET)
FHIR_POLL_SEC       30
WL_FOLDER           /worklist
MODALITY_AET        fallback AET when no per-modality AET is set
CR_AET / US_AET / CT_AET / MR_AET / RF_AET
"""

import logging
import os
import time

import httpx

from mwl_manager import MwlManager

log = logging.getLogger("fhir_mwl_poller")

FHIR_BASE_URL   = os.getenv("FHIR_BASE_URL",   "https://usa1.api.integration.advapacs.com/fhir/R5")
FHIR_KEY_ID     = os.getenv("FHIR_KEY_ID",     "")
FHIR_KEY_SECRET = os.getenv("FHIR_KEY_SECRET", "")
FHIR_POLL_SEC   = int(os.getenv("FHIR_POLL_SEC", "30"))
WL_FOLDER       = os.getenv("WL_FOLDER",        "/worklist")
MODALITY_AET    = os.getenv("MODALITY_AET",     "MODALITY_SIM")

_MODALITY_AET_MAP = {
    "CR": os.getenv("CR_AET", MODALITY_AET),
    "DX": os.getenv("CR_AET", MODALITY_AET),
    "US": os.getenv("US_AET", MODALITY_AET),
    "CT": os.getenv("CT_AET", MODALITY_AET),
    "MR": os.getenv("MR_AET", MODALITY_AET),
    "RF": os.getenv("RF_AET", MODALITY_AET),
}

# AdvaPACS may echo back our parameter's code ("modality") as the valueString
# instead of the value ("CR").  Fall back to AE title → modality when that happens.
_KNOWN_MODALITIES = frozenset(
    {"AR", "AS", "ASMT", "AU", "BDUS", "BI", "BMD", "CD", "CF", "CP", "CR",
     "CS", "CT", "CTPROTOCOL", "DD", "DF", "DG", "DM", "DS", "DX", "EC",
     "ECG", "EPS", "ES", "FA", "FID", "FS", "GM", "HC", "HD", "IO", "IVOCT",
     "IVUS", "KER", "KO", "LEN", "LS", "MG", "MR", "MS", "NM", "OAM", "OCT",
     "OP", "OPM", "OPR", "OPT", "OPV", "OSS", "OT", "PLAN", "PR", "PT",
     "PX", "REG", "RESP", "RF", "RG", "RTDOSE", "RTIMAGE", "RTPLAN",
     "RTRECORD", "RTSTRUCT", "RWV", "SEG", "SM", "SMR", "SR", "SRF", "ST",
     "STAIN", "TG", "US", "VA", "XA", "XC"}
)
_AET_TO_MODALITY = {
    "IML_CR_01": "CR",
    "IML_US_01": "US",
    "IML_CT_01": "CT",
    "IML_MR_01": "MR",
    "IML_RF_01": "RF",
}


def _aet_for(modality: str) -> str:
    return _MODALITY_AET_MAP.get(modality.upper(), MODALITY_AET)


# Keyword→modality fallback for when AdvaPACS returns no usable modality code
# and there is no station AET to map from (e.g. orders with no performer).
_MODALITY_KEYWORDS = [
    ("ultrasound", "US"), ("echo", "US"),
    ("ct ",        "CT"), (" ct", "CT"), ("computed", "CT"),
    ("mri",        "MR"), ("magnetic", "MR"),
    ("fluoro",     "RF"),
    ("nuclear",    "NM"),
]

def _guess_modality(text: str) -> str:
    t = text.lower()
    for kw, code in _MODALITY_KEYWORDS:
        if kw in t:
            return code
    return "CR"  # default for unmatched radiology orders


def _auth_headers() -> dict:
    return {
        "Authorization": f"ID={FHIR_KEY_ID},Secret={FHIR_KEY_SECRET}",
        "Accept": "application/fhir+json",
    }


def _fetch_resource(client: httpx.Client, ref: str) -> dict:
    """GET any FHIR resource by relative reference (e.g. 'Patient/uuid')."""
    try:
        url = f"{FHIR_BASE_URL.rstrip('/')}/{ref}"
        r = client.get(url, headers=_auth_headers(), timeout=10)
        if r.status_code == 200:
            return r.json()
        log.debug(f"FHIR GET {ref}: HTTP {r.status_code}")
    except Exception as e:
        log.debug(f"FHIR GET {ref}: {e}")
    return {}


def _extract_station_aet(device: dict) -> str:
    """Extract DICOM Station AE Title from a FHIR Device resource.

    AdvaPACS encodes the AE title as an identifier with DICOM code 110119
    ('Station AE Title') from the DICOM ontology system.
    """
    for ident in device.get("identifier", []):
        codings = ident.get("type", {}).get("coding", [])
        if any(c.get("code") == "110119" for c in codings):
            return ident.get("value", "")
    return ""


def _parse_patient(resource: dict) -> tuple[str, str, str, str]:
    """Return (patient_id, patient_name, dob_yyyymmdd, sex_dicom) from FHIR Patient."""
    # Patient ID from first non-empty identifier
    patient_id = ""
    for ident in resource.get("identifier", []):
        val = ident.get("value", "")
        if val:
            patient_id = val
            break
    if not patient_id:
        patient_id = resource.get("id", "UNKNOWN")

    # Name: FHIR name[0] → DICOM Family^Given
    patient_name = ""
    for name in resource.get("name", []):
        family = name.get("family", "")
        given  = (name.get("given") or [""])[0]
        if family or given:
            patient_name = f"{family}^{given}".strip("^")
            break

    # DOB: "1986-01-01" → "19860101"
    dob = resource.get("birthDate", "").replace("-", "")[:8]

    # Sex: FHIR "male"/"female" → DICOM "M"/"F"
    sex = {"male": "M", "female": "F", "other": "O"}.get(
        resource.get("gender", "").lower(), "U"
    )

    return patient_id, patient_name, dob, sex


def _poll_once(
    client: httpx.Client,
    mwl: MwlManager,
    owned: set[str],
) -> set[str]:
    """
    Reconcile FHIR draft orders with the worklist folder.

    owned  — accession numbers of .wl files created by this poller in prior runs.
    Returns the updated owned set.
    """
    url = f"{FHIR_BASE_URL.rstrip('/')}/ServiceRequest"
    try:
        r = client.get(url, params={"status": "draft,active", "_count": "200"},
                       headers=_auth_headers(), timeout=15)
        if r.status_code != 200:
            log.error(f"FHIR query failed: HTTP {r.status_code}: {r.text[:200]}")
            return owned
    except Exception as e:
        log.error(f"FHIR query exception: {e}")
        return owned

    entries = r.json().get("entry", [])
    current: set[str] = set()
    patient_cache: dict[str, dict] = {}
    device_cache:  dict[str, dict] = {}

    for entry in entries:
        sr = entry.get("resource", {})

        # Accession (ACSN identifier) and study UID (urn:dicom:uid identifier)
        accession = ""
        study_uid = ""
        for ident in sr.get("identifier", []):
            if ident.get("system") == "urn:dicom:uid":
                study_uid = ident.get("value", "").removeprefix("urn:oid:")
            else:
                type_code = (ident.get("type", {}).get("coding", [{}])[0]
                             .get("code", ""))
                if type_code == "ACSN":
                    accession = ident.get("value", "")

        if not accession:
            continue
        if not study_uid:
            log.debug(f"Skipping {accession} — no study UID (pre-ZDS order)")
            continue

        current.add(accession)

        # Station AE Title — fetch Device first so we can fall back for modality.
        device_ref = (sr.get("performer") or [{}])[0].get("reference", "")
        if device_ref and device_ref not in device_cache:
            device_cache[device_ref] = _fetch_resource(client, device_ref)
        station_aet = _extract_station_aet(device_cache.get(device_ref, {}))

        # Procedure description — extracted early so modality can fall back to it.
        # AdvaPACS may not preserve concept.coding[0].display for externally-posted SRs.
        proc_desc = (
            sr.get("code", {}).get("concept", {}).get("coding", [{}])[0].get("display", "")
            or sr.get("code", {}).get("concept", {}).get("text", "")
            or sr.get("code", {}).get("text", "")
            or "Radiology Procedure"
        )

        # Modality: orderDetail parameter first; fall back to AE-title map, then
        # procedure text. AdvaPACS may echo the parameter code name ("modality")
        # as the valueString instead of the value ("CR").
        modality = ""
        for od in sr.get("orderDetail", []):
            for p in od.get("parameter", []):
                if any(c.get("code") == "modality"
                       for c in p.get("code", {}).get("coding", [])):
                    modality = p.get("valueString", "")
        if modality not in _KNOWN_MODALITIES:
            modality = _AET_TO_MODALITY.get(station_aet, "")
        if not modality:
            modality = _guess_modality(proc_desc)
            log.debug(f"Modality guessed from procedure text for {accession}: {modality}")

        if not station_aet:
            station_aet = _aet_for(modality)

        # Patient demographics (fetch once per unique Patient reference)
        subj_ref = sr.get("subject", {}).get("reference", "")
        if subj_ref and subj_ref not in patient_cache:
            patient_cache[subj_ref] = _fetch_resource(client, subj_ref)
        patient_id, patient_name, dob, sex = _parse_patient(
            patient_cache.get(subj_ref, {})
        )
        if not patient_id:
            patient_id = subj_ref.split("/")[-1]   # fallback: FHIR UUID

        # Scheduled date/time: prefer occurrenceDateTime, fall back to authoredOn
        scheduled_date = scheduled_time = None
        occurrence = sr.get("occurrenceDateTime", "") or sr.get("authoredOn", "")
        if occurrence:
            clean = (occurrence.replace("-", "").replace(":", "")
                               .replace("T", "").split("+")[0].split("Z")[0])
            scheduled_date = clean[:8]  if len(clean) >= 8  else None
            scheduled_time = clean[8:14] if len(clean) >= 14 else None

        log.info(f"MWL ← FHIR: {accession}  {modality}  station={station_aet}  "
                 f"patient={patient_id}  {proc_desc}")
        mwl.create(
            patient_id=patient_id,
            patient_name=patient_name,
            dob=dob,
            sex=sex,
            accession=accession,
            procedure_id=accession,
            procedure_desc=proc_desc,
            modality=modality,
            scheduled_date=scheduled_date,
            scheduled_time=scheduled_time,
            station_aet=station_aet,
            study_uid=study_uid,
        )

    # Remove .wl files for orders we own that are no longer draft or active
    for acc in owned - current:
        log.info(f"FHIR order no longer draft/active — removing MWL: {acc}")
        mwl.delete(acc)

    if current != owned:
        log.info(f"FHIR MWL: {len(current)} active orders "
                 f"(+{len(current-owned)} added, -{len(owned-current)} removed)")

    return current


def main():
    if not FHIR_KEY_ID or not FHIR_KEY_SECRET:
        log.info("FHIR_KEY_ID/FHIR_KEY_SECRET not set — FHIR MWL poller disabled")
        return

    log.info(f"FHIR MWL poller starting  base={FHIR_BASE_URL}  interval={FHIR_POLL_SEC}s")
    mwl = MwlManager(WL_FOLDER, station_aet=MODALITY_AET)
    # Seed from any .wl files already on disk so orphans from previous sessions
    # are cleaned up on the first poll if they're no longer draft in AdvaPACS.
    owned: set[str] = set(mwl.list_accessions())
    if owned:
        log.info(f"Seeded {len(owned)} existing .wl file(s) into reconciliation set")

    with httpx.Client(follow_redirects=True) as client:
        while True:
            try:
                owned = _poll_once(client, mwl, owned)
            except Exception as e:
                log.error(f"FHIR poll iteration error: {e}", exc_info=True)
            time.sleep(FHIR_POLL_SEC)
