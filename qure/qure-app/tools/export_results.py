#!/usr/bin/env python3
"""export_results.py — copy qTrack/qXR results for patients out of the Qure stack.

For each PatientID, looks up its image series in the platform database, then
copies every DICOM object qTrack keeps for that series from the filestore
(prod-data volume, /srv/data/hct/<workspace>/<SeriesInstanceUID>/):

  <imageID>                    original image as received (e.g. our DX capture)
  <imageID>_sc.dcm             qXR secondary capture with findings sidebar
  <imageID>_sc_without_sidebar.dcm   qXR secondary capture, overlay only
  <imageID>_sr.dcm             qXR structured report
  <imageID>_reports/<id>.dcm   report as DICOM (PDF counterpart alongside)

Output: <out>/<PatientID>/<SeriesInstanceUID>/..., plus a summary of each
object's SOP class, study/series UIDs and modality, so it is clear what a PACS
will receive. Exported files carry patient identity (fictional in the lab) —
keep them outside git.

Usage (host, needs docker + pydicom):
  python export_results.py GN21TF AKNGME --out %USERPROFILE%\\qure-dev\\export
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

import pydicom

SQL = """
select p.patient_id, se."seriesInstanceUID", i."imageID"
from portal_manager_patient p
join portal_manager_patient_image_studies pis on pis.patient_id = p.id
join image_manager_imageseries se on se.image_study_id = pis.imagestudy_id
join image_manager_image i on i.image_series_id = se.id
where p.patient_id = any(string_to_array('{ids}', ','))
order by p.patient_id, i.created_at
"""


def run(cmd: list[str], **kw) -> str:
    return subprocess.run(cmd, check=True, capture_output=True, text=True, **kw).stdout


def series_for(patient_ids: list[str]) -> list[tuple[str, str, str]]:
    out = run(["docker", "exec", "-i", "postgres", "psql", "-U", "postgres", "-d", "platform",
               "-At", "-F", "|"], input=SQL.format(ids=",".join(patient_ids)))
    return [tuple(line.split("|")) for line in out.splitlines() if line.strip()]


def dicom_files(series_uid: str, image_id: str) -> list[str]:
    # Everything for this image in its series dir, except renderings (png/mask/pdf).
    out = run(["docker", "exec", "qureapi", "sh", "-c",
               f"find /srv/data/hct -path '*/{series_uid}/*' -type f -name '{image_id}*' "
               f"! -name '*.png' ! -name '*.mask' ! -name '*.pdf' ! -name '*.ppr'"])
    return sorted(out.split())


def describe(path: Path) -> str:
    ds = pydicom.dcmread(path, stop_before_pixels=True, force=True)
    return (f"{ds.get('SOPClassUID', '?').name if 'SOPClassUID' in ds else '?':45.45}  "
            f"mod={ds.get('Modality', '')!s:3}  acc={ds.get('AccessionNumber', '')!s:9}  "
            f"study=…{str(ds.get('StudyInstanceUID', ''))[-12:]}  series=…{str(ds.get('SeriesInstanceUID', ''))[-12:]}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("patient_ids", nargs="+")
    ap.add_argument("--out", type=Path, default=Path.home() / "qure-dev" / "export")
    a = ap.parse_args()

    rows = series_for(a.patient_ids)
    missing = set(a.patient_ids) - {r[0] for r in rows}
    for pid in sorted(missing):
        print(f"{pid}: no images found")
    for pid, series_uid, image_id in rows:
        dest = a.out / pid / series_uid
        dest.mkdir(parents=True, exist_ok=True)
        print(f"\n{pid}  series {series_uid}")
        for src in dicom_files(series_uid, image_id):
            rel = src.split(f"/{series_uid}/", 1)[1]
            target = dest / rel.replace("/", "__")
            target = target if target.suffix == ".dcm" else target.with_name(target.name + ".dcm")
            subprocess.run(["docker", "cp", f"qureapi:{src}", str(target)], check=True,
                           env={**os.environ, "MSYS_NO_PATHCONV": "1"})
            print(f"  {target.name:60.60}  {describe(target)}")
    print(f"\nExported to {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
