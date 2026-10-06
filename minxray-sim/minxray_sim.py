#!/usr/bin/env python3
"""minxray_sim.py — simulated MinXray wireless DR station (dicomPACS DX-R style).

Plays the modality side of the Qure.ai field workflow:

  qTrack "Register" --HTTP--> MWL server --C-FIND--> this simulator
                                  ^                     | MPPS N-CREATE (IN PROGRESS)
                                  +---- MPPS -----------+ C-STORE DX -> dcmio :5252
                                                        | MPPS N-SET  (COMPLETED)

Commands:
  worklist                     list scheduled procedures from the MWL SCP
  capture                      pick a worklist item, "expose" a PNG, send it
  watch                        agent: poll the worklist and capture each new item (see agent.py)
  convert PNG OUT.dcm          offline PNG -> MinXray DX conversion only

Configuration (environment variables; defaults suit running on the laptop host,
the compose file overrides them for running inside the Qure docker network):
  STATION_AE   our AE title / scheduled station         (default: MIX)
  MWL_HOST     MWL SCP host                              (default: 127.0.0.1)
  MWL_PORT     MWL SCP port                              (default: 9003)
  MWL_AE       MWL SCP called AE                         (default: ANY-SCP)
  STORE_HOST   dcmio DICOM gateway host                  (default: 127.0.0.1)
  STORE_PORT   dcmio DICOM gateway port                  (default: 5252)
  STORE_AE     dcmio called AE                           (default: QUREAI)
  LIBRARY_DIR  directory of source chest PNGs            (default: ./library)
  OUTPUT_DIR   where copies of sent DICOM are kept       (default: ./output)
  FORWARD_TO   extra C-STORE destinations for each capture, comma-separated
               CALLED_AE@host:port (e.g. ADVAPACS_GW_02@host.docker.internal:11112)
  FORWARD_AE   calling AE for those forwards, i.e. the AE registered for this
               modality at the destination                (default: STATION_AE)
"""
from __future__ import annotations

import argparse
import logging
import os
import random
import sys
from datetime import datetime
from pathlib import Path

from pydicom.dataset import Dataset
from pydicom.sequence import Sequence
from pydicom.uid import generate_uid
from pynetdicom import AE
from pynetdicom.sop_class import (
    DigitalXRayImageStorageForPresentation,
    DigitalXRayImageStorageForProcessing,
    ModalityPerformedProcedureStep,
    ModalityWorklistInformationFind,
)

import dx

log = logging.getLogger("minxray-sim")

CFG = {
    "STATION_AE": os.environ.get("STATION_AE", "MIX"),
    "MWL_HOST": os.environ.get("MWL_HOST", "127.0.0.1"),
    "MWL_PORT": int(os.environ.get("MWL_PORT", "9003")),
    "MWL_AE": os.environ.get("MWL_AE", "ANY-SCP"),
    "STORE_HOST": os.environ.get("STORE_HOST", "127.0.0.1"),
    "STORE_PORT": int(os.environ.get("STORE_PORT", "5252")),
    "STORE_AE": os.environ.get("STORE_AE", "QUREAI"),
    "LIBRARY_DIR": Path(os.environ.get("LIBRARY_DIR", "library")),
    "OUTPUT_DIR": Path(os.environ.get("OUTPUT_DIR", "output")),
    "FORWARD_TO": os.environ.get("FORWARD_TO", ""),
}
CFG["FORWARD_AE"] = os.environ.get("FORWARD_AE", CFG["STATION_AE"])

PATIENT_KEYS = ("PatientName", "PatientID", "PatientBirthDate", "PatientSex",
                "AccessionNumber", "StudyInstanceUID", "RequestedProcedureID",
                "RequestedProcedureDescription", "ReferringPhysicianName")
SPS_KEYS = ("Modality", "ScheduledStationAETitle", "ScheduledProcedureStepStartDate",
            "ScheduledProcedureStepStartTime", "ScheduledProcedureStepID",
            "ScheduledProcedureStepDescription")


def _ae(calling_ae: str | None = None) -> AE:
    ae = AE(ae_title=calling_ae or CFG["STATION_AE"])
    ae.acse_timeout = ae.dimse_timeout = ae.network_timeout = 30
    return ae


# ---------------------------------------------------------------- worklist

def _fix_text(value) -> str:
    """Qure's MWL server sends UTF-8 text without declaring a UTF-8 Specific
    Character Set, so pydicom decodes it as Latin-1 ('Tšepiso' -> 'TÅ¡episo').
    Undo that when the Latin-1 bytes form valid UTF-8; leave real Latin-1 alone."""
    s = str(value or "")
    try:
        return s.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return s


def query_worklist(station: str | None, date: str | None, modality: str | None) -> list[dict]:
    q = Dataset()
    for kw in PATIENT_KEYS:
        setattr(q, kw, "")
    sps = Dataset()
    for kw in SPS_KEYS:
        setattr(sps, kw, "")
    if station:
        sps.ScheduledStationAETitle = station
    if date:
        sps.ScheduledProcedureStepStartDate = date
    if modality:
        sps.Modality = modality
    q.ScheduledProcedureStepSequence = Sequence([sps])

    ae = _ae()
    ae.add_requested_context(ModalityWorklistInformationFind)
    assoc = ae.associate(CFG["MWL_HOST"], CFG["MWL_PORT"], ae_title=CFG["MWL_AE"])
    if not assoc.is_established:
        raise SystemExit(f"MWL association to {CFG['MWL_HOST']}:{CFG['MWL_PORT']} failed")
    items = []
    try:
        for status, ident in assoc.send_c_find(q, ModalityWorklistInformationFind):
            if status and status.Status in (0xFF00, 0xFF01) and ident is not None:
                item = {kw: _fix_text(ident.get(kw, "")) for kw in PATIENT_KEYS}
                s = ident.ScheduledProcedureStepSequence[0] if ident.get("ScheduledProcedureStepSequence") else Dataset()
                item.update({kw: _fix_text(s.get(kw, "")) for kw in SPS_KEYS})
                items.append(item)
    finally:
        assoc.release()
    items.sort(key=lambda i: (i["ScheduledProcedureStepStartDate"], i["ScheduledProcedureStepStartTime"]), reverse=True)
    return items


def print_worklist(items: list[dict]) -> None:
    if not items:
        print("(worklist empty)")
        return
    print(f"{'#':>3}  {'Date':8}  {'Accession':12}  {'Patient ID':16}  {'Name':28}  {'Sex':3}  {'DOB':8}  Mod  Station")
    for n, i in enumerate(items):
        print(f"{n:>3}  {i['ScheduledProcedureStepStartDate']:8}  {i['AccessionNumber']:12}  {i['PatientID']:16}  "
              f"{i['PatientName'][:28]:28}  {i['PatientSex']:3}  {i['PatientBirthDate']:8}  "
              f"{i['Modality']:3}  {i['ScheduledStationAETitle']}")


# ---------------------------------------------------------------- MPPS

def _mpps_assoc():
    # Short timeout: Qure's MWL SCP (qureai/dicom-scp) never answers an MPPS
    # request when its callback to the platform API fails (seen: HTTP 403).
    ae = _ae()
    ae.dimse_timeout = int(os.environ.get("MPPS_TIMEOUT", "10"))
    ae.add_requested_context(ModalityPerformedProcedureStep)
    assoc = ae.associate(CFG["MWL_HOST"], CFG["MWL_PORT"], ae_title=CFG["MWL_AE"])
    return assoc if assoc.is_established else None


def mpps_create(item: dict, mpps_uid: str, started: datetime) -> bool:
    ds = Dataset()
    ds.SpecificCharacterSet = "ISO_IR 192"
    ssa = Dataset()
    ssa.StudyInstanceUID = item.get("StudyInstanceUID", "")
    ssa.AccessionNumber = item.get("AccessionNumber", "")
    ssa.RequestedProcedureID = item.get("RequestedProcedureID", "")
    ssa.RequestedProcedureDescription = item.get("RequestedProcedureDescription", "")
    ssa.ScheduledProcedureStepID = item.get("ScheduledProcedureStepID", "")
    ssa.ScheduledProcedureStepDescription = item.get("ScheduledProcedureStepDescription", "")
    ssa.ScheduledProtocolCodeSequence = Sequence()
    ssa.ReferencedStudySequence = Sequence()
    ds.ScheduledStepAttributesSequence = Sequence([ssa])
    ds.PatientName = item.get("PatientName", "")
    ds.PatientID = item.get("PatientID", "")
    ds.PatientBirthDate = item.get("PatientBirthDate", "")
    ds.PatientSex = item.get("PatientSex", "")
    ds.ReferencedPatientSequence = Sequence()
    ds.PerformedProcedureStepID = mpps_uid[-16:]
    ds.PerformedStationAETitle = CFG["STATION_AE"]
    ds.PerformedStationName = CFG["STATION_AE"]
    ds.PerformedLocation = ""
    ds.PerformedProcedureStepStartDate = started.strftime("%Y%m%d")
    ds.PerformedProcedureStepStartTime = started.strftime("%H%M%S")
    ds.PerformedProcedureStepStatus = "IN PROGRESS"
    ds.PerformedProcedureStepDescription = item.get("ScheduledProcedureStepDescription", "") or "CHEST PA"
    ds.PerformedProcedureTypeDescription = ""
    ds.ProcedureCodeSequence = Sequence()
    ds.PerformedProcedureStepEndDate = ""
    ds.PerformedProcedureStepEndTime = ""
    ds.Modality = "DX"
    ds.StudyID = item.get("RequestedProcedureID", "")[:16]
    ds.PerformedProtocolCodeSequence = Sequence()
    ds.PerformedSeriesSequence = Sequence()

    assoc = _mpps_assoc()
    if assoc is None:
        log.warning("MPPS association failed; continuing without MPPS")
        return False
    try:
        status, _ = assoc.send_n_create(ds, ModalityPerformedProcedureStep, mpps_uid)
        ok = bool(status) and status.Status == 0x0000
        log.info("MPPS N-CREATE IN PROGRESS -> 0x%04X", status.Status if status else -1)
        return ok
    finally:
        assoc.release()


def mpps_finish(mpps_uid: str, sent: Dataset | None, completed: bool) -> None:
    now = datetime.now()
    ds = Dataset()
    ds.PerformedProcedureStepStatus = "COMPLETED" if completed else "DISCONTINUED"
    ds.PerformedProcedureStepEndDate = now.strftime("%Y%m%d")
    ds.PerformedProcedureStepEndTime = now.strftime("%H%M%S")
    series = Dataset()
    if sent is not None:
        series.SeriesInstanceUID = sent.SeriesInstanceUID
        series.SeriesDescription = sent.get("SeriesDescription", "")
        series.PerformingPhysicianName = ""
        series.OperatorsName = ""
        series.ProtocolName = "CHEST PA"
        series.RetrieveAETitle = ""
        ref = Dataset()
        ref.ReferencedSOPClassUID = sent.SOPClassUID
        ref.ReferencedSOPInstanceUID = sent.SOPInstanceUID
        series.ReferencedImageSequence = Sequence([ref])
        series.ReferencedNonImageCompositeSOPInstanceSequence = Sequence()
        ds.PerformedSeriesSequence = Sequence([series])
    assoc = _mpps_assoc()
    if assoc is None:
        log.warning("MPPS association failed; could not send %s", ds.PerformedProcedureStepStatus)
        return
    try:
        status, _ = assoc.send_n_set(ds, ModalityPerformedProcedureStep, mpps_uid)
        log.info("MPPS N-SET %s -> 0x%04X", ds.PerformedProcedureStepStatus, status.Status if status else -1)
    finally:
        assoc.release()


# ---------------------------------------------------------------- store

def c_store(ds: Dataset, path: Path, host: str | None = None, port: int | None = None,
            called_ae: str | None = None, calling_ae: str | None = None) -> bool:
    """Send the saved file, so the bytes on the wire match its Explicit VR
    encoding exactly (an in-memory FileDataset may be flagged as implicit).
    Defaults to the dcmio gateway (STORE_*)."""
    host, port = host or CFG["STORE_HOST"], port or CFG["STORE_PORT"]
    called_ae = called_ae or CFG["STORE_AE"]
    ae = _ae(calling_ae)
    ae.add_requested_context(ds.SOPClassUID, ds.file_meta.TransferSyntaxUID)
    assoc = ae.associate(host, port, ae_title=called_ae, max_pdu=0)
    if not assoc.is_established:
        log.error("C-STORE association to %s@%s:%s failed%s", called_ae, host, port,
                  " (rejected: is our calling AE registered there?)" if assoc.is_rejected else "")
        return False
    try:
        status = assoc.send_c_store(path)
        ok = bool(status) and status.Status == 0x0000
        log.info("C-STORE -> %s@%s:%s %s -> 0x%04X", called_ae, host, port,
                 ds.SOPInstanceUID, status.Status if status else -1)
        return ok
    finally:
        assoc.release()


def forward_destinations() -> list[tuple[str, str, int]]:
    """Parse FORWARD_TO ('AE@host:port,...') into (called_ae, host, port)."""
    dests = []
    for spec in filter(None, (s.strip() for s in CFG["FORWARD_TO"].split(","))):
        called, _, hostport = spec.partition("@")
        host, _, port = hostport.rpartition(":")
        if not (called and host and port.isdigit()):
            raise SystemExit(f"Bad FORWARD_TO entry {spec!r}; expected CALLED_AE@host:port")
        dests.append((called, host, int(port)))
    return dests


def capture_item(item: dict, png: Path, params: dx.SimParams, use_mpps: bool = True) -> bool:
    """Expose one worklist item: MPPS IN PROGRESS -> build DX -> C-STORE to dcmio
    -> MPPS COMPLETED (or DISCONTINUED) -> forward to FORWARD_TO destinations.
    Returns True when the image reached dcmio."""
    log.info("Capturing %s (%s, acc %s) from %s", item["PatientName"], item["PatientID"],
             item["AccessionNumber"], png)
    mpps_uid = generate_uid()
    mpps_ok = use_mpps and mpps_create(item, mpps_uid, datetime.now())

    ds = dx.build_dx(png, params, item, station_ae=CFG["STATION_AE"])
    if mpps_ok:
        ref = Dataset()
        ref.ReferencedSOPClassUID = ModalityPerformedProcedureStep
        ref.ReferencedSOPInstanceUID = mpps_uid
        ds.ReferencedPerformedProcedureStepSequence = Sequence([ref])
    out = CFG["OUTPUT_DIR"] / f"{ds.AccessionNumber or ds.PatientID}_{ds.SOPInstanceUID}.dcm"
    out.parent.mkdir(parents=True, exist_ok=True)
    ds.save_as(out, enforce_file_format=True)
    log.info("Saved %s", out)

    sent = c_store(ds, out)
    if mpps_ok:
        mpps_finish(mpps_uid, ds if sent else None, completed=sent)
    if sent:
        # Like a DX-R station configured with several send destinations; failures
        # here don't undo the capture (the gateway queues/retries on its own side).
        for called, host, port in forward_destinations():
            c_store(ds, out, host, port, called, CFG["FORWARD_AE"])
    return sent


# ---------------------------------------------------------------- commands

SOURCE_SUFFIXES = {".png", ".jpg", ".jpeg"}


def _pick_source(explicit: str | None, label: str | None) -> Path:
    """An explicit file, or a random image from LIBRARY_DIR (optionally only
    from the <label>/ subfolder, e.g. Normal or Tuberculosis)."""
    if explicit:
        return Path(explicit)
    lib = CFG["LIBRARY_DIR"]
    root = lib / label if label else lib
    images = sorted(p for p in root.rglob("*") if p.suffix.lower() in SOURCE_SUFFIXES)
    if not images:
        raise SystemExit(f"No PNG/JPEG images under {root}; pass --image or populate LIBRARY_DIR")
    return random.choice(images)


def _sim_params(a) -> dx.SimParams:
    return dx.SimParams(panel=a.panel, dose=a.dose, seed=a.seed, anatomy_fraction=a.anatomy_fraction,
                        presentation=a.presentation, defects=a.defects,
                        image_type_original=a.image_type_original)


def cmd_worklist(a) -> int:
    print_worklist(query_worklist(a.station, a.date, a.modality))
    return 0


def cmd_capture(a) -> int:
    items = query_worklist(a.station, a.date, a.modality)
    if a.accession:
        items = [i for i in items if i["AccessionNumber"] == a.accession]
    if a.patient_id:
        items = [i for i in items if i["PatientID"] == a.patient_id]
    if not items:
        raise SystemExit("No matching worklist item")
    if a.index is None and len(items) > 1 and not (a.accession or a.patient_id):
        print_worklist(items)
        raise SystemExit("Several items match; choose one with --index, --accession or --patient-id")
    item = items[a.index or 0]
    png = _pick_source(a.image, a.label)
    return 0 if capture_item(item, png, _sim_params(a), use_mpps=not a.no_mpps) else 1


def cmd_watch(a) -> int:
    import agent  # imports this module; keep the dependency one-way at load time
    return agent.run(_sim_params(a), once=a.once, dry_run=a.dry_run)


def cmd_convert(a) -> int:
    patient = {"PatientName": a.patient_name, "PatientID": a.patient_id or "", "PatientSex": a.sex,
               "PatientBirthDate": a.birth_date, "AccessionNumber": a.accession or ""}
    ds = dx.build_dx(Path(a.png), _sim_params(a), {k: v for k, v in patient.items() if v},
                     station_ae=CFG["STATION_AE"])
    ds.save_as(a.out, enforce_file_format=True)
    print(f"Wrote {a.out}: {ds.Rows}x{ds.Columns} {ds.BitsStored}-bit {ds.PresentationIntentType}")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    def wl_filters(sp):
        sp.add_argument("--station", help="filter ScheduledStationAETitle (default: no filter)")
        sp.add_argument("--date", help="filter ScheduledProcedureStepStartDate, YYYYMMDD or range")
        sp.add_argument("--modality", help="filter Modality, e.g. DX")

    def sim_opts(sp):
        sp.add_argument("--panel", choices=sorted(dx.PANELS), default="wireless154")
        sp.add_argument("--dose", type=float, default=1.0, help="relative dose (noise level)")
        sp.add_argument("--seed", type=int)
        sp.add_argument("--anatomy-fraction", type=float, default=0.86)
        sp.add_argument("--presentation", choices=["presentation", "processing"], default="presentation")
        sp.add_argument("--defects", action="store_true", help="add gain banding and dead pixels/column")
        sp.add_argument("--image-type-original", action="store_true",
                        help="ImageType ORIGINAL\\PRIMARY instead of DERIVED\\SECONDARY")

    sp = sub.add_parser("worklist", help="list worklist items")
    wl_filters(sp)
    sp.set_defaults(func=cmd_worklist)

    sp = sub.add_parser("capture", help="expose a worklist patient and send the image")
    wl_filters(sp)
    sp.add_argument("--accession")
    sp.add_argument("--patient-id")
    sp.add_argument("--index", type=int, help="row number from `worklist`")
    sp.add_argument("--image", help="source PNG/JPEG (default: random from LIBRARY_DIR)")
    sp.add_argument("--label", help="pick randomly from LIBRARY_DIR/<label>/, e.g. Normal or Tuberculosis")
    sp.add_argument("--no-mpps", action="store_true")
    sim_opts(sp)
    sp.set_defaults(func=cmd_capture)

    sp = sub.add_parser("watch", help="agent: poll the worklist and capture each new item")
    sp.add_argument("--once", action="store_true", help="one worklist pass, then exit")
    sp.add_argument("--dry-run", action="store_true", help="log what would be captured; send nothing")
    sim_opts(sp)
    sp.set_defaults(func=cmd_watch)

    sp = sub.add_parser("convert", help="PNG -> DX file, no network")
    sp.add_argument("png")
    sp.add_argument("out")
    sp.add_argument("--patient-name", default="SIMULATED^PATIENT")
    sp.add_argument("--patient-id")
    sp.add_argument("--sex", default="")
    sp.add_argument("--birth-date", default="")
    sp.add_argument("--accession")
    sim_opts(sp)
    sp.set_defaults(func=cmd_convert)

    a = p.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    if not a.verbose:
        logging.getLogger("pynetdicom").setLevel(logging.WARNING)
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
