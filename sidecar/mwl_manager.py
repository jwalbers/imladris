"""
mwl_manager.py — DICOM Modality Worklist file manager.

Creates and removes DICOM .wl files in the folder that the Orthanc
Modality Worklist plugin reads.  Each file represents one scheduled
procedure step (one radiology order from OpenMRS).

Orthanc modality.json must have:
  "Worklists": { "Enable": true, "Database": "/worklist" }
and the /worklist folder must be the same volume mounted by this
container at WL_FOLDER (default /worklist).
"""

import logging
import os
from datetime import datetime
from pathlib import Path

import pydicom
from pydicom.dataset import Dataset, FileDataset, FileMetaDataset
from pydicom.sequence import Sequence
from pydicom.uid import ExplicitVRLittleEndian, generate_uid

log = logging.getLogger("mwl_manager")

# SOP Class UID for Modality Worklist Information - FIND
_MWL_SOP_CLASS = "1.2.840.10008.5.1.4.31"
_IMPL_CLASS_UID = "1.2.826.0.1.3680043.2.1.1.1"   # arbitrary fixed UID


class MwlManager:
    """Manages DICOM worklist files for Orthanc."""

    def __init__(self, folder: str, station_aet: str = "MODALITY_SIM"):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.station_aet = station_aet
        log.info(f"MWL folder: {self.folder}  station AET: {self.station_aet}")

    # ── Public API ────────────────────────────────────────────────────

    def create(
        self,
        patient_id: str,
        patient_name: str,
        dob: str,
        sex: str,
        accession: str,
        procedure_id: str,
        procedure_desc: str,
        modality: str,
        scheduled_date: str | None = None,
        scheduled_time: str | None = None,
    ) -> str:
        """Write a DICOM worklist file and return its path."""
        if not scheduled_date:
            scheduled_date = datetime.now().strftime("%Y%m%d")
        if not scheduled_time:
            scheduled_time = datetime.now().strftime("%H%M%S")

        ds = self._build(
            patient_id, patient_name, dob, sex,
            accession, procedure_id, procedure_desc, modality,
            scheduled_date, scheduled_time,
        )
        path = self._path(accession)
        pydicom.dcmwrite(str(path), ds)
        log.info(f"MWL created: {path.name}  ({procedure_desc} / {modality} / {patient_id})")
        return str(path)

    def delete(self, accession: str) -> bool:
        """Remove the worklist file for accession.  Returns True if found."""
        path = self._path(accession)
        if path.exists():
            path.unlink()
            log.info(f"MWL deleted: {path.name}")
            return True
        log.warning(f"MWL delete: file not found for accession={accession}")
        return False

    def list_accessions(self) -> list[str]:
        """Return list of accession numbers currently in the worklist."""
        return [p.stem for p in self.folder.glob("*.wl")]

    # ── Internals ─────────────────────────────────────────────────────

    def _path(self, accession: str) -> Path:
        safe = accession.replace("/", "_").replace("\\", "_").replace(" ", "_")
        return self.folder / f"{safe}.wl"

    def _build(
        self,
        patient_id, patient_name, dob, sex,
        accession, procedure_id, procedure_desc, modality,
        scheduled_date, scheduled_time,
    ) -> FileDataset:
        instance_uid = generate_uid()

        # File meta
        meta = FileMetaDataset()
        meta.MediaStorageSOPClassUID = _MWL_SOP_CLASS
        meta.MediaStorageSOPInstanceUID = instance_uid
        meta.TransferSyntaxUID = ExplicitVRLittleEndian
        meta.ImplementationClassUID = _IMPL_CLASS_UID
        meta.ImplementationVersionName = "IMLADRIS_1.0"

        ds = FileDataset(None, {}, file_meta=meta, preamble=b"\x00" * 128)
        ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian

        # SOP
        ds.SOPClassUID = _MWL_SOP_CLASS
        ds.SOPInstanceUID = instance_uid
        ds.SpecificCharacterSet = "ISO_IR 6"

        # Patient
        # HL7 name is Family^Given^Middle — DICOM uses Family^Given
        ds.PatientName = _hl7_to_dicom_name(patient_name)
        ds.PatientID = patient_id
        ds.PatientBirthDate = dob
        ds.PatientSex = sex

        # AccessionNumber is SH (max 16 chars) — truncate UUID by stripping dashes
        accession_sh = accession.replace("-", "")[:16]

        # Order-level
        ds.AccessionNumber = accession_sh
        ds.RequestedProcedureID = accession_sh
        ds.RequestedProcedureDescription = procedure_desc
        ds.RequestedProcedurePriority = "ROUTINE"
        ds.StudyInstanceUID = generate_uid()
        ds.ReferencedStudySequence = Sequence([])
        ds.ReferencedPatientSequence = Sequence([])
        ds.PlacerOrderNumberImagingServiceRequest = accession_sh
        ds.FillerOrderNumberImagingServiceRequest = ""
        ds.ReferringPhysicianName = ""
        ds.AdmissionID = ""
        ds.CurrentPatientLocation = ""
        ds.MedicalAlerts = ""
        ds.Allergies = ""
        ds.PatientWeight = ""
        ds.MedicalRecordLocator = ""
        ds.PregnancyStatus = 4    # unknown

        # Scheduled Procedure Step
        sps = Dataset()
        sps.ScheduledProcedureStepID = accession_sh
        sps.ScheduledProcedureStepStartDate = scheduled_date
        sps.ScheduledProcedureStepStartTime = scheduled_time
        sps.Modality = modality.upper()
        sps.ScheduledStationAETitle = self.station_aet
        sps.ScheduledStationName = self.station_aet
        sps.ScheduledPerformingPhysicianName = ""
        sps.ScheduledProcedureStepDescription = procedure_desc
        sps.ScheduledProcedureStepStatus = "SCHEDULED"
        sps.CommentsOnTheScheduledProcedureStep = ""
        sps.ScheduledPatientInstitutionResidence = ""

        code = Dataset()
        code.CodeValue = procedure_id
        code.CodingSchemeDesignator = "LOCAL"
        code.CodeMeaning = procedure_desc
        sps.ScheduledProtocolCodeSequence = Sequence([code])

        ds.ScheduledProcedureStepSequence = Sequence([sps])

        return ds


# ── Helpers ───────────────────────────────────────────────────────────

def _hl7_to_dicom_name(hl7_name: str) -> str:
    """
    HL7 name component separator is ^, same as DICOM.
    HL7 may have 5 components (Family^Given^Middle^Suffix^Prefix).
    DICOM uses Family^Given^Middle^Suffix^Prefix — same order, just truncate.
    """
    return hl7_name.strip()
