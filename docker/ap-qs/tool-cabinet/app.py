"""
tool-cabinet — Imladris Lab Tool Cabinet
Network Connectivity Simulator: controls outbound iptables rules to simulate
WAN outages to AdvaPACS cloud while the gateway remains fully running.

Requires:
  network_mode: host   (shares WSL2 root netns with advapacs-gw)
  cap_add: [NET_ADMIN] (permission to run iptables)
  /var/run/docker.sock (read container status)
"""

import asyncio
import datetime
import io
import ipaddress
import json
import logging
import os
import socket
import subprocess
import threading
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path

import docker
import httpx
import pydicom
from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

logging.getLogger("pynetdicom").setLevel(logging.WARNING)
log = logging.getLogger("tool_cabinet")
log.setLevel(logging.INFO)
if not log.handlers:
    _h = logging.StreamHandler()
    _h.setLevel(logging.INFO)
    _h.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-8s  %(message)s"))
    log.addHandler(_h)
    log.propagate = False

PACS_URL         = os.getenv("PACS_URL", "http://localhost:8043")
PACS_USER        = os.getenv("PACS_USER", "admin")
PACS_PASSWORD    = os.getenv("PACS_PASSWORD", "admin")
GATEWAY_CONTAINER = os.getenv("GATEWAY_CONTAINER", "imladris-advapacs-gw")
ADVAPACS_HOSTS   = [h.strip() for h in os.getenv(
    "ADVAPACS_HOSTS", "usa1.api.dicomweb.advapacs.com"
).split(",") if h.strip()]

FHIR_BASE_URL    = os.getenv("FHIR_BASE_URL", "https://usa1.api.integration.advapacs.com/fhir/R5")
FHIR_KEY_ID      = os.getenv("FHIR_KEY_ID", "")
FHIR_KEY_SECRET  = os.getenv("FHIR_KEY_SECRET", "")

DICOM_GW_HOST    = os.getenv("DICOM_GW_HOST",    "localhost")
DICOM_GW_PORT    = int(os.getenv("DICOM_GW_PORT", "11112"))
DICOM_GW_AE      = os.getenv("DICOM_GW_AE",      "ADVAPACS_GW_01")
DICOM_CALLING_AE = os.getenv("DICOM_CALLING_AE", "IML_CR_01")
DICOM_TOOLS_AE   = os.getenv("DICOM_TOOLS_AE",   "IML_TOOLS")

_profile: str = "online"
_blocked_ips: set[str] = set()

# ── Models ────────────────────────────────────────────────────────────────────

class ServiceRequestInput(BaseModel):
    patient_id:     str = "XP92EU"
    patient_name:   str = "Lethabo^Tau"   # family^given
    dob:            str = "19860101"       # YYYYMMDD
    sex:            str = "M"             # M/F/U
    procedure_desc: str = "X-ray of apical lordotic chest"
    modality:       str = "CR"
    accession:      str = ""              # blank = auto-generate
    fhir_base:      str = FHIR_BASE_URL
    key_id:         str = FHIR_KEY_ID
    key_secret:     str = FHIR_KEY_SECRET


class FhirOrdersRequest(BaseModel):
    fhir_base:   str = FHIR_BASE_URL
    key_id:      str = FHIR_KEY_ID
    key_secret:  str = FHIR_KEY_SECRET
    status:      str = "draft"    # draft = scheduled (pre-acquisition) in AdvaPACS
    modality:    str = ""         # blank = all modalities


class DeleteStudiesRequest(BaseModel):
    patient_id:  str = ""          # delete all studies for this patient
    accession:   str = ""          # or delete the single study with this accession
    dry_run:     bool = True
    fhir_base:   str = FHIR_BASE_URL
    key_id:      str = FHIR_KEY_ID
    key_secret:  str = FHIR_KEY_SECRET


class DeleteOrdersRequest(BaseModel):
    patient_id:  str = ""          # delete all orders for this patient
    accession:   str = ""          # or delete the single order with this accession
    dry_run:     bool = True
    fhir_base:   str = FHIR_BASE_URL
    key_id:      str = FHIR_KEY_ID
    key_secret:  str = FHIR_KEY_SECRET


class MwlQueryRequest(BaseModel):
    host:       str = DICOM_GW_HOST
    port:       int = DICOM_GW_PORT
    called_ae:  str = DICOM_GW_AE
    calling_ae: str = DICOM_CALLING_AE
    modality:   str = ""   # blank = all modalities


# ── FHIR helpers ─────────────────────────────────────────────────────────────

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


def _extract_station_aet(device: dict) -> str:
    """Extract DICOM Station AE Title (code 110119) from a FHIR Device resource."""
    for ident in device.get("identifier", []):
        if any(c.get("code") == "110119"
               for c in ident.get("type", {}).get("coding", [])):
            return ident.get("value", "")
    return ""


# ── FHIR ServiceRequest sender ────────────────────────────────────────────────

def _post_service_request(req: ServiceRequestInput) -> dict:
    base       = (req.fhir_base or FHIR_BASE_URL).rstrip("/")
    key_id     = req.key_id     or FHIR_KEY_ID
    key_secret = req.key_secret or FHIR_KEY_SECRET
    headers = {
        "Authorization": f"ID={key_id},Secret={key_secret}",
        "Accept":        "application/fhir+json",
        "Content-Type":  "application/fhir+json",
    }

    ts        = datetime.datetime.now().strftime("%m%d%H%M%S")
    accession = req.accession or f"TC-{ts}"
    study_uid = pydicom.uid.generate_uid()

    # ── Find or create Patient ──────────────────────────────────────────
    patient_uuid = None
    try:
        r = httpx.get(f"{base}/Patient", params={"identifier": req.patient_id},
                      headers=headers, timeout=10, follow_redirects=True)
        entries = r.json().get("entry", []) if r.status_code == 200 else []
        if entries:
            patient_uuid = entries[0]["resource"]["id"]
        else:
            parts  = req.patient_name.split("^", 1)
            family = parts[0].strip()
            given  = [parts[1].strip()] if len(parts) > 1 and parts[1].strip() else []
            gender = {"M": "male", "F": "female"}.get(req.sex.upper(), "unknown")
            dob    = req.dob
            birth  = f"{dob[:4]}-{dob[4:6]}-{dob[6:]}" if len(dob) == 8 else ""
            pt = {
                "resourceType": "Patient",
                "identifier":   [{"system": "http://openmrs.org/identifier", "value": req.patient_id}],
                "name":         [{"family": family, "given": given}],
                "gender":       gender,
            }
            if birth:
                pt["birthDate"] = birth
            r2 = httpx.post(f"{base}/Patient", json=pt, headers=headers,
                            timeout=10, follow_redirects=True)
            if r2.status_code in (200, 201):
                patient_uuid = r2.json().get("id")
            else:
                return {"ok": False, "error": f"Patient create failed: HTTP {r2.status_code}  {r2.text[:200]}"}
    except Exception as e:
        return {"ok": False, "error": f"Patient lookup/create error: {e}"}

    # ── POST ServiceRequest ─────────────────────────────────────────────
    proc_code = req.procedure_desc.replace(" ", "_").upper()
    resource = {
        "resourceType": "ServiceRequest",
        "status":  "draft",
        "intent":  "order",
        "subject": {"reference": f"Patient/{patient_uuid}"},
        "code": {
            "concept": {
                "coding": [{
                    "system":  "http://imladrislab.org/procedures",
                    "code":    proc_code,
                    "display": req.procedure_desc,
                }],
                "text": req.procedure_desc,
            }
        },
        "occurrenceDateTime": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "orderDetail": [{
            "parameter": [{
                "code": {"coding": [{
                    "system": "http://advapacs.com/fhir/servicerequest-orderdetail-parameter-code",
                    "code":   "modality",
                }]},
                "valueString": req.modality,
            }]
        }],
        "identifier": [
            {
                "system": "http://imladrislab.org/accession-number",
                "type": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/v2-0203", "code": "ACSN"}]},
                "value": accession,
            },
            {"system": "urn:dicom:uid", "value": f"urn:oid:{study_uid}"},
        ],
    }

    try:
        r3 = httpx.post(f"{base}/ServiceRequest", json=resource, headers=headers,
                        timeout=15, follow_redirects=True)
        if r3.status_code in (200, 201):
            sr_id = r3.json().get("id", "")
            return {"ok": True, "accession": accession, "study_uid": study_uid,
                    "patient_uuid": patient_uuid, "fhir_id": sr_id}
        return {"ok": False, "error": f"HTTP {r3.status_code}  {r3.text[:300]}",
                "accession": accession, "study_uid": study_uid}
    except Exception as e:
        return {"ok": False, "error": str(e), "accession": accession, "study_uid": study_uid}


# ── AdvaPACS FHIR orders query ────────────────────────────────────────────────

def _query_fhir_orders(req: FhirOrdersRequest) -> dict:
    url = f"{(req.fhir_base or FHIR_BASE_URL).rstrip('/')}/ServiceRequest"
    key_id     = req.key_id     or FHIR_KEY_ID
    key_secret = req.key_secret or FHIR_KEY_SECRET
    params: dict = {"_count": "200"}
    if req.status:
        params["status"] = req.status
    headers = {
        "Authorization": f"ID={key_id},Secret={key_secret}",
        "Accept": "application/fhir+json",
    }
    try:
        r = httpx.get(url, params=params, headers=headers, timeout=15,
                      follow_redirects=True)
        if r.status_code != 200:
            return {"ok": False, "error": f"HTTP {r.status_code}: {r.text[:300]}", "orders": []}

        bundle = r.json()
        entries = bundle.get("entry", [])
        base = (req.fhir_base or FHIR_BASE_URL).rstrip("/")
        device_cache: dict[str, dict] = {}
        orders = []
        for e in entries:
            sr = e.get("resource", {})

            # Modality: orderDetail[].parameter[].code.coding[0].code == "modality"
            modality_val = ""
            for od in sr.get("orderDetail", []):
                for p in od.get("parameter", []):
                    codings = p.get("code", {}).get("coding", [])
                    if any(c.get("code") == "modality" for c in codings):
                        modality_val = p.get("valueString", "")

            if req.modality and modality_val.upper() != req.modality.upper():
                continue

            # Accession: identifier with type.coding[0].code == "ACSN"
            # Study UID: identifier with system == "urn:dicom:uid" (value = "urn:oid:1.2...")
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

            # Procedure description: code.concept.coding[0].display
            proc_desc = (sr.get("code", {})
                           .get("concept", {})
                           .get("coding", [{}])[0]
                           .get("display", ""))

            # Patient: subject.display if present, else extract ID from reference
            subj = sr.get("subject", {})
            patient = subj.get("display") or subj.get("reference", "").split("/")[-1]

            # Performer Device (station) — fetch once per unique Device reference
            device_ref = ""
            device_raw = None
            performers = sr.get("performer", [])
            if performers:
                device_ref = performers[0].get("reference", "")
            if device_ref:
                if device_ref not in device_cache:
                    try:
                        dr = httpx.get(f"{base}/{device_ref}", headers=headers,
                                       timeout=10, follow_redirects=True)
                        device_cache[device_ref] = dr.json() if dr.status_code == 200 else {}
                    except Exception:
                        device_cache[device_ref] = {}
                device_raw = device_cache[device_ref]

            station_aet = _extract_station_aet(device_raw) if device_raw else ""

            # Fall back to AE-title map when AdvaPACS echoes the parameter code
            # name ("modality") as the valueString instead of the value ("CR").
            if modality_val not in _KNOWN_MODALITIES:
                modality_val = _AET_TO_MODALITY.get(station_aet, modality_val)

            # If station_aet still blank (no performer in SR), derive from modality.
            if not station_aet and modality_val in _AET_TO_MODALITY.values():
                station_aet = next(
                    (aet for aet, mod in _AET_TO_MODALITY.items() if mod == modality_val), ""
                )

            orders.append({
                "id":           sr.get("id", ""),
                "status":       sr.get("status", ""),
                "modality":     modality_val,
                "accession":    accession,
                "study_uid":    study_uid,
                "patient":      patient,
                "procedure":    proc_desc,
                "occurrence":   sr.get("occurrenceDateTime", ""),
                "station_aet":  station_aet,
                "device_ref":   device_ref,   # not shown in table; used for first_device_raw lookup
            })

        statuses_seen = list({o["status"] for o in orders})
        first_raw = entries[0]["resource"] if entries else None
        # Include first Device resource so we can see the station/AET structure
        first_device_ref = orders[0]["device_ref"] if orders else ""
        first_device_raw = device_cache.get(first_device_ref) if first_device_ref else None
        return {"ok": True, "total": bundle.get("total", len(orders)),
                "returned": len(orders), "statuses_seen": statuses_seen,
                "orders": orders, "first_raw": first_raw,
                "first_device_raw": first_device_raw}
    except Exception as ex:
        return {"ok": False, "error": str(ex), "orders": []}


# ── AdvaPACS study deletion ───────────────────────────────────────────────────

def _dw_headers(key_id: str, secret: str) -> dict:
    import base64
    b64 = base64.b64encode(f"{key_id}:{secret}".encode()).decode()
    return {"Authorization": f"Basic {b64}"}


def _delete_studies(req: DeleteStudiesRequest) -> dict:
    import base64
    base    = (req.fhir_base or FHIR_BASE_URL).rstrip("/")
    key_id  = req.key_id     or FHIR_KEY_ID
    secret  = req.key_secret or FHIR_KEY_SECRET
    fhdr    = {
        "Authorization": f"ID={key_id},Secret={secret}",
        "Accept": "application/fhir+json",
    }
    dwdr = _dw_headers(key_id, secret)
    dw_base = "https://usa1.api.dicomweb.advapacs.com"

    if not req.patient_id and not req.accession:
        return {"ok": False, "error": "Supply patient_id or accession", "studies": []}

    studies = []
    try:
        with httpx.Client(follow_redirects=True) as client:

            if req.accession:
                # Find ImagingStudy by accession identifier
                r = client.get(f"{base}/ImagingStudy",
                               params={"identifier": req.accession},
                               headers=fhdr, timeout=15)
                if r.status_code != 200:
                    return {"ok": False,
                            "error": f"ImagingStudy search: HTTP {r.status_code}",
                            "studies": []}
                entries = r.json().get("entry", [])
                if not entries:
                    return {"ok": False,
                            "error": f"No study found with accession '{req.accession}'",
                            "studies": []}
                for e in entries:
                    res = e.get("resource", {})
                    uid = next(
                        (i.get("value", "").removeprefix("urn:oid:")
                         for i in res.get("identifier", [])
                         if i.get("system") == "urn:dicom:uid"),
                        ""
                    )
                    studies.append({"fhir_id": res.get("id", ""), "uid": uid,
                                    "series": res.get("numberOfSeries", "?"),
                                    "instances": res.get("numberOfInstances", "?"),
                                    "started": res.get("started", "")[:10]})
            else:
                # Find patient UUID then all their ImagingStudy resources
                r = client.get(f"{base}/Patient",
                               params={"identifier": req.patient_id},
                               headers=fhdr, timeout=15)
                if r.status_code != 200:
                    return {"ok": False,
                            "error": f"Patient search: HTTP {r.status_code}: {r.text[:200]}",
                            "studies": []}
                pt_entries = r.json().get("entry", [])
                if not pt_entries:
                    return {"ok": False,
                            "error": f"Patient '{req.patient_id}' not found",
                            "studies": []}
                pt_uuid = pt_entries[0]["resource"]["id"]

                url    = f"{base}/ImagingStudy"
                params: dict = {"patient": pt_uuid, "_count": "200"}
                while url:
                    r = client.get(url, params=params, headers=fhdr, timeout=15)
                    if r.status_code != 200:
                        return {"ok": False,
                                "error": f"ImagingStudy list: HTTP {r.status_code}: {r.text[:200]}",
                                "studies": studies}
                    bundle = r.json()
                    for e in bundle.get("entry", []):
                        res = e.get("resource", {})
                        uid = next(
                            (i.get("value", "").removeprefix("urn:oid:")
                             for i in res.get("identifier", [])
                             if i.get("system") == "urn:dicom:uid"),
                            ""
                        )
                        studies.append({"fhir_id": res.get("id", ""), "uid": uid,
                                        "series": res.get("numberOfSeries", "?"),
                                        "instances": res.get("numberOfInstances", "?"),
                                        "started": res.get("started", "")[:10]})
                    url    = next((l["url"] for l in bundle.get("link", [])
                                   if l.get("relation") == "next"), None)
                    params = {}

            if req.dry_run:
                return {"ok": True, "dry_run": True,
                        "message": f"Would delete {len(studies)} study/studies (dry run)",
                        "studies": studies}

            deleted = failed = 0
            results = []
            for st in studies:
                uid, fhir_id = st["uid"], st["fhir_id"]
                outcome = "failed"
                # Try FHIR DELETE first — may bypass AdvaPACS validation queue
                if fhir_id:
                    r = client.delete(f"{base}/ImagingStudy/{fhir_id}",
                                      headers=fhdr, timeout=30)
                    if r.status_code in (200, 204):
                        outcome = "deleted (FHIR)"
                    elif uid:
                        # DICOMweb fallback
                        r2 = client.delete(f"{dw_base}/studies/{uid}",
                                           headers=dwdr, timeout=30)
                        outcome = ("deleted (DICOMweb)" if r2.status_code in (200, 204)
                                   else f"failed HTTP {r2.status_code}")
                    else:
                        outcome = f"failed HTTP {r.status_code}"
                elif uid:
                    r = client.delete(f"{dw_base}/studies/{uid}",
                                      headers=dwdr, timeout=30)
                    outcome = ("deleted (DICOMweb)" if r.status_code in (200, 204)
                               else f"failed HTTP {r.status_code}")

                if "deleted" in outcome:
                    deleted += 1
                else:
                    failed += 1
                results.append({**st, "outcome": outcome})

            return {"ok": True, "dry_run": False,
                    "message": f"Deleted {deleted}, failed {failed}",
                    "studies": results}

    except Exception as ex:
        return {"ok": False, "error": str(ex), "studies": studies}


# ── DICOM MWL C-FIND ─────────────────────────────────────────────────────────

def _query_dicom_mwl(req: MwlQueryRequest) -> dict:
    try:
        from pynetdicom import AE
        from pynetdicom.sop_class import ModalityWorklistInformationFind
        from pydicom.dataset import Dataset
        from pydicom.sequence import Sequence as DicomSequence
    except ImportError as e:
        return {"ok": False, "error": f"pynetdicom not installed: {e}", "entries": []}

    ae = AE(ae_title=req.calling_ae[:16])
    ae.add_requested_context(ModalityWorklistInformationFind)

    try:
        assoc = ae.associate(req.host, req.port, ae_title=req.called_ae)
    except Exception as e:
        return {"ok": False, "error": f"Association failed: {e}", "entries": []}

    if not assoc.is_established:
        return {"ok": False, "error": "Association rejected or could not be established", "entries": []}

    # C-FIND identifier — empty string on each attribute means "match all"
    ds = Dataset()
    ds.PatientName               = ""
    ds.PatientID                 = ""
    ds.PatientBirthDate          = ""
    ds.PatientSex                = ""
    ds.AccessionNumber           = ""
    ds.RequestedProcedureDescription = ""
    ds.StudyInstanceUID          = ""

    sps = Dataset()
    sps.Modality                          = req.modality or ""
    sps.ScheduledStationAETitle           = ""
    sps.ScheduledProcedureStepStartDate   = ""
    sps.ScheduledProcedureStepStartTime   = ""
    sps.ScheduledProcedureStepDescription = ""
    ds.ScheduledProcedureStepSequence = DicomSequence([sps])

    entries = []
    try:
        for status, identifier in assoc.send_c_find(ds, ModalityWorklistInformationFind):
            if status and status.Status in (0xFF00, 0xFF01) and identifier:
                sps_seq  = getattr(identifier, "ScheduledProcedureStepSequence", None)
                sps_item = sps_seq[0] if sps_seq else Dataset()
                entries.append({
                    "patient_name": str(getattr(identifier, "PatientName",                      "")),
                    "patient_id":   str(getattr(identifier, "PatientID",                        "")),
                    "dob":          str(getattr(identifier, "PatientBirthDate",                  "")),
                    "sex":          str(getattr(identifier, "PatientSex",                        "")),
                    "accession":    str(getattr(identifier, "AccessionNumber",                   "")),
                    "procedure":    (str(getattr(identifier, "RequestedProcedureDescription",    ""))
                                     or str(getattr(sps_item, "ScheduledProcedureStepDescription", ""))),
                    "modality":     str(getattr(sps_item,   "Modality",                         "")),
                    "station_aet":  str(getattr(sps_item,   "ScheduledStationAETitle",          "")),
                    "scheduled":    str(getattr(sps_item,   "ScheduledProcedureStepStartDate",  "")),
                    "study_uid":    str(getattr(identifier, "StudyInstanceUID",                  "")),
                })
    finally:
        assoc.release()

    return {"ok": True, "count": len(entries), "entries": entries}


# ── DICOM C-STORE upload ──────────────────────────────────────────────────────

def _collect_dcm(files_data: list[tuple[str, bytes]]) -> list[tuple[str, bytes]]:
    """Expand zip uploads; return list of (display_name, raw_bytes) for every .dcm."""
    out = []
    for filename, raw in files_data:
        if filename.lower().endswith(".zip"):
            try:
                with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                    for name in sorted(zf.namelist()):
                        if name.lower().endswith(".dcm") and not name.startswith("__MACOSX"):
                            out.append((name, zf.read(name)))
            except Exception as exc:
                out.append((filename, b""))  # will surface as parse error below
        elif filename.lower().endswith(".dcm"):
            out.append((filename, raw))
    return out


def _c_store_worker(files_data, my_ae, gw_ae, gw_host, gw_port, queue, loop):
    """Background thread: C-STOREs each file and puts result dicts into queue."""
    def put(item):
        asyncio.run_coroutine_threadsafe(queue.put(item), loop)

    all_dcm = _collect_dcm(files_data)
    if not all_dcm:
        put({"file": "(none)", "ok": False, "error": "No .dcm files found"})
        put(None)
        return

    datasets = []
    for name, raw in all_dcm:
        if not raw:
            put({"file": name, "ok": False, "error": "Could not read from ZIP"})
            continue
        try:
            ds = pydicom.dcmread(io.BytesIO(raw), force=True)
            sop = str(ds.get("SOPClassUID", ""))
            if not sop:
                put({"file": name, "ok": False, "error": "No SOPClassUID"})
            else:
                datasets.append((name, ds, sop))
        except Exception as exc:
            put({"file": name, "ok": False, "error": f"Parse failed: {exc}"})

    if not datasets:
        put(None)
        return

    from pynetdicom import AE as DicomAE
    from pydicom.uid import ImplicitVRLittleEndian, ExplicitVRLittleEndian
    ae = DicomAE(ae_title=my_ae[:16])

    # Build per-SOP-class set of transfer syntaxes actually present in the
    # datasets, plus the standard uncompressed fallbacks.  pynetdicom's
    # Only propose the TS the file is actually encoded in — proposing uncompressed
    # TS we can't deliver lets the peer accept one we can't use, causing a
    # send_c_store() failure even though the association succeeded.
    from collections import defaultdict
    sop_ts: defaultdict[str, set[str]] = defaultdict(set)
    for _, ds, sop in datasets:
        try:
            ts = str(ds.file_meta.TransferSyntaxUID)
            sop_ts[sop].add(ts)
        except Exception:
            sop_ts[sop].add(ExplicitVRLittleEndian)

    for sop, ts_set in sop_ts.items():
        try:
            ae.add_requested_context(sop, list(ts_set))
        except Exception:
            pass

    sop_classes = set(sop_ts.keys())
    log.info(
        f"DICOM upload: {len(datasets)} instance(s) → {gw_ae}@{gw_host}:{gw_port} "
        f"as {my_ae}  requested_contexts={sorted(sop_ts.items())}"
    )

    try:
        assoc = ae.associate(gw_host, gw_port, ae_title=gw_ae)
    except Exception as exc:
        log.warning(f"DICOM upload: association to {gw_ae}@{gw_host}:{gw_port} failed: {exc}")
        for name, _, _ in datasets:
            put({"file": name, "ok": False, "error": f"Association failed: {exc}"})
        put(None)
        return

    if not assoc.is_established:
        log.warning(f"DICOM upload: association rejected by {gw_ae}@{gw_host}:{gw_port}")
        for name, _, _ in datasets:
            put({"file": name, "ok": False, "error": "Association rejected by gateway"})
        put(None)
        return

    accepted = [f"{cx.abstract_syntax}@{cx.transfer_syntax}" for cx in assoc.accepted_contexts]
    rejected = [f"{cx.abstract_syntax}@{cx.transfer_syntax}" for cx in assoc.rejected_contexts]
    log.info(f"DICOM upload: association established  accepted={accepted}  rejected={rejected}")

    try:
        for name, ds, _ in datasets:
            try:
                status = assoc.send_c_store(ds)
                if status and status.Status == 0x0000:
                    log.debug(f"DICOM upload: C-STORE OK  {name}")
                    put({"file": name, "ok": True})
                else:
                    code = getattr(status, "Status", None)
                    msg = f"C-STORE 0x{code:04x}" if isinstance(code, int) else "no response"
                    log.warning(f"DICOM upload: C-STORE failed  {name}  status={msg}")
                    put({"file": name, "ok": False, "error": msg})
            except Exception as exc:
                log.warning(f"DICOM upload: C-STORE exception  {name}  error={exc}")
                put({"file": name, "ok": False, "error": str(exc)})
    finally:
        assoc.release()
        put(None)


# ── Startup: recover state from existing iptables rules ──────────────────────

def _load_existing_rules() -> None:
    global _blocked_ips, _profile
    try:
        result = subprocess.run(
            ["iptables-save", "-t", "filter"],
            capture_output=True, text=True, check=True,
        )
        for line in result.stdout.splitlines():
            # Match rules in OUTPUT (host-networked) and DOCKER-USER (bridge-networked)
            if ("-A OUTPUT" in line or "-A DOCKER-USER" in line) and "--dport 443" in line and "-j REJECT" in line:
                for part in line.split():
                    if "/" in part:
                        try:
                            net = ipaddress.ip_network(part, strict=False)
                            ip = str(net.network_address)
                            if not ipaddress.ip_address(ip).is_private:
                                _blocked_ips.add(ip)
                        except ValueError:
                            pass
        if _blocked_ips:
            _profile = "offline"
    except Exception:
        pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    _load_existing_rules()
    yield


app = FastAPI(title="Imladris Lab Tool Cabinet", lifespan=lifespan)
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")


# ── Network utilities ─────────────────────────────────────────────────────────

def _resolve_fqdns(fqdns: list[str]) -> set[str]:
    ips: set[str] = set()
    for fqdn in fqdns:
        try:
            for info in socket.getaddrinfo(fqdn, 443, type=socket.SOCK_STREAM):
                addr = info[4][0]
                if not ipaddress.ip_address(addr).is_private:
                    ips.add(addr)
        except OSError:
            pass
    return ips


def _scan_https_connections() -> set[str]:
    """Return public IPs with established HTTPS (port 443) connections in this netns."""
    ips: set[str] = set()
    for proc_path in ["/proc/net/tcp6", "/proc/net/tcp"]:
        try:
            lines = Path(proc_path).read_text().splitlines()[1:]
            for line in lines:
                parts = line.split()
                if len(parts) < 4 or parts[3] != "01":   # 01 = ESTABLISHED
                    continue
                remote = parts[2]
                addr_hex, port_hex = remote.rsplit(":", 1)
                if int(port_hex, 16) != 443:
                    continue
                try:
                    # /proc/net/tcp6: 32-hex IPv4-mapped; /proc/net/tcp: 8-hex IPv4
                    raw = addr_hex[-8:]                   # last 8 hex = IPv4 part
                    ip_bytes = bytes.fromhex(raw)[::-1]   # little-endian → network order
                    addr = str(ipaddress.IPv4Address(ip_bytes))
                    if not ipaddress.ip_address(addr).is_private:
                        ips.add(addr)
                except Exception:
                    pass
        except OSError:
            pass
    return ips


def _iptables(action: str, ip: str) -> None:
    # OUTPUT covers host-networked containers (advapacs-gateway).
    # DOCKER-USER covers bridge-networked containers (orthanc-pacs, etc.).
    for chain in ("OUTPUT", "DOCKER-USER"):
        r = subprocess.run(
            ["iptables", action, chain,
             "-d", ip, "-p", "tcp", "--dport", "443", "-j", "REJECT"],
            capture_output=True,
        )
        if r.returncode != 0 and action != "-D":
            raise subprocess.CalledProcessError(r.returncode, r.args, r.stdout, r.stderr)


# ── Service queries ───────────────────────────────────────────────────────────

def _pacs_stats() -> dict:
    try:
        r = httpx.get(
            f"{PACS_URL}/statistics",
            auth=(PACS_USER, PACS_PASSWORD),
            timeout=3,
        )
        s = r.json()
        return {
            "studies": s.get("CountStudies", 0),
            "instances": s.get("CountInstances", 0),
            "ok": True,
        }
    except Exception:
        return {"studies": "—", "instances": "—", "ok": False}


def _gw_status() -> str:
    try:
        return docker.from_env().containers.get(GATEWAY_CONTAINER).status
    except Exception:
        return "unknown"


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html", {
        "profile":     _profile,
        "blocked_ips": sorted(_blocked_ips),
        "pacs":        _pacs_stats(),
        "gw_status":   _gw_status(),
    })


@app.post("/profile/offline")
async def go_offline():
    global _profile, _blocked_ips
    ips = _resolve_fqdns(ADVAPACS_HOSTS) | _scan_https_connections()
    errors = []
    for ip in ips:
        if ip not in _blocked_ips:
            try:
                _iptables("-I", ip)
                _blocked_ips.add(ip)
            except subprocess.CalledProcessError as e:
                errors.append(f"{ip}: {e.stderr.decode().strip()}")
    _profile = "offline"
    return JSONResponse({
        "profile":     _profile,
        "blocked_ips": sorted(_blocked_ips),
        "errors":      errors,
    })


@app.post("/profile/online")
async def go_online():
    global _profile, _blocked_ips
    errors = []
    for ip in list(_blocked_ips):
        try:
            _iptables("-D", ip)
            _blocked_ips.discard(ip)
        except subprocess.CalledProcessError as e:
            errors.append(f"{ip}: {e.stderr.decode().strip()}")
    _profile = "online"
    return JSONResponse({
        "profile":     _profile,
        "blocked_ips": sorted(_blocked_ips),
        "errors":      errors,
    })


@app.get("/status")
async def status_json():
    return JSONResponse({
        "profile":     _profile,
        "blocked_ips": sorted(_blocked_ips),
        "pacs":        _pacs_stats(),
        "gw_status":   _gw_status(),
    })


@app.post("/fhir/sr")
def post_service_request(req: ServiceRequestInput):
    return JSONResponse(_post_service_request(req))


@app.post("/fhir/orders")
def fhir_orders(req: FhirOrdersRequest):
    return JSONResponse(_query_fhir_orders(req))


@app.post("/fhir/delete-studies")
def delete_studies(req: DeleteStudiesRequest):
    return JSONResponse(_delete_studies(req))


def _delete_orders(req: DeleteOrdersRequest) -> dict:
    base   = (req.fhir_base or FHIR_BASE_URL).rstrip("/")
    key_id = req.key_id     or FHIR_KEY_ID
    secret = req.key_secret or FHIR_KEY_SECRET
    fhdr   = {
        "Authorization": f"ID={key_id},Secret={secret}",
        "Accept": "application/fhir+json",
    }

    if not req.patient_id and not req.accession:
        return {"ok": False, "error": "Supply patient_id or accession", "orders": []}

    orders = []
    try:
        with httpx.Client(follow_redirects=True) as client:

            if req.accession:
                r = client.get(f"{base}/ServiceRequest",
                               params={"identifier": req.accession},
                               headers=fhdr, timeout=15)
                if r.status_code != 200:
                    return {"ok": False,
                            "error": f"ServiceRequest search: HTTP {r.status_code}: {r.text[:200]}",
                            "orders": []}
                entries = r.json().get("entry", [])
                if not entries:
                    return {"ok": False,
                            "error": f"No order found with accession '{req.accession}'",
                            "orders": []}
            else:
                r = client.get(f"{base}/Patient",
                               params={"identifier": req.patient_id},
                               headers=fhdr, timeout=15)
                if r.status_code != 200:
                    return {"ok": False,
                            "error": f"Patient search: HTTP {r.status_code}: {r.text[:200]}",
                            "orders": []}
                pt_entries = r.json().get("entry", [])
                if not pt_entries:
                    return {"ok": False,
                            "error": f"Patient '{req.patient_id}' not found",
                            "orders": []}
                pt_uuid = pt_entries[0]["resource"]["id"]

                r = client.get(f"{base}/ServiceRequest",
                               params={"patient": pt_uuid, "_count": "200"},
                               headers=fhdr, timeout=15)
                if r.status_code != 200:
                    return {"ok": False,
                            "error": f"ServiceRequest list: HTTP {r.status_code}: {r.text[:200]}",
                            "orders": []}
                entries = r.json().get("entry", [])
                if not entries:
                    return {"ok": False,
                            "error": f"No orders found for patient '{req.patient_id}'",
                            "orders": []}

            for e in entries:
                res = e.get("resource", {})
                accession = next(
                    (i.get("value", "") for i in res.get("identifier", [])
                     if i.get("type", {}).get("coding", [{}])[0].get("code") == "ACSN"),
                    res.get("identifier", [{}])[0].get("value", "") if res.get("identifier") else ""
                )
                proc = (res.get("code", {}).get("concept", {}).get("coding", [{}])[0].get("display", "")
                        or res.get("code", {}).get("concept", {}).get("text", "")
                        or res.get("code", {}).get("text", ""))
                orders.append({
                    "fhir_id":    res.get("id", ""),
                    "status":     res.get("status", ""),
                    "accession":  accession,
                    "patient":    res.get("subject", {}).get("display", ""),
                    "procedure":  proc,
                    "occurrence": res.get("occurrenceDateTime", "")[:10],
                })

            if req.dry_run:
                return {"ok": True, "dry_run": True,
                        "message": f"Would revoke {len(orders)} order(s) (dry run)",
                        "orders": orders}

            revoked = failed = 0
            results = []
            patch_hdrs = {**fhdr, "Content-Type": "application/json-patch+json"}
            for o in orders:
                fhir_id = o["fhir_id"]
                # AdvaPACS does not support DELETE on ServiceRequest;
                # try JSON Patch first, then GET+PUT full resource as fallback.
                r = client.patch(
                    f"{base}/ServiceRequest/{fhir_id}",
                    content=b'[{"op":"replace","path":"/status","value":"revoked"}]',
                    headers=patch_hdrs, timeout=30,
                )
                if r.status_code in (200, 204):
                    outcome = "revoked"
                else:
                    # Fallback: GET full resource, update status, PUT back
                    rg = client.get(f"{base}/ServiceRequest/{fhir_id}",
                                    headers=fhdr, timeout=15)
                    if rg.status_code == 200:
                        res_body = rg.json()
                        res_body["status"] = "revoked"
                        put_hdrs = {**fhdr, "Content-Type": "application/fhir+json"}
                        rp = client.put(f"{base}/ServiceRequest/{fhir_id}",
                                        json=res_body, headers=put_hdrs, timeout=30)
                        if rp.status_code in (200, 204):
                            outcome = "revoked (PUT)"
                        else:
                            outcome = f"failed HTTP {rp.status_code}: {rp.text[:200]}"
                    else:
                        outcome = f"failed HTTP {r.status_code}: {r.text[:200]}"
                if "revoked" in outcome:
                    revoked += 1
                else:
                    failed += 1
                results.append({**o, "outcome": outcome})

            return {"ok": True, "dry_run": False,
                    "message": f"Revoked {revoked}, failed {failed}",
                    "orders": results}

    except Exception as ex:
        return {"ok": False, "error": str(ex), "orders": orders}


@app.post("/fhir/delete-orders")
def delete_orders(req: DeleteOrdersRequest):
    return JSONResponse(_delete_orders(req))


@app.post("/dicom/mwl")
def dicom_mwl(req: MwlQueryRequest):
    return JSONResponse(_query_dicom_mwl(req))


@app.post("/dicom/upload")
async def dicom_upload(
    files:      list[UploadFile] = File(...),
    host:       str = Form(default=""),
    port:       str = Form(default=""),
    called_ae:  str = Form(default=""),
    calling_ae: str = Form(default=""),
):
    gw_host = host.strip()       or DICOM_GW_HOST
    gw_port = int(port.strip())  if port.strip().isdigit() else DICOM_GW_PORT
    gw_ae   = called_ae.strip()  or DICOM_GW_AE
    my_ae   = calling_ae.strip() or DICOM_TOOLS_AE

    files_data = [(f.filename or "unknown", await f.read()) for f in files]

    queue = asyncio.Queue()
    loop  = asyncio.get_event_loop()
    threading.Thread(
        target=_c_store_worker,
        args=(files_data, my_ae, gw_ae, gw_host, gw_port, queue, loop),
        daemon=True,
    ).start()

    async def stream():
        while True:
            item = await queue.get()
            if item is None:
                break
            yield json.dumps(item) + "\n"

    return StreamingResponse(stream(), media_type="application/x-ndjson")
