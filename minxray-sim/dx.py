"""PNG -> synthetic MinXray DX DICOM.

Implements the conversion pipeline in docs/minxray-detector-specs.md. Public
chest X-ray PNGs are 8-bit and already processed, so the aim is geometric and
statistical plausibility, not recovery of real raw data:

  1. geometry   resample into the panel matrix at the panel pitch, with the
                anatomy scaled to a realistic fraction of the field and the rest
                of the field collimated
  2. physics    Gaussian PSF tuned to the panel MTF, Poisson quantum noise
                (dose parameter), Gaussian electronic noise, optional defects
  3. DICOM      a DX (For Presentation by default) instance, marked synthetic
                (ImageType DERIVED\\SECONDARY + DerivationDescription)

The acquisition software on a real MinXray system is OR Technology's
dicomPACS DX-R with a CareRay CareView 1500Cw panel (FDA K201575). Tag values
below imitate that where known and are clearly labelled as simulated.
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image
from pydicom.dataset import Dataset, FileDataset, FileMetaDataset
from pydicom.sequence import Sequence
from pydicom.uid import ExplicitVRLittleEndian, generate_uid

from pynetdicom.sop_class import (
    DigitalXRayImageStorageForPresentation,
    DigitalXRayImageStorageForProcessing,
)

SIM_VERSION = "imladris-minxray-sim 0.1"


@dataclass(frozen=True)
class Panel:
    key: str
    columns: int
    rows: int
    pitch_mm: float
    bits_stored: int
    mtf_at_2lpmm: float
    description: str
    detector_manufacturer: str
    detector_model: str


PANELS = {
    "wireless154": Panel("wireless154", 2304, 2816, 0.154, 16, 0.40,
                         "14x17 wireless CsI (CMDR Wireless / Impact Wireless)",
                         "CareRay", "CareView 1500Cw"),
    "toshiba140": Panel("toshiba140", 2448, 2984, 0.140, 14, 0.36,
                        "14x17 tethered CsI (Toshiba FDX3543RP)",
                        "Toshiba", "FDX3543RP"),
    "enduras120": Panel("enduras120", 2048, 2560, 0.120, 16, 0.40,
                        "10x12 CsI (Enduras)",
                        "CareRay", "CareView (Enduras 10x12)"),
}

# Attenuation scale for mapping presentation intensity to a line integral.
# A pixel of intensity i (MONOCHROME2, bright = dense) transmits exp(-K*i).
_ATTENUATION_K = 4.0


@dataclass
class SimParams:
    panel: str = "wireless154"
    dose: float = 1.0            # relative dose; 1.0 ~ typical PA chest
    seed: int | None = None
    anatomy_fraction: float = 0.86  # anatomy height / panel height
    presentation: str = "presentation"  # or "processing"
    defects: bool = False
    image_type_original: bool = False  # True -> ORIGINAL\PRIMARY (less honest, for filter testing)


def _load_png(path: Path) -> np.ndarray:
    img = Image.open(path)
    if img.mode in ("I;16", "I;16B", "I"):
        arr = np.asarray(img, dtype=np.float64)
        arr /= max(arr.max(), 1.0)
    else:
        arr = np.asarray(img.convert("L"), dtype=np.float64) / 255.0
    return arr


def _gaussian_blur(img: np.ndarray, sigma_px: float) -> np.ndarray:
    """Gaussian blur via FFT (reflect-padded), exact for any float image.
    Multiplying by the Gaussian transfer function applies the MTF directly."""
    if sigma_px <= 0:
        return img
    pad = int(math.ceil(4 * sigma_px))
    p = np.pad(img, pad, mode="reflect")
    fy = np.fft.fftfreq(p.shape[0])[:, None]
    fx = np.fft.rfftfreq(p.shape[1])[None, :]
    h = np.exp(-2 * math.pi ** 2 * sigma_px ** 2 * (fx ** 2 + fy ** 2))
    out = np.fft.irfft2(np.fft.rfft2(p) * h, s=p.shape)
    return out[pad:-pad, pad:-pad]


def _place_on_panel(src: np.ndarray, panel: Panel, anatomy_fraction: float) -> tuple[np.ndarray, tuple]:
    """Scale the source (keeping its aspect ratio) so it spans anatomy_fraction
    of the panel in its tighter dimension, and center it on a collimated
    (bright, unexposed) field with a soft shutter edge."""
    scale = anatomy_fraction * min(panel.rows / src.shape[0], panel.columns / src.shape[1])
    target_h = int(round(src.shape[0] * scale))
    target_w = int(round(src.shape[1] * scale))
    resized = Image.fromarray((src * 65535).astype(np.uint16)).resize(
        (target_w, target_h), Image.Resampling.LANCZOS)
    body = np.asarray(resized, dtype=np.float64) / 65535.0

    field = np.full((panel.rows, panel.columns), 0.92)  # collimated region
    top = (panel.rows - target_h) // 2
    left = (panel.columns - target_w) // 2
    field[top:top + target_h, left:left + target_w] = body

    # Soften the shutter edge (penumbra) over ~2 mm.
    soft = _gaussian_blur(field, 2.0 / panel.pitch_mm / 3)
    mask = np.zeros_like(field, dtype=bool)
    m = int(4 / panel.pitch_mm)
    mask[max(top - m, 0):top + target_h + m, max(left - m, 0):left + target_w + m] = True
    mask[top + m:top + target_h - m, left + m:left + target_w - m] = False
    field[mask] = soft[mask]
    return field, (top, top + target_h, left, left + target_w)


def _mtf_blur(img: np.ndarray, panel: Panel) -> np.ndarray:
    # Gaussian PSF: MTF(f) = exp(-2 pi^2 sigma^2 f^2)  ->  solve for sigma at 2 lp/mm.
    sigma_mm = math.sqrt(-math.log(panel.mtf_at_2lpmm) / (2 * math.pi ** 2 * 2.0 ** 2))
    return _gaussian_blur(img, sigma_mm / panel.pitch_mm)


def _detector_physics(img: np.ndarray, params: SimParams, rng: np.random.Generator) -> np.ndarray:
    """Return linear detector signal (quanta per pixel) after noise."""
    n0 = 1200.0 * params.dose                     # unattenuated quanta per pixel
    quanta = n0 * np.exp(-_ATTENUATION_K * np.clip(img, 0.0, 1.0))
    if params.defects:
        gain = 1.0 + rng.normal(0.0, 0.01, size=(1, img.shape[1]))  # column gain banding
        quanta = quanta * gain
    signal = rng.poisson(quanta).astype(np.float64)
    signal += rng.normal(0.0, 2.5, size=img.shape)  # electronic noise floor
    if params.defects:
        signal[:, rng.integers(0, img.shape[1])] = 0.0          # one dead column
        ys, xs = rng.integers(0, img.shape[0], 40), rng.integers(0, img.shape[1], 40)
        signal[ys, xs] = 0.0                                     # dead pixels
    return np.clip(signal, 0.5, None), n0


def synthesize_pixels(png: Path, params: SimParams) -> tuple[np.ndarray, Panel, tuple]:
    """Return (pixels, panel, anatomy box as (top, bottom, left, right))."""
    panel = PANELS[params.panel]
    rng = np.random.default_rng(params.seed)
    img, box = _place_on_panel(_load_png(png), panel, params.anatomy_fraction)
    img = _mtf_blur(img, panel)
    signal, n0 = _detector_physics(img, params, rng)
    maxval = (1 << panel.bits_stored) - 1
    if params.presentation == "processing":
        # For Processing: linear in exposure (high value = high exposure).
        pixels = signal / (n0 * 1.05) * maxval
    else:
        # For Presentation: log-transformed back to attenuation, MONOCHROME2.
        atten = -np.log(signal / n0) / _ATTENUATION_K
        pixels = atten * maxval
    return np.clip(np.rint(pixels), 0, maxval).astype(np.uint16), panel, box


def _sha256(path: Path) -> str:
    """Content hash of the source image, so a capture traces back to the
    exact library file (same scheme as imladris-data manifests)."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _code(value: str, scheme: str, meaning: str) -> Dataset:
    c = Dataset()
    c.CodeValue, c.CodingSchemeDesignator, c.CodeMeaning = value, scheme, meaning
    return c


def build_dx(png: Path, params: SimParams, patient: dict, station_ae: str = "MIX") -> FileDataset:
    """Build a DX instance. `patient` keys (all optional): PatientName, PatientID,
    PatientBirthDate, PatientSex, AccessionNumber, StudyInstanceUID,
    RequestedProcedureID, ScheduledProcedureStepID, RequestedProcedureDescription,
    ReferringPhysicianName, StudyDescription."""
    pixels, panel, (top, bottom, left, right) = synthesize_pixels(png, params)
    now = datetime.now()
    processing = params.presentation == "processing"
    sop_class = DigitalXRayImageStorageForProcessing if processing else DigitalXRayImageStorageForPresentation

    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID = sop_class
    meta.MediaStorageSOPInstanceUID = generate_uid()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    meta.ImplementationVersionName = "IMLMINXSIM01"

    ds = FileDataset(None, {}, file_meta=meta, preamble=b"\0" * 128)
    ds.SOPClassUID = sop_class
    ds.SOPInstanceUID = meta.MediaStorageSOPInstanceUID
    ds.SpecificCharacterSet = "ISO_IR 192"  # UTF-8: Sesotho names use š, which Latin-1 lacks

    # Patient / study (from the worklist when available)
    ds.PatientName = patient.get("PatientName", "SIMULATED^PATIENT")
    ds.PatientID = patient.get("PatientID", "SIM" + now.strftime("%H%M%S"))
    ds.PatientBirthDate = patient.get("PatientBirthDate", "")
    ds.PatientSex = patient.get("PatientSex", "")
    ds.StudyInstanceUID = patient.get("StudyInstanceUID") or generate_uid()
    ds.AccessionNumber = patient.get("AccessionNumber", "")
    ds.StudyID = patient.get("RequestedProcedureID", "")[:16] or "1"
    ds.StudyDate = ds.SeriesDate = ds.ContentDate = ds.AcquisitionDate = now.strftime("%Y%m%d")
    ds.StudyTime = ds.SeriesTime = ds.ContentTime = ds.AcquisitionTime = now.strftime("%H%M%S")
    ds.AcquisitionDateTime = now.strftime("%Y%m%d%H%M%S")
    ds.ReferringPhysicianName = patient.get("ReferringPhysicianName", "")
    ds.StudyDescription = patient.get("StudyDescription") or patient.get("RequestedProcedureDescription") or "CHEST PA"
    if patient.get("ScheduledProcedureStepID") or patient.get("RequestedProcedureID"):
        ra = Dataset()
        ra.RequestedProcedureID = patient.get("RequestedProcedureID", "")
        ra.ScheduledProcedureStepID = patient.get("ScheduledProcedureStepID", "")
        ds.RequestAttributesSequence = Sequence([ra])

    # Series / equipment
    ds.Modality = "DX"
    ds.SeriesInstanceUID = generate_uid()
    ds.SeriesNumber = 1
    ds.SeriesDescription = "CHEST PA"
    ds.PresentationIntentType = "FOR PROCESSING" if processing else "FOR PRESENTATION"
    ds.Manufacturer = "MinXray (IMLADRIS simulated)"
    ds.ManufacturerModelName = "CMDR 2CW (simulated)"
    ds.StationName = station_ae
    ds.SoftwareVersions = ["dicomPACS DX-R (emulated)", SIM_VERSION]
    ds.DeviceSerialNumber = "SIM-" + panel.key.upper()
    ds.InstitutionName = "IMLADRIS Lab (simulated)"

    # Image
    ds.InstanceNumber = 1
    ds.ImageType = ["ORIGINAL", "PRIMARY"] if params.image_type_original else ["DERIVED", "SECONDARY"]
    ds.DerivationDescription = (
        f"SYNTHETIC - not a patient image. Derived from {png.parent.name}/{png.name} "
        f"(sha256 {_sha256(png)}) by {SIM_VERSION}; "
        f"panel={panel.key} dose={params.dose} seed={params.seed} "
        f"anatomy_fraction={params.anatomy_fraction}")[:1024]
    ds.BurnedInAnnotation = "NO"
    ds.LossyImageCompression = "00"
    ds.BodyPartExamined = "CHEST"
    ds.ViewPosition = "PA"
    ds.ImageLaterality = "U"
    ds.PatientOrientation = ["L", "F"]
    ds.AnatomicRegionSequence = Sequence([_code("51185008", "SCT", "Thorax")])
    view = _code("399348003", "SCT", "postero-anterior")
    view.ViewModifierCodeSequence = Sequence()
    ds.ViewCodeSequence = Sequence([view])
    ds.AcquisitionContextSequence = Sequence()

    # Acquisition / detector
    ds.KVP = 110
    ds.ExposureTime = 20
    ds.XRayTubeCurrent = 160
    ds.ExposureInuAs = int(3200 * params.dose)
    ds.DistanceSourceToDetector = 1800
    ds.DetectorType = "SCINTILLATOR"
    ds.DetectorConfiguration = "AREA"
    ds.DetectorDescription = f"{panel.description} (simulated)"
    ds.DetectorManufacturerName = panel.detector_manufacturer
    ds.DetectorManufacturerModelName = panel.detector_model
    ds.DetectorID = "SIM-" + panel.key
    ds.ImagerPixelSpacing = [panel.pitch_mm, panel.pitch_mm]
    ds.PixelSpacing = [panel.pitch_mm, panel.pitch_mm]
    ds.PixelSpacingCalibrationType = "GEOMETRY"
    ds.DetectorElementSpacing = [panel.pitch_mm, panel.pitch_mm]
    ds.FieldOfViewShape = "RECTANGLE"
    ds.FieldOfViewDimensions = [int(panel.rows * panel.pitch_mm), int(panel.columns * panel.pitch_mm)]

    # Pixel data
    ds.Rows, ds.Columns = pixels.shape
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.BitsAllocated = 16
    ds.BitsStored = panel.bits_stored
    ds.HighBit = panel.bits_stored - 1
    ds.PixelRepresentation = 0
    ds.PixelIntensityRelationship = "LIN" if processing else "LOG"
    ds.PixelIntensityRelationshipSign = 1
    ds.RescaleIntercept = 0
    ds.RescaleSlope = 1
    ds.RescaleType = "US"
    ds.PresentationLUTShape = "IDENTITY"
    lo, hi = np.percentile(pixels[top:bottom, left:right], [0.5, 99.5])  # anatomy only, not collimation
    ds.WindowCenter = int((lo + hi) / 2)
    ds.WindowWidth = max(int(hi - lo), 1)
    ds.PixelData = pixels.tobytes()
    return ds
