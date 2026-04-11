#!/usr/bin/env python3
"""
regenerate_processed.py — Regenerate botsabelo_processed DICOM files locally.

Reads botsabelo_census_v2.csv (Patient_ID column = current ZL EMR IDs) and
rebuilds both xray and ultrasound_cine DICOM files from local raw sources.

Usage:
    python tools/regenerate_processed.py [--xray] [--cine] [--patient PATIENT_ID]

Flags:
    --xray       regenerate CR X-ray DICOMs only
    --cine       regenerate US cine DICOMs only
    (default: both)

    --patient ID  regenerate for a single Patient_ID only
    --dry-run     print what would be done without writing files
    --substitute  comma-separated "bad.mp4:good.mp4" substitutions
                  (default: pos_pleural_effusion_01.mp4:pos_pleural_spine_sign_02.mp4)

Paths are resolved relative to this script's grandparent (the repo root).
"""

import argparse
import csv
import datetime
import io
import os
import struct
import subprocess
import sys
from pathlib import Path

import numpy as np
import pydicom
from PIL import Image
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, generate_uid

REPO_ROOT  = Path(__file__).resolve().parent.parent
RECORDS    = REPO_ROOT / "botsabelo-hospital-records"
RAW_XRAY   = RECORDS / "botsabelo_raw" / "TB_Chest_Radiography_Database"
RAW_US     = RECORDS / "botsabelo_raw" / "ultrasound"
OUT_XRAY   = RECORDS / "botsabelo_processed" / "xray"
OUT_CINE   = RECORDS / "botsabelo_processed" / "ultrasound_cine"
CENSUS_CSV = REPO_ROOT / "botsabelo_census_v2.csv"

INSTITUTION    = "Botsabelo MDR-TB Hospital"
CR_SOP_CLASS   = "1.2.840.10008.5.1.4.1.1.1"          # Computed Radiography
US_MULTI_SOP   = "1.2.840.10008.5.1.4.1.1.3.1"        # US Multiframe

# Source clips to substitute (1-frame or otherwise unusable → replacement)
DEFAULT_SUBSTITUTIONS = {
    "pos_pleural_effusion_01.mp4": "pos_pleural_spine_sign_02.mp4",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def to_dicom_date(iso: str) -> str:
    return iso.replace("-", "")[:8] if iso else ""


def to_dicom_name(name: str) -> str:
    if "^" in name:
        return name
    parts = name.strip().split()
    return f"{parts[-1]}^{' '.join(parts[:-1])}" if len(parts) >= 2 else name


def read_census() -> list[dict]:
    with open(CENSUS_CSV, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def probe_mp4(mp4_path: Path) -> tuple[int, int, int, float]:
    """Return (n_frames, width, height, fps) via ffprobe."""
    import json
    r = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", str(mp4_path)],
        capture_output=True, text=True, check=True,
    )
    data = json.loads(r.stdout)
    vs = next(s for s in data["streams"] if s["codec_type"] == "video")
    width  = int(vs["width"])
    height = int(vs["height"])
    frames = int(vs.get("nb_frames", 1))
    num, den = vs.get("avg_frame_rate", "15/1").split("/")
    fps = float(num) / float(den) if float(den) else 15.0
    return frames, width, height, fps


def decode_mp4_frames(mp4_path: Path, width: int, height: int) -> np.ndarray:
    """Decode all frames from MP4 to grayscale numpy array (N, H, W)."""
    result = subprocess.run(
        ["ffmpeg", "-i", str(mp4_path), "-f", "rawvideo", "-pix_fmt", "gray", "pipe:1"],
        capture_output=True, check=True,
    )
    raw = result.stdout
    frame_size = width * height
    n = len(raw) // frame_size
    return np.frombuffer(raw, dtype=np.uint8).reshape(n, height, width)


# ── DICOM builders ────────────────────────────────────────────────────────────

def build_xray_dicom(pixel_array: np.ndarray, patient_id: str, patient_name: str,
                     patient_dob: str, patient_sex: str, series_desc: str) -> bytes:
    rows, cols = pixel_array.shape
    now = datetime.datetime.now()
    date_str, time_str = now.strftime("%Y%m%d"), now.strftime("%H%M%S")
    sop_uid = generate_uid()

    fm = FileMetaDataset()
    fm.MediaStorageSOPClassUID    = CR_SOP_CLASS
    fm.MediaStorageSOPInstanceUID = sop_uid
    fm.TransferSyntaxUID          = ExplicitVRLittleEndian

    ds = FileDataset(None, {}, file_meta=fm, preamble=b"\0" * 128)
    ds.SpecificCharacterSet      = "ISO_IR 6"
    ds.SOPClassUID               = CR_SOP_CLASS
    ds.SOPInstanceUID            = sop_uid
    ds.PatientName               = patient_name
    ds.PatientID                 = patient_id
    ds.PatientBirthDate          = patient_dob
    ds.PatientSex                = patient_sex
    ds.StudyInstanceUID          = generate_uid()
    ds.StudyDate                 = date_str
    ds.StudyTime                 = time_str
    ds.StudyDescription          = "Chest X-Ray"
    ds.AccessionNumber           = ""
    ds.ReferringPhysicianName    = ""
    ds.SeriesInstanceUID         = generate_uid()
    ds.SeriesDate                = date_str
    ds.SeriesTime                = time_str
    ds.Modality                  = "CR"
    ds.SeriesDescription         = series_desc
    ds.SeriesNumber              = "1"
    ds.InstanceNumber            = "1"
    ds.InstitutionName           = INSTITUTION
    ds.ContentDate               = date_str
    ds.ContentTime               = time_str
    ds.SamplesPerPixel           = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.PixelRepresentation       = 0
    ds.HighBit                   = 7
    ds.BitsStored                = 8
    ds.BitsAllocated             = 8
    ds.Rows                      = rows
    ds.Columns                   = cols
    ds.PixelData                 = pixel_array.tobytes()

    buf = io.BytesIO()
    pydicom.dcmwrite(buf, ds)
    return buf.getvalue()


def build_cine_dicom(pixel_stack: np.ndarray, fps: float, patient_id: str,
                     patient_name: str, patient_dob: str, patient_sex: str,
                     series_desc: str) -> bytes:
    n_frames, rows, cols = pixel_stack.shape
    frame_time_ms = round(1000.0 / fps, 2)
    now = datetime.datetime.now()
    date_str, time_str = now.strftime("%Y%m%d"), now.strftime("%H%M%S")
    sop_uid = generate_uid()

    fm = FileMetaDataset()
    fm.MediaStorageSOPClassUID    = US_MULTI_SOP
    fm.MediaStorageSOPInstanceUID = sop_uid
    fm.TransferSyntaxUID          = ExplicitVRLittleEndian

    ds = FileDataset(None, {}, file_meta=fm, preamble=b"\0" * 128)
    ds.SpecificCharacterSet      = "ISO_IR 6"
    ds.SOPClassUID               = US_MULTI_SOP
    ds.SOPInstanceUID            = sop_uid
    ds.PatientName               = patient_name
    ds.PatientID                 = patient_id
    ds.PatientBirthDate          = patient_dob
    ds.PatientSex                = patient_sex
    ds.StudyInstanceUID          = generate_uid()
    ds.StudyDate                 = date_str
    ds.StudyTime                 = time_str
    ds.StudyDescription          = "FASH Ultrasound"
    ds.AccessionNumber           = ""
    ds.ReferringPhysicianName    = ""
    ds.SeriesInstanceUID         = generate_uid()
    ds.SeriesDate                = date_str
    ds.SeriesTime                = time_str
    ds.Modality                  = "US"
    ds.SeriesDescription         = series_desc
    ds.SeriesNumber              = "1"
    ds.InstanceNumber            = "1"
    ds.InstitutionName           = INSTITUTION
    ds.ContentDate               = date_str
    ds.ContentTime               = time_str
    ds.SamplesPerPixel           = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.Rows                      = rows
    ds.Columns                   = cols
    ds.BitsAllocated             = 8
    ds.BitsStored                = 8
    ds.HighBit                   = 7
    ds.PixelRepresentation       = 0
    ds.NumberOfFrames            = n_frames
    ds.CineRate                  = round(fps)
    ds.FrameTime                 = str(frame_time_ms)
    ds.FrameDelay                = "0"
    ds.RecommendedDisplayFrameRate = str(round(fps))
    ds.PixelData                 = pixel_stack.tobytes()

    buf = io.BytesIO()
    pydicom.dcmwrite(buf, ds)
    return buf.getvalue()


# ── Per-patient processing ────────────────────────────────────────────────────

# Pre-index available source PNGs
_tb_pngs  = sorted((RAW_XRAY / "Tuberculosis").glob("*.png"))
_neg_pngs = sorted((RAW_XRAY / "Normal").glob("*.png"))


def process_xray(row: dict, dry_run: bool) -> bool:
    pid        = row["Patient_ID"]
    name       = to_dicom_name(row["Name"])
    dob        = to_dicom_date(row.get("Birthdate", ""))
    sex        = row.get("Gender", "")
    mdr_status = row.get("MDR_Status", "")
    is_pos     = "Confirmed" in mdr_status or "Positive" in mdr_status

    idx       = int(row.get("Sequence", 1)) - 1
    png_pool  = _tb_pngs if is_pos else _neg_pngs
    src_png   = png_pool[idx % len(png_pool)]
    finding   = "MDR-TB Positive" if is_pos else "Normal"
    series_desc = f"CXR: {finding}"[:64]

    out_path  = OUT_XRAY / pid / f"XRAY_{pid}.dcm"
    print(f"  [xray] {pid:10s}  {src_png.name:40s}  → {out_path.relative_to(REPO_ROOT)}")

    if dry_run:
        return True

    img = Image.open(src_png).convert("L")
    pixel_array = np.array(img, dtype=np.uint8)
    dicom_bytes = build_xray_dicom(pixel_array, pid, name, dob, sex, series_desc)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(dicom_bytes)
    return True


def process_cine(row: dict, substitutions: dict, dry_run: bool) -> bool:
    pid        = row["Patient_ID"]
    name       = to_dicom_name(row["Name"])
    dob        = to_dicom_date(row.get("Birthdate", ""))
    sex        = row.get("Gender", "")
    finding    = row.get("FASH_Ultrasound_Finding", "FASH Ultrasound")
    series_desc = f"FASH Cine: {finding}"[:64]

    clip_gcs  = row.get("FASH_Clip", "")
    clip_name = os.path.basename(clip_gcs) if clip_gcs else ""
    clip_name = substitutions.get(clip_name, clip_name)

    if not clip_name:
        print(f"  [cine] {pid:10s}  WARNING: no clip assigned — skipping")
        return False

    src_mp4 = RAW_US / clip_name
    if not src_mp4.exists():
        print(f"  [cine] {pid:10s}  ERROR: {src_mp4} not found — skipping")
        return False

    out_path = OUT_CINE / pid / f"CINE_{pid}.dcm"

    try:
        n_frames, width, height, fps = probe_mp4(src_mp4)
    except Exception as e:
        print(f"  [cine] {pid:10s}  ERROR probing {src_mp4.name}: {e}")
        return False

    print(f"  [cine] {pid:10s}  {src_mp4.name:45s}  {n_frames}f {width}x{height} {fps:.1f}fps"
          f"  → {out_path.relative_to(REPO_ROOT)}")

    if dry_run:
        return True

    try:
        pixel_stack = decode_mp4_frames(src_mp4, width, height)
    except Exception as e:
        print(f"  [cine] {pid:10s}  ERROR decoding: {e}")
        return False

    dicom_bytes = build_cine_dicom(pixel_stack, fps, pid, name, dob, sex, series_desc)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(dicom_bytes)
    return True


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Regenerate botsabelo_processed DICOMs locally")
    parser.add_argument("--xray",      action="store_true", help="Regenerate X-ray DICOMs only")
    parser.add_argument("--cine",      action="store_true", help="Regenerate cine DICOMs only")
    parser.add_argument("--patient",   help="Regenerate a single patient ID only")
    parser.add_argument("--dry-run",   action="store_true", help="Print plan without writing")
    parser.add_argument("--substitute", default="",
                        help="Clip substitutions: 'bad.mp4:good.mp4,...'")
    args = parser.parse_args()

    do_xray = args.xray or (not args.xray and not args.cine)
    do_cine = args.cine or (not args.xray and not args.cine)

    substitutions = dict(DEFAULT_SUBSTITUTIONS)
    if args.substitute:
        for pair in args.substitute.split(","):
            bad, good = pair.strip().split(":")
            substitutions[bad.strip()] = good.strip()

    rows = read_census()
    if args.patient:
        rows = [r for r in rows if r["Patient_ID"] == args.patient]
        if not rows:
            print(f"ERROR: Patient_ID '{args.patient}' not found in census.", file=sys.stderr)
            sys.exit(1)

    print(f"Regenerating {len(rows)} patient(s)  "
          f"xray={'yes' if do_xray else 'no'}  cine={'yes' if do_cine else 'no'}"
          f"{'  [DRY RUN]' if args.dry_run else ''}\n")

    xray_ok = xray_fail = cine_ok = cine_fail = 0

    for row in rows:
        if do_xray:
            if process_xray(row, args.dry_run):
                xray_ok += 1
            else:
                xray_fail += 1
        if do_cine:
            if process_cine(row, substitutions, args.dry_run):
                cine_ok += 1
            else:
                cine_fail += 1

    print(f"\nDone.")
    if do_xray:
        print(f"  X-ray:  {xray_ok} ok  {xray_fail} failed")
    if do_cine:
        print(f"  Cine:   {cine_ok} ok  {cine_fail} failed")


if __name__ == "__main__":
    main()
