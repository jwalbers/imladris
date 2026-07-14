#!/usr/bin/env python3
"""
delete_patient_studies.py — Delete all AdvaPACS studies for a patient.

Finds the patient by OpenMRS identifier via FHIR, lists all ImagingStudy
resources, then deletes each via DICOMweb DELETE /studies/{uid}.

Usage:
    python delete_patient_studies.py XP92EU
    python delete_patient_studies.py XP92EU --dry-run
    python delete_patient_studies.py XP92EU --modality SC   # only SC series

Credentials (any of these, in priority order):
    Environment vars:  ADVAPACS_KEY_ID / ADVAPACS_SECRET
    .env file in cwd or any parent directory
"""

import argparse
import base64
import os
import sys
from pathlib import Path

import httpx

FHIR_BASE     = "https://usa1.api.integration.advapacs.com/fhir/R5"
DICOMWEB_BASE = "https://usa1.api.dicomweb.advapacs.com"


# ── Credential loading ────────────────────────────────────────────────────────

def _load_dotenv():
    for d in [Path.cwd()] + list(Path.cwd().parents):
        p = d / ".env"
        if p.exists():
            for line in p.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    os.environ.setdefault(k.strip(), v.strip().strip("\"'"))
            return


def _creds():
    _load_dotenv()
    key_id = os.getenv("ADVAPACS_KEY_ID") or os.getenv("FHIR_KEY_ID", "")
    secret  = os.getenv("ADVAPACS_SECRET")  or os.getenv("FHIR_KEY_SECRET", "")
    if not key_id or not secret:
        sys.exit("ERROR: set ADVAPACS_KEY_ID and ADVAPACS_SECRET in environment or .env")
    return key_id, secret


def _fhir_headers(key_id, secret):
    return {
        "Authorization": f"ID={key_id},Secret={secret}",
        "Accept": "application/fhir+json",
    }


def _dicomweb_headers(key_id, secret):
    b64 = base64.b64encode(f"{key_id}:{secret}".encode()).decode()
    return {"Authorization": f"Basic {b64}"}


# ── FHIR queries ──────────────────────────────────────────────────────────────

def find_patient(client, hdrs, patient_id):
    r = client.get(f"{FHIR_BASE}/Patient",
                   params={"identifier": patient_id}, headers=hdrs, timeout=15)
    r.raise_for_status()
    entries = r.json().get("entry", [])
    if not entries:
        return None, None
    res = entries[0]["resource"]
    return res["id"], res


def list_imaging_studies(client, hdrs, patient_uuid):
    studies = []
    url    = f"{FHIR_BASE}/ImagingStudy"
    params = {"patient": patient_uuid, "_count": "200"}
    while url:
        r = client.get(url, params=params, headers=hdrs, timeout=15)
        r.raise_for_status()
        bundle = r.json()
        for entry in bundle.get("entry", []):
            res = entry.get("resource", {})
            uid = ""
            for ident in res.get("identifier", []):
                if ident.get("system") == "urn:dicom:uid":
                    uid = ident.get("value", "").removeprefix("urn:oid:")
            studies.append({
                "fhir_id":   res.get("id", ""),
                "uid":       uid,
                "series":    res.get("numberOfSeries", "?"),
                "instances": res.get("numberOfInstances", "?"),
                "started":   res.get("started", ""),
                "desc":      res.get("description", ""),
            })
        url    = next((l["url"] for l in bundle.get("link", [])
                       if l.get("relation") == "next"), None)
        params = {}
    return studies


def list_series(client, dw_hdrs, study_uid):
    """QIDO-RS series list for a study (used for modality filter)."""
    r = client.get(f"{DICOMWEB_BASE}/studies/{study_uid}/series",
                   headers=dw_hdrs, timeout=15)
    if r.status_code != 200:
        return []
    return r.json()


# ── Deletion ──────────────────────────────────────────────────────────────────

def delete_series(client, dw_hdrs, study_uid, series_uid, dry_run):
    if dry_run:
        print(f"      [dry-run] DELETE /studies/{study_uid}/series/{series_uid}")
        return True
    r = client.delete(
        f"{DICOMWEB_BASE}/studies/{study_uid}/series/{series_uid}",
        headers=dw_hdrs, timeout=30,
    )
    if r.status_code in (200, 204):
        print(f"      ✓ series {series_uid[:16]}…")
        return True
    print(f"      ✗ HTTP {r.status_code}: {r.text[:80]}")
    return False


def delete_study(client, dw_hdrs, fhir_hdrs, study, dry_run):
    uid     = study["uid"]
    fhir_id = study["fhir_id"]

    if dry_run:
        print(f"  [dry-run] DELETE study {uid or fhir_id}")
        return True

    # DICOMweb DELETE /studies/{uid}
    if uid:
        r = client.delete(f"{DICOMWEB_BASE}/studies/{uid}",
                          headers=dw_hdrs, timeout=30)
        if r.status_code in (200, 204):
            print(f"  ✓ DICOMweb study deleted")
            return True
        print(f"  ! DICOMweb HTTP {r.status_code} — trying FHIR DELETE…")

    # FHIR fallback DELETE /ImagingStudy/{id}
    r = client.delete(f"{FHIR_BASE}/ImagingStudy/{fhir_id}",
                      headers=fhir_hdrs, timeout=30)
    if r.status_code in (200, 204):
        print(f"  ✓ FHIR ImagingStudy deleted")
        return True
    print(f"  ✗ FHIR HTTP {r.status_code}: {r.text[:100]}")
    return False


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(
        description="Delete AdvaPACS studies for a patient by OpenMRS ID"
    )
    ap.add_argument("patient_id", help="OpenMRS patient identifier (e.g. XP92EU)")
    ap.add_argument("--dry-run", action="store_true",
                    help="List what would be deleted without actually deleting")
    ap.add_argument("--modality", metavar="MOD",
                    help="Only delete series with this modality (e.g. SC). "
                         "Studies with no remaining series are deleted entirely.")
    args = ap.parse_args()

    key_id, secret = _creds()
    fhdr = _fhir_headers(key_id, secret)
    dwdr = _dicomweb_headers(key_id, secret)

    with httpx.Client(follow_redirects=True) as client:
        print(f"Patient: {args.patient_id}")
        uuid, _pt = find_patient(client, fhdr, args.patient_id)
        if not uuid:
            sys.exit(f"ERROR: patient '{args.patient_id}' not found in AdvaPACS")
        print(f"UUID:    {uuid}\n")

        studies = list_imaging_studies(client, fhdr, uuid)
        print(f"Studies: {len(studies)}\n")
        if not studies:
            return

        ok = fail = skipped = 0
        for i, st in enumerate(studies, 1):
            label = f"[{i}/{len(studies)}]"
            print(f"{label} {st['uid'] or st['fhir_id']}")
            print(f"         {st['started'][:10]}  {st['series']} series  "
                  f"{st['instances']} instances  {st['desc']}")

            if args.modality and st["uid"]:
                # Filter: only delete matching series; skip study if none match
                series_list = list_series(client, dwdr, st["uid"])
                matching = [
                    s for s in series_list
                    if s.get("00080060", {}).get("Value", [""])[0].upper()
                    == args.modality.upper()
                ]
                if not matching:
                    print(f"         (no {args.modality} series — skipping)")
                    skipped += 1
                    continue
                print(f"         {len(matching)} {args.modality} series to delete")
                series_ok = all(
                    delete_series(client, dwdr, st["uid"],
                                  s["0020000E"]["Value"][0], args.dry_run)
                    for s in matching
                )
                if series_ok:
                    ok += 1
                else:
                    fail += 1
            else:
                if delete_study(client, dwdr, fhdr, st, args.dry_run):
                    ok += 1
                else:
                    fail += 1

        print(f"\n{'DRY RUN — ' if args.dry_run else ''}Done: "
              f"{ok} deleted, {fail} failed, {skipped} skipped")


if __name__ == "__main__":
    main()
