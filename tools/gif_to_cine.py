"""
gif_to_cine.py — Convert an animated GIF to a multi-frame DICOM Cine file.

Usage:
    python gif_to_cine.py input.gif output.dcm [options]

Options:
    --patient-name    "Last^First"        (default: Anonymous^Patient)
    --patient-id      "BHTB-2026-001"     (default: UNKNOWN)
    --study-desc      "FASH Ultrasound"   (default: derived from filename)
    --modality        "US"                (default: US)
    --fps             15                  (default: from GIF frame duration)

Output is an uncompressed multi-frame DICOM using Explicit VR Little Endian,
compatible with Cornerstone3D's /frames/N WADO-RS fetching.

Requirements:
    pip install pydicom pydicom-PIL Pillow numpy
"""

import argparse
import sys
import os
import datetime
import numpy as np
from pathlib import Path
from PIL import Image
import pydicom
from pydicom.dataset import Dataset, FileDataset, FileMetaDataset
from pydicom.uid import (
    ExplicitVRLittleEndian,
    generate_uid,
)
from pydicom.sequence import Sequence


def extract_gif_frames(gif_path: Path) -> tuple[list[np.ndarray], float]:
    """
    Extract frames from an animated GIF.
    Returns (list of RGB numpy arrays, frames-per-second).
    """
    img = Image.open(gif_path)
    frames = []
    durations = []

    try:
        while True:
            frame = img.convert("RGB")
            frames.append(np.array(frame, dtype=np.uint8))
            durations.append(img.info.get("duration", 100))  # ms per frame
            img.seek(img.tell() + 1)
    except EOFError:
        pass

    avg_duration_ms = sum(durations) / len(durations) if durations else 100
    fps = 1000.0 / avg_duration_ms
    return frames, fps


def build_cine_dicom(
    frames: list[np.ndarray],
    fps: float,
    output_path: Path,
    patient_name: str,
    patient_id: str,
    study_desc: str,
    modality: str,
) -> None:
    rows, cols, _ = frames[0].shape
    n_frames = len(frames)

    # ── File meta ────────────────────────────────────────────────────
    file_meta = FileMetaDataset()
    file_meta.MediaStorageSOPClassUID    = pydicom.uid.UID("1.2.840.10008.5.1.4.1.1.3.1")  # US Multi-frame
    file_meta.MediaStorageSOPInstanceUID = generate_uid()
    file_meta.TransferSyntaxUID          = ExplicitVRLittleEndian

    ds = FileDataset(str(output_path), {}, file_meta=file_meta, is_implicit_VR=False)
    ds.is_little_endian = True
    ds.is_implicit_VR   = False

    now = datetime.datetime.now()
    date_str = now.strftime("%Y%m%d")
    time_str = now.strftime("%H%M%S")

    # ── Patient / study / series / instance UIDs ─────────────────────
    ds.SOPClassUID       = file_meta.MediaStorageSOPClassUID
    ds.SOPInstanceUID    = file_meta.MediaStorageSOPInstanceUID
    ds.StudyInstanceUID  = generate_uid()
    ds.SeriesInstanceUID = generate_uid()

    # ── Patient ──────────────────────────────────────────────────────
    ds.PatientName      = patient_name
    ds.PatientID        = patient_id
    ds.PatientBirthDate = ""
    ds.PatientSex       = ""

    # ── Study ────────────────────────────────────────────────────────
    ds.StudyDate        = date_str
    ds.StudyTime        = time_str
    ds.AccessionNumber  = ""
    ds.StudyDescription = study_desc
    ds.ReferringPhysicianName = ""

    # ── Series ───────────────────────────────────────────────────────
    ds.SeriesDate        = date_str
    ds.SeriesTime        = time_str
    ds.Modality          = modality
    ds.SeriesDescription = study_desc
    ds.SeriesNumber      = "1"
    ds.InstanceNumber    = "1"

    # ── Image geometry ───────────────────────────────────────────────
    ds.Rows                  = rows
    ds.Columns               = cols
    ds.NumberOfFrames        = n_frames
    ds.SamplesPerPixel       = 3
    ds.PhotometricInterpretation = "RGB"
    ds.BitsAllocated         = 8
    ds.BitsStored            = 8
    ds.HighBit               = 7
    ds.PixelRepresentation   = 0
    ds.PlanarConfiguration   = 0   # pixel-interleaved (R,G,B,R,G,B,…)

    # ── Cine / timing ────────────────────────────────────────────────
    frame_time_ms = round(1000.0 / fps, 2)
    ds.CineRate              = round(fps)
    ds.FrameTime             = str(frame_time_ms)
    ds.FrameDelay            = "0"
    ds.RecommendedDisplayFrameRate = str(round(fps))

    # ── Pixel data ───────────────────────────────────────────────────
    pixel_array = np.stack(frames, axis=0)          # (N, rows, cols, 3)
    ds.PixelData = pixel_array.tobytes()
    ds["PixelData"].is_undefined_length = False

    pydicom.dcmwrite(str(output_path), ds)
    print(
        f"Written: {output_path}  "
        f"({n_frames} frames, {cols}x{rows}, {fps:.1f} fps, "
        f"modality={modality})"
    )


def main():
    parser = argparse.ArgumentParser(description="Convert animated GIF to multi-frame DICOM Cine")
    parser.add_argument("input",         help="Input GIF file")
    parser.add_argument("output",        help="Output DICOM file (.dcm)")
    parser.add_argument("--patient-name", default="Anonymous^Patient")
    parser.add_argument("--patient-id",   default="UNKNOWN")
    parser.add_argument("--study-desc",   default=None)
    parser.add_argument("--modality",     default="US")
    parser.add_argument("--fps",          type=float, default=None,
                        help="Override frame rate (default: read from GIF)")
    args = parser.parse_args()

    gif_path    = Path(args.input)
    output_path = Path(args.output)

    if not gif_path.exists():
        print(f"Error: {gif_path} not found", file=sys.stderr)
        sys.exit(1)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    study_desc = args.study_desc or gif_path.stem.replace("_", " ").replace("-", " ").title()

    print(f"Extracting frames from {gif_path} …")
    frames, gif_fps = extract_gif_frames(gif_path)
    fps = args.fps if args.fps else gif_fps
    print(f"  {len(frames)} frames at {fps:.1f} fps")

    build_cine_dicom(
        frames=frames,
        fps=fps,
        output_path=output_path,
        patient_name=args.patient_name,
        patient_id=args.patient_id,
        study_desc=study_desc,
        modality=args.modality,
    )


if __name__ == "__main__":
    main()
