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
# PIH EMR concepts often encode modality in parentheses, e.g. "Abdomen, 1-2 organs (US)"
_MODALITY_MAP = [
    ("ultrasound", "US"),
    ("echo",       "US"),
    ("(us)",       "US"),   # PIH EMR suffix pattern
    ("ct ",        "CT"),
    (" ct",        "CT"),
    ("(ct)",       "CT"),
    ("computed",   "CT"),
    ("mri",        "MR"),
    ("magnetic",   "MR"),
    ("(mr)",       "MR"),
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

def _fetch_patient_full(sess: requests.Session, patient_uuid: str) -> dict:
    """Fetch full patient resource (with person demographics) by UUID."""
    try:
        r = sess.get(f"{OPENMRS_URL}/ws/rest/v1/patient/{patient_uuid}",
                     params={"v": "full"}, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log.warning(f"Could not fetch patient {patient_uuid}: {e}")
        return {}


def _extract_patient_info(patient: dict, sess: requests.Session | None = None) -> tuple[str, str, str, str]:
    """Return (patient_id, patient_name, dob, sex) from a patient resource.

    The order endpoint with v=full returns only a patient reference
    (uuid + display), not the full patient. If person demographics are
    missing we parse the display string and optionally do a follow-up
    fetch for DOB/sex.
    """
    display = patient.get("display", "")  # e.g. "GTLE29 - Tau, Thabo"

    # ── Patient ID ────────────────────────────────────────────────────
    identifiers = patient.get("identifiers") or []
    patient_id = ""
    for ident in identifiers:
        if not ident.get("voided", False):
            patient_id = ident.get("identifier", "")
            break
    if not patient_id:
        patient_id = display.split(" - ")[0].strip() if " - " in display else display

    # ── Name ──────────────────────────────────────────────────────────
    person = patient.get("person") or {}
    full_name = person.get("display", "")

    if not full_name and " - " in display:
        # Parse "GTLE29 - Tau, Thabo" → "Tau, Thabo" → "Tau^Thabo"
        name_part = display.split(" - ", 1)[1].strip()
        if "," in name_part:
            last, first = name_part.split(",", 1)
            full_name = f"{last.strip()}^{first.strip()}"
        else:
            full_name = name_part

    if full_name and "^" not in full_name:
        # Plain "First Last" → "Last^First"
        parts = full_name.strip().split()
        if len(parts) >= 2:
            full_name = f"{parts[-1]}^{' '.join(parts[:-1])}"

    # ── DOB + sex — follow-up fetch if missing ────────────────────────
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

def _process_order(order: dict, mwl: MwlManager, sess: requests.Session | None = None):
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
    patient_id, patient_name, dob, sex = _extract_patient_info(patient, sess)

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
    """Fetch orders since last_polled, process new ones, return updated state.

    PIH OpenMRS rejects /order?orderType=UUID without a patient parameter.
    Workaround: query by activatedOnOrAfterDate only (works without patient),
    then filter client-side to radiology orders only.
    """
    last_polled = state.get("last_polled")  # ISO 8601 string or None

    # activatedOnOrAfterDate alone is accepted; orderType alone is not (400).
    params: dict = {"v": "full", "limit": 100}
    if last_polled:
        params["activatedOnOrAfterDate"] = last_polled
    else:
        # First run: only look back 24 hours to avoid replaying old orders.
        from datetime import timedelta
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%S.000%z")
        params["activatedOnOrAfterDate"] = cutoff

    try:
        r = sess.get(f"{OPENMRS_URL}/ws/rest/v1/order", params=params, timeout=15)
        r.raise_for_status()
    except requests.RequestException as e:
        log.error(f"OpenMRS REST poll failed: {e}")
        return state

    all_orders = r.json().get("results", [])
    # Filter to radiology orders only
    orders = [o for o in all_orders if (o.get("orderType") or {}).get("uuid") == order_type_uuid]
    if len(all_orders) != len(orders):
        log.debug(f"Filtered {len(all_orders)} total orders → {len(orders)} radiology orders")
    log.debug(f"Poll returned {len(orders)} orders (since {last_polled or 'beginning'})")

    # Track the latest dateActivated we've seen
    max_activated = last_polled

    for order in orders:
        date_activated = order.get("dateActivated") or ""

        # Skip stopped/discontinued orders
        if order.get("dateStopped"):
            log.debug(f"Skipping stopped order {order.get('uuid')}")
            if date_activated and (max_activated is None or date_activated > max_activated):
                max_activated = date_activated
            continue

        try:
            _process_order(order, mwl, sess)
        except Exception as e:
            log.error(f"Failed to process order {order.get('uuid')}: {e}", exc_info=True)

        if date_activated and (max_activated is None or date_activated > max_activated):
            max_activated = date_activated

    if max_activated and max_activated != last_polled:
        # Advance by 1 second so the next poll's activatedOnOrAfterDate
        # excludes this boundary order (the endpoint is inclusive).
        try:
            dt = datetime.fromisoformat(max_activated.replace("Z", "+00:00"))
            from datetime import timedelta
            dt += timedelta(seconds=1)
            state["last_polled"] = dt.isoformat()
        except Exception:
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

    # Resolve order type UUID — retry indefinitely so startup order doesn't matter
    order_type_uuid = _ORDER_TYPE_UUID_ENV
    if not order_type_uuid:
        attempt = 0
        while not order_type_uuid:
            attempt += 1
            try:
                order_type_uuid = _lookup_radiology_order_type(sess)
            except Exception as e:
                log.warning(f"Order type lookup failed (attempt {attempt}), retrying in 15s: {e}")
                time.sleep(15)

    state = _load_state()
    log.info(f"Resuming from last_polled={state.get('last_polled', 'beginning')}")

    while True:
        state = _poll_once(sess, order_type_uuid, mwl, state)
        time.sleep(ORDER_POLL_SEC)
