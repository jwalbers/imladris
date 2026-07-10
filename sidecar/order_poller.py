"""
order_poller.py — Polls OpenMRS REST API for new radiology orders,
                  creates them in AdvaPACS via FHIR R5 ServiceRequest POST.

Staff review orders in the AdvaPACS console and assign them to a station
(IML_CR_01, IML_US_01, IML_CT_01).  The FHIR MWL poller (fhir_mwl_poller.py)
then picks up the assigned orders and writes the per-modality .wl files.

State (last-seen timestamp) is persisted to ORDER_STATE_FILE so restarts do
not replay already-processed orders.

Environment variables
---------------------
OPENMRS_URL               http://openmrs:8080/openmrs
OPENMRS_USER              admin
OPENMRS_PASSWORD          Admin123
RADIOLOGY_ORDER_TYPE_UUID blank = auto-discovered from /ws/rest/v1/ordertype
ORDER_STATE_FILE          /data/order_poller_state.json
ORDER_POLL_SEC            30
FHIR_BASE_URL             https://usa1.api.integration.advapacs.com/fhir/R5
FHIR_KEY_ID               (AdvaPACS API key ID)
FHIR_KEY_SECRET           (AdvaPACS API key secret)
"""

import datetime
import json
import logging
import os
import time
from datetime import timezone
from pathlib import Path

import httpx
import pydicom.uid
import requests

log = logging.getLogger("order_poller")

# ── Configuration ─────────────────────────────────────────────────────

OPENMRS_URL      = os.getenv("OPENMRS_URL",      "http://openmrs:8080/openmrs")
OPENMRS_USER     = os.getenv("OPENMRS_USER",     "admin")
OPENMRS_PASSWORD = os.getenv("OPENMRS_PASSWORD", "Admin123")

_ORDER_TYPE_UUID_ENV = os.getenv("RADIOLOGY_ORDER_TYPE_UUID", "")

ORDER_STATE_FILE = os.getenv("ORDER_STATE_FILE", "/data/order_poller_state.json")
ORDER_POLL_SEC   = int(os.getenv("ORDER_POLL_SEC", "30"))

FHIR_BASE_URL    = os.getenv("FHIR_BASE_URL",
                              "https://usa1.api.integration.advapacs.com/fhir/R5")
FHIR_KEY_ID      = os.getenv("FHIR_KEY_ID",     "")
FHIR_KEY_SECRET  = os.getenv("FHIR_KEY_SECRET", "")

# Concept name keywords → DICOM modality code
_MODALITY_MAP = [
    ("ultrasound", "US"), ("echo", "US"), ("(us)", "US"),
    ("ct ",        "CT"), (" ct", "CT"), ("(ct)", "CT"), ("computed", "CT"),
    ("mri",        "MR"), ("magnetic", "MR"), ("(mr)", "MR"),
    ("fluoro",     "RF"),
    ("nuclear",    "NM"),
]
_MODALITY_DEFAULT = "CR"


def _guess_modality(concept_name: str) -> str:
    name = concept_name.lower()
    for keyword, code in _MODALITY_MAP:
        if keyword in name:
            return code
    return _MODALITY_DEFAULT


# AE title → FHIR Device UUID cache (populated lazily)
_device_uuid_cache: dict[str, str] = {}

# Modality → AE title (mirrors fhir_mwl_poller; drives performer lookup)
_MODALITY_AET: dict[str, str] = {
    "CR": os.getenv("CR_AET", "IML_CR_01"),
    "DX": os.getenv("CR_AET", "IML_CR_01"),
    "US": os.getenv("US_AET", "IML_US_01"),
    "CT": os.getenv("CT_AET", "IML_CT_01"),
    "MR": os.getenv("MR_AET", "IML_CR_01"),
    "RF": os.getenv("RF_AET", "IML_CR_01"),
}


# ── FHIR helpers ──────────────────────────────────────────────────────

def _fhir_headers() -> dict:
    return {
        "Authorization": f"ID={FHIR_KEY_ID},Secret={FHIR_KEY_SECRET}",
        "Accept":        "application/fhir+json",
        "Content-Type":  "application/fhir+json",
    }


def _find_device_uuid(client: httpx.Client, ae_title: str) -> str:
    """Return AdvaPACS Device UUID for the given AE title, or '' if not found."""
    if ae_title in _device_uuid_cache:
        return _device_uuid_cache[ae_title]
    try:
        r = client.get(f"{FHIR_BASE_URL}/Device",
                       params={"identifier": ae_title},
                       headers=_fhir_headers(), timeout=10)
        if r.status_code == 200:
            for entry in r.json().get("entry", []):
                _device_uuid_cache[ae_title] = entry["resource"]["id"]
                return _device_uuid_cache[ae_title]
    except Exception as e:
        log.debug(f"Device lookup failed for {ae_title}: {e}")
    return ""


def _find_or_create_patient(
    client: httpx.Client,
    patient_id: str,
    patient_name: str,   # HL7 family^given
    dob: str,            # YYYYMMDD
    sex: str,            # M/F/U
    cache: dict,
) -> str | None:
    """Return AdvaPACS Patient UUID, creating the Patient if needed."""
    if patient_id in cache:
        return cache[patient_id]

    # Search by OpenMRS identifier
    r = client.get(f"{FHIR_BASE_URL}/Patient",
                   params={"identifier": patient_id}, timeout=10)
    if r.status_code == 200:
        entries = r.json().get("entry", [])
        if entries:
            uuid = entries[0]["resource"]["id"]
            cache[patient_id] = uuid
            return uuid

    # Build FHIR R5 Patient
    parts = patient_name.split("^", 1)
    family = parts[0].strip()
    given  = [parts[1].strip()] if len(parts) > 1 and parts[1].strip() else []

    gender_map = {"M": "male", "F": "female"}
    gender = gender_map.get(sex.upper(), "unknown")

    birth_date = ""
    if len(dob) == 8 and dob.isdigit():
        birth_date = f"{dob[:4]}-{dob[4:6]}-{dob[6:]}"

    resource: dict = {
        "resourceType": "Patient",
        "identifier": [{"system": "http://openmrs.org/identifier", "value": patient_id}],
        "name":        [{"family": family, "given": given}],
        "gender":      gender,
    }
    if birth_date:
        resource["birthDate"] = birth_date

    r2 = client.post(f"{FHIR_BASE_URL}/Patient", json=resource, timeout=10)
    if r2.status_code in (200, 201):
        uuid = r2.json().get("id", "")
        if uuid:
            cache[patient_id] = uuid
            log.info(f"Created AdvaPACS Patient: {patient_name}  id={patient_id}  uuid={uuid}")
            return uuid
    log.warning(f"Could not create Patient {patient_id}: HTTP {r2.status_code}  {r2.text[:200]}")
    return None


def _service_request_exists(client: httpx.Client, accession: str) -> bool:
    """True if AdvaPACS already has a ServiceRequest with this accession."""
    r = client.get(f"{FHIR_BASE_URL}/ServiceRequest",
                   params={"identifier": accession}, timeout=10)
    if r.status_code == 200:
        return bool(r.json().get("entry"))
    return False


def _post_service_request(
    client: httpx.Client,
    patient_uuid: str,
    accession: str,
    procedure_desc: str,
    modality: str,
    study_uid: str,
    device_uuid: str = "",
    concept_uuid: str = "",
    occurrence: str = "",
) -> bool:
    """POST a new ServiceRequest to AdvaPACS.  Returns True on success."""
    import json as _json
    import re as _re
    from datetime import datetime, timezone

    proc_code = concept_uuid or procedure_desc.replace(" ", "_").upper()
    # OpenMRS timestamps arrive as "2026-07-10T05:35:02.000+0000"; FHIR R5 needs "+00:00"
    _raw = occurrence or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    _raw = _re.sub(r'\.\d+', '', _raw)                          # strip fractional seconds
    occurrence_dt = _re.sub(r'([+-])(\d{2})(\d{2})$', r'\1\2:\3', _raw)  # +HHMM → +HH:MM

    resource: dict = {
        "resourceType": "ServiceRequest",
        "status":  "draft",
        "intent":  "order",
        "subject": {"reference": f"Patient/{patient_uuid}"},
        "code": {
            "concept": {
                "coding": [{
                    "system":  "http://openmrs.org/concept",
                    "code":    proc_code,
                    "display": procedure_desc,
                }],
                "text": procedure_desc,
            }
        },
        "occurrenceDateTime": occurrence_dt,
        "orderDetail": [{
            "parameter": [{
                "code": {
                    "coding": [{
                        "system": "http://advapacs.com/fhir/servicerequest-orderdetail-parameter-code",
                        "code":   "modality",
                    }]
                },
                "valueString": modality,
            }]
        }],
        "identifier": [
            {
                "system": "http://imladrislab.org/accession-number",
                "type": {
                    "coding": [{
                        "system": "http://terminology.hl7.org/CodeSystem/v2-0203",
                        "code":   "ACSN",
                    }]
                },
                "value": accession,
            },
            {
                "system": "urn:dicom:uid",
                "value":  f"urn:oid:{study_uid}",
            },
        ],
    }

    if device_uuid:
        resource["performer"] = [{"reference": f"Device/{device_uuid}"}]

    log.debug(f"POST ServiceRequest body: {_json.dumps(resource)}")
    r = client.post(f"{FHIR_BASE_URL}/ServiceRequest", json=resource, timeout=15)
    if r.status_code in (200, 201):
        sr_id = r.json().get("id", "")
        log.info(
            f"ServiceRequest created: accession={accession}  {modality}  "
            f"{procedure_desc}  fhir_id={sr_id}"
        )
        return True
    log.warning(
        f"ServiceRequest POST failed for {accession}: "
        f"HTTP {r.status_code}  {r.text[:300]}"
    )
    return False


def _revoke_service_request(client: httpx.Client, accession: str) -> bool:
    """Set an existing ServiceRequest to 'revoked' (cancelled order)."""
    r = client.get(f"{FHIR_BASE_URL}/ServiceRequest",
                   params={"identifier": accession}, timeout=10)
    if r.status_code != 200:
        return False
    entries = r.json().get("entry", [])
    if not entries:
        log.debug(f"No ServiceRequest found to revoke for accession={accession}")
        return False

    sr_id = entries[0]["resource"]["id"]
    patch = [{"op": "replace", "path": "/status", "value": "revoked"}]
    r2 = client.patch(
        f"{FHIR_BASE_URL}/ServiceRequest/{sr_id}",
        content=json.dumps(patch),
        headers={"Content-Type": "application/json-patch+json"},
        timeout=10,
    )
    ok = r2.status_code in (200, 201)
    if ok:
        log.info(f"ServiceRequest revoked: accession={accession}  fhir_id={sr_id}")
    else:
        log.warning(f"Revoke failed for {accession}: HTTP {r2.status_code}  {r2.text[:200]}")
    return ok


# ── OpenMRS REST helpers ──────────────────────────────────────────────

def _session() -> requests.Session:
    s = requests.Session()
    s.auth = (OPENMRS_USER, OPENMRS_PASSWORD)
    s.headers["Accept"] = "application/json"
    return s


def _lookup_radiology_order_type(sess: requests.Session) -> str:
    r = sess.get(f"{OPENMRS_URL}/ws/rest/v1/ordertype",
                 params={"v": "full"}, timeout=10)
    r.raise_for_status()
    for ot in r.json().get("results", []):
        if "radiology" in ot.get("name", "").lower():
            uuid = ot["uuid"]
            log.info(f"Found radiology order type: '{ot['name']}'  uuid={uuid}")
            return uuid
    for ot in r.json().get("results", []):
        if "test" in ot.get("name", "").lower():
            uuid = ot["uuid"]
            log.warning(f"No 'Radiology' order type; falling back to '{ot['name']}'  uuid={uuid}")
            return uuid
    raise RuntimeError("Cannot find a radiology or test order type in OpenMRS")


# ── State persistence ─────────────────────────────────────────────────

def _load_state() -> dict:
    path = Path(ORDER_STATE_FILE)
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            pass
    return {}


def _save_state(state: dict):
    path = Path(ORDER_STATE_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2))


# ── Patient info helpers ──────────────────────────────────────────────

def _fetch_patient_full(sess: requests.Session, patient_uuid: str) -> dict:
    try:
        r = sess.get(f"{OPENMRS_URL}/ws/rest/v1/patient/{patient_uuid}",
                     params={"v": "full"}, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log.warning(f"Could not fetch patient {patient_uuid}: {e}")
        return {}


def _extract_patient_info(
    patient: dict, sess: requests.Session | None = None
) -> tuple[str, str, str, str]:
    """Return (patient_id, patient_name, dob, sex) from an OpenMRS patient dict."""
    display = patient.get("display", "")

    patient_id = ""
    for ident in (patient.get("identifiers") or []):
        if not ident.get("voided", False):
            patient_id = ident.get("identifier", "")
            break
    if not patient_id:
        patient_id = display.split(" - ")[0].strip() if " - " in display else display

    person = patient.get("person") or {}
    full_name = person.get("display", "")

    if not full_name and " - " in display:
        name_part = display.split(" - ", 1)[1].strip()
        if "," in name_part:
            last, first = name_part.split(",", 1)
            full_name = f"{last.strip()}^{first.strip()}"
        else:
            full_name = name_part

    if full_name and "^" not in full_name:
        parts = full_name.strip().split()
        if len(parts) >= 2:
            full_name = f"{parts[-1]}^{' '.join(parts[:-1])}"

    dob = person.get("birthdate", "") or ""
    sex = person.get("gender", "") or ""

    if (not dob or not sex) and sess and patient.get("uuid"):
        full = _fetch_patient_full(sess, patient["uuid"])
        sub = full.get("person") or {}
        dob = dob or sub.get("birthdate", "") or ""
        sex = sex or sub.get("gender", "") or ""

    dob = dob.replace("-", "")[:8]
    sex = sex.upper() or "U"

    return patient_id, full_name, dob, sex


# ── Order processing ──────────────────────────────────────────────────

def _process_order(
    order: dict,
    fhir_client: httpx.Client,
    patient_cache: dict,
    sess: requests.Session | None = None,
) -> bool:
    """Process one OpenMRS order. Returns True on success or skip, False on failure."""
    action    = (order.get("action") or "NEW").upper()
    accession = order.get("accessionNumber") or order.get("uuid", "")
    # DICOM SH (AccessionNumber) is max 16 chars; truncate UUID fallbacks to match.
    accession = accession.replace("-", "")[:16]
    if not accession:
        log.warning("Order has no accessionNumber — skipping")
        return True

    if action == "DISCONTINUE":
        _revoke_service_request(fhir_client, accession)
        return True

    if _service_request_exists(fhir_client, accession):
        log.debug(f"ServiceRequest already exists for accession={accession} — skipping")
        return True

    patient = order.get("patient") or {}
    patient_id, patient_name, dob, sex = _extract_patient_info(patient, sess)

    concept        = order.get("concept") or {}
    procedure_desc = concept.get("display") or "Radiology Procedure"
    concept_uuid   = concept.get("uuid", "")
    modality       = _guess_modality(procedure_desc)
    study_uid      = pydicom.uid.generate_uid()
    occurrence     = order.get("dateActivated", "")

    patient_uuid = _find_or_create_patient(
        fhir_client, patient_id, patient_name, dob, sex, patient_cache
    )
    if not patient_uuid:
        log.error(f"Cannot post order {accession}: no AdvaPACS Patient UUID")
        return False

    ae_title    = _MODALITY_AET.get(modality, "")
    device_uuid = _find_device_uuid(fhir_client, ae_title) if ae_title else ""

    return _post_service_request(
        fhir_client, patient_uuid, accession, procedure_desc, modality, study_uid,
        device_uuid=device_uuid,
        concept_uuid=concept_uuid,
        occurrence=occurrence,
    )


def _poll_once(
    sess: requests.Session,
    fhir_client: httpx.Client,
    order_type_uuid: str,
    state: dict,
) -> dict:
    last_polled = state.get("last_polled")

    params: dict = {"v": "full", "limit": 100}
    if last_polled:
        params["activatedOnOrAfterDate"] = last_polled
    else:
        from datetime import timedelta
        cutoff = (datetime.datetime.now(timezone.utc) - timedelta(hours=24)).strftime(
            "%Y-%m-%dT%H:%M:%S.000%z"
        )
        params["activatedOnOrAfterDate"] = cutoff

    try:
        r = sess.get(f"{OPENMRS_URL}/ws/rest/v1/order", params=params, timeout=15)
        r.raise_for_status()
    except requests.RequestException as e:
        log.error(f"OpenMRS REST poll failed: {e}")
        return state

    all_orders = r.json().get("results", [])
    orders = [
        o for o in all_orders
        if (o.get("orderType") or {}).get("uuid") == order_type_uuid
    ]
    if len(all_orders) != len(orders):
        log.debug(f"Filtered {len(all_orders)} total → {len(orders)} radiology orders")

    patient_cache: dict = {}
    max_activated = None
    # Accessions that have failed too many times — skip and record in state.
    # Keyed by accession; value is consecutive failure count.
    fail_counts: dict = state.get("fail_counts", {})
    MAX_FAILURES = 3

    for order in orders:
        date_activated = order.get("dateActivated") or ""
        accession = order.get("accessionNumber") or order.get("uuid", "")

        if order.get("dateStopped"):
            log.debug(f"Skipping stopped order {order.get('uuid')}")
        elif accession and fail_counts.get(accession, 0) >= MAX_FAILURES:
            log.debug(f"Skipping {accession} — {fail_counts[accession]} consecutive failures")
        else:
            try:
                ok = _process_order(order, fhir_client, patient_cache, sess)
            except Exception as e:
                log.error(f"Failed to process order {order.get('uuid')}: {e}", exc_info=True)
                ok = False
            if ok:
                if accession in fail_counts:
                    del fail_counts[accession]
            else:
                fail_counts[accession] = fail_counts.get(accession, 0) + 1
                if fail_counts[accession] >= MAX_FAILURES:
                    log.warning(
                        f"Order {accession} failed {MAX_FAILURES} times — "
                        f"skipping until removed from state fail_counts."
                    )

        if date_activated and (max_activated is None or date_activated > max_activated):
            max_activated = date_activated

    state["fail_counts"] = fail_counts

    # Always advance the watermark when we saw orders, even if max_activated
    # equals last_polled — prevents infinite retry of same-timestamp orders.
    if max_activated:
        try:
            from datetime import timedelta
            dt = datetime.datetime.fromisoformat(max_activated.replace("Z", "+00:00"))
            dt += datetime.timedelta(seconds=1)
            state["last_polled"] = dt.isoformat()
        except Exception:
            state["last_polled"] = max_activated
    _save_state(state)

    return state


# ── Main loop ─────────────────────────────────────────────────────────

def main():
    if not FHIR_KEY_ID or not FHIR_KEY_SECRET:
        log.warning(
            "FHIR_KEY_ID / FHIR_KEY_SECRET not set — order poller disabled"
        )
        return

    log.info(
        f"Order poller starting  openmrs={OPENMRS_URL}  "
        f"fhir={FHIR_BASE_URL}  poll_interval={ORDER_POLL_SEC}s"
    )

    omrs_sess = _session()

    order_type_uuid = _ORDER_TYPE_UUID_ENV
    if not order_type_uuid:
        attempt = 0
        while not order_type_uuid:
            attempt += 1
            try:
                order_type_uuid = _lookup_radiology_order_type(omrs_sess)
            except Exception as e:
                log.warning(f"Order type lookup failed (attempt {attempt}), retrying in 15s: {e}")
                time.sleep(15)

    state = _load_state()
    log.info(f"Resuming from last_polled={state.get('last_polled', 'beginning')}")

    with httpx.Client(headers=_fhir_headers(), follow_redirects=True) as fhir_client:
        while True:
            state = _poll_once(omrs_sess, fhir_client, order_type_uuid, state)
            time.sleep(ORDER_POLL_SEC)
