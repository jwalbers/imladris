"""
modality_console_web.py — Imladris Modality Console (web UI)

A browser-based modality simulator console.  Shows pending worklist
entries for this modality and lets a radiology technician simulate
image acquisition with one click.

Orthanc-free: reads .wl files directly, C-STOREs via pynetdicom.

Routes
------
GET  /                     Worklist page (all modalities)
GET  /?modality=CR         Filtered to X-ray / CR items only
GET  /?modality=US         Filtered to Ultrasound items only
POST /acquire/<accession>  Simulate acquisition for one worklist item
GET  /status               JSON health check
POST /webhook/advapacs     AdvaPACS outbound webhook receiver
GET  /events               Webhook event log page
GET  /events/json          Recent webhook events as JSON (for polling)

Environment
-----------
WL_FOLDER            /worklist
HOSPITAL_RECORDS     /hospital-records
ADVAPACS_GW_HOST     host.docker.internal
ADVAPACS_GW_PORT     11112
ADVAPACS_GW_AE       ADVAPACS_GW
QURE_HOST            imladris-qure-sim
QURE_PORT            5252
QURE_AE              QUREAI
ENABLE_QURE          true   (set false to skip qure-sim for non-CR acquisitions)
CONSOLE_PORT         5001
WEBHOOK_SECRET       (optional) bearer token AdvaPACS sends in Authorization header

Network note
------------
AdvaPACS cloud cannot reach host.docker.internal directly.  To receive webhooks,
expose port 5001 via ngrok on BESSIE:
    ngrok http 5001
Then set the AdvaPACS webhook Endpoint URL to the ngrok https:// URL +
/webhook/advapacs  (e.g. https://abc123.ngrok.io/webhook/advapacs).
"""

import json
import logging
import os
import threading
from collections import deque
from datetime import datetime
from pathlib import Path

import requests

import pydicom
from flask import Flask, jsonify, render_template_string, request, send_file
from mwl_manager import MwlManager
from pydicom.uid import ExplicitVRLittleEndian, generate_uid

import dicom_client as dc
import acquisition_loop as _acq
import hl7_bridge

log = logging.getLogger("console_web")

# ── Config ────────────────────────────────────────────────────────────────────

WL_FOLDER    = Path(os.getenv("WL_FOLDER",    "/worklist"))
CONSOLE_PORT = int(os.getenv("CONSOLE_PORT",  "5001"))
INSTITUTION  = os.getenv("INSTITUTION",       "Bophelong MDR-TB Hospital")
CR_AET       = os.getenv("CR_AET",            "IML_CR_01")
US_AET       = os.getenv("US_AET",            "IML_US_01")
CT_AET       = os.getenv("CT_AET",            "IML_CT_01")

mwl = MwlManager(str(WL_FOLDER))

WEBHOOK_SECRET  = os.getenv("WEBHOOK_SECRET", "")
FHIR_BASE_URL   = os.getenv("FHIR_BASE_URL",   "https://usa1.api.integration.advapacs.com/fhir/R5")
FHIR_KEY_ID     = os.getenv("FHIR_KEY_ID",     "")
FHIR_KEY_SECRET = os.getenv("FHIR_KEY_SECRET", "")

# Order state label and color per FHIR ServiceRequest status
_STATUS_META: dict[str, tuple[str, str]] = {
    "draft":            ("Pending Review", "#5aafff"),
    "active":           ("Approved",      "#4dcc70"),
    "on-hold":          ("On Hold",     "#ffaa44"),
    "completed":        ("Completed",   "#7a8aaa"),
    "revoked":          ("Cancelled",   "#ff6666"),
    "entered-in-error": ("Error",       "#ff4444"),
    "unknown":          ("Unknown",     "#4a5570"),
}

_ORDER_STATES_FILE = Path(
    os.getenv("ORDER_STATE_FILE", "/data/order_poller_state.json")
).parent / "order_states.json"

_IMAGEABLE_STATUSES = {"active"}

MODALITY_LABELS = {
    "CR": "X-Ray",
    "DX": "X-Ray",
    "US": "Ultrasound",
    "CT": "CT Scanner",
    "MR": "MRI",
}

app = Flask(__name__)

# Ring buffer of recent AdvaPACS webhook events (survives only until container restart)
_webhook_events: deque = deque(maxlen=50)

# Order state cache — accession → order info dict; persisted across restarts
def _load_order_states() -> dict:
    try:
        with open(_ORDER_STATES_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def _persist_order_states() -> None:
    try:
        with open(_ORDER_STATES_FILE, "w") as f:
            json.dump(_order_states, f)
    except Exception as e:
        log.warning(f"Could not persist order states: {e}")

_order_states: dict = _load_order_states()


@app.route('/favicon.ico')
def favicon():
    return send_file('favicon.ico', mimetype='image/vnd.microsoft.icon')


# ── Worklist helpers ──────────────────────────────────────────────────────────

def _get_worklist(modality_filter: str | None = None) -> list[dict]:
    """Return all orders: .wl files merged with _order_states, each with status."""
    entries: dict[str, dict] = {}

    # --- Primary source: .wl files (authoritative for draft/active orders) ---
    for wl_file in sorted(WL_FOLDER.glob("*.wl")):
        try:
            ds = pydicom.dcmread(str(wl_file), force=True)
        except Exception as e:
            log.debug(f"Skipping {wl_file.name}: {e}")
            continue

        sps_seq = getattr(ds, "ScheduledProcedureStepSequence", [])
        sps = sps_seq[0] if sps_seq else pydicom.Dataset()
        mod = str(getattr(sps, "Modality", ""))
        if modality_filter and mod.upper() != modality_filter.upper():
            continue

        raw_date = str(getattr(sps, "ScheduledProcedureStepStartDate", ""))
        raw_time = str(getattr(sps, "ScheduledProcedureStepStartTime", ""))
        try:
            scheduled = datetime.strptime(raw_date, "%Y%m%d").strftime("%Y-%m-%d") if raw_date else ""
        except ValueError:
            scheduled = raw_date
        scheduled_time = raw_time[:2] + ":" + raw_time[2:4] if len(raw_time) >= 4 else raw_time

        _raw_name = str(getattr(ds, "PatientName", ""))
        acc = str(getattr(ds, "AccessionNumber", ""))

        # Status from webhook cache if present, otherwise assume draft
        state = _order_states.get(acc, {})
        status = state.get("status", "draft")
        status_label, status_color = _STATUS_META.get(status, ("Pending Review", "#5aafff"))

        entries[acc] = {
            "id":                 wl_file.stem,
            "patient_name":       _raw_name.replace("^", " ").strip(),
            "patient_name_dicom": _raw_name,
            "patient_id":         str(getattr(ds, "PatientID", "")),
            "dob":                str(getattr(ds, "PatientBirthDate", "")),
            "sex":                str(getattr(ds, "PatientSex", "")),
            "accession":          acc,
            "procedure":          str(getattr(ds, "RequestedProcedureDescription", "")),
            "modality":           mod,
            "scheduled":          scheduled,
            "scheduled_time":     scheduled_time,
            "order_created_sort": (raw_date + raw_time)[:14],
            "study_uid":          str(getattr(ds, "StudyInstanceUID", "")),
            "status":             status,
            "status_label":       status_label,
            "status_color":       status_color,
        }

    # --- Secondary source: webhook state cache (completed/revoked/on-hold not in .wl) ---
    for acc, state in _order_states.items():
        if acc in entries:
            continue  # already covered by .wl file above
        if modality_filter and state.get("modality", "").upper() != modality_filter.upper():
            continue
        status = state.get("status", "unknown")
        status_label, status_color = _STATUS_META.get(status, ("Unknown", "#4a5570"))
        updated = state.get("updated_at", "")
        sort_key = updated[:16].replace("-", "").replace("T", "").replace(":", "")
        entries[acc] = {
            "id":                 acc,
            "patient_name":       state.get("patient_name", ""),
            "patient_name_dicom": state.get("patient_name_dicom", ""),
            "patient_id":         state.get("patient_id", ""),
            "dob":                state.get("patient_dob", ""),
            "sex":                state.get("patient_sex", ""),
            "accession":          acc,
            "procedure":          state.get("procedure", ""),
            "modality":           state.get("modality", ""),
            "scheduled":          "",
            "scheduled_time":     "",
            "order_created_sort": sort_key,
            "study_uid":          "",
            "status":             status,
            "status_label":       status_label,
            "status_color":       status_color,
        }

    return list(entries.values())


# ── Acquisition ───────────────────────────────────────────────────────────────

def _aet_for(modality: str) -> str:
    return {"US": US_AET, "CT": CT_AET}.get(modality.upper(), CR_AET)


def _acquire_and_send(entry: dict) -> dict:
    """
    Pull source DICOM from library, patch with MWL demographics,
    C-STORE primary to AdvaPACS gateway, and (for CR) also to qure-sim
    so the scp_relay receives the SC and forwards it automatically.
    """
    files = dc.find_study_files(entry["patient_id"], entry["modality"])
    if not files:
        return {"ok": False, "error": f"No source image for patient {entry['patient_id']} modality {entry['modality']}"}

    fallback = (files[0].parent.name != entry["patient_id"])

    now      = datetime.now()
    date_str = now.strftime("%Y%m%d")
    time_str = now.strftime("%H%M%S")
    modality = entry.get("modality", "CR")
    study_uid = entry.get("study_uid") or generate_uid()

    patched = []
    series_uid = generate_uid()
    for i, path in enumerate(files, start=1):
        ds = pydicom.dcmread(str(path))

        ds.PatientName          = entry["patient_name_dicom"]
        ds.PatientID            = entry["patient_id"]
        ds.PatientBirthDate     = entry.get("dob", "")
        ds.PatientSex           = entry.get("sex", "")
        ds.StudyInstanceUID     = study_uid
        ds.StudyDate            = entry.get("scheduled", "").replace("-", "") or date_str
        ds.StudyTime            = time_str
        ds.StudyDescription     = entry.get("procedure", "Radiology Study")
        ds.AccessionNumber      = entry.get("accession", "")
        ds.SeriesInstanceUID    = series_uid
        ds.SeriesDate           = date_str
        ds.SeriesTime           = time_str
        ds.SeriesDescription    = entry.get("procedure", "Radiology Study")
        ds.SeriesNumber         = "1"
        ds.SOPInstanceUID       = generate_uid()
        ds.InstanceNumber       = str(i)
        ds.ContentDate          = date_str
        ds.ContentTime          = time_str
        ds.Modality             = modality
        ds.InstitutionName      = INSTITUTION

        if hasattr(ds, "file_meta"):
            ds.file_meta.MediaStorageSOPInstanceUID = ds.SOPInstanceUID
            ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
            ds.file_meta.SourceApplicationEntityTitle = _aet_for(modality)

        patched.append(ds)

    calling_ae = _aet_for(modality)

    # Send primary to AdvaPACS gateway
    sent = dc.cstore_to(patched, dc.ADVAPACS_GW_HOST, dc.ADVAPACS_GW_PORT,
                        dc.ADVAPACS_GW_AE, calling_ae)
    log.info(f"Sent {sent}/{len(patched)} instance(s) → AdvaPACS  study={study_uid[:24]}…")

    # For CR: also send to qure-sim; scp_relay will forward the SC to AdvaPACS
    if modality.upper() in ("CR", "DX") and dc.ENABLE_QURE:
        try:
            dc.cstore_to(patched, dc.QURE_HOST, dc.QURE_PORT, dc.QURE_AE, calling_ae)
            log.info(f"Sent primary → qure-sim; SC will be relayed to AdvaPACS")
        except Exception as e:
            log.warning(f"qure-sim send failed (SC skipped): {e}")

    return {
        "ok":       True,
        "source":   files[0].name,
        "fallback": fallback,
        "study_uid": study_uid,
        "instances": sent,
    }


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def worklist_page():
    modality = request.args.get("modality", "").upper() or None
    entries  = _get_worklist(modality)
    label    = MODALITY_LABELS.get(modality, "Radiology") if modality else "All Modalities"
    return render_template_string(
        _HTML_TEMPLATE,
        entries=entries,
        modality=modality or "",
        label=label,
        now=datetime.now().strftime("%Y-%m-%d %H:%M"),
        cr_aet=CR_AET,
        us_aet=US_AET,
    )


@app.route("/acquire/<accession>", methods=["POST"])
def acquire(accession: str):
    modality = request.json.get("modality", "CR") if request.is_json else "CR"
    entries  = _get_worklist()
    entry    = next((e for e in entries if e["accession"] == accession), None)

    if not entry:
        return jsonify({"ok": False, "error": f"Accession {accession} not found in worklist"}), 404

    if accession in _acq._sent:
        return jsonify({"ok": False, "error": f"Already acquired: {accession}"}), 409

    try:
        result = _acquire_and_send(entry)
    except Exception as e:
        log.error(f"Acquire failed for {accession}: {e}", exc_info=True)
        return jsonify({"ok": False, "error": str(e)}), 500

    if result["ok"]:
        log.info(
            f"Acquired: {entry['patient_name']} ({entry['patient_id']}) "
            f"{entry['procedure']}  instances={result['instances']}  study={result['study_uid'][:24]}…"
        )
        _acq._sent.add(accession)
        _acq._persist_sent(accession)
    return jsonify(result)


@app.route("/remove/<accession>", methods=["POST"])
def remove(accession: str):
    ok = mwl.dismiss(accession)
    return jsonify({"ok": ok})


@app.route("/status")
def status():
    import socket
    try:
        s = socket.create_connection((dc.ADVAPACS_GW_HOST, dc.ADVAPACS_GW_PORT), timeout=3)
        s.close()
        gw_ok = True
    except Exception:
        gw_ok = False
    hr = dc.HOSPITAL_RECORDS
    return jsonify({
        "advapacs_gateway": gw_ok,
        "hospital_records": hr.exists(),
        "wl_count": len(list(WL_FOLDER.glob("*.wl"))),
    })


# ── AdvaPACS order event handler ─────────────────────────────────────────────

def _fhir_auth() -> dict:
    return {"Authorization": f"ID={FHIR_KEY_ID},Secret={FHIR_KEY_SECRET}",
            "Accept": "application/fhir+json"}

def _guess_modality(text: str) -> str:
    t = text.lower()
    for kw, code in [("ultrasound","US"),("echo","US"),("ct ","CT"),(" ct","CT"),
                     ("computed","CT"),("mri","MR"),("magnetic","MR"),("fluoro","RF")]:
        if kw in t:
            return code
    return "CR"


def _fetch_and_handle_sr(sr_id: str, event_type: str):
    """Fetch ServiceRequest from AdvaPACS FHIR; update order_states; ORU if completed."""
    try:
        base = FHIR_BASE_URL.rstrip("/")
        auth = _fhir_auth()

        r = requests.get(f"{base}/ServiceRequest/{sr_id}", headers=auth, timeout=10)
        r.raise_for_status()
        sr = r.json()

        status = sr.get("status", "unknown")
        log.info(f"{event_type} {sr_id}: status={status}")

        # Accession number
        accession = next(
            (i.get("value", "") for i in sr.get("identifier", [])
             if "accession" in i.get("system", "").lower()),
            sr.get("identifier", [{}])[0].get("value", sr_id[:8])
        )

        # Procedure description
        code      = sr.get("code", {})
        procedure = (code.get("text") or
                     next((c.get("display","") for c in code.get("coding",[])), "") or
                     "Radiology Study")

        # Modality — try orderDetail coding first, fall back to keyword guess
        modality = ""
        for od in sr.get("orderDetail", []):
            for param in od.get("parameter", []):
                val = param.get("valueCoding", {})
                code_val = val.get("code", "")
                if code_val.upper() in {"CR","DX","CT","MR","US","RF","NM","PT","MG","XA"}:
                    modality = code_val.upper()
                    break
        if not modality:
            modality = _guess_modality(procedure)

        # Patient details via subject reference
        patient_id = patient_name = patient_name_dicom = dob = sex = ""
        subject_ref = sr.get("subject", {}).get("reference", "")
        if subject_ref:
            pr = requests.get(f"{base}/{subject_ref.lstrip('/')}", headers=auth, timeout=10)
            if pr.ok:
                patient = pr.json()
                patient_id = next(
                    (i.get("value","") for i in patient.get("identifier",[])
                     if i.get("system") == "http://openmrs.org/identifier"),
                    ""
                )
                names  = patient.get("name", [{}])
                n      = names[0] if names else {}
                family = n.get("family", "")
                given  = " ".join(n.get("given", []))
                patient_name_dicom = f"{family}^{given}" if given else family
                patient_name = patient_name_dicom.replace("^", " ").strip()
                dob = patient.get("birthDate", "").replace("-", "")[:8]
                sex = {"male": "M", "female": "F", "other": "O"}.get(
                    patient.get("gender", "").lower(), "")

        # Update persistent order state cache
        _order_states[accession] = {
            "accession":          accession,
            "sr_id":              sr_id,
            "patient_id":         patient_id,
            "patient_name":       patient_name,
            "patient_name_dicom": patient_name_dicom,
            "patient_dob":        dob,
            "patient_sex":        sex,
            "procedure":          procedure,
            "modality":           modality,
            "status":             status,
            "updated_at":         datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        _persist_order_states()
        log.info(f"Order state: accession={accession} patient={patient_id} status={status}")

        # Send ORU^R01 to OpenMRS when study is complete
        if status == "completed":
            now = datetime.now()
            oru = hl7_bridge._build_oru(
                patient_id=patient_id,
                patient_name=patient_name_dicom,
                accession=accession,
                procedure_desc=procedure,
                modality=modality or "OT",
                study_uid="",
                study_date=now.strftime("%Y%m%d"),
                study_time=now.strftime("%H%M%S"),
            )
            log.info(f"Sending ORU^R01: accession={accession} patient={patient_id}")
            hl7_bridge._send_hl7_rest(oru)

    except Exception as e:
        log.error(f"Order event handler failed for {sr_id}: {e}", exc_info=True)


def _handle_order_event(event_type: str, payload: dict):
    sr_id = payload.get("data", {}).get("id")
    if not sr_id:
        log.warning(f"Webhook {event_type}: missing data.id")
        return
    threading.Thread(
        target=_fetch_and_handle_sr, args=(sr_id, event_type), daemon=True
    ).start()


# ── Webhook routes ────────────────────────────────────────────────────────────

@app.route("/webhook/advapacs", methods=["POST"])
def webhook_advapacs():
    if WEBHOOK_SECRET:
        auth = request.headers.get("Authorization", "")
        if auth != f"Bearer {WEBHOOK_SECRET}":
            return jsonify({"error": "Unauthorized"}), 401

    try:
        payload = request.get_json(force=True, silent=True) or {}
    except Exception:
        payload = {}

    event_type = payload.get("eventType") or payload.get("event") or "unknown"
    received_at = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

    event = {
        "receivedAt": received_at,
        "eventType":  event_type,
        "payload":    payload,
    }
    _webhook_events.appendleft(event)
    log.info(f"Webhook received: {event_type}  src={request.remote_addr}  payload={json.dumps(payload)[:200]}")

    if event_type in ("ORDER_CREATED", "ORDER_UPDATED"):
        _handle_order_event(event_type, payload)

    return jsonify({"ok": True}), 200


@app.route("/events/json")
def events_json():
    return jsonify(list(_webhook_events))


@app.route("/events")
def events_page():
    return render_template_string(_EVENTS_TEMPLATE)


# ── HTML template ─────────────────────────────────────────────────────────────

_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>Bophelong {{ label }} Console</title>
  <link rel="icon" href="/favicon.ico">
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }

    body {
      font-family: 'Segoe UI', Arial, sans-serif;
      background: #1a1f2e;
      color: #e0e4ef;
      min-height: 100vh;
    }

    header {
      background: #0d111d;
      border-bottom: 2px solid #2a7fff;
      padding: 14px 24px;
      display: flex;
      align-items: center;
      justify-content: space-between;
    }
    header .title { font-size: 1.25rem; font-weight: 600; color: #fff; letter-spacing: 0.04em; }
    header .subtitle { font-size: 0.8rem; color: #7a8aaa; margin-top: 2px; }
    header .clock { font-size: 0.85rem; color: #7a8aaa; text-align: right; }

    nav {
      background: #141829;
      padding: 10px 24px;
      display: flex;
      gap: 8px;
      border-bottom: 1px solid #252d45;
    }
    nav a {
      color: #7a8aaa;
      text-decoration: none;
      padding: 5px 14px;
      border-radius: 4px;
      font-size: 0.85rem;
      border: 1px solid #252d45;
    }
    nav a:hover { background: #1e253a; color: #c0cce8; }
    nav a.active { background: #1a3a6a; color: #5aafff; border-color: #2a7fff; }

    main { padding: 20px 24px; }

    .worklist-header {
      display: flex;
      align-items: baseline;
      gap: 12px;
      margin-bottom: 14px;
    }
    .worklist-header h2 { font-size: 1rem; font-weight: 600; color: #c0cce8; }
    .worklist-header .count {
      font-size: 0.8rem;
      color: #7a8aaa;
      background: #1e253a;
      padding: 2px 8px;
      border-radius: 10px;
    }
    .refresh-btn {
      margin-left: auto;
      background: none;
      border: 1px solid #2a4a7a;
      color: #5aafff;
      padding: 4px 14px;
      border-radius: 4px;
      cursor: pointer;
      font-size: 0.8rem;
    }
    .refresh-btn:hover { background: #1a3a6a; }

    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 0.85rem;
    }
    thead tr { background: #141829; }
    thead th {
      text-align: left;
      padding: 9px 12px;
      color: #7a8aaa;
      font-weight: 500;
      font-size: 0.75rem;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      border-bottom: 1px solid #252d45;
      white-space: nowrap;
    }
    thead th.sortable {
      cursor: pointer;
      user-select: none;
    }
    thead th.sortable:hover { color: #c0cce8; }
    thead th .sort-icon { margin-left: 4px; opacity: 0.4; font-style: normal; }
    thead th.asc  .sort-icon::after { content: '▲'; opacity: 1; }
    thead th.desc .sort-icon::after { content: '▼'; opacity: 1; }
    thead th:not(.asc):not(.desc) .sort-icon::after { content: '⇅'; }
    tbody tr { border-bottom: 1px solid #1e253a; }
    tbody tr:hover { background: #1e253a; }
    tbody td { padding: 10px 12px; color: #c0cce8; vertical-align: middle; }
    tbody td.muted { color: #7a8aaa; font-size: 0.8rem; }

    .badge {
      display: inline-block;
      padding: 2px 8px;
      border-radius: 3px;
      font-size: 0.73rem;
      font-weight: 600;
      letter-spacing: 0.04em;
    }
    .badge-CR, .badge-DX { background: #162a4a; color: #5aafff; }
    .badge-US { background: #1a3a20; color: #4dcc70; }
    .badge-CT { background: #3a2010; color: #ffaa44; }
    .badge-MR { background: #2a1a3a; color: #bb77ff; }

    .status-badge {
      display: inline-block;
      padding: 2px 9px;
      border-radius: 3px;
      font-size: 0.72rem;
      font-weight: 600;
      letter-spacing: 0.04em;
      background: rgba(255,255,255,0.07);
    }

    .btn-filter {
      background: none;
      border: 1px solid #2a4a7a;
      color: #7a8aaa;
      padding: 4px 14px;
      border-radius: 4px;
      cursor: pointer;
      font-size: 0.8rem;
      margin-left: 6px;
    }
    .btn-filter:hover { background: #1e253a; color: #c0cce8; }
    .btn-filter.active-filter { border-color: #5aafff; color: #5aafff; background: #1a3a6a; }

    .btn-acquire {
      background: #155a28;
      color: #4dcc70;
      border: 1px solid #1e7a38;
      padding: 6px 16px;
      border-radius: 4px;
      cursor: pointer;
      font-size: 0.82rem;
      font-weight: 600;
      white-space: nowrap;
    }
    .btn-acquire:hover:not(:disabled) { background: #1a7032; }
    .btn-acquire:disabled { opacity: 0.4; cursor: default; }
    .btn-acquire.working { background: #1a3a6a; color: #5aafff; border-color: #2a5a9a; }
    .btn-acquire.done    { background: #0d2a10; color: #2a8a3a; border-color: #1a5a25; }
    .btn-acquire.error   { background: #3a1010; color: #ff6666; border-color: #7a2020; }
    .btn-remove {
      font-size: 0.72rem; padding: 4px 10px; border-radius: 4px; cursor: pointer;
      background: #2a1010; color: #cc6666; border: 1px solid #7a2020;
      margin-left: 6px; display: none;
    }
    .btn-remove:hover { background: #3a1515; }

    .status-msg {
      font-size: 0.78rem;
      color: #7a8aaa;
      margin-top: 3px;
    }
    .status-msg.ok    { color: #4dcc70; }
    .status-msg.error { color: #ff6666; }

    .empty-state {
      text-align: center;
      padding: 48px 24px;
      color: #4a5570;
    }
    .empty-state .icon { font-size: 2.5rem; margin-bottom: 12px; }
    .empty-state p { font-size: 0.9rem; }

    .log-section { margin-top: 24px; }
    .log-section h3 {
      font-size: 0.75rem;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      color: #4a5570;
      margin-bottom: 8px;
    }
    #activity-log {
      background: #0d111d;
      border: 1px solid #1e253a;
      border-radius: 4px;
      padding: 10px 14px;
      font-family: monospace;
      font-size: 0.78rem;
      color: #6a8aaa;
      min-height: 80px;
      max-height: 160px;
      overflow-y: auto;
    }
    #activity-log .entry { margin-bottom: 3px; }
    #activity-log .entry.ok    { color: #4dcc70; }
    #activity-log .entry.error { color: #ff6666; }
    #activity-log .entry.info  { color: #5aafff; }
  </style>
</head>
<body>

<header>
  <div>
    <div class="title">Bophelong Hospital — {{ label }} Console</div>
    <div class="subtitle">Imladris Virtual Integration Lab  ·  AE: {{ cr_aet }} / {{ us_aet }}</div>
  </div>
  <div class="clock" id="clock">{{ now }}</div>
</header>

<nav>
  <a href="/" class="{{ 'active' if not modality else '' }}">All</a>
  <a href="/?modality=CR" class="{{ 'active' if modality == 'CR' else '' }}">X-Ray (CR)</a>
  <a href="/?modality=US" class="{{ 'active' if modality == 'US' else '' }}">Ultrasound (US)</a>
  <a href="/?modality=CT" class="{{ 'active' if modality == 'CT' else '' }}">CT</a>
  <a href="/events" style="margin-left:auto">Events</a>
</nav>

<main>
  <div class="worklist-header">
    <h2>Scheduled Exams — Modality Worklist</h2>
    <span class="count" id="order-count">{{ entries|length }} orders</span>
    <button class="btn-filter active-filter" id="filter-btn" onclick="toggleFilter()">Active Orders</button>
    <button class="refresh-btn" onclick="location.reload()">⟳ Refresh</button>
  </div>

  {% if entries %}
  <table id="wl-table">
    <thead>
      <tr>
        <th class="sortable" data-col="0">Patient <i class="sort-icon"></i></th>
        <th class="sortable" data-col="1">ID <i class="sort-icon"></i></th>
        <th class="sortable" data-col="2">Modality <i class="sort-icon"></i></th>
        <th class="sortable" data-col="3">Procedure <i class="sort-icon"></i></th>
        <th class="sortable desc" data-col="4">Order Created <i class="sort-icon"></i></th>
        <th class="sortable" data-col="5">Accession <i class="sort-icon"></i></th>
        <th class="sortable" data-col="6">Status <i class="sort-icon"></i></th>
        <th>Action</th>
      </tr>
    </thead>
    <tbody>
    {% for e in entries %}
      <tr id="row-{{ e.accession }}"
          data-status="{{ e.status }}"
          data-col0="{{ e.patient_name }}"
          data-col1="{{ e.patient_id }}"
          data-col2="{{ e.modality }}"
          data-col3="{{ e.procedure }}"
          data-col4="{{ e.order_created_sort }}"
          data-col5="{{ e.accession }}"
          data-col6="{{ e.status_label }}">
        <td>{{ e.patient_name or '—' }}</td>
        <td class="muted">{{ e.patient_id }}</td>
        <td>
          <span class="badge badge-{{ e.modality }}">{{ e.modality }}</span>
        </td>
        <td>{{ e.procedure }}</td>
        <td class="muted">{{ e.scheduled }}{% if e.scheduled_time %} {{ e.scheduled_time }}{% endif %}</td>
        <td class="muted" style="font-size:0.75rem">{{ e.accession }}</td>
        <td>
          <span class="status-badge" style="color: {{ e.status_color }}">{{ e.status_label }}</span>
        </td>
        <td>
          {% if e.status == 'active' %}
          <button
            class="btn-acquire"
            id="btn-{{ e.accession }}"
            onclick="acquire('{{ e.accession }}', '{{ e.modality }}')"
          >Image Patient</button>
          {% else %}
          <button class="btn-acquire" id="btn-{{ e.accession }}" disabled>Image Patient</button>
          {% endif %}
          <button
            class="btn-remove"
            id="rm-{{ e.accession }}"
            onclick="removeEntry('{{ e.accession }}')"
          >✕ Remove</button>
          <div class="status-msg" id="msg-{{ e.accession }}"></div>
        </td>
      </tr>
    {% endfor %}
    </tbody>
  </table>
  {% else %}
  <div class="empty-state">
    <div class="icon">📋</div>
    <p>No orders{% if modality %} for modality <strong>{{ modality }}</strong>{% endif %}.</p>
  </div>
  {% endif %}

  <div class="log-section">
    <h3>Activity Log</h3>
    <div id="activity-log"></div>
  </div>
</main>

<script>
  // Active/All filter
  const ACTIVE_STATUSES = new Set(['draft', 'active']);
  let filterActive = true;

  function filterRows() {
    const table = document.getElementById('wl-table');
    if (!table) return;
    let visible = 0;
    Array.from(table.tBodies[0].rows).forEach(r => {
      const show = !filterActive || ACTIVE_STATUSES.has(r.dataset.status);
      r.style.display = show ? '' : 'none';
      if (show) visible++;
    });
    const total = table.tBodies[0].rows.length;
    const countEl = document.getElementById('order-count');
    if (countEl) countEl.textContent = filterActive
      ? visible + ' active order' + (visible !== 1 ? 's' : '')
      : total + ' order' + (total !== 1 ? 's' : '');
  }

  function toggleFilter() {
    filterActive = !filterActive;
    const btn = document.getElementById('filter-btn');
    if (btn) {
      btn.textContent = filterActive ? 'Active Orders' : 'All Orders';
      btn.classList.toggle('active-filter', filterActive);
    }
    filterRows();
  }

  // Table sort
  (function() {
    const table = document.getElementById('wl-table');
    if (!table) return;
    let sortCol = 4, sortDir = -1;  // default: Order Created descending

    function sortTable(col) {
      const tbody = table.tBodies[0];
      const rows  = Array.from(tbody.rows);
      if (col === sortCol) {
        sortDir *= -1;
      } else {
        sortCol = col;
        sortDir = 1;
      }
      rows.sort((a, b) => {
        const av = (a.dataset['col' + col] || '').toLowerCase();
        const bv = (b.dataset['col' + col] || '').toLowerCase();
        return av < bv ? -sortDir : av > bv ? sortDir : 0;
      });
      rows.forEach(r => tbody.appendChild(r));

      // Update header indicators
      table.querySelectorAll('thead th.sortable').forEach(th => {
        th.classList.remove('asc', 'desc');
        if (parseInt(th.dataset.col) === sortCol) {
          th.classList.add(sortDir === 1 ? 'asc' : 'desc');
        }
      });
    }

    table.querySelectorAll('thead th.sortable').forEach(th => {
      th.addEventListener('click', () => sortTable(parseInt(th.dataset.col)));
    });

    // Apply initial sort (Order Created desc)
    sortTable(4);
    filterRows();
  })();

  // Persist acquired state across tab switches via localStorage
  const STORAGE_KEY = 'imladris_acquired';

  function getAcquired() {
    try { return JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}'); }
    catch { return {}; }
  }

  async function removeEntry(accession) {
    const row = document.getElementById('row-' + accession);
    await fetch('/remove/' + accession, { method: 'POST' });
    if (row) row.style.display = 'none';
  }

  function markAcquired(accession, label) {
    const acquired = getAcquired();
    acquired[accession] = label;
    localStorage.setItem(STORAGE_KEY, JSON.stringify(acquired));
  }

  // On load: restore done state for any already-imaged rows on this page
  (function restoreAcquiredState() {
    const acquired = getAcquired();
    for (const [accession, label] of Object.entries(acquired)) {
      const btn = document.getElementById('btn-' + accession);
      const msg = document.getElementById('msg-' + accession);
      if (btn) {
        btn.className = 'btn-acquire done';
        btn.textContent = '✓ Acquired';
        btn.disabled = true;
        if (msg) { msg.className = 'status-msg ok'; msg.textContent = label; }
        const rm = document.getElementById('rm-' + accession);
        if (rm) rm.style.display = 'inline-block';
      }
    }
  })();

  // Live clock
  function updateClock() {
    const now = new Date();
    document.getElementById('clock').textContent =
      now.toISOString().slice(0,10) + '  ' + now.toTimeString().slice(0,8);
  }
  setInterval(updateClock, 1000);

  function log(msg, type='info') {
    const el = document.getElementById('activity-log');
    const ts = new Date().toTimeString().slice(0,8);
    const div = document.createElement('div');
    div.className = 'entry ' + type;
    div.textContent = '[' + ts + ']  ' + msg;
    el.prepend(div);
  }

  async function acquire(accession, modality) {
    const btn = document.getElementById('btn-' + accession);
    const msg = document.getElementById('msg-' + accession);

    btn.disabled = true;
    btn.className = 'btn-acquire working';
    btn.textContent = 'Acquiring…';
    msg.textContent = '';
    msg.className = 'status-msg';

    log('Acquiring ' + accession + ' (' + modality + ')…');

    try {
      const resp = await fetch('/acquire/' + accession, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({modality}),
      });
      const data = await resp.json();

      if (data.ok) {
        btn.className = 'btn-acquire done';
        btn.textContent = '✓ Acquired';
        const label = data.fallback ? '(sample image)' : '(patient image)';
        msg.className = 'status-msg ok';
        msg.textContent = label;
        markAcquired(accession, label);
        const rm = document.getElementById('rm-' + accession);
        if (rm) rm.style.display = 'inline-block';
        log('✓ ' + accession + ' sent  instances=' + data.instances + '  study=' + (data.study_uid || '').slice(0,24), 'ok');
      } else {
        btn.className = 'btn-acquire error';
        btn.textContent = '✗ Failed';
        btn.disabled = false;
        msg.className = 'status-msg error';
        msg.textContent = data.error;
        log('✗ ' + accession + ': ' + data.error, 'error');
      }
    } catch (err) {
      btn.className = 'btn-acquire error';
      btn.textContent = '✗ Error';
      btn.disabled = false;
      msg.className = 'status-msg error';
      msg.textContent = 'Network error';
      log('✗ Network error: ' + err, 'error');
    }
  }
</script>
</body>
</html>
"""


# ── Events page template ──────────────────────────────────────────────────────

_EVENTS_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>Bophelong — AdvaPACS Events</title>
  <link rel="icon" href="/favicon.ico">
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: 'Segoe UI', Arial, sans-serif; background: #1a1f2e; color: #e0e4ef; min-height: 100vh; }
    header { background: #0d111d; border-bottom: 2px solid #2a7fff; padding: 14px 24px; display: flex; align-items: center; justify-content: space-between; }
    header .title { font-size: 1.25rem; font-weight: 600; color: #fff; letter-spacing: 0.04em; }
    header .subtitle { font-size: 0.8rem; color: #7a8aaa; margin-top: 2px; }
    nav { background: #141829; padding: 10px 24px; display: flex; gap: 8px; border-bottom: 1px solid #252d45; }
    nav a { color: #7a8aaa; text-decoration: none; padding: 5px 14px; border-radius: 4px; font-size: 0.85rem; border: 1px solid #252d45; }
    nav a:hover { background: #1e253a; color: #c0cce8; }
    nav a.active { background: #1a3a6a; color: #5aafff; border-color: #2a7fff; }
    main { padding: 20px 24px; }
    .page-header { display: flex; align-items: baseline; gap: 12px; margin-bottom: 16px; }
    .page-header h2 { font-size: 1rem; font-weight: 600; color: #c0cce8; }
    .badge-count { font-size: 0.8rem; color: #7a8aaa; background: #1e253a; padding: 2px 8px; border-radius: 10px; }
    .hint { font-size: 0.78rem; color: #4a5570; margin-bottom: 16px; }
    .hint code { color: #5aafff; background: #0d111d; padding: 1px 5px; border-radius: 3px; }
    .event-card { background: #141829; border: 1px solid #252d45; border-radius: 6px; margin-bottom: 10px; overflow: hidden; }
    .event-card.order   { border-left: 3px solid #5aafff; }
    .event-card.report  { border-left: 3px solid #4dcc70; }
    .event-card.study   { border-left: 3px solid #ffaa44; }
    .event-card.patient { border-left: 3px solid #bb77ff; }
    .event-card.unknown { border-left: 3px solid #4a5570; }
    .card-header { padding: 10px 14px; display: flex; align-items: center; gap: 10px; cursor: pointer; }
    .card-header:hover { background: #1a2035; }
    .event-type { font-weight: 600; font-size: 0.85rem; color: #c0cce8; }
    .event-time { font-size: 0.75rem; color: #4a5570; margin-left: auto; }
    .card-body { display: none; padding: 0 14px 12px; }
    .card-body pre { font-size: 0.75rem; color: #6a8aaa; background: #0d111d; padding: 10px; border-radius: 4px; overflow-x: auto; white-space: pre-wrap; }
    .empty { text-align: center; padding: 48px; color: #4a5570; font-size: 0.9rem; }
  </style>
</head>
<body>
<header>
  <div>
    <div class="title">Bophelong Hospital — AdvaPACS Events</div>
    <div class="subtitle">Imladris Virtual Integration Lab — webhook receiver</div>
  </div>
</header>
<nav>
  <a href="/">All</a>
  <a href="/?modality=CR">X-Ray (CR)</a>
  <a href="/?modality=US">Ultrasound (US)</a>
  <a href="/?modality=CT">CT</a>
  <a href="/events" class="active" style="margin-left:auto">Events</a>
</nav>
<main>
  <div class="page-header">
    <h2>AdvaPACS Webhook Events</h2>
    <span class="badge-count" id="count">0 events</span>
  </div>
  <p class="hint">
    Webhook endpoint: <code>POST /webhook/advapacs</code> &nbsp;·&nbsp;
    Auto-refreshes every 5 seconds &nbsp;·&nbsp;
    Last 50 events (in-memory, resets on container restart)
  </p>
  <div id="events-container"><div class="empty">No events received yet.</div></div>
</main>
<script>
  function colorClass(eventType) {
    const t = (eventType || '').toLowerCase();
    if (t.includes('order'))   return 'order';
    if (t.includes('report'))  return 'report';
    if (t.includes('study'))   return 'study';
    if (t.includes('patient')) return 'patient';
    return 'unknown';
  }

  function toggleBody(id) {
    const el = document.getElementById('body-' + id);
    if (el) el.style.display = el.style.display === 'block' ? 'none' : 'block';
  }

  async function refresh() {
    try {
      const resp = await fetch('/events/json');
      const events = await resp.json();
      const container = document.getElementById('events-container');
      document.getElementById('count').textContent = events.length + ' event' + (events.length !== 1 ? 's' : '');
      if (events.length === 0) {
        container.innerHTML = '<div class="empty">No events received yet.</div>';
        return;
      }
      container.innerHTML = events.map((e, i) => `
        <div class="event-card ${colorClass(e.eventType)}">
          <div class="card-header" onclick="toggleBody(${i})">
            <span class="event-type">${e.eventType || 'unknown'}</span>
            <span class="event-time">${e.receivedAt}</span>
          </div>
          <div class="card-body" id="body-${i}">
            <pre>${JSON.stringify(e.payload, null, 2)}</pre>
          </div>
        </div>
      `).join('');
    } catch(err) {
      console.error('Refresh failed:', err);
    }
  }

  refresh();
  setInterval(refresh, 5000);
</script>
</body>
</html>
"""


# ── Entry point (when run standalone) ────────────────────────────────────────

def main():
    log.info(f"Modality console starting on port {CONSOLE_PORT}")
    app.run(host="0.0.0.0", port=CONSOLE_PORT, debug=False, use_reloader=False)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s  %(levelname)-8s  %(message)s")
    main()
