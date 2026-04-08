"""
dicom_info.py — Quick DICOM file inspector.

Prints the key tags that distinguish MP4-wrapped, Cine, and single-frame DICOM.

Usage:
    python tools/dicom_info.py file.dcm [file2.dcm ...]
    python tools/dicom_info.py /path/to/folder/
"""

import sys
from pathlib import Path
import pydicom

# Transfer syntax UIDs worth knowing
TRANSFER_SYNTAX_NAMES = {
    "1.2.840.10008.1.2"        : "Implicit VR Little Endian",
    "1.2.840.10008.1.2.1"      : "Explicit VR Little Endian",
    "1.2.840.10008.1.2.2"      : "Explicit VR Big Endian",
    "1.2.840.10008.1.2.4.50"   : "JPEG Baseline (lossy)",
    "1.2.840.10008.1.2.4.51"   : "JPEG Extended",
    "1.2.840.10008.1.2.4.57"   : "JPEG Lossless",
    "1.2.840.10008.1.2.4.70"   : "JPEG Lossless SV1",
    "1.2.840.10008.1.2.4.90"   : "JPEG 2000 Lossless",
    "1.2.840.10008.1.2.4.91"   : "JPEG 2000",
    "1.2.840.10008.1.2.4.100"  : "MPEG2 Main Profile",
    "1.2.840.10008.1.2.4.101"  : "MPEG2 Main Profile High Level",
    "1.2.840.10008.1.2.4.102"  : "MPEG-4 AVC/H.264 High Profile",
    "1.2.840.10008.1.2.4.103"  : "MPEG-4 AVC/H.264 BD-compatible",
    "1.2.840.10008.1.2.4.104"  : "MPEG-4 AVC/H.264 High Profile 2D",
    "1.2.840.10008.1.2.4.105"  : "MPEG-4 AVC/H.264 High Profile Stereo",
    "1.2.840.10008.1.2.5"      : "RLE Lossless",
}

# SOP classes that are inherently video — Orthanc DICOMweb /frames/N returns
# "Not implemented yet" for these regardless of transfer syntax.
VIDEO_SOP_CLASSES = {
    "1.2.840.10008.5.1.4.1.1.77.1.1.1" : "Video Endoscopic Image Storage",
    "1.2.840.10008.5.1.4.1.1.77.1.2.1" : "Video Microscopic Image Storage",
    "1.2.840.10008.5.1.4.1.1.77.1.4.1" : "Video Photographic Image Storage",
}

def classify(ts_uid: str, n_frames: int, sop_uid: str) -> str:
    if ts_uid in ("1.2.840.10008.1.2.4.100",
                  "1.2.840.10008.1.2.4.101",
                  "1.2.840.10008.1.2.4.102",
                  "1.2.840.10008.1.2.4.103",
                  "1.2.840.10008.1.2.4.104",
                  "1.2.840.10008.1.2.4.105"):
        return "VIDEO (MP4/MPEG transfer syntax) — not renderable by Cornerstone3D /frames/N"
    if sop_uid in VIDEO_SOP_CLASSES:
        return (f"VIDEO SOP CLASS ({VIDEO_SOP_CLASSES[sop_uid]}) — "
                f"not renderable by Cornerstone3D /frames/N even if uncompressed")
    if n_frames > 1:
        return "CINE (multi-frame) — renderable by Cornerstone3D"
    return "SINGLE FRAME"

def inspect(path: Path):
    try:
        ds = pydicom.dcmread(str(path), stop_before_pixels=True)
    except Exception as e:
        print(f"{path.name}: ERROR reading — {e}")
        return

    ts  = str(getattr(ds.file_meta, "TransferSyntaxUID", "unknown"))
    ts_name = TRANSFER_SYNTAX_NAMES.get(ts, ts)
    n_frames = int(getattr(ds, "NumberOfFrames", 1))
    modality = str(getattr(ds, "Modality", "?"))
    sop      = str(getattr(ds, "SOPClassUID", "?"))
    patient  = str(getattr(ds, "PatientName", "?"))
    study    = str(getattr(ds, "StudyDescription", "?"))
    rows     = getattr(ds, "Rows", "?")
    cols     = getattr(ds, "Columns", "?")

    verdict = classify(ts, n_frames, sop)

    print(f"\n{'─'*60}")
    print(f"  File:     {path.name}")
    print(f"  Patient:  {patient}")
    print(f"  Study:    {study}  |  Modality: {modality}")
    print(f"  Size:     {rows} x {cols}  |  Frames: {n_frames}")
    print(f"  Transfer: {ts_name}")
    print(f"  SOP:      {sop}")
    print(f"  >>> {verdict}")

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    paths = []
    for arg in sys.argv[1:]:
        p = Path(arg)
        if p.is_dir():
            paths.extend(sorted(p.rglob("*.dcm")))
        else:
            paths.append(p)

    if not paths:
        print("No .dcm files found.")
        sys.exit(1)

    for p in paths:
        inspect(p)
    print(f"\n{'─'*60}")
    print(f"  {len(paths)} file(s) inspected.")

if __name__ == "__main__":
    main()
