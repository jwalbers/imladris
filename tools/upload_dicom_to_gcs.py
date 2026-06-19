#!/usr/bin/env python3
"""
upload_dicom_to_gcs.py — IMLADRIS Lab

Uploads DICOM files to GCS using the body-part-aware path structure:
    gs://<bucket>/botsabelo_processed/<modality>/<body_part>/<study_uid>/<file>

Reads instances.csv produced by extract_dicom_metadata.py, computes the
correct GCS path for each file, uploads in parallel, and writes an updated
instances.csv with the actual gcs_path used.

Usage:
    python3 tools/upload_dicom_to_gcs.py \\
        --instances reports/ct_mri_20260619/instances.csv \\
        --bucket    botsabelo-hospital-records \\
        --base-prefix botsabelo_processed \\
        --key       keys/imladris-492521-95510b26a959.json \\
        --workers   16

Output:
    Overwrites gcs_path column in instances.csv with the actual uploaded paths.
    Writes upload_errors.txt if any files fail.
"""

import os
import sys
import argparse
import traceback
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
from google.cloud import storage
from tqdm import tqdm


MODALITY_MAP = {
    'CT':  'ct',
    'MR':  'mri',
    'CR':  'xray',
    'DX':  'xray',
    'US':  'ultrasound',
    'XA':  'xray',
    'NM':  'nm',
    'PT':  'pt',
    'MG':  'mammo',
}


def gcs_path_for(row, bucket: str, base_prefix: str) -> str:
    """
    Compute canonical GCS path for one instance row.
    Structure: gs://<bucket>/<base_prefix>/<modality>/<body_part>/<study_uid>/<filename>
    """
    modality_dir  = MODALITY_MAP.get(row['modality'], row['modality'].lower())
    bp = row['body_part']
    body_part_dir = (str(bp) if bp == bp else 'unknown').lower().replace(' ', '_') or 'unknown'
    study_uid     = row['study_instance_uid']
    filename      = Path(row['file_path']).name
    blob_name     = f"{base_prefix}/{modality_dir}/{body_part_dir}/{study_uid}/{filename}"
    return f"gs://{bucket}/{blob_name}"


def upload_one(args) -> tuple[str, str | None]:
    """
    Upload a single file.  Returns (file_path, error_msg | None).
    """
    blob, local_path = args
    try:
        blob.upload_from_filename(local_path)
        return local_path, None
    except Exception as e:
        return local_path, str(e)


def main():
    parser = argparse.ArgumentParser(description='DICOM GCS uploader — IMLADRIS Lab')
    parser.add_argument('--instances',    required=True,
                        help='instances.csv from extract_dicom_metadata.py')
    parser.add_argument('--bucket',       default='botsabelo-hospital-records',
                        help='GCS bucket name')
    parser.add_argument('--base-prefix',  default='botsabelo_processed',
                        help='Path prefix within bucket')
    parser.add_argument('--key',          default='keys/imladris-492521-95510b26a959.json',
                        help='GCP service account JSON key (relative to repo root or absolute)')
    parser.add_argument('--workers',      type=int, default=16,
                        help='Parallel upload threads (default: 16)')
    parser.add_argument('--dry-run',      action='store_true',
                        help='Print computed GCS paths without uploading')
    args = parser.parse_args()

    instances_path = Path(args.instances)
    key_path       = Path(args.key) if not Path(args.key).is_absolute() else Path(args.key)
    # Resolve relative to repo root (parent of tools/)
    if not key_path.is_absolute():
        key_path = Path(__file__).parent.parent / key_path

    print(f'\n📋  Loading {instances_path} …')
    df = pd.read_csv(instances_path)
    total = len(df)
    print(f'    {total:,} instances  ·  '
          f'{df["modality"].nunique()} modalities  ·  '
          f'{df["body_part"].nunique()} body parts')

    # ── Compute target GCS paths ───────────────────────────────────────────────
    df['gcs_path'] = df.apply(
        lambda r: gcs_path_for(r, args.bucket, args.base_prefix), axis=1
    )

    if args.dry_run:
        print('\n── DRY RUN — sample paths ──')
        for mod, grp in df.groupby(['modality', 'body_part']):
            print(f'\n  {mod[0]} / {mod[1]}  ({len(grp):,} files)')
            print(f'    {grp["gcs_path"].iloc[0]}')
            print(f'    …')
        print(f'\n  Total would upload: {total:,} files')
        df.to_csv(instances_path, index=False)
        print(f'\n  instances.csv updated with new gcs_path column (no files uploaded)')
        return

    # ── Connect to GCS ────────────────────────────────────────────────────────
    print(f'\n☁️   Connecting to GCS bucket {args.bucket!r} …')
    client = storage.Client.from_service_account_json(str(key_path))
    bucket = client.bucket(args.bucket)

    # Show upload plan
    plan = df.groupby(['modality', 'body_part']).size().reset_index(name='files')
    print('\n  Upload plan:')
    for _, r in plan.iterrows():
        sample = df[(df['modality'] == r['modality']) & (df['body_part'] == r['body_part'])]['gcs_path'].iloc[0]
        prefix = '/'.join(sample.split('/')[:6])
        print(f'    {r["files"]:>5,}  →  {prefix}/…')
    print()

    # ── Upload ────────────────────────────────────────────────────────────────
    print(f'⬆️   Uploading {total:,} files with {args.workers} threads …')

    upload_args = [
        (bucket.blob('/'.join(row['gcs_path'].split('/')[3:])), row['file_path'])
        for _, row in df.iterrows()
    ]

    errors = []
    ok_count = 0

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(upload_one, a): a[1] for a in upload_args}
        with tqdm(total=total, unit='file', ncols=80) as pbar:
            for future in as_completed(futures):
                pbar.update(1)
                local_path, err = future.result()
                if err:
                    errors.append(f'{local_path}: {err}')
                else:
                    ok_count += 1

    # ── Save updated CSV ───────────────────────────────────────────────────────
    df.to_csv(instances_path, index=False)
    print(f'\n    instances.csv updated with final gcs_path column')

    if errors:
        err_path = instances_path.parent / 'upload_errors.txt'
        err_path.write_text('\n'.join(errors))
        print(f'    ⚠️  {len(errors)} errors → {err_path}')

    print(f'''
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  UPLOAD COMPLETE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Uploaded : {ok_count:>6,}
  Errors   : {len(errors):>6,}
  Bucket   : gs://{args.bucket}/{args.base_prefix}/
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
''')


if __name__ == '__main__':
    main()
