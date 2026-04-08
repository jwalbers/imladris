"""
png_to_dicom.py — Convert PNG chest X-rays to single-frame CR DICOM files.

Pulls source PNGs from GCS, matches them to the Botsabelo patient census,
builds a compliant CR DICOM, and uploads to GCS.

Configuration via .env:
    GCP_BUCKET_NAME     GCS bucket name
    GCP_KEY_PATH        Path to service account JSON key
    GCP_PROJECT_ID      GCP project ID
    CENSUS_CSV_PATH     Path to patient census CSV

CSV expected columns:
    Name, Patient_ID, MDR_Status, CXR_Finding (or falls back to MDR_Status),
    PatientBirthDate (YYYYMMDD), PatientSex (M/F/O)

Requirements:
    pip install pydicom Pillow numpy pandas python-dotenv google-cloud-storage
"""

import os
import io
import datetime
import numpy as np
import pydicom
from pydicom.dataset import Dataset, FileDataset, FileMetaDataset
from pydicom.uid import generate_uid, ExplicitVRLittleEndian
import pandas as pd
from dotenv import load_dotenv
from google.cloud import storage
from PIL import Image

# ── Config ────────────────────────────────────────────────────────────
load_dotenv()
PROJECT_ID  = os.getenv("GCP_PROJECT_ID")
BUCKET_NAME = os.getenv("GCP_BUCKET_NAME")
KEY_PATH    = os.getenv("GCP_KEY_PATH")
CENSUS_CSV  = os.getenv("CENSUS_CSV_PATH")

SOURCE_BASE = "botsabelo_raw/TB_Chest_Radiography_Database"
DEST_PREFIX = "botsabelo_processed/xray/"

INSTITUTION   = "Botsabelo MDR-TB Hospital"
CR_SOP_CLASS  = "1.2.840.10008.5.1.4.1.1.1"   # Computed Radiography Image Storage

client = storage.Client.from_service_account_json(KEY_PATH, project=PROJECT_ID)
bucket = client.bucket(BUCKET_NAME)


# ── Name helper ───────────────────────────────────────────────────────

def to_dicom_name(name: str) -> str:
    """Convert 'First Last' → 'Last^First' DICOM PN format."""
    if "^" in name:
        return name
    parts = name.strip().split()
    if len(parts) >= 2:
        return f"{parts[-1]}^{' '.join(parts[:-1])}"
    return name


# ── DICOM builder ─────────────────────────────────────────────────────

def build_cr_dicom(
    pixel_array: np.ndarray,
    patient_name: str,
    patient_id: str,
    patient_dob: str,
    patient_sex: str,
    series_desc: str,
    study_desc: str,
) -> bytes:
    """Build a compliant single-frame CR DICOM. Returns serialised bytes."""
    rows, cols = pixel_array.shape
    now        = datetime.datetime.now()
    date_str   = now.strftime("%Y%m%d")
    time_str   = now.strftime("%H%M%S")

    sop_instance_uid = generate_uid()

    # ── File meta ─────────────────────────────────────────────────────
    file_meta = FileMetaDataset()
    file_meta.MediaStorageSOPClassUID    = CR_SOP_CLASS
    file_meta.MediaStorageSOPInstanceUID = sop_instance_uid
    file_meta.TransferSyntaxUID          = ExplicitVRLittleEndian

    ds = FileDataset(None, {}, file_meta=file_meta, preamble=b"\0" * 128)

    # ── General ───────────────────────────────────────────────────────
    ds.SpecificCharacterSet = "ISO_IR 6"
    ds.SOPClassUID          = CR_SOP_CLASS
    ds.SOPInstanceUID       = sop_instance_uid

    # ── Patient ───────────────────────────────────────────────────────
    ds.PatientName          = patient_name
    ds.PatientID            = patient_id
    ds.PatientBirthDate     = patient_dob
    ds.PatientSex           = patient_sex

    # ── Study ─────────────────────────────────────────────────────────
    ds.StudyInstanceUID         = generate_uid()
    ds.StudyDate                = date_str
    ds.StudyTime                = time_str
    ds.StudyDescription         = study_desc
    ds.AccessionNumber          = ""
    ds.ReferringPhysicianName   = ""

    # ── Series ────────────────────────────────────────────────────────
    ds.SeriesInstanceUID    = generate_uid()
    ds.SeriesDate           = date_str
    ds.SeriesTime           = time_str
    ds.Modality             = "CR"
    ds.SeriesDescription    = series_desc
    ds.SeriesNumber         = "1"
    ds.InstanceNumber       = "1"
    ds.InstitutionName      = INSTITUTION

    # ── Content ───────────────────────────────────────────────────────
    ds.ContentDate          = date_str
    ds.ContentTime          = time_str

    # ── Image geometry (grayscale 8-bit) ──────────────────────────────
    ds.SamplesPerPixel           = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.PixelRepresentation       = 0
    ds.HighBit                   = 7
    ds.BitsStored                = 8
    ds.BitsAllocated             = 8
    ds.Rows                      = rows
    ds.Columns                   = cols
    ds.PixelData                 = pixel_array.tobytes()

    out_io = io.BytesIO()
    pydicom.dcmwrite(out_io, ds)
    out_io.seek(0)
    return out_io.read()


# ── Main deployment loop ──────────────────────────────────────────────

def run_xray_deployment(count: int = 50):
    df = pd.read_csv(CENSUS_CSV)

    print("Indexing TB Chest Radiography Database …")
    pos_blobs = [b for b in bucket.list_blobs(prefix=f"{SOURCE_BASE}/Tuberculosis/")
                 if b.name.lower().endswith(".png")]
    neg_blobs = [b for b in bucket.list_blobs(prefix=f"{SOURCE_BASE}/Normal/")
                 if b.name.lower().endswith(".png")]
    print(f"  {len(pos_blobs)} TB images, {len(neg_blobs)} Normal images")

    if not pos_blobs or not neg_blobs:
        print("WARNING: source image pool is empty — check SOURCE_BASE prefix")

    success = 0
    for index, row in df.head(count).iterrows():
        patient_id   = str(row["Patient_ID"])
        patient_name = to_dicom_name(str(row["Name"]))
        patient_dob  = str(row.get("PatientBirthDate", ""))
        patient_sex  = str(row.get("PatientSex", ""))
        mdr_status   = str(row.get("MDR_Status", ""))
        cxr_finding  = str(row.get("CXR_Finding", mdr_status))
        series_desc  = f"CXR: {cxr_finding}"[:64]
        study_desc   = "Chest X-Ray"

        is_positive  = "Confirmed" in mdr_status or "Positive" in mdr_status
        source_pool  = pos_blobs if is_positive else neg_blobs
        if not source_pool:
            print(f"  SKIP {patient_id}: no source images for positive={is_positive}")
            continue

        source_blob = source_pool[index % len(source_pool)]
        print(f"[{index+1}/{min(count, len(df))}] {patient_id} ({patient_name}) "
              f"← {os.path.basename(source_blob.name)}")

        try:
            img_bytes   = source_blob.download_as_bytes()
            img         = Image.open(io.BytesIO(img_bytes)).convert("L")
            pixel_array = np.array(img, dtype=np.uint8)

            dicom_bytes = build_cr_dicom(
                pixel_array  = pixel_array,
                patient_name = patient_name,
                patient_id   = patient_id,
                patient_dob  = patient_dob,
                patient_sex  = patient_sex,
                series_desc  = series_desc,
                study_desc   = study_desc,
            )

            dest_path = f"{DEST_PREFIX}{patient_id}/XRAY_{patient_id}.dcm"
            bucket.blob(dest_path).upload_from_string(dicom_bytes, content_type="application/dicom")
            print(f"  Uploaded → {dest_path}")
            success += 1

        except Exception as e:
            print(f"  ERROR processing {patient_id}: {e}")
            continue

    print(f"\nDone: {success}/{min(count, len(df))} X-rays uploaded to {BUCKET_NAME}/{DEST_PREFIX}")


if __name__ == "__main__":
    run_xray_deployment(50)
