#!/usr/bin/env python3
"""
study_loader.py — Bophelong CT study loader

Reads studies.csv for the study list, walks the DICOM root dir to find files,
and POSTs selected studies to Orthanc via REST so they appear in OHIF and
forward to AdvaPACS Gateway.

Usage:
    source ../.imladris_venv/bin/activate
    python3 study_loader.py \
        --dicom-root "/Volumes/BURT_H/PIH/CT&MRI STUDIES FROM BOPHELONG VIRTUALHOSPITAL" \
        --studies-csv ../reports/ct_mri_20260619/studies.csv \
        --orthanc http://localhost:8043 \
        --port 5010
"""

import argparse
import csv
import os
import sys
import threading
import time
from pathlib import Path

import requests
from flask import Flask, Response, jsonify, render_template_string, request

# ── CLI ───────────────────────────────────────────────────────────────────────

parser = argparse.ArgumentParser(description="Bophelong CT study loader")
parser.add_argument(
    "--dicom-root",
    default="/Volumes/BURT_H/PIH/CT&MRI STUDIES FROM BOPHELONG VIRTUALHOSPITAL",
    help="Directory containing <study_uid>/<instance_uid>.dcm files",
)
parser.add_argument(
    "--studies-csv",
    default=str(Path(__file__).parent.parent / "reports/ct_mri_20260619/studies.csv"),
    help="Path to studies.csv from extract_dicom_metadata.py",
)
parser.add_argument("--orthanc", default="http://localhost:8043", help="Orthanc base URL")
parser.add_argument("--orthanc-user", default="admin")
parser.add_argument("--orthanc-password", default="admin")
parser.add_argument("--port", type=int, default=5010)
args = parser.parse_args()

# ── Path resolution ───────────────────────────────────────────────────────────

def find_study_dir(uid: str) -> Path:
    """
    Locate the study directory for a given StudyInstanceUID under dicom_root.
    Supports two layouts:
      flat:   {dicom_root}/{uid}/          (original Bophelong CT layout)
      nested: {dicom_root}/{ANON-ID}/{uid}/ (anonymize_dicom.py staging layout)
    Returns the first match, or a non-existent Path if not found.
    """
    direct = Path(args.dicom_root) / uid
    if direct.exists():
        return direct
    for parent in sorted(Path(args.dicom_root).iterdir()):
        if parent.is_dir():
            candidate = parent / uid
            if candidate.exists():
                return candidate
    return direct  # caller checks .exists()


# ── Load study list ───────────────────────────────────────────────────────────

def load_studies():
    studies = []
    csv_path = Path(args.studies_csv)
    if not csv_path.exists():
        print(f"WARNING: studies CSV not found: {csv_path}", file=sys.stderr)
        return studies
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            uid = row["study_instance_uid"]
            study_dir = find_study_dir(uid)
            file_count = len(list(study_dir.glob("*.dcm"))) if study_dir.exists() else 0
            studies.append(
                {
                    "uid": uid,
                    "patient_id": row.get("patient_id", ""),
                    "description": row.get("study_description", "") or "(no description)",
                    "body_part": row.get("body_parts", ""),
                    "modality": row.get("modalities", "CT"),
                    "series": row.get("series_count", ""),
                    "instances": row.get("instance_count", ""),
                    "date": row.get("study_date", ""),
                    "dir_exists": study_dir.exists(),
                    "file_count": file_count,
                }
            )
    return studies

STUDIES = load_studies()

# ── Upload state ──────────────────────────────────────────────────────────────

upload_log: list[str] = []
upload_lock = threading.Lock()
upload_running = False


def log(msg: str):
    with upload_lock:
        upload_log.append(msg)
    print(msg)


def upload_study(uid: str) -> tuple[int, int]:
    study_dir = find_study_dir(uid)
    files = sorted(study_dir.glob("*.dcm"))
    ok = fail = 0
    for f in files:
        try:
            with open(f, "rb") as fh:
                data = fh.read()
            resp = requests.post(
                f"{args.orthanc}/instances",
                data=data,
                headers={"Content-Type": "application/dicom"},
                auth=(args.orthanc_user, args.orthanc_password),
                timeout=30,
            )
            if resp.status_code in (200, 409):  # 409 = already exists, fine
                ok += 1
            else:
                fail += 1
                log(f"  WARN {f.name}: HTTP {resp.status_code}")
        except Exception as e:
            fail += 1
            log(f"  ERROR {f.name}: {e}")
    return ok, fail


def run_upload(uids: list[str]):
    global upload_running
    upload_running = True
    total_ok = total_fail = 0
    log(f"Starting upload of {len(uids)} study(ies) to {args.orthanc} ...")
    for uid in uids:
        meta = next((s for s in STUDIES if s["uid"] == uid), None)
        label = meta["description"] if meta else uid[:20] + "…"
        log(f"\n[{label}] — {uid[:30]}…")
        ok, fail = upload_study(uid)
        total_ok += ok
        total_fail += fail
        log(f"  → {ok} uploaded, {fail} failed")
    log(f"\nDone. {total_ok} instances uploaded, {total_fail} failed.")
    upload_running = False


# ── HTML template ─────────────────────────────────────────────────────────────

HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Bophelong CT Study Loader</title>
<style>
  body { font-family: system-ui, sans-serif; max-width: 960px; margin: 2rem auto; padding: 0 1rem; color: #1a1a1a; }
  h1   { font-size: 1.4rem; margin-bottom: 0.25rem; }
  .sub { color: #666; font-size: 0.85rem; margin-bottom: 1.5rem; }
  table { width: 100%; border-collapse: collapse; font-size: 0.9rem; }
  th   { text-align: left; padding: 0.5rem 0.6rem; background: #f0f4f8; border-bottom: 2px solid #cdd5df; }
  td   { padding: 0.45rem 0.6rem; border-bottom: 1px solid #e8ecf0; vertical-align: top; }
  tr:hover td { background: #f7f9fb; }
  .badge { display: inline-block; padding: 0.15rem 0.5rem; border-radius: 9999px; font-size: 0.75rem; font-weight: 600; }
  .brain   { background: #dbeafe; color: #1e40af; }
  .chest   { background: #dcfce7; color: #166534; }
  .abdomen { background: #fef9c3; color: #854d0e; }
  .other   { background: #f3f4f6; color: #374151; }
  .missing { color: #dc2626; font-style: italic; font-size: 0.8rem; }
  .btn  { padding: 0.5rem 1.2rem; border: none; border-radius: 6px; cursor: pointer; font-size: 0.9rem; }
  .btn-send  { background: #2563eb; color: #fff; }
  .btn-send:hover { background: #1d4ed8; }
  .btn-send:disabled { background: #93c5fd; cursor: default; }
  .btn-all   { background: #e5e7eb; color: #374151; font-size: 0.8rem; padding: 0.3rem 0.8rem; }
  .toolbar { display: flex; align-items: center; gap: 0.8rem; margin: 1rem 0 0.5rem; }
  #log-box { font-family: monospace; font-size: 0.82rem; background: #0f172a; color: #94a3b8;
             padding: 1rem; border-radius: 8px; height: 220px; overflow-y: auto;
             white-space: pre-wrap; margin-top: 1.2rem; display: none; }
  #log-box.visible { display: block; }
  .ohif-link { font-size: 0.8rem; color: #2563eb; }
</style>
</head>
<body>
<h1>Bophelong CT Study Loader</h1>
<div class="sub">
  {{ studies|length }} studies &nbsp;·&nbsp; DICOM root: <code>{{ dicom_root }}</code>
  &nbsp;·&nbsp; Orthanc: <a href="{{ orthanc }}/app/explorer.html" target="_blank">{{ orthanc }}</a>
  &nbsp;·&nbsp; <a href="http://localhost:3000" target="_blank" class="ohif-link">OHIF Viewer ↗</a>
</div>

<form id="study-form">
<div class="toolbar">
  <button type="button" class="btn btn-all" onclick="toggleAll(true)">Select all</button>
  <button type="button" class="btn btn-all" onclick="toggleAll(false)">Clear</button>
  <button type="submit" class="btn btn-send" id="send-btn">Send to Orthanc / OHIF</button>
  <span id="status-msg" style="color:#64748b;font-size:0.85rem;"></span>
</div>

<table>
<thead>
  <tr>
    <th style="width:2rem"></th>
    <th>Description</th>
    <th>Body part</th>
    <th>Modality</th>
    <th>Series</th>
    <th>Instances</th>
    <th>Files on disk</th>
  </tr>
</thead>
<tbody>
{% for s in studies %}
<tr>
  <td><input type="checkbox" name="uid" value="{{ s.uid }}"
       {% if not s.dir_exists %}disabled title="Directory not found on disk"{% endif %}></td>
  <td>{{ s.description }}</td>
  <td>
    <span class="badge {{ s.body_part | lower | replace(' ','') }}">{{ s.body_part }}</span>
  </td>
  <td>{{ s.modality }}</td>
  <td style="text-align:right">{{ s.series }}</td>
  <td style="text-align:right">{{ s.instances }}</td>
  <td style="text-align:right">
    {% if s.dir_exists %}
      {{ s.file_count }}
    {% else %}
      <span class="missing">not found</span>
    {% endif %}
  </td>
</tr>
{% endfor %}
</tbody>
</table>
</form>

<div id="log-box"></div>

<script>
function toggleAll(on) {
  document.querySelectorAll('input[name=uid]:not(:disabled)').forEach(cb => cb.checked = on);
}

document.getElementById('study-form').addEventListener('submit', async e => {
  e.preventDefault();
  const uids = [...document.querySelectorAll('input[name=uid]:checked')].map(cb => cb.value);
  if (!uids.length) { alert('Select at least one study.'); return; }

  const btn = document.getElementById('send-btn');
  btn.disabled = true;
  btn.textContent = 'Uploading…';

  const box = document.getElementById('log-box');
  box.className = 'visible';
  box.textContent = '';
  document.getElementById('status-msg').textContent = '';

  const resp = await fetch('/upload', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ uids }),
  });

  const reader = resp.body.getReader();
  const dec = new TextDecoder();
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    box.textContent += dec.decode(value);
    box.scrollTop = box.scrollHeight;
  }

  btn.disabled = false;
  btn.textContent = 'Send to Orthanc / OHIF';
  document.getElementById('status-msg').textContent = 'Done — open OHIF to view studies.';
});
</script>
</body>
</html>
"""

# ── Flask app ─────────────────────────────────────────────────────────────────

app = Flask(__name__)


@app.route("/")
def index():
    return render_template_string(
        HTML,
        studies=STUDIES,
        dicom_root=args.dicom_root,
        orthanc=args.orthanc,
    )


@app.route("/upload", methods=["POST"])
def upload():
    body = request.get_json(force=True)
    uids = body.get("uids", [])
    if not uids:
        return jsonify({"error": "no uids"}), 400

    def stream():
        upload_log.clear()
        t = threading.Thread(target=run_upload, args=(uids,), daemon=True)
        t.start()
        yielded = 0
        while t.is_alive() or yielded < len(upload_log):
            with upload_lock:
                while yielded < len(upload_log):
                    yield upload_log[yielded] + "\n"
                    yielded += 1
            time.sleep(0.15)

    return Response(stream(), mimetype="text/plain")


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"Study loader — {len(STUDIES)} studies")
    print(f"DICOM root : {args.dicom_root}")
    print(f"Orthanc    : {args.orthanc}")
    print(f"Open       : http://localhost:{args.port}/")
    app.run(host="0.0.0.0", port=args.port, debug=False)
