"""
hl7_orders.py — AdvaPACS orders over HL7 (the gateway's Inbound HL7 Service, MLLP).

Why HL7: AdvaPACS gives an order created by HL7 the Inbound HL7 Service's
"AdvaPACS Worklist Status" (Ready to Report → Unread board) once it is completed;
an order created through the FHIR API enters the reporting worklist as Draft
(issues/advapacs-fhir-orders-enter-worklist-as-draft.md). AdvaPACS also rejects
FHIR updates to HL7-created orders, so completing and cancelling them goes over
HL7 too.

Messages follow docs.advapacs.com/interfaces/hl7/workflows/procedure_scheduled
and procedure_updated: ORM^O01; accession OBR-18 (<= 16 chars); placer ORC-2 /
OBR-2, filler ORC-3 / OBR-3; Study Instance UID ZDS-1 (how AdvaPACS finds the
order on update); modality OBR-24. New: ORC NW/SC. Completed: XO/CM. Cancel: CA/CA.
Every update repeats the original ORC/OBR, so the order details are kept here.

Also the sidecar's record of every order it has sent to AdvaPACS (HL7 or FHIR):
AdvaPACS rejects ?identifier= searches, so "already sent?" is answered locally.

Environment
-----------
HL7_GW_HOST   gateway host (default ADVAPACS_GW_HOST, else host.docker.internal)
HL7_GW_PORT   Inbound HL7 Service port (default 2576)
DICOM_ISSUER_OF_PATIENT_ID   PID-3 assigning authority (default PIH_A)
"""

import json
import logging
import os
import secrets
import socket
import threading
from datetime import datetime
from pathlib import Path

log = logging.getLogger("hl7_orders")

HOST   = os.getenv("HL7_GW_HOST") or os.getenv("ADVAPACS_GW_HOST") or "host.docker.internal"
PORT   = int(os.getenv("HL7_GW_PORT", "2576"))
ISSUER = os.getenv("DICOM_ISSUER_OF_PATIENT_ID") or "PIH_A"
STORE  = Path(os.getenv("ORDER_STATE_FILE", "/data/order_poller_state.json")).parent / "advapacs_orders.json"

_lock = threading.Lock()


# ── Record of orders sent ─────────────────────────────────────────────────────

def _load() -> dict:
    try:
        return json.loads(STORE.read_text())
    except (FileNotFoundError, ValueError):
        return {}


def get(accession: str) -> dict:
    with _lock:
        return _load().get(accession, {})


def record(accession: str, transport: str, **info) -> None:
    with _lock:
        d = _load()
        d[accession] = {**d.get(accession, {}), "transport": transport, **info,
                        "updated": datetime.now().astimezone().isoformat(timespec="seconds")}
        STORE.write_text(json.dumps(d, indent=1))


# ── HL7 ───────────────────────────────────────────────────────────────────────

def _esc(text: str) -> str:
    """HL7 v2 escaping for a single component."""
    return (str(text or "").replace("\\", "\\E\\").replace("|", "\\F\\")
            .replace("^", "\\S\\").replace("&", "\\T\\").replace("~", "\\R\\"))


def _message(o: dict, control: str, status: str) -> str:
    ts = datetime.now().astimezone().strftime("%Y%m%d%H%M%S%z")   # with offset (docs/timezones.md)
    acc, placer, filler = o["accession"], o["placer"], o["filler"]
    family, _, given = (o.get("patient_name") or "").partition("^")
    segs = [
        f"MSH|^~\\&|IMLADRIS|BOPHELONG|ADVAPACS|ADVAPACS|{ts}||ORM^O01|{secrets.token_hex(8)}|P|2.5.1",
        f"PID|1||{_esc(o['patient_id'])}^^^{_esc(ISSUER)}||{_esc(family)}^{_esc(given)}"
        f"||{o.get('dob', '')}|{o.get('sex', 'U')}",
        "PV1|1|O",
        f"ORC|{control}|{placer}|{filler}||{status}||^^^{o['scheduled']}",
        f"OBR|1|{placer}|{filler}|{_esc(o['code'])}^{_esc(o['procedure'])}^L|||{o['scheduled']}"
        f"|||||||||||{acc}|{acc}|{acc}||||{o['modality']}|||^^^{o['scheduled']}",
        f"ZDS|{o['study_uid']}^^Application^DICOM",
    ]
    return "\r".join(segs) + "\r"


def _send(msg: str) -> tuple[bool, str]:
    try:
        with socket.create_connection((HOST, PORT), timeout=15) as s:
            s.sendall(b"\x0b" + msg.encode("utf-8") + b"\x1c\x0d")
            ack = s.recv(65536).decode("utf-8", "replace").strip("\x0b\x1c\r")
    except OSError as e:
        return False, str(e)
    msa = next((seg for seg in ack.split("\r") if seg.startswith("MSA|")), "")
    return msa.split("|")[1:2] in (["AA"], ["CA"]), msa or ack[:200]


def create_order(accession: str, patient_id: str, patient_name: str, dob: str, sex: str,
                 procedure: str, modality: str, study_uid: str, code: str = "",
                 scheduled: str = "") -> bool:
    """New order (ORC NW/SC). Records it, with what later updates must repeat."""
    o = {
        "accession": accession, "placer": accession, "filler": accession,
        "patient_id": patient_id, "patient_name": patient_name, "dob": dob,
        "sex": sex if sex in ("M", "F", "O", "U") else "U",
        "procedure": procedure, "code": code or procedure.replace(" ", "_").upper()[:40],
        "modality": modality, "study_uid": study_uid,
        "scheduled": scheduled or datetime.now().astimezone().strftime("%Y%m%d%H%M%S%z"),
    }
    ok, ack = _send(_message(o, "NW", "SC"))
    if ok:
        record(accession, "hl7", order=o, status="scheduled")
        log.info(f"HL7 order created: {accession}  {modality}  {procedure}  patient={patient_id}")
    else:
        log.warning(f"HL7 order {accession} not accepted by {HOST}:{PORT}: {ack}")
    return ok


def _update(accession: str, control: str, status: str, label: str) -> bool:
    o = get(accession).get("order")
    if not o:
        log.warning(f"HL7 {label}: no record of order {accession}")
        return False
    ok, ack = _send(_message(o, control, status))
    if ok:
        record(accession, "hl7", status=label)
        log.info(f"HL7 order {label}: {accession}")
    else:
        log.warning(f"HL7 {label} for {accession} not accepted: {ack}")
    return ok


def complete_order(accession: str) -> bool:
    """Exam done (ORC XO/CM): the study enters the reporting worklist."""
    return _update(accession, "XO", "CM", "completed")


def cancel_order(accession: str) -> bool:
    """Order cancelled in OpenMRS (ORC CA/CA)."""
    return _update(accession, "CA", "CA", "cancelled")
