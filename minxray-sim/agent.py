"""agent.py — MinXray modality agent: watches qTrack's worklist and images each new patient.

The headless counterpart of `minxray_sim.py capture`, modelled on the lab
sidecar's acquisition loop (sidecar/acquisition_loop.py):

  every POLL_SECONDS:
    C-FIND the qTrack MWL (station STATION_FILTER)
    for each scheduled item not yet acquired:
      wait CAPTURE_DELAY_SECONDS ("patient positioning")
      pick the source chest image (census assignment, else per-patient choice)
      capture_item(): MPPS IN PROGRESS -> DX -> dcmio -> MPPS COMPLETED -> FORWARD_TO

qTrack's MWL server only returns REGISTERED items; MPPS COMPLETED removes an
item from the worklist. The agent also keeps its own record (STATE_FILE) so an
item whose MPPS fails is not re-imaged on every poll.

Image choice (deterministic per patient, so a re-capture shows the same chest):
  1. CENSUS_CSV row for the PatientID -> its CR_raw image (e.g. Tuberculosis/Tuberculosis-1.png)
  2. otherwise a library image of class NEW_PATIENT_LABEL (Normal | Tuberculosis | random,
     where random is Tuberculosis with probability TB_FRACTION), excluding census images.

Environment (in addition to minxray_sim.py's):
  POLL_SECONDS           15
  CAPTURE_DELAY_SECONDS  5
  STATION_FILTER         ScheduledStationAETitle to serve      (default STATION_AE)
  SKIP_PATIENT_PREFIXES  comma list of PatientID prefixes to ignore (default E2ETEST)
  MAX_ITEM_AGE_DAYS      ignore items scheduled more than N days ago (default 2; 0 = no limit)
  MAX_ATTEMPTS           failed captures retried up to N times (default 3)
  STATE_FILE             /state/acquired.json
  CENSUS_CSV             Bophelong census (optional)
  NEW_PATIENT_LABEL      random
  TB_FRACTION            0.3
"""
from __future__ import annotations

import csv
import hashlib
import json
import logging
import os
import random
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import dx
import minxray_sim as sim

log = logging.getLogger("minxray-agent")

POLL_SECONDS = float(os.environ.get("POLL_SECONDS", "15"))
CAPTURE_DELAY = float(os.environ.get("CAPTURE_DELAY_SECONDS", "5"))
STATION_FILTER = os.environ.get("STATION_FILTER", sim.CFG["STATION_AE"])
SKIP_PREFIXES = tuple(p for p in os.environ.get("SKIP_PATIENT_PREFIXES", "E2ETEST").split(",") if p)
MAX_AGE_DAYS = int(os.environ.get("MAX_ITEM_AGE_DAYS", "2"))
MAX_ATTEMPTS = int(os.environ.get("MAX_ATTEMPTS", "3"))
STATE_FILE = Path(os.environ.get("STATE_FILE", "/state/acquired.json"))
CENSUS_CSV = os.environ.get("CENSUS_CSV", "")
NEW_LABEL = os.environ.get("NEW_PATIENT_LABEL", "random")
TB_FRACTION = float(os.environ.get("TB_FRACTION", "0.3"))


# ---------------------------------------------------------------- state

def _key(item: dict) -> str:
    return f"{item['AccessionNumber']}|{item['StudyInstanceUID']}"


def load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text())
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError:
        log.warning("State file %s unreadable; starting empty", STATE_FILE)
        return {}


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1, sort_keys=True))
    tmp.replace(STATE_FILE)


# ---------------------------------------------------------------- image choice

def load_census() -> dict[str, str]:
    """PatientID -> '<label>/<file>' from the census CR_raw column."""
    if not CENSUS_CSV or not Path(CENSUS_CSV).is_file():
        if CENSUS_CSV:
            log.warning("CENSUS_CSV %s not found; all patients treated as new", CENSUS_CSV)
        return {}
    with open(CENSUS_CSV, newline="", encoding="utf-8-sig") as f:
        rows = csv.DictReader(f)
        return {r["Patient_ID"].strip(): "/".join(r["CR_raw"].strip().split("/")[-2:])
                for r in rows if r.get("Patient_ID") and r.get("CR_raw")}


def _library(label: str) -> list[Path]:
    root = sim.CFG["LIBRARY_DIR"] / label
    return sorted(p for p in root.glob("*") if p.suffix.lower() in sim.SOURCE_SUFFIXES)


def choose_image(patient_id: str, census: dict[str, str]) -> tuple[Path, str]:
    """Return (image path, reason). Deterministic per PatientID."""
    if patient_id in census:
        path = sim.CFG["LIBRARY_DIR"] / census[patient_id]
        if path.is_file():
            return path, "census assignment"
        log.warning("Census image %s for %s missing from library; choosing one", path, patient_id)
    rng = random.Random(int(hashlib.sha256(patient_id.encode()).hexdigest(), 16))
    label = NEW_LABEL
    if label == "random":
        label = "Tuberculosis" if rng.random() < TB_FRACTION else "Normal"
    used = set(census.values())
    pool = [p for p in _library(label) if f"{label}/{p.name}" not in used]
    if not pool:
        raise RuntimeError(f"No {label} images under {sim.CFG['LIBRARY_DIR'] / label}")
    return rng.choice(pool), f"new patient, {label}"


# ---------------------------------------------------------------- loop

def _eligible(item: dict) -> str | None:
    """Reason to skip, or None if the item should be imaged."""
    if item["PatientID"].startswith(SKIP_PREFIXES):
        return "skip-listed patient"
    if MAX_AGE_DAYS and item["ScheduledProcedureStepStartDate"]:
        try:
            sched = datetime.strptime(item["ScheduledProcedureStepStartDate"][:8], "%Y%m%d").date()
            if sched < date.today() - timedelta(days=MAX_AGE_DAYS):
                return f"scheduled {sched}, older than {MAX_AGE_DAYS} days"
        except ValueError:
            pass
    return None


def poll_once(params: dx.SimParams, state: dict, census: dict, dry_run: bool = False) -> int:
    """One worklist pass; returns the number of captures attempted."""
    items = sim.query_worklist(STATION_FILTER or None, None, None)
    attempted = 0
    for item in items:
        k = _key(item)
        entry = state.get(k, {})
        if entry.get("status") == "done":
            continue
        if entry.get("attempts", 0) >= MAX_ATTEMPTS:
            continue
        reason = _eligible(item)
        if reason:
            if entry.get("skip") != reason:
                log.info("Skipping %s (%s): %s", item["PatientID"], item["AccessionNumber"], reason)
                state[k] = {**entry, "skip": reason}
            continue
        png, why = choose_image(item["PatientID"], census)
        log.info("New worklist item: %s %s acc=%s -> %s (%s)", item["PatientID"], item["PatientName"],
                 item["AccessionNumber"], png.relative_to(sim.CFG["LIBRARY_DIR"]), why)
        if dry_run:
            continue
        time.sleep(CAPTURE_DELAY)
        attempted += 1
        try:
            ok = sim.capture_item(item, png, params)
        except Exception:
            log.exception("Capture of %s failed", item["AccessionNumber"])
            ok = False
        state[k] = {"status": "done" if ok else "failed",
                    "attempts": entry.get("attempts", 0) + 1,
                    "patient_id": item["PatientID"], "source": str(png.relative_to(sim.CFG["LIBRARY_DIR"])),
                    "at": datetime.now().isoformat(timespec="seconds")}
        save_state(state)
    return attempted


def run(params: dx.SimParams, once: bool = False, dry_run: bool = False) -> int:
    census = load_census()
    state = load_state()
    log.info("MinXray agent: station=%s mwl=%s:%s store=%s:%s forward=%s poll=%ss census=%d patients state=%d items",
             STATION_FILTER or "*", sim.CFG["MWL_HOST"], sim.CFG["MWL_PORT"], sim.CFG["STORE_HOST"],
             sim.CFG["STORE_PORT"], sim.CFG["FORWARD_TO"] or "-", POLL_SECONDS, len(census), len(state))
    while True:
        try:
            poll_once(params, state, census, dry_run)
        except SystemExit as e:          # query_worklist raises on association failure
            log.warning("Worklist unavailable: %s", e)
        except Exception:
            log.exception("Poll failed")
        if once:
            return 0
        time.sleep(POLL_SECONDS)
