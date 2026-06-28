#!/usr/bin/env python3
"""
qure_sim.py — Simulated Qure.ai DCMIO gateway for Imladris lab.

Simulates the Qure.ai qXR workflow:
  1. Listens as DICOM SCP on port 5252 (AE: QUREAI).
  2. Accepts C-STORE of CXR instances (modality CR, DX, RG).
  3. For each received instance, picks a random Qure.ai annotated PNG from
     the sample library, wraps it as a Secondary Capture DICOM preserving
     the received study's patient/study identifiers, then C-STOREs it back
     to Orthanc PACS as a new "qXR AI Analysis" series.

This creates the appearance of a real Qure.ai cloud round-trip:
  Orthanc PACS → QUREAI gateway → (cloud analysis) → Orthanc PACS
                    ↑ this service

Configuration (environment variables):
  SCP_AE        AE title to listen as          (default: QUREAI)
  SCP_PORT      DICOM SCP port                 (default: 5252)
  ORTHANC_HOST  Orthanc PACS hostname          (default: orthanc-pacs)
  ORTHANC_PORT  Orthanc DICOM port             (default: 4242)
  ORTHANC_AE    Orthanc AE title               (default: IML_PACS_01)
  SAMPLE_DIR    Directory of annotated PNGs    (default: /sample_outputs)
  DELAY_SEC     Simulated processing delay (s) (default: 3)
"""

import os
import random
import logging
import threading
import time
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image
from pydicom.dataset import Dataset
from pydicom.uid import generate_uid, ExplicitVRLittleEndian
from pynetdicom import AE, evt, StoragePresentationContexts
from pynetdicom.sop_class import SecondaryCaptureImageStorage

# ── Configuration ──────────────────────────────────────────────────────────────

SCP_AE       = os.getenv("SCP_AE",       "QUREAI")
SCP_PORT     = int(os.getenv("SCP_PORT", "5252"))
ORTHANC_HOST = os.getenv("ORTHANC_HOST", "orthanc-pacs")
ORTHANC_PORT = int(os.getenv("ORTHANC_PORT", "4242"))
ORTHANC_AE   = os.getenv("ORTHANC_AE",   "IML_PACS_01")
SAMPLE_DIR   = Path(os.getenv("SAMPLE_DIR", "/sample_outputs"))
DELAY_SEC    = float(os.getenv("DELAY_SEC", "3"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("qure_sim")

# ── Sample library ─────────────────────────────────────────────────────────────

def load_samples(sample_dir: Path) -> list[Path]:
    pngs = sorted(sample_dir.glob("*.png"))
    if not pngs:
        raise RuntimeError(f"No PNG files in {sample_dir}")
    log.info("Loaded %d sample Qure.ai outputs from %s", len(pngs), sample_dir)
    return pngs

# ── DICOM Secondary Capture builder ───────────────────────────────────────────

PATIENT_TAGS = [
    "PatientName", "PatientID", "PatientBirthDate", "PatientSex",
    "PatientAge", "PatientWeight",
]
STUDY_TAGS = [
    "StudyInstanceUID", "StudyDate", "StudyTime", "StudyID",
    "AccessionNumber", "StudyDescription", "ReferringPhysicianName",
]

def build_secondary_capture(png_path: Path, src: Dataset) -> Dataset:
    """
    Wrap the Qure.ai annotated PNG as a Secondary Capture DICOM, using
    patient/study metadata from the received (source) DICOM instance.
    """
    rgba = np.array(Image.open(png_path).convert("RGB"))
    # Qure.ai output is a grayscale CXR — R==G==B, use R channel
    gray = rgba[:, :, 0].astype(np.uint8)

    now = datetime.now()
    sop_instance_uid = generate_uid()

    ds = Dataset()

    # ── File meta ──────────────────────────────────────────────────────
    file_meta = Dataset()
    file_meta.MediaStorageSOPClassUID    = SecondaryCaptureImageStorage
    file_meta.MediaStorageSOPInstanceUID = sop_instance_uid
    file_meta.TransferSyntaxUID          = ExplicitVRLittleEndian
    ds.file_meta = file_meta

    # ── Patient / Study (copied from received DICOM) ───────────────────
    for tag in PATIENT_TAGS + STUDY_TAGS:
        if hasattr(src, tag):
            setattr(ds, tag, getattr(src, tag))

    # ── Series (new — the qXR output series) ──────────────────────────
    ds.Modality           = "OT"
    ds.SeriesInstanceUID  = generate_uid()
    ds.SeriesNumber       = "999"
    ds.SeriesDate         = now.strftime("%Y%m%d")
    ds.SeriesTime         = now.strftime("%H%M%S.%f")
    ds.SeriesDescription  = "qXR AI Analysis"
    ds.BodyPartExamined   = "CHEST"

    # ── Instance ──────────────────────────────────────────────────────
    ds.SOPClassUID        = SecondaryCaptureImageStorage
    ds.SOPInstanceUID     = sop_instance_uid
    ds.InstanceNumber     = "1"
    ds.ContentDate        = now.strftime("%Y%m%d")
    ds.ContentTime        = now.strftime("%H%M%S.%f")
    ds.InstanceCreationDate = now.strftime("%Y%m%d")
    ds.InstanceCreationTime = now.strftime("%H%M%S")

    # ── Equipment ─────────────────────────────────────────────────────
    ds.Manufacturer             = "Qure.ai (simulated)"
    ds.ManufacturerModelName    = "qXR"
    ds.SoftwareVersions         = "qure_sim/1.0"
    ds.StationName              = "QUREAI_GW"
    ds.InstitutionName          = "Partners in Health (Imladris Lab)"
    ds.ConversionType           = "WSD"  # Workstation

    # ── Image pixel data ──────────────────────────────────────────────
    ds.Rows                     = gray.shape[0]
    ds.Columns                  = gray.shape[1]
    ds.SamplesPerPixel          = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.BitsAllocated            = 8
    ds.BitsStored               = 8
    ds.HighBit                  = 7
    ds.PixelRepresentation      = 0
    ds.PixelData                = gray.tobytes()

    return ds


# ── Response sender (runs in background thread) ────────────────────────────────

def send_response(sc_ds: Dataset, png_name: str) -> None:
    """C-STORE the Secondary Capture back to Orthanc PACS."""
    if DELAY_SEC > 0:
        log.info("  Simulating %ss analysis delay …", DELAY_SEC)
        time.sleep(DELAY_SEC)

    ae_send = AE(ae_title=SCP_AE)
    ae_send.add_requested_context(SecondaryCaptureImageStorage)

    assoc = ae_send.associate(ORTHANC_HOST, ORTHANC_PORT, ae_title=ORTHANC_AE)
    if not assoc.is_established:
        log.error("  Cannot connect to %s@%s:%s", ORTHANC_AE, ORTHANC_HOST, ORTHANC_PORT)
        return

    status = assoc.send_c_store(sc_ds)
    assoc.release()

    if status and status.Status == 0x0000:
        log.info("  Sent SC (%s) → %s@%s:%s",
                 png_name, ORTHANC_AE, ORTHANC_HOST, ORTHANC_PORT)
    else:
        log.warning("  C-STORE returned status 0x%04X", status.Status if status else 0)


# ── C-STORE handler ────────────────────────────────────────────────────────────

def handle_store(event, samples: list[Path]):
    ds = event.dataset
    ds.file_meta = event.file_meta

    modality = getattr(ds, "Modality", "")
    patient  = str(getattr(ds, "PatientName",     "Unknown"))
    accession = str(getattr(ds, "AccessionNumber", ""))

    log.info("Received C-STORE: modality=%s  patient=%s  acc=%s",
             modality, patient, accession)

    if modality not in ("CR", "DX", "RG", ""):
        log.info("  Skipping non-CXR modality (%s)", modality)
        return 0x0000

    png_path = random.choice(samples)
    log.info("  Selected sample: %s", png_path.name)

    try:
        sc_ds = build_secondary_capture(png_path, ds)
    except Exception as exc:
        log.exception("  Failed to build SC: %s", exc)
        return 0x0000

    # Send response in background so the C-STORE association returns immediately
    t = threading.Thread(target=send_response, args=(sc_ds, png_path.name), daemon=True)
    t.start()

    return 0x0000   # Success — association completes immediately


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    samples = load_samples(SAMPLE_DIR)

    ae = AE(ae_title=SCP_AE)
    ae.supported_contexts = StoragePresentationContexts

    handlers = [(evt.EVT_C_STORE, lambda e: handle_store(e, samples))]

    log.info("Qure.ai gateway simulator ready")
    log.info("  AE title : %s", SCP_AE)
    log.info("  Port     : %s", SCP_PORT)
    log.info("  Samples  : %d PNGs in %s", len(samples), SAMPLE_DIR)
    log.info("  Return to: %s@%s:%s", ORTHANC_AE, ORTHANC_HOST, ORTHANC_PORT)

    ae.start_server(("0.0.0.0", SCP_PORT), block=True, evt_handlers=handlers)


if __name__ == "__main__":
    main()
