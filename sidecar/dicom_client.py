"""
dicom_client.py — DICOM network helpers for the Imladris modality console.

Handles:
  - MWL C-FIND SCU (query OpenMRS for scheduled exams)
  - Orthanc REST API helpers (patient/study lookup, C-STORE trigger)
"""

import os
from typing import Optional
import requests
from pynetdicom import AE
from pynetdicom.sop_class import ModalityWorklistInformationFind
from pydicom.dataset import Dataset


# ── Configuration (overridden by environment variables) ───────────────

ORTHANC_URL   = os.getenv("ORTHANC_URL",    "http://localhost:8042")
MWL_HOST      = os.getenv("MWL_HOST",       "localhost")
MWL_PORT      = int(os.getenv("MWL_PORT",   "4242"))
MODALITY_AET  = os.getenv("MODALITY_AET",   "MODALITY_SIM")
CLOUD_PACS_AE = os.getenv("CLOUD_PACS_AE",  "CLOUD_PACS")


# ── Data class ────────────────────────────────────────────────────────

class WorklistEntry:
    """Holds the fields of a single MWL C-FIND response item."""

    def __init__(self, ds: Dataset):
        self.patient_name  = str(ds.get("PatientName",  "")).replace("^", " ").strip()
        self.patient_id    = str(ds.get("PatientID",    ""))
        self.dob           = _fmt_date(str(ds.get("PatientBirthDate", "")))
        self.sex           = str(ds.get("PatientSex", ""))
        self.accession     = str(ds.get("AccessionNumber", ""))
        self.study_desc    = str(ds.get("RequestedProcedureDescription", ""))

        sps = ds.get("ScheduledProcedureStepSequence")
        if sps and len(sps) > 0:
            step = sps[0]
            self.modality       = str(step.get("Modality", ""))
            self.scheduled_date = _fmt_date(str(step.get("ScheduledProcedureStepStartDate", "")))
            self.scheduled_time = str(step.get("ScheduledProcedureStepStartTime", ""))
            self.station_name   = str(step.get("ScheduledStationName", ""))
        else:
            self.modality       = ""
            self.scheduled_date = ""
            self.scheduled_time = ""
            self.station_name   = ""

    def detail_string(self) -> str:
        parts = [
            f"Patient:  {self.patient_name}",
            f"ID:       {self.patient_id}",
            f"DOB:      {self.dob}",
            f"Sex:      {self.sex}",
            f"Modality: {self.modality}",
            f"Study:    {self.study_desc}",
            f"Accession:{self.accession}",
            f"Scheduled:{self.scheduled_date}  {self.scheduled_time}",
        ]
        return "     ".join(parts)


# ── MWL query ─────────────────────────────────────────────────────────

def query_mwl() -> list[WorklistEntry]:
    """
    C-FIND SCU: query the MWL SCP (OpenMRS Radiology Module) and return
    a list of WorklistEntry objects for all pending scheduled exams.

    Raises ConnectionError or RuntimeError on failure.
    """
    ae = AE(ae_title=MODALITY_AET)
    ae.add_requested_context(ModalityWorklistInformationFind)

    # Build a wide-open query (return all scheduled exams)
    ds = Dataset()
    ds.PatientName                    = ""
    ds.PatientID                      = ""
    ds.PatientBirthDate               = ""
    ds.PatientSex                     = ""
    ds.RequestedProcedureDescription  = ""
    ds.AccessionNumber                = ""

    sps = Dataset()
    sps.ScheduledProcedureStepStartDate = ""
    sps.ScheduledProcedureStepStartTime = ""
    sps.Modality                        = ""
    sps.ScheduledStationName            = ""
    sps.ScheduledPerformingPhysicianName = ""
    ds.ScheduledProcedureStepSequence   = [sps]

    entries: list[WorklistEntry] = []

    assoc = ae.associate(MWL_HOST, MWL_PORT)
    if not assoc.is_established:
        raise ConnectionError(
            f"Could not associate with MWL SCP at {MWL_HOST}:{MWL_PORT}"
        )
    try:
        for status, identifier in assoc.send_c_find(ds, ModalityWorklistInformationFind):
            if identifier is not None:
                entries.append(WorklistEntry(identifier))
    finally:
        assoc.release()

    return entries


# ── Orthanc helpers ───────────────────────────────────────────────────

def check_orthanc() -> dict:
    """Return Orthanc /system info, or raise on failure."""
    r = requests.get(f"{ORTHANC_URL}/system", timeout=4)
    r.raise_for_status()
    return r.json()


def match_tb_study(patient_id: str, modality: str) -> Optional[str]:
    """
    Find the best Orthanc study UID to use for a given PatientID + modality.

    Strategy:
      1. Exact PatientID match in Orthanc — return the most recent study.
      2. Fall back to any study whose ModalitiesInStudy contains the modality.
      3. Return None if nothing is found.
    """
    # 1. Exact patient match
    r = requests.get(f"{ORTHANC_URL}/patients", timeout=5)
    r.raise_for_status()
    for oid in r.json():
        p = requests.get(f"{ORTHANC_URL}/patients/{oid}", timeout=5).json()
        if p.get("MainDicomTags", {}).get("PatientID") == patient_id:
            studies = p.get("Studies", [])
            if studies:
                return studies[-1]   # last = most recent

    # 2. Modality fallback
    r2 = requests.get(f"{ORTHANC_URL}/studies", timeout=5)
    r2.raise_for_status()
    for sid in r2.json():
        s = requests.get(f"{ORTHANC_URL}/studies/{sid}", timeout=5).json()
        mods = s.get("MainDicomTags", {}).get("ModalitiesInStudy", "")
        if modality.upper() in mods.upper():
            return sid

    return None


def send_study_to_pacs(study_uid: str) -> dict:
    """
    Trigger Orthanc to C-STORE the given study to the Cloud PACS.
    Returns the Orthanc job response dict.
    Raises on HTTP error.
    """
    r = requests.post(
        f"{ORTHANC_URL}/modalities/{CLOUD_PACS_AE}/store",
        json=[study_uid],
        timeout=120,
    )
    r.raise_for_status()
    return r.json()


# ── Utility ───────────────────────────────────────────────────────────

def _fmt_date(raw: str) -> str:
    """Convert YYYYMMDD to YYYY-MM-DD for display."""
    if len(raw) == 8 and raw.isdigit():
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:]}"
    return raw
