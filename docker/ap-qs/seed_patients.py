#!/usr/bin/env python3
"""
seed_patients.py — Create / confirm all Bophelong census patients in AdvaPACS FHIR R5.

Usage (from docker/ap-qs/):
    python seed_patients.py [--csv PATH] [--dry-run]

Reads credentials from the local .env file (ADVAPACS_KEY_ID, ADVAPACS_SECRET).
For each patient in the CSV:
  - Searches AdvaPACS by Patient_ID identifier.
  - Prints "EXISTS" with the current AdvaPACS name if found.
  - Creates a new Patient resource and prints "CREATED" if not found.

Name convention in CSV: "GivenName Surname" (last word = family name).
"""

import argparse
import csv
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

# ── Config ────────────────────────────────────────────────────────────────────

DEFAULT_CSV = Path(__file__).parent.parent.parent.parent / (
    "imladris-bophelong/patients/bophelong_census.csv"
)
FHIR_BASE = "https://usa1.api.integration.advapacs.com/fhir/R5"

GENDER_MAP = {"M": "male", "F": "female"}


# ── Auth ──────────────────────────────────────────────────────────────────────

def _auth_header(key_id: str, secret: str) -> dict:
    return {"Authorization": f"ID={key_id},Secret={secret}"}


# ── Name parsing ──────────────────────────────────────────────────────────────

def _parse_name(name: str) -> tuple[str, str]:
    """'GivenName Surname' → (family, given). Last word is the family name."""
    parts = name.strip().split()
    if len(parts) == 1:
        return parts[0], ""
    return parts[-1], " ".join(parts[:-1])


# ── FHIR operations ───────────────────────────────────────────────────────────

def _search(client: httpx.Client, patient_id: str) -> dict | None:
    """Return first matching Patient resource or None."""
    r = client.get(f"{FHIR_BASE}/Patient", params={"identifier": patient_id})
    r.raise_for_status()
    bundle = r.json()
    entries = bundle.get("entry", [])
    return entries[0]["resource"] if entries else None


def _display_name(resource: dict) -> str:
    names = resource.get("name", [{}])
    n = names[0] if names else {}
    family = n.get("family", "")
    given  = " ".join(n.get("given", []))
    return f"{family}^{given}" if given else family


def _create(client: httpx.Client, patient_id: str, family: str, given: str,
            dob: str, gender: str, dry_run: bool) -> str:
    """POST a new Patient. Returns the new FHIR UUID or 'DRY-RUN'."""
    body = {
        "resourceType": "Patient",
        "identifier": [{"system": "http://openmrs.org/identifier", "value": patient_id}],
        "name": [{"family": family, "given": [given] if given else []}],
        "gender": gender,
        "birthDate": dob,
    }
    if dry_run:
        return "DRY-RUN"
    r = client.post(f"{FHIR_BASE}/Patient", json=body)
    r.raise_for_status()
    return r.json().get("id", "?")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--csv",     default=str(DEFAULT_CSV), help="Path to bophelong_census.csv")
    parser.add_argument("--dry-run", action="store_true",      help="Search only, do not create")
    args = parser.parse_args()

    load_dotenv(Path(__file__).parent / ".env")
    key_id = os.getenv("ADVAPACS_KEY_ID")
    secret = os.getenv("ADVAPACS_SECRET")
    if not key_id or not secret:
        sys.exit("ERROR: ADVAPACS_KEY_ID / ADVAPACS_SECRET not set in .env or environment")

    csv_path = Path(args.csv)
    if not csv_path.exists():
        sys.exit(f"ERROR: CSV not found: {csv_path}")

    headers = _auth_header(key_id, secret)
    created = exists = patched = errors = 0

    with httpx.Client(headers=headers, timeout=30) as client, \
         open(csv_path, newline="", encoding="utf-8-sig") as f:

        reader = csv.DictReader(f)
        rows = list(reader)
        print(f"Processing {len(rows)} patients from {csv_path.name} …\n")
        print(f"{'#':<4} {'Patient_ID':<10} {'Name':<28} {'Status':<10} {'Detail'}")
        print("-" * 75)

        for row in rows:
            seq        = row["Sequence"]
            patient_id = row["Patient_ID"].strip()
            raw_name   = row["Name"].strip()
            dob        = row["Birthdate"].strip()[:10]
            gender     = GENDER_MAP.get(row["Gender"].strip().upper(), "unknown")
            family, given = _parse_name(raw_name)

            try:
                existing = _search(client, patient_id)
                if existing:
                    adva_name = _display_name(existing)
                    adva_uuid = existing.get("id", "?")
                    # CSV is "GIVENNAME SURNAME"; AdvaPACS is "SURNAME^GIVENNAME"
                    adva_parts = adva_name.split("^", 1)
                    adva_family = adva_parts[0].lower()
                    adva_given  = adva_parts[1].lower() if len(adva_parts) > 1 else ""
                    match = "OK" if adva_family == family.lower() and adva_given == given.lower() else "!="

                    # Ensure the identifier has the correct system URI so DICOM
                    # IssuerOfPatientID=PIH_A can match this patient.
                    has_system_id = any(
                        i.get("system") == "http://openmrs.org/identifier"
                        and i.get("value") == patient_id
                        for i in existing.get("identifier", [])
                    )
                    if not has_system_id and not args.dry_run:
                        resource = dict(existing)
                        resource.setdefault("identifier", [])
                        resource["identifier"].append(
                            {"system": "http://openmrs.org/identifier", "value": patient_id}
                        )
                        r = client.put(f"{FHIR_BASE}/Patient/{adva_uuid}", json=resource)
                        r.raise_for_status()
                        id_note = " [ID-FIXED]"
                        patched += 1
                    else:
                        id_note = "" if has_system_id else " [ID-MISSING(dry)]"

                    print(f"{seq:<4} {patient_id:<10} {raw_name:<28} {'EXISTS':<10} {match} {adva_name}  [{adva_uuid[:8]}...]{id_note}")
                    exists += 1
                else:
                    uuid = _create(client, patient_id, family, given, dob, gender, args.dry_run)
                    tag = "DRY-RUN" if args.dry_run else "CREATED"
                    print(f"{seq:<4} {patient_id:<10} {raw_name:<28} {tag:<10} {family}^{given}  [{uuid[:8]}...]")
                    if not args.dry_run:
                        created += 1

            except Exception as e:
                print(f"{seq:<4} {patient_id:<10} {raw_name:<28} {'ERROR':<10} {e}")
                errors += 1

    print("-" * 75)
    print(f"\nDone.  Exists: {exists}  Created: {created}  ID-fixed: {patched}  Errors: {errors}")
    if args.dry_run:
        print("(dry-run — no patients were created or updated)")


if __name__ == "__main__":
    main()
