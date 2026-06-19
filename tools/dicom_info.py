#!/usr/bin/env python3
"""
dicom_info.py — IMLADRIS Lab
Display DICOM metadata for one or more .dcm files.
PHI-flagged tags are marked with ⚠️

Usage:
    python3 tools/dicom_info.py path/to/file.dcm [another.dcm ...]
"""

import sys
from pathlib import Path
import pydicom
from pydicom.sequence import Sequence

PHI_TAGS = {
    'PatientName', 'PatientID', 'PatientBirthDate', 'PatientSex',
    'PatientAge', 'PatientWeight', 'PatientAddress', 'PatientTelephoneNumbers',
    'PatientMotherBirthName', 'OtherPatientIDs', 'OtherPatientNames',
    'AdditionalPatientHistory', 'PatientComments',
    'ReferringPhysicianName', 'PhysiciansOfRecord', 'RequestingPhysician',
    'OperatorsName', 'PerformingPhysicianName', 'NameOfPhysiciansReadingStudy',
    'InstitutionName', 'InstitutionAddress', 'InstitutionalDepartmentName',
    'StationName', 'DeviceSerialNumber',
    'AccessionNumber', 'StudyID',
}

GROUPS = [
    ('PATIENT', [
        'PatientName', 'PatientID', 'PatientBirthDate', 'PatientSex',
        'PatientAge', 'PatientWeight', 'PatientAddress',
        'OtherPatientIDs', 'PatientComments',
    ]),
    ('STUDY', [
        'StudyDate', 'StudyTime', 'StudyDescription', 'StudyID',
        'AccessionNumber', 'InstitutionName', 'InstitutionAddress',
        'ReferringPhysicianName', 'StudyInstanceUID',
    ]),
    ('SERIES', [
        'SeriesDate', 'SeriesTime', 'SeriesNumber', 'SeriesDescription',
        'Modality', 'BodyPartExamined', 'ProtocolName',
        'Manufacturer', 'ManufacturerModelName', 'StationName',
        'SoftwareVersions', 'SeriesInstanceUID',
    ]),
    ('INSTANCE', [
        'SOPInstanceUID', 'SOPClassUID', 'InstanceNumber', 'ImageType',
        'Rows', 'Columns', 'BitsAllocated', 'BitsStored',
        'PixelSpacing', 'SliceThickness', 'SliceLocation',
    ]),
    ('ACQUISITION', [
        'KVP', 'XRayTubeCurrent', 'ExposureTime', 'ConvolutionKernel',
        'ReconstructionDiameter', 'CTDIvol',
        'MagneticFieldStrength', 'RepetitionTime', 'EchoTime',
        'FlipAngle', 'SequenceName', 'ScanningSequence',
    ]),
]


def fmt_value(elem) -> str:
    if isinstance(elem.value, Sequence):
        return f'[sequence, {len(elem.value)} item(s)]'
    if elem.VR in ('OB', 'OW', 'UN'):
        return f'<binary, {len(elem.value)} bytes>'
    v = str(elem.value).strip()
    return v if v else '(empty)'


def print_dcm(path: Path) -> None:
    print(f'\n{"═"*72}')
    print(f'  {path}')
    print(f'{"═"*72}')

    try:
        ds = pydicom.dcmread(str(path), stop_before_pixels=True, force=True)
    except Exception as e:
        print(f'  ERROR: {e}')
        return

    shown = set()

    for title, attr_names in GROUPS:
        rows = []
        for name in attr_names:
            if not hasattr(ds, name):
                continue
            elem = ds[pydicom.datadict.tag_for_keyword(name)]
            val = fmt_value(elem)
            phi = '  ⚠️ ' if name in PHI_TAGS and val not in ('(empty)', '') else ''
            rows.append((name, val, phi))
            shown.add(elem.tag)
        if rows:
            print(f'\n  ── {title} {"─" * (64 - len(title))}')
            for name, val, phi in rows:
                print(f'  {name:<38} {val}{phi}')

    # Everything else (skip pixel data and pure binary)
    others = [
        e for e in ds
        if e.tag not in shown
        and e.keyword != 'PixelData'
        and e.VR not in ('OB', 'OW')
        and e.tag.group != 0xFFFC
    ]
    if others:
        print(f'\n  ── OTHER TAGS {"─" * 58}')
        for e in others:
            tag_str = f'({e.tag.group:04X},{e.tag.element:04X})'
            kw      = e.keyword or '?'
            val     = fmt_value(e)
            phi     = '  ⚠️ ' if kw in PHI_TAGS and val not in ('(empty)', '') else ''
            print(f'  {tag_str} {kw:<30} {val}{phi}')
    print()


def main():
    if len(sys.argv) < 2:
        print('Usage: python3 tools/dicom_info.py <file.dcm> [file.dcm ...]')
        sys.exit(1)
    for arg in sys.argv[1:]:
        print_dcm(Path(arg))

if __name__ == '__main__':
    main()
