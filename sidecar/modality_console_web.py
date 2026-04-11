"""
modality_console_web.py — Imladris Modality Console (web UI)

A browser-based modality simulator console.  Shows pending worklist
entries for this modality and lets a radiology technician simulate
image acquisition with one click.

Routes
------
GET  /                     Worklist page (all modalities)
GET  /?modality=CR         Filtered to X-ray / CR items only
GET  /?modality=US         Filtered to Ultrasound items only
POST /acquire/<accession>  Simulate acquisition for one worklist item
GET  /status               JSON health check

Environment
-----------
ORTHANC_URL          http://orthanc-modality:8042
ORTHANC_USER         admin
ORTHANC_PASSWORD     admin
XRAY_DIR             /hospital-records/xray
US_DIR               /hospital-records/ultrasound_cine
CONSOLE_PORT         5001
"""

import io
import logging
import os
import random
from datetime import datetime
from pathlib import Path

import pydicom
import requests
from flask import Flask, jsonify, render_template_string, request
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, generate_uid

log = logging.getLogger("console_web")

# ── Config ────────────────────────────────────────────────────────────────────

ORTHANC_URL      = os.getenv("ORTHANC_URL",      "http://orthanc-modality:8042")
ORTHANC_USER     = os.getenv("ORTHANC_USER",     "admin")
ORTHANC_PASSWORD = os.getenv("ORTHANC_PASSWORD", "admin")
XRAY_DIR         = Path(os.getenv("XRAY_DIR",    "/hospital-records/xray"))
US_DIR           = Path(os.getenv("US_DIR",      "/hospital-records/ultrasound_cine"))
CONSOLE_PORT     = int(os.getenv("CONSOLE_PORT", "5001"))
INSTITUTION      = "Botsabelo MDR-TB Hospital"

MODALITY_LABELS = {
    "CR": "X-Ray",
    "DX": "X-Ray",
    "US": "Ultrasound",
    "CT": "CT Scanner",
    "MR": "MRI",
}

app = Flask(__name__)


# ── Worklist helpers ──────────────────────────────────────────────────────────

def _get_worklist(modality_filter: str | None = None) -> list[dict]:
    """Fetch pending worklist entries from Orthanc REST API."""
    try:
        r = requests.get(
            f"{ORTHANC_URL}/worklists",
            auth=(ORTHANC_USER, ORTHANC_PASSWORD),
            timeout=5,
        )
        r.raise_for_status()
        items = r.json()
    except Exception as e:
        log.warning(f"Worklist fetch failed: {e}")
        return []

    entries = []
    for item in items:
        tags = item.get("Tags", {})
        sps_list = tags.get("ScheduledProcedureStepSequence", [])
        sps = sps_list[0] if sps_list else {}
        mod = sps.get("Modality", "")
        if modality_filter and mod.upper() != modality_filter.upper():
            continue

        raw_date = sps.get("ScheduledProcedureStepStartDate", "")
        raw_time = sps.get("ScheduledProcedureStepStartTime", "")
        try:
            scheduled = datetime.strptime(raw_date, "%Y%m%d").strftime("%Y-%m-%d") if raw_date else ""
        except ValueError:
            scheduled = raw_date
        # Format HHMMSS → HH:MM
        try:
            scheduled_time = raw_time[:2] + ":" + raw_time[2:4] if len(raw_time) >= 4 else raw_time
        except Exception:
            scheduled_time = raw_time
        # ISO-style sortable string for JS sorting
        order_created_sort = (raw_date + raw_time)[:14]  # YYYYMMDDHHmmss

        entries.append({
            "id":               item.get("ID", ""),
            "patient_name":     tags.get("PatientName", ""),
            "patient_id":       tags.get("PatientID", ""),
            "dob":              tags.get("PatientBirthDate", ""),
            "sex":              tags.get("PatientSex", ""),
            "accession":        tags.get("AccessionNumber", ""),
            "procedure":        tags.get("RequestedProcedureDescription", ""),
            "modality":         mod,
            "scheduled":        scheduled,
            "scheduled_time":   scheduled_time,
            "order_created_sort": order_created_sort,
            "study_uid":        tags.get("StudyInstanceUID", ""),
        })

    return entries


# ── Image lookup ──────────────────────────────────────────────────────────────

def _find_image(patient_id: str, modality: str) -> Path | None:
    """Find the best source DICOM for this patient and modality."""
    if modality.upper() in ("US",):
        base_dir = US_DIR
        pattern  = f"CINE_{patient_id}.dcm"
    else:
        base_dir = XRAY_DIR
        pattern  = f"XRAY_{patient_id}.dcm"

    candidate = base_dir / patient_id / pattern
    if candidate.exists():
        return candidate

    # Fallback: any image in the modality dir
    all_files = list(base_dir.glob(f"*/{'CINE' if modality == 'US' else 'XRAY'}_*.dcm"))
    if all_files:
        chosen = random.choice(all_files)
        log.warning(f"No image for {patient_id} — using fallback {chosen.name}")
        return chosen

    return None


# ── DICOM patching ────────────────────────────────────────────────────────────

def _patch_and_upload(entry: dict) -> dict:
    """Patch source DICOM with MWL demographics and upload to Orthanc."""
    source = _find_image(entry["patient_id"], entry["modality"])
    if not source:
        return {"ok": False, "error": f"No source image found for patient {entry['patient_id']}"}

    fallback = (source.parent.name != entry["patient_id"])

    ds = pydicom.dcmread(str(source))
    now = datetime.now()
    date_str = now.strftime("%Y%m%d")
    time_str = now.strftime("%H%M%S")

    ds.PatientName      = entry["patient_name"]
    ds.PatientID        = entry["patient_id"]
    ds.PatientBirthDate = entry.get("dob", "")
    ds.PatientSex       = entry.get("sex", "")

    ds.StudyInstanceUID     = entry.get("study_uid") or generate_uid()
    ds.StudyDate            = entry.get("scheduled", "").replace("-", "") or date_str
    ds.StudyTime            = time_str
    ds.StudyDescription     = entry.get("procedure", "Radiology Study")
    ds.AccessionNumber      = entry.get("accession", "")

    ds.SeriesInstanceUID    = generate_uid()
    ds.SeriesDate           = date_str
    ds.SeriesTime           = time_str
    ds.SeriesDescription    = entry.get("procedure", "Radiology Study")
    ds.SeriesNumber         = "1"
    ds.SOPInstanceUID       = generate_uid()
    ds.InstanceNumber       = "1"
    ds.ContentDate          = date_str
    ds.ContentTime          = time_str
    ds.Modality             = entry.get("modality", "CR")
    ds.InstitutionName      = INSTITUTION

    if hasattr(ds, "file_meta"):
        ds.file_meta.MediaStorageSOPInstanceUID = ds.SOPInstanceUID
        ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian

    buf = io.BytesIO()
    pydicom.dcmwrite(buf, ds)
    buf.seek(0)

    r = requests.post(
        f"{ORTHANC_URL}/instances",
        data=buf.read(),
        headers={"Content-Type": "application/dicom"},
        auth=(ORTHANC_USER, ORTHANC_PASSWORD),
        timeout=30,
    )
    r.raise_for_status()
    instance_id = r.json().get("ID", "")

    return {
        "ok":          True,
        "instance_id": instance_id,
        "source":      source.name,
        "fallback":    fallback,
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
    )


@app.route("/acquire/<accession>", methods=["POST"])
def acquire(accession: str):
    modality = request.json.get("modality", "CR") if request.is_json else "CR"
    entries  = _get_worklist()
    entry    = next((e for e in entries if e["accession"] == accession), None)

    if not entry:
        return jsonify({"ok": False, "error": f"Accession {accession} not found in worklist"}), 404

    try:
        result = _patch_and_upload(entry)
    except Exception as e:
        log.error(f"Acquire failed for {accession}: {e}", exc_info=True)
        return jsonify({"ok": False, "error": str(e)}), 500

    if result["ok"]:
        log.info(
            f"Acquired: {entry['patient_name']} ({entry['patient_id']}) "
            f"{entry['procedure']}  instance={result['instance_id']}"
        )
    return jsonify(result)


@app.route("/status")
def status():
    try:
        r = requests.get(f"{ORTHANC_URL}/system",
                         auth=(ORTHANC_USER, ORTHANC_PASSWORD), timeout=3)
        orthanc_ok = r.status_code == 200
    except Exception:
        orthanc_ok = False
    return jsonify({"orthanc": orthanc_ok, "xray_dir": XRAY_DIR.exists(), "us_dir": US_DIR.exists()})


# ── HTML template ─────────────────────────────────────────────────────────────

_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>Botsabelo {{ label }} Console</title>
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
    <div class="title">Botsabelo Hospital — {{ label }} Console</div>
    <div class="subtitle">Imladris Virtual Integration Lab  ·  AE: MODALITY_SIM</div>
  </div>
  <div class="clock" id="clock">{{ now }}</div>
</header>

<nav>
  <a href="/" class="{{ 'active' if not modality else '' }}">All</a>
  <a href="/?modality=CR" class="{{ 'active' if modality == 'CR' else '' }}">X-Ray (CR)</a>
  <a href="/?modality=US" class="{{ 'active' if modality == 'US' else '' }}">Ultrasound (US)</a>
  <a href="/?modality=CT" class="{{ 'active' if modality == 'CT' else '' }}">CT</a>
</nav>

<main>
  <div class="worklist-header">
    <h2>Scheduled Exams — Modality Worklist</h2>
    <span class="count">{{ entries|length }} pending</span>
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
        <th>Action</th>
      </tr>
    </thead>
    <tbody>
    {% for e in entries %}
      <tr id="row-{{ e.accession }}"
          data-col0="{{ e.patient_name }}"
          data-col1="{{ e.patient_id }}"
          data-col2="{{ e.modality }}"
          data-col3="{{ e.procedure }}"
          data-col4="{{ e.order_created_sort }}"
          data-col5="{{ e.accession }}">
        <td>{{ e.patient_name or '—' }}</td>
        <td class="muted">{{ e.patient_id }}</td>
        <td>
          <span class="badge badge-{{ e.modality }}">{{ e.modality }}</span>
        </td>
        <td>{{ e.procedure }}</td>
        <td class="muted">{{ e.scheduled }}{% if e.scheduled_time %} {{ e.scheduled_time }}{% endif %}</td>
        <td class="muted" style="font-size:0.75rem">{{ e.accession }}</td>
        <td>
          <button
            class="btn-acquire"
            id="btn-{{ e.accession }}"
            onclick="acquire('{{ e.accession }}', '{{ e.modality }}')"
          >Image the Patient</button>
          <div class="status-msg" id="msg-{{ e.accession }}"></div>
        </td>
      </tr>
    {% endfor %}
    </tbody>
  </table>
  {% else %}
  <div class="empty-state">
    <div class="icon">📋</div>
    <p>No pending worklist entries{% if modality %} for modality <strong>{{ modality }}</strong>{% endif %}.</p>
  </div>
  {% endif %}

  <div class="log-section">
    <h3>Activity Log</h3>
    <div id="activity-log"></div>
  </div>
</main>

<script>
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
  })();

  // Persist acquired state across tab switches via localStorage
  const STORAGE_KEY = 'imladris_acquired';

  function getAcquired() {
    try { return JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}'); }
    catch { return {}; }
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
        log('✓ ' + accession + ' uploaded  instance=' + data.instance_id, 'ok');
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


# ── Entry point (when run standalone) ────────────────────────────────────────

def main():
    log.info(f"Modality console starting on port {CONSOLE_PORT}")
    app.run(host="0.0.0.0", port=CONSOLE_PORT, debug=False, use_reloader=False)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s  %(levelname)-8s  %(message)s")
    main()
