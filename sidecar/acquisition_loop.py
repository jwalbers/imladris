"""
acquisition_loop.py — Headless acquisition daemon (runs inside container).

Polls the worklist (.wl files) on a fixed interval and auto-sends matched
studies to AdvaPACS directly via pynetdicom C-STORE.  For CR/DX modalities,
also sends to qure-sim so the scp_relay can forward the SC.

The web console (modality_console_web.py) provides the manual version.
"""

import os
import time
import logging
from datetime import datetime

import dicom_client as dc
from pydicom.uid import ExplicitVRLittleEndian, generate_uid
import pydicom

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("acquisition_loop")

POLL_MINUTES      = float(os.getenv("POLL_INTERVAL_MINUTES", "5"))
INSTITUTION       = os.getenv("INSTITUTION", "Bophelong MDR-TB Hospital")
ISSUER_OF_PATIENT = os.getenv("DICOM_ISSUER_OF_PATIENT_ID", "")
CR_AET            = os.getenv("CR_AET", "IML_CR_01")
US_AET            = os.getenv("US_AET", "IML_US_01")
CT_AET            = os.getenv("CT_AET", "IML_CT_01")


def _aet_for(modality: str) -> str:
    return {"US": US_AET, "CT": CT_AET}.get(modality.upper(), CR_AET)


# Accessions already imaged this container lifetime — reset on restart.
_sent: set[str] = set()


def run_cycle():
    log.info("Starting acquisition cycle …")
    try:
        entries = dc.read_wl_entries()
        log.info(f"Worklist: {len(entries)} scheduled exam(s).")
    except Exception as e:
        log.error(f"Worklist read failed: {e}")
        return

    now      = datetime.now()
    date_str = now.strftime("%Y%m%d")
    time_str = now.strftime("%H%M%S")

    for entry in entries:
        if entry.accession in _sent:
            log.debug(f"Already imaged {entry.accession} this session — skipping.")
            continue

        log.info(
            f"Processing: {entry.patient_name} ({entry.patient_id}) "
            f"— {entry.study_desc}  Accession: {entry.accession}"
        )
        try:
            files = dc.find_study_files(entry.patient_id, entry.modality)
            if not files:
                log.warning(
                    f"No source image for PatientID={entry.patient_id} "
                    f"Modality={entry.modality} — skipping."
                )
                continue

            modality   = entry.modality or "CR"
            study_uid  = entry.study_uid or generate_uid()
            series_uid = generate_uid()
            calling_ae = _aet_for(modality)

            patched = []
            for i, path in enumerate(files, start=1):
                ds = pydicom.dcmread(str(path))
                ds.PatientName       = entry.patient_name
                ds.PatientID         = entry.patient_id
                ds.PatientBirthDate  = entry.dob.replace("-", "") if entry.dob else ""
                ds.PatientSex        = entry.sex
                ds.StudyInstanceUID  = study_uid
                ds.StudyDate         = date_str
                ds.StudyTime         = time_str
                ds.StudyDescription  = entry.study_desc
                ds.AccessionNumber   = entry.accession
                ds.SeriesInstanceUID = series_uid
                ds.SeriesDate        = date_str
                ds.SeriesTime        = time_str
                ds.SeriesDescription = entry.study_desc
                ds.SeriesNumber      = "1"
                ds.SOPInstanceUID    = generate_uid()
                ds.InstanceNumber    = str(i)
                ds.ContentDate       = date_str
                ds.ContentTime       = time_str
                ds.Modality          = modality
                ds.InstitutionName   = INSTITUTION
                if ISSUER_OF_PATIENT:
                    ds.IssuerOfPatientID = ISSUER_OF_PATIENT
                if hasattr(ds, "file_meta"):
                    ds.file_meta.MediaStorageSOPInstanceUID = ds.SOPInstanceUID
                    ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
                    ds.file_meta.SourceApplicationEntityTitle = calling_ae
                patched.append(ds)

            sent = dc.cstore_to(patched, dc.ADVAPACS_GW_HOST, dc.ADVAPACS_GW_PORT,
                                dc.ADVAPACS_GW_AE, calling_ae)
            log.info(
                f"✓  Sent {sent}/{len(patched)} instance(s) → AdvaPACS  "
                f"study={study_uid[:24]}…  patient={entry.patient_name}"
            )
            _sent.add(entry.accession)

            if modality.upper() in ("CR", "DX") and dc.ENABLE_QURE:
                try:
                    dc.cstore_to(patched, dc.QURE_HOST, dc.QURE_PORT, dc.QURE_AE, calling_ae)
                    log.info(f"Sent primary → qure-sim; SC will be relayed to AdvaPACS")
                except Exception as e:
                    log.warning(f"qure-sim send failed (SC skipped): {e}")

        except Exception as e:
            log.error(f"Failed to process {entry.accession}: {e}")


def main():
    log.info(
        f"Imladris acquisition loop starting  "
        f"(poll every {POLL_MINUTES} min, "
        f"gateway={dc.ADVAPACS_GW_HOST}:{dc.ADVAPACS_GW_PORT}  AE={dc.ADVAPACS_GW_AE})"
    )
    while True:
        run_cycle()
        log.info(f"Sleeping {POLL_MINUTES} min until next cycle …")
        time.sleep(POLL_MINUTES * 60)


if __name__ == "__main__":
    main()
