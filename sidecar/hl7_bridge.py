"""
hl7_bridge.py — Lightweight HL7 MLLP bridge (replaces Mirth Connect).

Inbound (from OpenMRS):
  Listens on MLLP_PORT (default 2575) for HL7 v2.3 messages.
  ORM^O01 (new order)    → creates DICOM worklist entry via MwlManager
  ORM^O01 (cancel/DC)   → deletes worklist entry
  ACK returned for every message.

Outbound (to OpenMRS):
  Polls Orthanc PACS /changes feed for StableStudy events.
  For each new study, sends HL7 ORU^R01 (result/status) to OpenMRS
  via MLLP at OPENMRS_HL7_HOST:OPENMRS_HL7_PORT.

Usage (standalone):
  python hl7_bridge.py

Or import run_forever() and schedule it in an asyncio loop.
"""

import asyncio
import logging
import os
import socket
from datetime import datetime, timezone

import hl7
import requests

from mwl_manager import MwlManager

log = logging.getLogger("hl7_bridge")

# ── Configuration ─────────────────────────────────────────────────────

MLLP_BIND_HOST   = os.getenv("MLLP_BIND_HOST",    "0.0.0.0")
MLLP_PORT        = int(os.getenv("MLLP_PORT",      "2575"))

OPENMRS_HL7_HOST = os.getenv("OPENMRS_HL7_HOST",  "openmrs")
OPENMRS_HL7_PORT = int(os.getenv("OPENMRS_HL7_PORT", "8066"))

PACS_URL         = os.getenv("PACS_URL",           "http://orthanc-pacs:8042")
PACS_USER        = os.getenv("PACS_USER",          "admin")
PACS_PASS        = os.getenv("PACS_PASSWORD",      "admin")

WL_FOLDER        = os.getenv("WL_FOLDER",          "/worklist")
MODALITY_AET     = os.getenv("MODALITY_AET",       "MODALITY_SIM")

CHANGE_POLL_SEC  = int(os.getenv("CHANGE_POLL_SEC", "15"))

# MLLP framing bytes
_SB = b"\x0b"          # Start Block
_EB = b"\x1c"          # End Block
_CR = b"\x0d"          # Carriage Return

# ── Shared state ──────────────────────────────────────────────────────

_mwl = MwlManager(WL_FOLDER, station_aet=MODALITY_AET)

# Map accession → {patient_id, patient_name, procedure_desc, modality}
# so we can reference it when sending ORU
_pending_orders: dict[str, dict] = {}

# Track last Orthanc change sequence seen
_last_change_seq: int = 0


# ── MLLP helpers ──────────────────────────────────────────────────────

async def _read_mllp_message(reader: asyncio.StreamReader) -> bytes:
    """Read one MLLP-framed message from the stream."""
    # Discard bytes until start-block
    while True:
        byte = await reader.read(1)
        if not byte:
            raise asyncio.IncompleteReadError(byte, 1)
        if byte == _SB:
            break
    # Read until end-block + CR
    buf = bytearray()
    while True:
        chunk = await reader.read(1)
        if not chunk:
            raise asyncio.IncompleteReadError(chunk, 1)
        if chunk == _EB:
            await reader.read(1)   # consume trailing CR
            break
        buf.extend(chunk)
    return bytes(buf)


def _wrap_mllp(hl7_str: str) -> bytes:
    return _SB + hl7_str.encode("latin-1") + _EB + _CR


async def _send_mllp(host: str, port: int, hl7_str: str, timeout: float = 10.0):
    """Open a short-lived MLLP connection and send one message."""
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=timeout
        )
        writer.write(_wrap_mllp(hl7_str))
        await writer.drain()
        # Wait for ACK (best-effort — ignore parse errors)
        try:
            raw = await asyncio.wait_for(_read_mllp_message(reader), timeout=timeout)
            log.debug(f"ACK from {host}:{port}: {raw[:80]}")
        except Exception:
            pass
        writer.close()
        await writer.wait_closed()
    except Exception as e:
        log.error(f"MLLP send to {host}:{port} failed: {e}")


# ── MLLP server ───────────────────────────────────────────────────────

async def _handle_connection(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    peer = writer.get_extra_info("peername")
    log.info(f"HL7 connection from {peer}")
    try:
        while True:
            raw = await _read_mllp_message(reader)
            ack = _process_message(raw.decode("latin-1"))
            writer.write(_wrap_mllp(ack))
            await writer.drain()
    except asyncio.IncompleteReadError:
        pass
    except Exception as e:
        log.error(f"Connection error from {peer}: {e}")
    finally:
        writer.close()
        log.info(f"HL7 connection from {peer} closed")


def _process_message(raw: str) -> str:
    """Parse one HL7 message, dispatch, return ACK string."""
    try:
        msg = hl7.parse(raw)
    except Exception as e:
        log.error(f"HL7 parse error: {e}")
        return _make_ack("AE", "Parse error", "UNKNOWN")

    ctrl_id = _field(msg, "MSH", 10)
    msg_type = _field(msg, "MSH", 9)      # e.g. "ORM^O01"
    log.info(f"Received {msg_type}  ctrl={ctrl_id}")

    try:
        if msg_type.startswith("ORM"):
            _handle_orm(msg)
        else:
            log.warning(f"Unhandled message type: {msg_type}")
    except Exception as e:
        log.error(f"Message handling error: {e}", exc_info=True)
        return _make_ack("AE", str(e)[:80], ctrl_id)

    return _make_ack("AA", "", ctrl_id)


def _handle_orm(msg: hl7.Message):
    """Handle ORM^O01 — extract order, create or remove MWL entry."""

    # ORC-1: order control  (NW=new, CA=cancel, DC=discontinue, XO=change)
    order_control = _field(msg, "ORC", 1) or "NW"

    # Patient info from PID
    pid3 = _field(msg, "PID", 3)                    # Patient ID list (MRN^^^Site^MR)
    patient_id = pid3.split("^")[0] if pid3 else ""
    patient_name = _field(msg, "PID", 5)             # Family^Given^Middle
    dob  = _field(msg, "PID", 7)                     # YYYYMMDD
    sex  = _field(msg, "PID", 8)

    # Order info from OBR
    # OBR-4: Universal Service ID  (code^description^coding_system)
    obr4 = _field(msg, "OBR", 4)
    parts = obr4.split("^")
    procedure_id   = parts[0] if parts else obr4
    procedure_desc = parts[1] if len(parts) > 1 else obr4

    # OBR-24: Diagnostic service section ID (modality code)
    modality = _field(msg, "OBR", 24) or "CR"

    # Accession: OBR-18 (placer field 1) → ORC-3 (filler order #) → OBR-2
    accession = (
        _field(msg, "OBR", 18)
        or _field(msg, "ORC", 3)
        or _field(msg, "OBR", 2)
        or _field(msg, "ORC", 2)
    )
    if not accession:
        raise ValueError("Cannot determine accession number from ORM message")

    # Scheduled date/time from OBR-7 (observation date/time)
    obr7 = _field(msg, "OBR", 7)               # YYYYMMDDHHMMSS or YYYYMMDD
    scheduled_date = obr7[:8] if len(obr7) >= 8 else ""
    scheduled_time = obr7[8:14] if len(obr7) >= 14 else ""

    if order_control in ("CA", "DC", "OC"):
        # Cancel / discontinue
        _mwl.delete(accession)
        _pending_orders.pop(accession, None)
        log.info(f"Order cancelled: accession={accession}")
    else:
        # New or modified order
        _mwl.create(
            patient_id=patient_id,
            patient_name=patient_name,
            dob=dob,
            sex=sex,
            accession=accession,
            procedure_id=procedure_id,
            procedure_desc=procedure_desc,
            modality=modality,
            scheduled_date=scheduled_date or None,
            scheduled_time=scheduled_time or None,
        )
        _pending_orders[accession] = {
            "patient_id":    patient_id,
            "patient_name":  patient_name,
            "procedure_id":  procedure_id,
            "procedure_desc": procedure_desc,
            "modality":      modality,
            "placer_order":  _field(msg, "ORC", 2) or accession,
        }
        log.info(
            f"Order created: accession={accession}  "
            f"patient={patient_id}  {procedure_desc} ({modality})"
        )


# ── ACK builder ───────────────────────────────────────────────────────

def _make_ack(code: str, error_msg: str, ctrl_id: str) -> str:
    now = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return (
        f"MSH|^~\\&|IMLADRIS||OpenMRS||{now}||ACK|ACK{now}|P|2.3\r"
        f"MSA|{code}|{ctrl_id}|{error_msg}\r"
    )


# ── Orthanc PACS change watcher → ORU^R01 sender ─────────────────────

async def _watch_pacs_changes():
    """
    Polls Orthanc PACS /changes for StableStudy events and sends
    HL7 ORU^R01 to OpenMRS when a new study arrives.
    """
    global _last_change_seq
    auth = (PACS_USER, PACS_PASS)
    log.info(f"Orthanc PACS change watcher started ({PACS_URL}, poll={CHANGE_POLL_SEC}s)")

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
    """Fetch study metadata from PACS and send ORU^R01 to OpenMRS."""
    r = requests.get(f"{PACS_URL}/studies/{study_id}", auth=auth, timeout=10)
    r.raise_for_status()
    study = r.json()

    tags = study.get("MainDicomTags", {})
    patient_tags = study.get("PatientMainDicomTags", {})

    patient_id   = patient_tags.get("PatientID", "")
    patient_name = patient_tags.get("PatientName", "")
    accession    = tags.get("AccessionNumber", "")
    study_uid    = tags.get("StudyInstanceUID", "")
    study_desc   = tags.get("StudyDescription", "Study complete")
    study_date   = tags.get("StudyDate", datetime.now().strftime("%Y%m%d"))
    study_time   = tags.get("StudyTime", "000000")

    # Look up the original order for this accession (if we have it)
    order = _pending_orders.get(accession, {})
    placer_order  = order.get("placer_order", accession)
    procedure_id  = order.get("procedure_id", "PROC")
    procedure_desc = order.get("procedure_desc", study_desc)
    modality      = order.get("modality", tags.get("ModalitiesInStudy", "OT").split("\\")[0])

    oru = _build_oru(
        patient_id=patient_id,
        patient_name=patient_name,
        accession=accession,
        placer_order=placer_order,
        procedure_id=procedure_id,
        procedure_desc=procedure_desc,
        modality=modality,
        study_uid=study_uid,
        study_date=study_date,
        study_time=study_time,
    )

    log.info(
        f"Sending ORU^R01 to {OPENMRS_HL7_HOST}:{OPENMRS_HL7_PORT}  "
        f"accession={accession}  patient={patient_id}"
    )
    await _send_mllp(OPENMRS_HL7_HOST, OPENMRS_HL7_PORT, oru)

    # Remove from pending once we've notified OpenMRS
    _pending_orders.pop(accession, None)


# ── ORU^R01 builder ───────────────────────────────────────────────────

def _build_oru(
    patient_id, patient_name, accession, placer_order,
    procedure_id, procedure_desc, modality,
    study_uid, study_date, study_time,
) -> str:
    now = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    msg_id = f"ORU{now}"
    obs_time = f"{study_date}{study_time[:6]}"

    # OBX-5 observation value: a brief status note
    obs_value = f"Images available in PACS. StudyInstanceUID={study_uid}"

    return (
        f"MSH|^~\\&|IMLADRIS||OpenMRS||{now}||ORU^R01|{msg_id}|P|2.3\r"
        f"PID|1||{patient_id}^^^IMLADRIS^MR||{patient_name}||\r"
        f"OBR|1|{placer_order}|{accession}|{procedure_id}^{procedure_desc}^LOCAL"
        f"|||{obs_time}||||||||||||{modality}|||||||F\r"
        f"OBX|1|ST|{procedure_id}^{procedure_desc}^LOCAL||{obs_value}||||||F\r"
    )


# ── HL7 field helper ──────────────────────────────────────────────────

def _field(msg: hl7.Message, segment: str, index: int) -> str:
    """Return field value as str, or '' if absent."""
    try:
        return str(msg.segment(segment)[index]).strip()
    except Exception:
        return ""


# ── Entry point ───────────────────────────────────────────────────────

async def run_forever():
    """Start MLLP server and PACS change watcher. Runs indefinitely."""
    server = await asyncio.start_server(
        _handle_connection, MLLP_BIND_HOST, MLLP_PORT
    )
    log.info(f"MLLP listener on {MLLP_BIND_HOST}:{MLLP_PORT}")
    async with server:
        await asyncio.gather(
            server.serve_forever(),
            _watch_pacs_changes(),
        )


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    asyncio.run(run_forever())
