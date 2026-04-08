"""
mp4_to_cine.py — Convert MP4 ultrasound clips to multi-frame DICOM Cine.

Pulls source MP4s from GCS, matches them to the Botsabelo patient census,
builds a compliant US Multi-frame DICOM, and uploads to GCS.

Configuration via .env:
    GCP_BUCKET_NAME     GCS bucket name
    GCP_KEY_PATH        Path to service account JSON key
    GCP_PROJECT_ID      GCP project ID
    CENSUS_CSV_PATH     Path to patient census CSV

CSV expected columns:
    Name, Patient_ID, MDR_Status, FASH_Ultrasound_Finding,
    PatientBirthDate (YYYYMMDD), PatientSex (M/F/O)

Requirements:
    pip install pydicom Pillow numpy ffmpeg-python pandas python-dotenv google-cloud-storage
"""

import os
import io
import tempfile
import datetime
import numpy as np
import pydicom
from pydicom.dataset import Dataset, FileDataset, FileMetaDataset
from pydicom.uid import generate_uid, ExplicitVRLittleEndian
import ffmpeg
import pandas as pd
from dotenv import load_dotenv
from google.cloud import storage

# ── Config ────────────────────────────────────────────────────────────
load_dotenv()
BUCKET_NAME   = os.getenv("GCP_BUCKET_NAME")
CENSUS_CSV    = os.getenv("CENSUS_CSV_PATH")
KEY_PATH      = os.getenv("GCP_KEY_PATH")
PROJECT_ID    = os.getenv("GCP_PROJECT_ID")

SOURCE_PREFIX = "botsabelo_raw/ultrasound/"
DEST_PREFIX   = "botsabelo_processed/ultrasound_cine/"

INSTITUTION   = "Botsabelo MDR-TB Hospital"
US_MULTIFRAME_SOP = "1.2.840.10008.5.1.4.1.1.3.1"

client = storage.Client.from_service_account_json(KEY_PATH, project=PROJECT_ID)
bucket = client.bucket(BUCKET_NAME)


# ── Video helpers ─────────────────────────────────────────────────────

def get_frames_from_video(video_bytes: bytes) -> tuple[np.ndarray, float]:
    """
    Decode MP4 bytes to a grayscale frame stack and extract actual FPS.

    Returns:
        pixel_stack: uint8 ndarray (N_frames, height, width)
        fps: actual frames per second from video metadata
    """
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
        tmp.write(video_bytes)
        tmp_path = tmp.name

    try:
        # Probe for dimensions and FPS
        probe = ffmpeg.probe(tmp_path)
        video_stream = next(
            s for s in probe["streams"] if s["codec_type"] == "video"
        )
        width  = int(video_stream["width"])
        height = int(video_stream["height"])

        # Parse FPS from avg_frame_rate (e.g. "30/1" or "15000/1001")
        num, den = video_stream.get("avg_frame_rate", "15/1").split("/")
        fps = float(num) / float(den) if float(den) else 15.0

        # Decode to raw grayscale
        out, _ = (
            ffmpeg
            .input(tmp_path)
            .output("pipe:", format="rawvideo", pix_fmt="gray")
            .run(capture_stdout=True, quiet=True)
        )
    finally:
        os.unlink(tmp_path)

    pixel_stack = np.frombuffer(out, np.uint8).reshape([-1, height, width])
    return pixel_stack, fps


# ── DICOM builder ─────────────────────────────────────────────────────

def build_cine_dicom(
    pixel_stack: np.ndarray,
    fps: float,
    patient_name: str,
    patient_id: str,
    patient_dob: str,
    patient_sex: str,
    series_desc: str,
    study_desc: str,
) -> bytes:
    """
    Build a compliant US Multi-frame DICOM from a grayscale frame stack.
    Returns the serialised DICOM bytes.
    """
    n_frames, rows, cols = pixel_stack.shape
    frame_time_ms = round(1000.0 / fps, 2)

    now      = datetime.datetime.now()
    date_str = now.strftime("%Y%m%d")
    time_str = now.strftime("%H%M%S")

    sop_instance_uid = generate_uid()

    # ── File meta (must use FileMetaDataset) ──────────────────────────
    file_meta = FileMetaDataset()
    file_meta.MediaStorageSOPClassUID    = US_MULTIFRAME_SOP
    file_meta.MediaStorageSOPInstanceUID = sop_instance_uid
    file_meta.TransferSyntaxUID          = ExplicitVRLittleEndian

    ds = FileDataset(None, {}, file_meta=file_meta, preamble=b"\0" * 128)

    # ── General ───────────────────────────────────────────────────────
    ds.SpecificCharacterSet  = "ISO_IR 6"
    ds.SOPClassUID           = US_MULTIFRAME_SOP
    ds.SOPInstanceUID        = sop_instance_uid

    # ── Patient ───────────────────────────────────────────────────────
    ds.PatientName           = patient_name   # caller supplies Last^First
    ds.PatientID             = patient_id
    ds.PatientBirthDate      = patient_dob    # YYYYMMDD or ""
    ds.PatientSex            = patient_sex    # M / F / O / ""

    # ── Study ─────────────────────────────────────────────────────────
    ds.StudyInstanceUID      = generate_uid()
    ds.StudyDate             = date_str
    ds.StudyTime             = time_str
    ds.StudyDescription      = study_desc
    ds.AccessionNumber       = ""
    ds.ReferringPhysicianName = ""

    # ── Series ────────────────────────────────────────────────────────
    ds.SeriesInstanceUID     = generate_uid()
    ds.SeriesDate            = date_str
    ds.SeriesTime            = time_str
    ds.Modality              = "US"
    ds.SeriesDescription     = series_desc
    ds.SeriesNumber          = "1"
    ds.InstanceNumber        = "1"
    ds.InstitutionName       = INSTITUTION

    # ── Image geometry ────────────────────────────────────────────────
    ds.SamplesPerPixel           = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.Rows                      = rows
    ds.Columns                   = cols
    ds.BitsAllocated             = 8
    ds.BitsStored                = 8
    ds.HighBit                   = 7
    ds.PixelRepresentation       = 0
    ds.NumberOfFrames            = n_frames

    # ── Content date/time ─────────────────────────────────────────────
    ds.ContentDate               = date_str
    ds.ContentTime               = time_str

    # ── Cine timing ───────────────────────────────────────────────────
    ds.CineRate                      = round(fps)
    ds.FrameTime                     = str(frame_time_ms)
    ds.FrameDelay                    = "0"
    ds.RecommendedDisplayFrameRate   = str(round(fps))

    # ── Pixel data ────────────────────────────────────────────────────
    ds.PixelData = pixel_stack.tobytes()

    out_io = io.BytesIO()
    pydicom.dcmwrite(out_io, ds)
    out_io.seek(0)
    return out_io.read()


# ── Name helper ───────────────────────────────────────────────────────

def to_dicom_name(name: str) -> str:
    """
    Convert 'First Last' → 'Last^First' DICOM PN format.
    Passes through strings that already contain '^'.
    """
    if "^" in name:
        return name
    parts = name.strip().split()
    if len(parts) >= 2:
        return f"{parts[-1]}^{' '.join(parts[:-1])}"
    return name


# ── Main deployment loop ──────────────────────────────────────────────

def run_cine_deployment(count: int = 50):
    df = pd.read_csv(CENSUS_CSV)

    all_blobs   = list(bucket.list_blobs(prefix=SOURCE_PREFIX))
    video_blobs = [b for b in all_blobs if b.name.endswith(".mp4")]
    pos_clips   = [b for b in video_blobs if "pos_"    in b.name]
    neg_clips   = [b for b in video_blobs if "normal_" in b.name]

    if not pos_clips or not neg_clips:
        print(f"WARNING: pos_clips={len(pos_clips)}  neg_clips={len(neg_clips)} — check SOURCE_PREFIX")

    success = 0
    for index, row in df.head(count).iterrows():
        patient_id   = str(row["Patient_ID"])
        patient_name = to_dicom_name(str(row["Name"]))
        patient_dob  = str(row.get("PatientBirthDate", ""))
        patient_sex  = str(row.get("PatientSex", ""))
        finding      = str(row.get("FASH_Ultrasound_Finding", "FASH Ultrasound"))
        mdr_status   = str(row.get("MDR_Status", ""))
        series_desc  = f"FASH Cine: {finding}"[:64]
        study_desc   = "FASH Ultrasound"

        is_positive  = "Confirmed" in mdr_status or "Positive" in finding
        source_pool  = pos_clips if is_positive else neg_clips
        if not source_pool:
            print(f"  SKIP {patient_id}: no source clips for positive={is_positive}")
            continue

        source_blob = source_pool[index % len(source_pool)]

        print(f"Processing {patient_id} ({patient_name}) from {source_blob.name} …")
        try:
            video_bytes  = source_blob.download_as_bytes()
            pixel_stack, fps = get_frames_from_video(video_bytes)
            print(f"  {pixel_stack.shape[0]} frames, {pixel_stack.shape[2]}x{pixel_stack.shape[1]}, {fps:.1f} fps")

            dicom_bytes = build_cine_dicom(
                pixel_stack  = pixel_stack,
                fps          = fps,
                patient_name = patient_name,
                patient_id   = patient_id,
                patient_dob  = patient_dob,
                patient_sex  = patient_sex,
                series_desc  = series_desc,
                study_desc   = study_desc,
            )

            dest_path = f"{DEST_PREFIX}{patient_id}/CINE_{patient_id}.dcm"
            bucket.blob(dest_path).upload_from_string(dicom_bytes, content_type="application/dicom")
            print(f"  Uploaded → {dest_path}")
            success += 1

        except Exception as e:
            print(f"  ERROR processing {patient_id}: {e}")
            continue

    print(f"\nDone: {success}/{min(count, len(df))} patients processed successfully.")


if __name__ == "__main__":
    run_cine_deployment(50)
