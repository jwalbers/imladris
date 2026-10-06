#!/usr/bin/env python3
"""adapter.py — IMLADRIS PACS adapter: completed qTrack/qXR studies -> AdvaPACS Gateway.

For each study qXR has finished (image state PROCESSED in the Qure platform DB):

  1. assemble   primary DX + qXR secondary captures (with/without sidebar)
                + Basic Text SR + Encapsulated PDF report
                - primary: the MinXray simulator's lossless original (matched by
                  SOP Instance UID in PRIMARY_DIR), else qTrack's stored copy
                - qXR objects: the platform filestore (prod-data volume, read-only)
  2. normalize  every object gets the same, valid study:
                - invalid UIDs remapped deterministically (same input -> same UID)
                - AccessionNumber <= 16 chars
                - one patient module from the platform DB: Family^Given, sex, DOB
                - StudyDate/Time/Description from the primary on every object
                - UTF-8 (ISO_IR 192); synthetic marker carried to the images
  3. send       one DICOM association, C-STORE all objects
                ADAPTER_AE -> GATEWAY_AE@GATEWAY_HOST:GATEWAY_PORT

Lessons from the first manual uploads (2026-10-01): AdvaPACS silently drops
studies with invalid UIDs and de-duplicates by SOP Instance UID; the PDF report
has no PatientName; qTrack's import path writes names given^family and 32-char
accessions; the MWL path carries no sex/DOB.

Commands:
  watch [--once]                       poll for newly completed studies and send them
  send --patient-id ID [--dry-run]     (re)send all completed studies of a patient
  list                                 show completed studies and what was sent

Environment:
  PLATFORM_DB_HOST/PORT/NAME/USER   postgres / 5432 / platform / imladris_ro
  PLATFORM_DB_PASSWORD              (git-ignored .env)
  FILESTORE                         /srv/data/hct
  PRIMARY_DIR                       /primary   (minxray-sim/output)
  OUTPUT_DIR                        /output    (normalized copies of what was sent)
  STATE_FILE                        /state/sent.json
  GATEWAY_HOST/PORT/AE              advapacs-gateway / 11112 / QURE01_GW_01
  ADAPTER_AE                        QURE01_ADP_01
  POLL_SECONDS                      20
  READY_TIMEOUT_SECONDS             300  (send what exists if qXR objects never all appear)
"""
from __future__ import annotations

import argparse
import glob
import json
import logging
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import psycopg
import pydicom
from pydicom.dataset import Dataset
from pydicom.uid import ExplicitVRLittleEndian, ImplicitVRLittleEndian, generate_uid
from pynetdicom import AE

log = logging.getLogger("pacs-adapter")

ENV = os.environ.get
FILESTORE = Path(ENV("FILESTORE", "/srv/data/hct"))
PRIMARY_DIR = Path(ENV("PRIMARY_DIR", "/primary"))
OUTPUT_DIR = Path(ENV("OUTPUT_DIR", "/output"))
STATE_FILE = Path(ENV("STATE_FILE", "/state/sent.json"))
GATEWAY = (ENV("GATEWAY_AE", "QURE01_GW_01"), ENV("GATEWAY_HOST", "advapacs-gateway"), int(ENV("GATEWAY_PORT", "11112")))
ADAPTER_AE = ENV("ADAPTER_AE", "QURE01_ADP_01")
POLL_SECONDS = float(ENV("POLL_SECONDS", "20"))
READY_TIMEOUT = float(ENV("READY_TIMEOUT_SECONDS", "300"))

UID_RE = re.compile(r"^(0|[1-9][0-9]*)(\.(0|[1-9][0-9]*))*$")
SEX = {0: "M", 1: "F"}          # portal_manager_patient.gender, verified against registrations
SYNTHETIC_NOTE = "SYNTHETIC - IMLADRIS MinXray simulation; not a patient image"

SQL_COMPLETED = """
select p.patient_id, p.name, p.gender, p.dob,
       s."studyInstanceUID", s."accessionNumber", se."seriesInstanceUID",
       i."imageID", i."sopInstanceUID", i.updated_at
from portal_manager_patient p
join portal_manager_patient_image_studies pis on pis.patient_id = p.id
join image_manager_imagestudy s on s.id = pis.imagestudy_id
join image_manager_imageseries se on se.image_study_id = s.id
join image_manager_image i on i.image_series_id = se.id
where i.state = 'PROCESSED' {where}
order by i.updated_at
"""


@dataclass
class Completed:
    patient_id: str
    name: str
    gender: int | None
    dob: object
    study_uid: str
    accession: str
    series_uid: str
    image_id: str
    sop_uid: str
    updated_at: datetime
    files: dict = field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.study_uid}|{self.sop_uid}"


# ---------------------------------------------------------------- database

def db():
    return psycopg.connect(host=ENV("PLATFORM_DB_HOST", "postgres"), port=int(ENV("PLATFORM_DB_PORT", "5432")),
                           dbname=ENV("PLATFORM_DB_NAME", "platform"), user=ENV("PLATFORM_DB_USER", "imladris_ro"),
                           password=ENV("PLATFORM_DB_PASSWORD", ""), connect_timeout=10)


def completed(where: str = "", params: tuple = ()) -> list[Completed]:
    with db() as conn, conn.cursor() as cur:
        cur.execute(SQL_COMPLETED.format(where=where), params)
        return [Completed(*row) for row in cur.fetchall()]


# ---------------------------------------------------------------- assemble

def locate(c: Completed) -> dict[str, Path]:
    """Find this image's objects. Keys: primary, sc, sc_nosidebar, sr, pdf, qtrack_primary."""
    dirs = glob.glob(str(FILESTORE / "*" / c.series_uid))
    if not dirs:
        return {}
    d = Path(dirs[0])
    candidates = {
        "qtrack_primary": d / c.image_id,
        "sc": d / f"{c.image_id}_sc.dcm",
        "sc_nosidebar": d / f"{c.image_id}_sc_without_sidebar.dcm",
        "sr": d / f"{c.image_id}_sr.dcm",
        "pdf": d / f"{c.image_id}_reports" / f"{c.image_id}.dcm",
    }
    files = {k: p for k, p in candidates.items() if p.is_file()}
    lossless = sorted(PRIMARY_DIR.glob(f"*_{c.sop_uid}.dcm"))
    files["primary"] = lossless[0] if lossless else files.get("qtrack_primary")
    files["primary_source"] = "minxray lossless" if lossless else "qTrack copy (lossy JPEG)"
    return files


def ready(files: dict) -> bool:
    return all(k in files for k in ("primary", "sc", "sr", "pdf"))


# ---------------------------------------------------------------- normalize

def _remap(uid: str) -> str:
    return uid if UID_RE.match(uid) and len(uid) <= 64 else generate_uid(entropy_srcs=[uid])


def _person_name(db_name: str) -> str:
    """Platform DB stores 'Given Family' (e.g. 'Lehlohonolo Tšepiso') -> DICOM 'Family^Given'."""
    parts = db_name.split()
    return f"{parts[-1]}^{' '.join(parts[:-1])}" if len(parts) > 1 else db_name


def normalize(c: Completed, files: dict) -> list[Dataset]:
    primary = pydicom.dcmread(files["primary"])
    study_uid = _remap(str(primary.StudyInstanceUID))
    accession = (str(primary.get("AccessionNumber", "")) or c.accession or "")[:16]
    synthetic = "SYNTHETIC" in str(primary.get("DerivationDescription", ""))
    patient = {
        "PatientName": _person_name(c.name) if c.name else str(primary.PatientName),
        "PatientID": c.patient_id,
        "PatientBirthDate": c.dob.strftime("%Y%m%d") if c.dob else str(primary.get("PatientBirthDate", "")),
        "PatientSex": SEX.get(c.gender, "O") if c.gender is not None else str(primary.get("PatientSex", "")),
    }
    study = {
        "StudyInstanceUID": study_uid,
        "AccessionNumber": accession,
        "StudyDate": str(primary.get("StudyDate", "")) or datetime.now().strftime("%Y%m%d"),
        "StudyTime": str(primary.get("StudyTime", "")) or datetime.now().strftime("%H%M%S"),
        "StudyDescription": str(primary.get("StudyDescription", "")) or "CHEST PA",
        "StudyID": str(primary.get("StudyID", "")) or "1",
        "ReferringPhysicianName": str(primary.get("ReferringPhysicianName", "")),
    }
    old_study = str(primary.StudyInstanceUID)
    out = []
    for kind in ("primary", "sc", "sc_nosidebar", "sr", "pdf"):
        if kind not in files:
            continue
        ds = primary if kind == "primary" else pydicom.dcmread(files[kind])
        ds.decode()                                   # text -> str under its own charset, before switching to UTF-8
        ds.SpecificCharacterSet = "ISO_IR 192"
        for el in ds.iterall():                       # remap invalid UIDs everywhere (incl. SR references)
            if el.VR == "UI" and isinstance(el.value, str):
                el.value = study_uid if el.value == old_study else _remap(el.value)
        for kw, v in {**patient, **study}.items():
            setattr(ds, kw, v)
        if synthetic and kind in ("primary", "sc", "sc_nosidebar"):
            ds.ImageComments = SYNTHETIC_NOTE
        ds.file_meta.MediaStorageSOPInstanceUID = ds.SOPInstanceUID
        out.append(ds)
    return out


# ---------------------------------------------------------------- send

def send(datasets: list[Dataset]) -> tuple[int, int]:
    called, host, port = GATEWAY
    ae = AE(ae_title=ADAPTER_AE)
    ae.acse_timeout = ae.dimse_timeout = ae.network_timeout = 60
    # One presentation context per (SOP class, transfer syntax): with several syntaxes in
    # one context the SCP picks one, and a JPEG-encoded object then has no usable context.
    pairs = {(str(ds.SOPClassUID), str(ds.file_meta.TransferSyntaxUID)) for ds in datasets}
    pairs |= {(sop, ts) for sop, _ in pairs for ts in (ExplicitVRLittleEndian, ImplicitVRLittleEndian)}
    for sop, ts in sorted(pairs):
        ae.add_requested_context(sop, ts)
    assoc = ae.associate(host, port, ae_title=called, max_pdu=0)
    if not assoc.is_established:
        log.error("Association %s -> %s@%s:%s %s", ADAPTER_AE, called, host, port,
                  "rejected (is the adapter AE registered/accepted on the gateway?)" if assoc.is_rejected else "failed")
        return 0, len(datasets)
    ok = 0
    try:
        accepted = {(cx.abstract_syntax, cx.transfer_syntax[0]) for cx in assoc.accepted_contexts}
        for ds in datasets:
            sop, ts = str(ds.SOPClassUID), str(ds.file_meta.TransferSyntaxUID)
            if (sop, ts) not in accepted and ds.file_meta.TransferSyntaxUID.is_compressed:
                log.info("  %s: %s not accepted by the gateway; decompressing", ds.SOPInstanceUID[-12:],
                         ds.file_meta.TransferSyntaxUID.name)
                ds.decompress()                       # -> Explicit VR Little Endian
            try:
                st = assoc.send_c_store(ds)
            except ValueError as e:                   # no usable presentation context
                log.error("  C-STORE %s skipped: %s", ds.SOPInstanceUID[-12:], e)
                continue
            code = st.Status if st else -1
            good = code in (0x0000, 0xB000, 0xB006, 0xB007)
            ok += good
            log.info("  C-STORE %-40s %s -> 0x%04X", ds.SOPClassUID.name[:40], ds.SOPInstanceUID[-12:], code & 0xFFFF)
    finally:
        assoc.release()
    return ok, len(datasets)


def save_copies(c: Completed, datasets: list[Dataset]) -> Path:
    d = OUTPUT_DIR / c.patient_id / str(datasets[0].StudyInstanceUID)
    d.mkdir(parents=True, exist_ok=True)
    for ds in datasets:
        ds.save_as(d / f"{ds.Modality}_{ds.SOPInstanceUID}.dcm", enforce_file_format=True)
    return d


# ---------------------------------------------------------------- state / commands

def load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1, sort_keys=True, default=str))
    tmp.replace(STATE_FILE)


def process(c: Completed, state: dict, dry_run: bool = False, force: bool = False) -> bool:
    entry = state.get("studies", {}).get(c.key, {})
    if entry.get("status") == "sent" and not force:
        return True
    files = locate(c)
    if not files.get("primary"):
        log.warning("%s: no files in filestore yet for series %s", c.patient_id, c.series_uid)
        return False
    age = (datetime.now(timezone.utc) - c.updated_at).total_seconds()
    if not ready(files) and age < READY_TIMEOUT:
        log.info("%s: waiting for qXR objects (%s present)", c.patient_id,
                 ", ".join(k for k in ("sc", "sc_nosidebar", "sr", "pdf") if k in files) or "none")
        return False
    datasets = normalize(c, files)
    copies = save_copies(c, datasets)
    log.info("%s %s: %d objects, primary=%s, study %s -> %s (copies in %s)", c.patient_id, datasets[0].PatientName,
             len(datasets), files["primary_source"], c.study_uid[-14:], str(datasets[0].StudyInstanceUID)[-14:], copies)
    if dry_run:
        return True
    sent, total = send(datasets)
    status = "sent" if sent == total else "partial" if sent else "failed"
    state.setdefault("studies", {})[c.key] = {
        "status": status, "patient_id": c.patient_id, "sent": sent, "total": total,
        "normalized_study_uid": str(datasets[0].StudyInstanceUID), "primary": files["primary_source"],
        "at": datetime.now().isoformat(timespec="seconds"),
        "attempts": entry.get("attempts", 0) + 1}
    save_state(state)
    log.info("%s: %s (%d/%d) -> %s", c.patient_id, status.upper(), sent, total, GATEWAY[0])
    return status == "sent"


def cmd_watch(a) -> int:
    state = load_state()
    # Only studies completed after the adapter was first started; older ones via `send`.
    state.setdefault("watermark", datetime.now(timezone.utc).isoformat())
    save_state(state)
    log.info("PACS adapter: %s -> %s@%s:%s, primary from %s, watching studies completed after %s",
             ADAPTER_AE, *GATEWAY, PRIMARY_DIR, state["watermark"])
    while True:
        try:
            for c in completed("and i.updated_at > %s", (state["watermark"],)):
                if state.get("studies", {}).get(c.key, {}).get("attempts", 0) >= 3:
                    continue
                process(c, state)
        except Exception:
            log.exception("Poll failed")
        if a.once:
            return 0
        time.sleep(POLL_SECONDS)


def cmd_send(a) -> int:
    state = load_state()
    rows = completed("and p.patient_id = %s", (a.patient_id,))
    if not rows:
        log.error("No completed studies for %s", a.patient_id)
        return 1
    ok = all([process(c, state, dry_run=a.dry_run, force=True) for c in rows])
    return 0 if ok else 1


def cmd_list(a) -> int:
    sent = load_state().get("studies", {})
    for c in completed():
        e = sent.get(c.key, {})
        print(f"{c.updated_at:%Y-%m-%d %H:%M}  {c.patient_id:14} acc={c.accession[:16]:16} "
              f"{e.get('status', '-'):8} {e.get('primary', '')}")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("watch"); sp.add_argument("--once", action="store_true"); sp.set_defaults(func=cmd_watch)
    sp = sub.add_parser("send"); sp.add_argument("--patient-id", required=True)
    sp.add_argument("--dry-run", action="store_true", help="assemble + normalize + save copies, don't send")
    sp.set_defaults(func=cmd_send)
    sp = sub.add_parser("list"); sp.set_defaults(func=cmd_list)
    a = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("pynetdicom").setLevel(logging.WARNING)
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
