"""
hl7_bridge.py — Orthanc PACS change watcher + HL7 ORU^R01 sender.

Polls the Orthanc PACS /changes feed for StableStudy events and sends
an HL7 v2.3 ORU^R01 message to OpenMRS via the REST API
(POST /ws/rest/v1/hl7) to indicate that images are available.

Using REST rather than MLLP avoids the need for a separate MLLP listener
port in OpenMRS.  The & in MSH-2 is sent as the JSON Unicode escape
\u0026 to survive the OpenMRS XSS filter, which HTML-encodes bare & in
request bodies.

Inbound radiology orders are handled by order_poller.py (REST API
polling), so there is no MLLP listener in this module.

Usage
-----
Import watch_pacs_forever() and schedule it in an asyncio loop, or run
standalone for testing:

    python hl7_bridge.py
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timezone

import requests

log = logging.getLogger("hl7_bridge")

# ── Configuration ─────────────────────────────────────────────────────

OPENMRS_URL      = os.getenv("OPENMRS_URL",        "http://openmrs:8080/openmrs")
OPENMRS_USER     = os.getenv("OPENMRS_USER",       "admin")
OPENMRS_PASSWORD = os.getenv("OPENMRS_PASSWORD",   "Admin123")

PACS_URL         = os.getenv("PACS_URL",           "http://orthanc-pacs:8042")
PACS_USER        = os.getenv("PACS_USER",          "admin")
PACS_PASS        = os.getenv("PACS_PASSWORD",      "admin")

CHANGE_POLL_SEC  = int(os.getenv("CHANGE_POLL_SEC", "15"))

# Track last Orthanc change sequence seen (in-process only; resets on restart)
_last_change_seq: int = 0


# ── OpenMRS REST HL7 send helper ──────────────────────────────────────

def _send_hl7_rest(hl7_str: str):
    """POST an HL7 message to OpenMRS via the REST API.

    The & in MSH-2 (^~\\&) is sent as the JSON Unicode escape \\u0026
    so the OpenMRS XSS filter (which HTML-encodes bare & in request
    bodies) does not corrupt the HL7 encoding characters.
    """
    body = json.dumps({"hl7": hl7_str}).replace("&", "\\u0026").encode("ascii")
    r = requests.post(
        f"{OPENMRS_URL}/ws/rest/v1/hl7",
        data=body,
        headers={"Content-Type": "application/json"},
        auth=(OPENMRS_USER, OPENMRS_PASSWORD),
        timeout=10,
    )
    if r.status_code == 201:
        log.info(f"HL7 REST accepted: {r.json().get('uuid')}  state={r.json().get('messageState')}")
    else:
        log.error(f"HL7 REST rejected ({r.status_code}): {r.text[:200]}")
        r.raise_for_status()


# ── Orthanc PACS change watcher ───────────────────────────────────────

async def watch_pacs_forever():
    """Poll Orthanc PACS /changes for StableStudy events indefinitely."""
    global _last_change_seq
    auth = (PACS_USER, PACS_PASS)
    log.info(f"PACS change watcher started ({PACS_URL}, poll={CHANGE_POLL_SEC}s)")

    # Start from the current tail so we don't replay history on restart
    try:
        r = requests.get(f"{PACS_URL}/changes?last=1", auth=auth, timeout=5)
        if r.ok:
            _last_change_seq = r.json().get("Last", 0)
            log.info(f"Starting from change seq={_last_change_seq}")
    except Exception as e:
        log.warning(f"Could not fetch initial change seq: {e}")

    while True:
        await asyncio.sleep(CHANGE_POLL_SEC)
        try:
            await _poll_once(auth)
        except Exception as e:
            log.error(f"Change poll error: {e}")


async def _poll_once(auth: tuple):
    global _last_change_seq
    r = requests.get(
        f"{PACS_URL}/changes",
        params={"since": _last_change_seq, "limit": 50},
        auth=auth,
        timeout=10,
    )
    if not r.ok:
        log.warning(f"Orthanc /changes returned {r.status_code}")
        return

    data = r.json()
    for change in data.get("Changes", []):
        _last_change_seq = change["Seq"]
        if change["ChangeType"] != "StableStudy":
            continue
        study_id = change["ID"]
        log.info(f"New stable study in PACS: {study_id}")
        try:
            await _send_oru_for_study(study_id, auth)
        except Exception as e:
            log.error(f"ORU send failed for study {study_id}: {e}")

    if data.get("Last"):
        _last_change_seq = data["Last"]


async def _send_oru_for_study(study_id: str, auth: tuple):
    """Fetch study metadata from Orthanc and send ORU^R01 to OpenMRS."""
    r = requests.get(f"{PACS_URL}/studies/{study_id}", auth=auth, timeout=10)
    r.raise_for_status()
    study = r.json()

    tags         = study.get("MainDicomTags", {})
    patient_tags = study.get("PatientMainDicomTags", {})

    patient_id   = patient_tags.get("PatientID",   "")
    patient_name = patient_tags.get("PatientName", "")
    accession    = tags.get("AccessionNumber",      "")
    study_uid    = tags.get("StudyInstanceUID",     "")
    study_desc   = tags.get("StudyDescription",     "Study complete")
    study_date   = tags.get("StudyDate",  datetime.now().strftime("%Y%m%d"))
    study_time   = tags.get("StudyTime",  "000000")
    modality     = tags.get("ModalitiesInStudy", "OT").split("\\")[0]

    oru = _build_oru(
        patient_id=patient_id,
        patient_name=patient_name,
        accession=accession,
        procedure_desc=study_desc,
        modality=modality,
        study_uid=study_uid,
        study_date=study_date,
        study_time=study_time,
    )

    log.info(
        f"Sending ORU^R01 via REST  accession={accession}  patient={patient_id}"
    )
    await asyncio.get_event_loop().run_in_executor(None, _send_hl7_rest, oru)


# ── ORU^R01 builder ───────────────────────────────────────────────────

def _build_oru(
    patient_id, patient_name, accession,
    procedure_desc, modality, study_uid, study_date, study_time,
) -> str:
    now    = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    msg_id = f"ORU{now}"
    obs_time = f"{study_date}{study_time[:6]}"
    obs_value = f"Images available in PACS. StudyInstanceUID={study_uid}"

    return (
        f"MSH|^~\\&|IMLADRIS|IMLADRIS|OpenMRS||{now}||ORU^R01|{msg_id}|P|2.3\r"
        f"PID|1||{patient_id}^^^IMLADRIS^MR||{patient_name}||\r"
        f"OBR|1|{accession}|{accession}|RAD^{procedure_desc}^LOCAL"
        f"|||{obs_time}||||||||||||{modality}|||||||F\r"
        f"OBX|1|ST|RAD^{procedure_desc}^LOCAL||{obs_value}||||||F\r"
    )


# ── Entry point ───────────────────────────────────────────────────────

if __name__ == "__main__":
    import logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    asyncio.run(watch_pacs_forever())
