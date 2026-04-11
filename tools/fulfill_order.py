#!/usr/bin/env python3
"""
fulfill_order.py — Simulate modality image acquisition from the MWL.

For each pending worklist entry in orthanc-modality:
  1. C-FIND the MWL to get patient demographics and order info
  2. Find a matching DICOM in botsabelo_processed/xray/ by PatientID
     (falls back to a random available image if no exact match)
  3. Patch DICOM tags with MWL demographics and order info
  4. POST the patched DICOM to orthanc-modality REST API

The resulting study will appear in orthanc-modality under the correct
patient / accession number, ready for the acquisition loop to pick up
and forward to the cloud PACS.

Usage:
    python tools/fulfill_order.py [options]
    python tools/fulfill_order.py --dry-run
    python tools/fulfill_order.py --modality-url http://localhost:8042
    python tools/fulfill_order.py --mwl-host localhost --mwl-port 4242
"""

import argparse
import io
import random
import sys
from pathlib import Path
from datetime import datetime

import pydicom
import requests
from pydicom.dataset import Dataset, FileDataset, FileMetaDataset
from pydicom.uid import generate_uid, ExplicitVRLittleEndian
from pynetdicom import AE
from pynetdicom.sop_class import ModalityWorklistInformationFind

INSTITUTION = "Botsabelo MDR-TB Hospital"


# ── MWL C-FIND ───────────────────────────────────────────────────────────────

def query_mwl(host: str, port: int, calling_aet: str = "FULFILL_SCU") -> list[dict]:
    """
    C-FIND the Orthanc modality worklist SCP.
    Returns a list of dicts with keys:
        patient_id, patient_name, dob, sex,
        accession, procedure_desc, modality,
        scheduled_date, scheduled_time, study_instance_uid
    """
    ae = AE(ae_title=calling_aet)
    ae.add_requested_context(ModalityWorklistInformationFind)

    query_ds = Dataset()
    query_ds.PatientName                   = ""
    query_ds.PatientID                     = ""
    query_ds.PatientBirthDate              = ""
    query_ds.PatientSex                    = ""
    query_ds.AccessionNumber               = ""
    query_ds.RequestedProcedureDescription = ""
    query_ds.StudyInstanceUID              = ""

    sps = Dataset()
    sps.ScheduledProcedureStepStartDate = ""
    sps.ScheduledProcedureStepStartTime = ""
    sps.Modality                        = ""
    sps.ScheduledStationAETitle         = ""
    sps.ScheduledStationName            = ""
    query_ds.ScheduledProcedureStepSequence = [sps]

    entries = []
    assoc = ae.associate(host, port)
    if not assoc.is_established:
        raise ConnectionError(f"Cannot connect to MWL SCP at {host}:{port}")
    try:
        for status, identifier in assoc.send_c_find(query_ds, ModalityWorklistInformationFind):
            if identifier is None:
                continue
            step = {}
            if identifier.get("ScheduledProcedureStepSequence"):
                sps_item = identifier.ScheduledProcedureStepSequence[0]
                step = {
                    "modality":       str(sps_item.get("Modality", "CR")),
                    "scheduled_date": str(sps_item.get("ScheduledProcedureStepStartDate", "")),
                    "scheduled_time": str(sps_item.get("ScheduledProcedureStepStartTime", "")),
                    "station_aet":    str(sps_item.get("ScheduledStationAETitle", "")),
                }
            entries.append({
                "patient_id":    str(identifier.get("PatientID", "")),
                "patient_name":  str(identifier.get("PatientName", "")),
                "dob":           str(identifier.get("PatientBirthDate", "")),
                "sex":           str(identifier.get("PatientSex", "")),
                "accession":     str(identifier.get("AccessionNumber", "")),
                "procedure_desc":str(identifier.get("RequestedProcedureDescription", "Chest X-Ray")),
                "study_uid":     str(identifier.get("StudyInstanceUID", "")),
                **step,
            })
    finally:
        assoc.release()

    return entries


# ── Image lookup ─────────────────────────────────────────────────────────────

def find_dicom(xray_dir: Path, patient_id: str) -> Path | None:
    """
    Look for <xray_dir>/<patient_id>/XRAY_<patient_id>.dcm.
    Returns Path if found, None otherwise.
    """
    candidate = xray_dir / patient_id / f"XRAY_{patient_id}.dcm"
    return candidate if candidate.exists() else None


def pick_fallback_dicom(xray_dir: Path) -> Path | None:
    """Return a random available DICOM from the xray dir."""
    candidates = list(xray_dir.glob("*/XRAY_*.dcm"))
    return random.choice(candidates) if candidates else None


# ── DICOM patching ───────────────────────────────────────────────────────────

def patch_dicom(source_path: Path, entry: dict) -> bytes:
    """
    Load source DICOM, replace patient/study demographics with MWL values,
    generate new UIDs, and return serialised bytes.
    """
    ds = pydicom.dcmread(str(source_path))

    now = datetime.now()
    date_str = now.strftime("%Y%m%d")
    time_str = now.strftime("%H%M%S")

    # ── Patient demographics from MWL ─────────────────────────────────
    ds.PatientName      = entry["patient_name"]
    ds.PatientID        = entry["patient_id"]
    ds.PatientBirthDate = entry.get("dob", "")
    ds.PatientSex       = entry.get("sex", "")

    # ── Study from MWL ────────────────────────────────────────────────
    new_study_uid = entry.get("study_uid") or generate_uid()
    ds.StudyInstanceUID     = new_study_uid
    ds.StudyDate            = entry.get("scheduled_date") or date_str
    ds.StudyTime            = entry.get("scheduled_time") or time_str
    ds.StudyDescription     = entry.get("procedure_desc", "Chest X-Ray")
    ds.AccessionNumber      = entry.get("accession", "")

    # ── Series / instance — always fresh ─────────────────────────────
    ds.SeriesInstanceUID    = generate_uid()
    ds.SeriesDate           = date_str
    ds.SeriesTime           = time_str
    ds.SeriesDescription    = entry.get("procedure_desc", "Chest X-Ray")
    ds.SeriesNumber         = "1"

    ds.SOPInstanceUID       = generate_uid()
    ds.InstanceNumber       = "1"
    ds.ContentDate          = date_str
    ds.ContentTime          = time_str

    ds.Modality             = entry.get("modality", "CR")
    ds.InstitutionName      = INSTITUTION

    # Update file meta to match new SOP instance UID
    if hasattr(ds, "file_meta"):
        ds.file_meta.MediaStorageSOPInstanceUID = ds.SOPInstanceUID
        ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian

    out = io.BytesIO()
    pydicom.dcmwrite(out, ds)
    out.seek(0)
    return out.read()


# ── Upload to Orthanc ────────────────────────────────────────────────────────

def upload_to_orthanc(dicom_bytes: bytes, base_url: str, user: str, password: str) -> str:
    """POST DICOM instance to Orthanc REST API. Returns the Orthanc instance ID."""
    r = requests.post(
        f"{base_url}/instances",
        data=dicom_bytes,
        headers={"Content-Type": "application/dicom"},
        auth=(user, password),
        timeout=30,
    )
    r.raise_for_status()
    return r.json().get("ID", "")


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Fulfill MWL orders with sample DICOM images")
    parser.add_argument("--mwl-host",     default="localhost")
    parser.add_argument("--mwl-port",     type=int, default=4242)
    parser.add_argument("--modality-url", default="http://localhost:8042",
                        help="Orthanc modality REST base URL")
    parser.add_argument("--modality-user",     default="admin")
    parser.add_argument("--modality-password", default="admin")
    parser.add_argument("--xray-dir",
                        default=str(Path(__file__).parent.parent /
                                    "botsabelo-hospital-records/botsabelo_processed/xray"),
                        help="Directory containing per-patient DICOM subdirs")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be uploaded without actually uploading")
    args = parser.parse_args()

    xray_dir = Path(args.xray_dir)
    if not xray_dir.exists():
        print(f"ERROR: xray dir not found: {xray_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"Querying MWL at {args.mwl_host}:{args.mwl_port} …")
    try:
        entries = query_mwl(args.mwl_host, args.mwl_port)
    except Exception as e:
        print(f"ERROR: MWL query failed: {e}", file=sys.stderr)
        sys.exit(1)

    if not entries:
        print("No pending worklist entries found.")
        return

    print(f"Found {len(entries)} worklist entry(ies).\n")

    for entry in entries:
        pid   = entry["patient_id"]
        name  = entry["patient_name"]
        acc   = entry["accession"]
        desc  = entry["procedure_desc"]
        mod   = entry.get("modality", "CR")
        print(f"── {name} ({pid})  |  {desc} ({mod})  |  accession={acc}")

        # Find image
        dicom_path = find_dicom(xray_dir, pid)
        if dicom_path:
            print(f"   Image:  {dicom_path.name}  (exact patient match)")
        else:
            dicom_path = pick_fallback_dicom(xray_dir)
            if not dicom_path:
                print(f"   ERROR: no DICOM images found in {xray_dir} — skipping")
                continue
            print(f"   Image:  {dicom_path.parent.name}/{dicom_path.name}  (fallback — no image for {pid})")

        if args.dry_run:
            print(f"   DRY-RUN: would patch and upload to {args.modality_url}")
            continue

        # Patch and upload
        try:
            dicom_bytes = patch_dicom(dicom_path, entry)
            instance_id = upload_to_orthanc(
                dicom_bytes, args.modality_url,
                args.modality_user, args.modality_password,
            )
            print(f"   Uploaded ✓  Orthanc instance: {instance_id}")
        except Exception as e:
            print(f"   ERROR: {e}", file=sys.stderr)

    print("\nDone.")


if __name__ == "__main__":
    main()
