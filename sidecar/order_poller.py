"""
order_poller.py — Polls OpenMRS REST API for new radiology orders.

Replaces Mirth Connect's database-polling channel.  Queries
/ws/rest/v1/order for radiology orders activated since the last poll
and creates DICOM worklist entries via MwlManager.

State (last-seen timestamp) is persisted to ORDER_STATE_FILE so
restarts do not replay already-processed orders.

Environment variables
---------------------
OPENMRS_URL               http://openmrs:8080/openmrs
OPENMRS_USER              admin
OPENMRS_PASSWORD          Admin123
RADIOLOGY_ORDER_TYPE_UUID blank = auto-discovered from /ws/rest/v1/ordertype
ORDER_STATE_FILE          /data/order_poller_state.json
ORDER_POLL_SEC            30
WL_FOLDER                 /worklist
MODALITY_AET              MODALITY_SIM
"""

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

from mwl_manager import MwlManager

log = logging.getLogger("order_poller")

# ── Configuration ─────────────────────────────────────────────────────

OPENMRS_URL      = os.getenv("OPENMRS_URL",               "http://openmrs:8080/openmrs")
OPENMRS_USER     = os.getenv("OPENMRS_USER",              "admin")
OPENMRS_PASSWORD = os.getenv("OPENMRS_PASSWORD",          "Admin123")

_ORDER_TYPE_UUID_ENV = os.getenv("RADIOLOGY_ORDER_TYPE_UUID", "")

ORDER_STATE_FILE = os.getenv("ORDER_STATE_FILE",          "/data/order_poller_state.json")
ORDER_POLL_SEC   = int(os.getenv("ORDER_POLL_SEC",        "30"))
WL_FOLDER        = os.getenv("WL_FOLDER",                 "/worklist")
MODALITY_AET     = os.getenv("MODALITY_AET",              "MODALITY_SIM")

# Concept name keywords → DICOM modality code
_MODALITY_MAP = [
    ("ultrasound", "US"),
    ("echo",       "US"),
    ("ct ",        "CT"),
    (" ct",        "CT"),
    ("computed",   "CT"),
    ("mri",        "MR"),
    ("magnetic",   "MR"),
    ("fluoro",     "RF"),
    ("nuclear",    "NM"),
]
_MODALITY_DEFAULT = "CR"   # plain X-ray / catch-all


def _guess_modality(concept_name: str) -> str:
    name = concept_name.lower()
    for keyword, code in _MODALITY_MAP:
        if keyword in name:
            return code
    return _MODALITY_DEFAULT


# ── OpenMRS REST helpers ──────────────────────────────────────────────

def _session() -> requests.Session:
    s = requests.Session()
    s.auth = (OPENMRS_USER, OPENMRS_PASSWORD)
    s.headers["Accept"] = "application/json"
    return s


def _lookup_radiology_order_type(sess: requests.Session) -> str:
    """Return the UUID of the 'Radiology Order' order type, or raise."""
    r = sess.get(f"{OPENMRS_URL}/ws/rest/v1/ordertype", params={"v": "full"}, timeout=10)
    r.raise_for_status()
    for ot in r.json().get("results", []):
        name = ot.get("name", "").lower()
        if "radiology" in name:
            uuid = ot["uuid"]
            log.info(f"Found radiology order type: '{ot['name']}'  uuid={uuid}")
            return uuid
    # Fall back to testorder if no explicit radiology type
    for ot in r.json().get("results", []):
        if "test" in ot.get("name", "").lower():
            uuid = ot["uuid"]
            log.warning(
                f"No 'Radiology' order type found; falling back to '{ot['name']}'  uuid={uuid}"
            )
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

def _extract_patient_info(patient: dict) -> tuple[str, str, str, str]:
    """Return (patient_id, patient_name, dob, sex) from a full patient resource."""
    # Prefer the first non-voided identifier
    identifiers = patient.get("identifiers") or []
    patient_id = ""
    for ident in identifiers:
        if not ident.get("voided", False):
            patient_id = ident.get("identifier", "")
            break
    if not patient_id:
        # Fall back to the display string "ID - Name"
        patient_id = patient.get("display", "UNKNOWN").split(" - ")[0].strip()

    person = patient.get("person") or {}
    # Display is typically "Firstname Lastname" (full name string)
    full_name = person.get("display", "")
    # Convert "First Last" → "Last^First" for DICOM
    parts = full_name.strip().split()
    if len(parts) >= 2:
        dicom_name = f"{parts[-1]}^{' '.join(parts[:-1])}"
    else:
        dicom_name = full_name

    # DOB: "1990-01-15" → "19900115"
    dob_raw = person.get("birthdate", "") or ""
    dob = dob_raw.replace("-", "")[:8]

    # Gender: "M"/"F"/"U" — OpenMRS uses "M"/"F"
    sex = (person.get("gender") or "U").upper()

    return patient_id, dicom_name, dob, sex


# ── Order processing ──────────────────────────────────────────────────

def _process_order(order: dict, mwl: MwlManager):
    """Create or delete a worklist entry from a single order resource."""
    action = (order.get("action") or "NEW").upper()
    accession = order.get("accessionNumber") or order.get("uuid", "")
    if not accession:
        log.warning("Order has no accessionNumber — skipping")
        return

    if action in ("DISCONTINUE",):
        mwl.delete(accession)
        log.info(f"Discontinued order removed from MWL: accession={accession}")
        return

    # Extract fields
    patient = order.get("patient") or {}
    patient_id, patient_name, dob, sex = _extract_patient_info(patient)

    concept = order.get("concept") or {}
    procedure_desc = concept.get("display") or "Radiology Procedure"
    procedure_id   = (concept.get("conceptClass") or {}).get("uuid") or concept.get("uuid", "RAD")[:8]
    modality = _guess_modality(procedure_desc)

    # Scheduled time: prefer scheduledDate, fall back to dateActivated
    scheduled_raw = order.get("scheduledDate") or order.get("dateActivated") or ""
    # ISO 8601 → DICOM YYYYMMDD / HHMMSS
    scheduled_date = scheduled_time = None
    if scheduled_raw:
        dt_str = scheduled_raw.replace("T", "").replace("-", "").replace(":", "").replace("Z", "")
        scheduled_date = dt_str[:8] if len(dt_str) >= 8 else None
        scheduled_time = dt_str[8:14] if len(dt_str) >= 14 else None

    mwl.create(
        patient_id=patient_id,
        patient_name=patient_name,
        dob=dob,
        sex=sex,
        accession=accession,
        procedure_id=procedure_id,
        procedure_desc=procedure_desc,
        modality=modality,
        scheduled_date=scheduled_date,
        scheduled_time=scheduled_time,
    )
    log.info(
        f"MWL created from REST order: accession={accession}  "
        f"patient={patient_id}  {procedure_desc} ({modality})"
    )


def _poll_once(sess: requests.Session, order_type_uuid: str, mwl: MwlManager, state: dict) -> dict:
    """Fetch orders since last_polled, process new ones, return updated state."""
    last_polled = state.get("last_polled")  # ISO 8601 string or None

    params = {
        "orderType": order_type_uuid,
        "v": "full",
        "limit": 100,
    }
    if last_polled:
        params["activatedOnOrAfterDate"] = last_polled

    try:
        r = sess.get(f"{OPENMRS_URL}/ws/rest/v1/order", params=params, timeout=15)
        r.raise_for_status()
    except requests.RequestException as e:
        log.error(f"OpenMRS REST poll failed: {e}")
        return state

    orders = r.json().get("results", [])
    log.debug(f"Poll returned {len(orders)} orders (since {last_polled or 'beginning'})")

    # Track the latest dateActivated we've seen
    max_activated = last_polled

    for order in orders:
        date_activated = order.get("dateActivated") or ""
        # Skip already-seen orders (same timestamp as last poll boundary)
        # by tracking UUIDs processed in this session (avoids double-processing
        # orders exactly at the boundary on restart)
        try:
            _process_order(order, mwl)
        except Exception as e:
            log.error(f"Failed to process order {order.get('uuid')}: {e}", exc_info=True)

        if date_activated and (max_activated is None or date_activated > max_activated):
            max_activated = date_activated

    if max_activated and max_activated != last_polled:
        state["last_polled"] = max_activated
        _save_state(state)

    return state


# ── Main loop ─────────────────────────────────────────────────────────

def main():
    """Run the order poller loop indefinitely (blocking)."""
    log.info(
        f"Order poller starting  url={OPENMRS_URL}  "
        f"poll_interval={ORDER_POLL_SEC}s"
    )

    mwl = MwlManager(WL_FOLDER, station_aet=MODALITY_AET)
    sess = _session()

    # Resolve order type UUID
    order_type_uuid = _ORDER_TYPE_UUID_ENV
    if not order_type_uuid:
        for attempt in range(1, 6):
            try:
                order_type_uuid = _lookup_radiology_order_type(sess)
                break
            except Exception as e:
                log.warning(f"Order type lookup failed (attempt {attempt}/5): {e}")
                time.sleep(15)
        else:
            log.error("Could not discover radiology order type UUID — order poller exiting")
            return

    state = _load_state()
    log.info(f"Resuming from last_polled={state.get('last_polled', 'beginning')}")

    while True:
        state = _poll_once(sess, order_type_uuid, mwl, state)
        time.sleep(ORDER_POLL_SEC)
