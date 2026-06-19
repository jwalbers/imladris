#!/usr/bin/env python3
"""
extract_dicom_metadata.py — IMLADRIS Lab
Batch DICOM metadata extractor + team summary report generator.

Scans a directory tree of .dcm files, extracts patient/study/series/instance
metadata, writes CSVs for database import, and generates a Markdown summary
report ready to share with the team.

Usage:
    python3 tools/extract_dicom_metadata.py \\
        --source "/path/to/CT&MRI STUDIES FROM BOPHELONG VIRTUALHOSPITAL" \\
        --output reports/ct_mri_20260619

    # With GCS path prefix for the instances.csv gcs_path column:
    python3 tools/extract_dicom_metadata.py \\
        --source "/path/to/..." \\
        --output reports/ct_mri_20260619 \\
        --gcs-prefix gs://botsabelo-hospital-records/botsabelo_processed/ct_mri

Output (in --output directory):
    instances.csv     — one row per .dcm file (all extracted tags + gcs_path)
    series.csv        — one row per series (aggregated)
    studies.csv       — one row per study  (aggregated)
    patients.csv      — one row per patient (aggregated)
    summary_report.md — team-ready summary with counts and breakdowns
"""

import os
import sys
import argparse
import traceback
from pathlib import Path
from datetime import datetime
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

import pydicom
import pandas as pd
from tqdm import tqdm


# ── Tag extraction ─────────────────────────────────────────────────────────────

def safe_str(value, default=''):
    """Convert a pydicom value to plain string safely."""
    if value is None:
        return default
    try:
        return str(value).strip()
    except Exception:
        return default


def parse_dicom_date(raw, default=''):
    """DICOM date YYYYMMDD → YYYY-MM-DD, or return raw on failure."""
    if not raw or len(raw) < 8:
        return default
    try:
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"
    except Exception:
        return raw


def extract_tags(dcm_path: Path, gcs_prefix: str) -> dict | None:
    """
    Read one .dcm file and return a flat dict of extracted metadata.
    Returns None on read failure (logged by caller).
    """
    try:
        ds = pydicom.dcmread(str(dcm_path), stop_before_pixels=True, force=True)
    except Exception:
        return None

    def g(attr, default=''):
        return safe_str(getattr(ds, attr, None), default)

    # Patient
    patient_name_raw = g('PatientName')
    # PersonName format: Last^First^Middle — make it readable
    parts = patient_name_raw.split('^')
    patient_name_display = ' '.join(p for p in reversed(parts) if p).strip() or patient_name_raw

    # Image type list → comma-separated string
    image_type = ', '.join(safe_str(v) for v in getattr(ds, 'ImageType', [])) or ''

    # PixelSpacing → "row_mm x col_mm"
    pixel_spacing = ''
    ps = getattr(ds, 'PixelSpacing', None)
    if ps and len(ps) >= 2:
        pixel_spacing = f"{safe_str(ps[0])} x {safe_str(ps[1])}"

    # GCS path: preserve UID directory structure
    rel = dcm_path.relative_to(dcm_path.parent.parent)   # STUDY_UID/SOP_UID.dcm
    gcs_path = f"{gcs_prefix.rstrip('/')}/{rel}" if gcs_prefix else ''

    study_date_raw  = g('StudyDate')
    series_date_raw = g('SeriesDate')

    return {
        # ── File ──────────────────────────────────────────────────────────
        'file_path':               str(dcm_path),
        'gcs_path':                gcs_path,

        # ── Patient ───────────────────────────────────────────────────────
        'patient_id':              g('PatientID'),
        'patient_name':            patient_name_display,
        'patient_name_raw':        patient_name_raw,
        'patient_dob':             parse_dicom_date(g('PatientBirthDate')),
        'patient_sex':             g('PatientSex'),
        'patient_age':             g('PatientAge'),
        'patient_weight_kg':       g('PatientWeight'),

        # ── Study ─────────────────────────────────────────────────────────
        'study_instance_uid':      g('StudyInstanceUID'),
        'study_date':              parse_dicom_date(study_date_raw),
        'study_date_raw':          study_date_raw,
        'study_time':              g('StudyTime'),
        'study_description':       g('StudyDescription'),
        'accession_number':        g('AccessionNumber'),
        'study_id':                g('StudyID'),
        'referring_physician':     g('ReferringPhysicianName'),
        'institution_name':        g('InstitutionName'),
        'institution_address':     g('InstitutionAddress'),

        # ── Series ────────────────────────────────────────────────────────
        'series_instance_uid':     g('SeriesInstanceUID'),
        'series_number':           g('SeriesNumber'),
        'series_description':      g('SeriesDescription'),
        'series_date':             parse_dicom_date(series_date_raw),
        'modality':                g('Modality'),
        'body_part':               g('BodyPartExamined'),
        'protocol_name':           g('ProtocolName'),
        'manufacturer':            g('Manufacturer'),
        'manufacturer_model':      g('ManufacturerModelName'),
        'station_name':            g('StationName'),
        'software_versions':       g('SoftwareVersions'),

        # ── Instance ──────────────────────────────────────────────────────
        'sop_instance_uid':        g('SOPInstanceUID'),
        'sop_class_uid':           g('SOPClassUID'),
        'instance_number':         g('InstanceNumber'),
        'image_type':              image_type,
        'rows':                    g('Rows'),
        'columns':                 g('Columns'),
        'slice_thickness_mm':      g('SliceThickness'),
        'slice_location':          g('SliceLocation'),
        'pixel_spacing_mm':        pixel_spacing,
        'bits_allocated':          g('BitsAllocated'),

        # ── CT-specific ───────────────────────────────────────────────────
        'kvp':                     g('KVP'),
        'tube_current_ma':         g('XRayTubeCurrent'),
        'exposure_time_ms':        g('ExposureTime'),
        'convolution_kernel':      g('ConvolutionKernel'),
        'reconstruction_diameter': g('ReconstructionDiameter'),
        'ct_di_vol':               g('CTDIvol'),

        # ── MRI-specific ──────────────────────────────────────────────────
        'field_strength_t':        g('MagneticFieldStrength'),
        'repetition_time_ms':      g('RepetitionTime'),
        'echo_time_ms':            g('EchoTime'),
        'flip_angle_deg':          g('FlipAngle'),
        'sequence_name':           g('SequenceName'),
        'scanning_sequence':       g('ScanningSequence'),
        'sequence_variant':        g('SequenceVariant'),
        'mr_acquisition_type':     g('MRAcquisitionType'),
    }


# ── Aggregation ────────────────────────────────────────────────────────────────

def build_aggregates(df: pd.DataFrame):
    """Return (patients_df, studies_df, series_df) aggregated from instances_df."""

    # ── Series ────────────────────────────────────────────────────────────────
    series = (
        df.groupby('series_instance_uid', as_index=False)
        .agg(
            patient_id        = ('patient_id',         'first'),
            study_instance_uid= ('study_instance_uid', 'first'),
            series_number     = ('series_number',      'first'),
            series_description= ('series_description', 'first'),
            series_date       = ('series_date',        'first'),
            modality          = ('modality',            'first'),
            body_part         = ('body_part',           'first'),
            protocol_name     = ('protocol_name',       'first'),
            manufacturer      = ('manufacturer',        'first'),
            manufacturer_model= ('manufacturer_model',  'first'),
            station_name      = ('station_name',        'first'),
            rows              = ('rows',                'first'),
            columns           = ('columns',             'first'),
            slice_thickness_mm= ('slice_thickness_mm',  'first'),
            field_strength_t  = ('field_strength_t',    'first'),
            instance_count    = ('sop_instance_uid',    'count'),
        )
        .sort_values(['study_instance_uid', 'series_number'])
    )

    # ── Studies ───────────────────────────────────────────────────────────────
    studies = (
        df.groupby('study_instance_uid', as_index=False)
        .agg(
            patient_id         = ('patient_id',          'first'),
            patient_name       = ('patient_name',        'first'),
            study_date         = ('study_date',          'first'),
            study_description  = ('study_description',   'first'),
            accession_number   = ('accession_number',    'first'),
            institution_name   = ('institution_name',    'first'),
            referring_physician= ('referring_physician',  'first'),
            modalities         = ('modality',   lambda x: ', '.join(sorted(x.dropna().unique()))),
            body_parts         = ('body_part',  lambda x: ', '.join(sorted(x.dropna().replace('', pd.NA).dropna().unique()))),
            series_count       = ('series_instance_uid', 'nunique'),
            instance_count     = ('sop_instance_uid',    'count'),
        )
        .sort_values('study_date')
    )

    # ── Patients ──────────────────────────────────────────────────────────────
    patients = (
        df.groupby('patient_id', as_index=False)
        .agg(
            patient_name  = ('patient_name',        'first'),
            patient_dob   = ('patient_dob',          'first'),
            patient_sex   = ('patient_sex',          'first'),
            patient_age   = ('patient_age',          'first'),
            study_count   = ('study_instance_uid',  'nunique'),
            series_count  = ('series_instance_uid', 'nunique'),
            instance_count= ('sop_instance_uid',    'count'),
            modalities    = ('modality', lambda x: ', '.join(sorted(x.dropna().unique()))),
            date_earliest = ('study_date', 'min'),
            date_latest   = ('study_date', 'max'),
        )
        .sort_values('patient_name')
    )

    return patients, studies, series


# ── Summary report ─────────────────────────────────────────────────────────────

def build_report(df: pd.DataFrame, patients_df, studies_df, series_df,
                 source_dir: str, gcs_prefix: str, run_ts: str,
                 error_count: int, total_scanned: int) -> str:

    modality_counts = df.groupby('modality')['sop_instance_uid'].count().sort_values(ascending=False)
    body_part_counts = (
        df[df['body_part'] != '']
        .groupby('body_part')['sop_instance_uid'].count()
        .sort_values(ascending=False)
    )
    institution_counts = (
        df[df['institution_name'] != '']
        .groupby('institution_name')['sop_instance_uid'].count()
        .sort_values(ascending=False)
    )
    sex_counts = df.drop_duplicates('patient_id')['patient_sex'].value_counts()
    study_dates = df['study_date'].replace('', pd.NA).dropna()
    date_range  = f"{study_dates.min()} → {study_dates.max()}" if not study_dates.empty else 'N/A'

    def tbl(series, col1='Value', col2='Count'):
        lines = [f'| {col1} | {col2} |', '|---|---|']
        for k, v in series.items():
            lines.append(f'| {k} | {v:,} |')
        return '\n'.join(lines)

    missing_patient_id   = (df['patient_id']   == '').sum()
    missing_study_date   = (df['study_date']   == '').sum()
    missing_modality     = (df['modality']     == '').sum()
    missing_institution  = (df['institution_name'] == '').sum()

    lines = [
        f'# IMLADRIS Lab — DICOM Dataset Summary',
        f'',
        f'**Generated:** {run_ts}  ',
        f'**Source:** `{source_dir}`  ',
        f'**GCS target:** `{gcs_prefix}`  ',
        f'',
        f'---',
        f'',
        f'## Overview',
        f'',
        f'| Metric | Count |',
        f'|---|---|',
        f'| Files scanned | {total_scanned:,} |',
        f'| Files read successfully | {len(df):,} |',
        f'| Read errors / skipped | {error_count:,} |',
        f'| Unique patients | {df["patient_id"].nunique():,} |',
        f'| Unique studies | {df["study_instance_uid"].nunique():,} |',
        f'| Unique series | {df["series_instance_uid"].nunique():,} |',
        f'| Study date range | {date_range} |',
        f'',
        f'---',
        f'',
        f'## Modalities',
        f'',
        tbl(modality_counts, 'Modality', 'Instances'),
        f'',
        f'---',
        f'',
        f'## Body Parts Examined',
        f'',
        tbl(body_part_counts, 'Body Part', 'Instances') if not body_part_counts.empty else '_Not populated in this dataset._',
        f'',
        f'---',
        f'',
        f'## Patient Demographics',
        f'',
        f'| Sex | Patients |',
        f'|---|---|',
    ]
    for sex, count in sex_counts.items():
        label = {'M': 'Male', 'F': 'Female', 'O': 'Other'}.get(sex, sex or 'Unknown')
        lines.append(f'| {label} | {count} |')

    lines += [
        f'',
        f'---',
        f'',
        f'## Studies',
        f'',
        f'| Patient ID | Patient Name | Date | Description | Modalities | Series | Instances |',
        f'|---|---|---|---|---|---|---|',
    ]
    for _, r in studies_df.iterrows():
        lines.append(
            f'| {r.patient_id} | {r.patient_name} | {r.study_date} | '
            f'{r.study_description} | {r.modalities} | {r.series_count} | {r.instance_count} |'
        )

    if not institution_counts.empty:
        lines += [
            f'',
            f'---',
            f'',
            f'## Institutions / Sources',
            f'',
            tbl(institution_counts, 'Institution', 'Instances'),
        ]

    lines += [
        f'',
        f'---',
        f'',
        f'## Data Quality',
        f'',
        f'| Field | Missing instances | % |',
        f'|---|---|---|',
        f'| PatientID | {missing_patient_id:,} | {missing_patient_id/len(df)*100:.1f}% |',
        f'| StudyDate | {missing_study_date:,} | {missing_study_date/len(df)*100:.1f}% |',
        f'| Modality | {missing_modality:,} | {missing_modality/len(df)*100:.1f}% |',
        f'| InstitutionName | {missing_institution:,} | {missing_institution/len(df)*100:.1f}% |',
        f'',
        f'---',
        f'',
        f'## GCS Upload',
        f'',
        f'Files to upload: **{len(df):,}** instances  ',
        f'Target prefix: `{gcs_prefix}`  ',
        f'',
        f'```bash',
        f'# Upload (run from imladris-basotho directory):',
        f'gcloud storage rsync -r \\',
        f'  "{source_dir}" \\',
        f'  "{gcs_prefix}"',
        f'```',
    ]

    return '\n'.join(lines)


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='DICOM metadata extractor — IMLADRIS Lab')
    parser.add_argument('--source',     required=True,
                        help='Root directory containing DICOM files (can be nested)')
    parser.add_argument('--output',     required=True,
                        help='Output directory for CSVs and report')
    parser.add_argument('--gcs-prefix', default='gs://botsabelo-hospital-records/botsabelo_processed/ct_mri',
                        help='GCS path prefix written into instances.csv gcs_path column')
    parser.add_argument('--workers',    type=int, default=8,
                        help='Parallel reader threads (default: 8)')
    args = parser.parse_args()

    source_dir = Path(args.source)
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    run_ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f'\n🔍  Scanning {source_dir} …')

    dcm_files = sorted(source_dir.rglob('*.dcm'))
    total_scanned = len(dcm_files)
    print(f'    Found {total_scanned:,} .dcm files')

    if total_scanned == 0:
        print('ERROR: no .dcm files found.  Check --source path.')
        sys.exit(1)

    print(f'\n📂  Extracting metadata with {args.workers} threads …')
    rows = []
    errors = []

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(extract_tags, f, args.gcs_prefix): f for f in dcm_files}
        with tqdm(total=total_scanned, unit='file', ncols=80) as pbar:
            for future in as_completed(futures):
                pbar.update(1)
                result = future.result()
                if result is not None:
                    rows.append(result)
                else:
                    errors.append(str(futures[future]))

    error_count = len(errors)
    print(f'    ✓ {len(rows):,} files read   ✗ {error_count} errors')

    if not rows:
        print('ERROR: no files could be read.  Check file format.')
        sys.exit(1)

    # ── Build DataFrames ──────────────────────────────────────────────────────
    print('\n📊  Building aggregates …')
    instances_df = pd.DataFrame(rows)
    patients_df, studies_df, series_df = build_aggregates(instances_df)

    # ── Write CSVs ────────────────────────────────────────────────────────────
    print(f'\n💾  Writing output to {output_dir}/ …')
    instances_df.to_csv(output_dir / 'instances.csv', index=False)
    series_df.to_csv(output_dir / 'series.csv', index=False)
    studies_df.to_csv(output_dir / 'studies.csv', index=False)
    patients_df.to_csv(output_dir / 'patients.csv', index=False)

    # ── Write report ──────────────────────────────────────────────────────────
    report = build_report(
        instances_df, patients_df, studies_df, series_df,
        str(source_dir), args.gcs_prefix, run_ts, error_count, total_scanned
    )
    report_path = output_dir / 'summary_report.md'
    report_path.write_text(report, encoding='utf-8')

    if errors:
        (output_dir / 'read_errors.txt').write_text('\n'.join(errors))

    # ── Print summary ─────────────────────────────────────────────────────────
    print(f'''
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  DONE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Patients : {patients_df.shape[0]:>6,}
  Studies  : {studies_df.shape[0]:>6,}
  Series   : {series_df.shape[0]:>6,}
  Instances: {instances_df.shape[0]:>6,}   (errors: {error_count})

  Output   : {output_dir}/
    instances.csv
    series.csv
    studies.csv
    patients.csv
    summary_report.md{f"{chr(10)}    read_errors.txt" if errors else ""}

  GCS upload command:
    gcloud storage rsync -r \\
      "{source_dir}" \\
      "{args.gcs_prefix}"
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
''')


if __name__ == '__main__':
    main()
