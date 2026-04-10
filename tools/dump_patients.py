#!/usr/bin/env python3
"""
dump_patients.py — Dump OpenMRS patient demographics to CSV by identifier list.

Reads one patient identifier per line from an input file, looks each up via
GET /ws/rest/v1/patient?identifier=<id>, and writes demographics to CSV.

Usage:
    python tools/dump_patients.py <id-file> [options]

    python tools/dump_patients.py map.txt
    python tools/dump_patients.py map.txt --out patients_dump.csv
"""

import argparse
import csv
import sys
from pathlib import Path

import requests
from requests.auth import HTTPBasicAuth


class OpenMRSClient:
    def __init__(self, base_url: str, user: str, password: str):
        self.base = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.auth = HTTPBasicAuth(user, password)

    def get(self, path: str, **params):
        r = self.session.get(f"{self.base}{path}", params=params)
        r.raise_for_status()
        return r.json()

    def find_by_identifier(self, identifier: str) -> dict | None:
        data = self.get("/ws/rest/v1/patient", identifier=identifier, v="full")
        results = data.get("results", [])
        return results[0] if results else None


def extract_row(patient: dict, id_type_hint: str | None) -> dict:
    person = patient.get("person", {})

    # -- Name -----------------------------------------------------------------
    given, family = "", ""
    for name in person.get("names", []):
        if not name.get("voided"):
            given  = name.get("givenName", "")
            family = name.get("familyName", "")
            break

    # -- Preferred identifier (optionally filtered by type name) --------------
    identifier = ""
    for ident in patient.get("identifiers", []):
        if ident.get("voided"):
            continue
        if id_type_hint:
            type_name = ident.get("identifierType", {}).get("display", "")
            if id_type_hint.lower() not in type_name.lower():
                continue
        identifier = ident.get("identifier", "")
        if ident.get("preferred"):
            break   # prefer the preferred one but keep scanning

    # -- Address --------------------------------------------------------------
    district, country = "", ""
    for addr in person.get("addresses", []):
        if not addr.get("voided"):
            district = addr.get("countyDistrict", "")
            country  = addr.get("country", "")
            break

    return {
        "uuid":        patient.get("uuid", ""),
        "identifier":  identifier,
        "given_name":  given,
        "family_name": family,
        "gender":      person.get("gender", ""),
        "birthdate":   (person.get("birthdate") or "")[:10],  # trim time component
        "birthdate_estimated": person.get("birthdateEstimated", ""),
        "district":    district,
        "country":     country,
    }


def load_identifiers(path: Path) -> list[str]:
    """Read identifiers from a file — one per line, strip blanks and # comments.
    If the file looks like a CSV with a header, extract the Patient_ID column.
    """
    lines = path.read_text(encoding="utf-8").splitlines()
    # Detect CSV: if first non-blank line contains a comma, treat as CSV
    first = next((l for l in lines if l.strip() and not l.startswith("#")), "")
    if "," in first:
        import csv as _csv
        with open(path, newline="", encoding="utf-8") as f:
            reader = _csv.DictReader(f)
            # Accept Patient_ID or first column
            col = "Patient_ID" if "Patient_ID" in (reader.fieldnames or []) else (reader.fieldnames or [""])[0]
            return [row[col].strip() for row in reader if row[col].strip()]
    return [l.strip() for l in lines if l.strip() and not l.startswith("#")]


def main():
    parser = argparse.ArgumentParser(description="Dump OpenMRS patients to CSV by identifier list")
    parser.add_argument("id_file", help="Text file or CSV with patient identifiers (one per line, or Patient_ID column)")
    parser.add_argument("--url",      default="http://localhost:8080/openmrs")
    parser.add_argument("--user",     default="admin")
    parser.add_argument("--password", default="Admin123")
    parser.add_argument("--out",      default="patients_dump.csv",
                        help="Output CSV path (default: patients_dump.csv)")
    parser.add_argument("--id-type",  default="ZL EMR ID",
                        help="Filter identifiers by type name (default: ZL EMR ID)")
    args = parser.parse_args()

    id_file = Path(args.id_file)
    if not id_file.exists():
        sys.exit(f"File not found: {id_file}")

    identifiers = load_identifiers(id_file)
    if not identifiers:
        sys.exit("No identifiers found in file.")
    print(f"Loaded {len(identifiers)} identifiers from {id_file}")

    client = OpenMRSClient(args.url, args.user, args.password)

    fields = ["uuid", "identifier", "given_name", "family_name",
              "gender", "birthdate", "birthdate_estimated", "district", "country"]

    found, not_found = 0, 0
    out_path = Path(args.out)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for i, ident in enumerate(identifiers, 1):
            print(f"  [{i:02d}/{len(identifiers)}] {ident}…", end="\r", flush=True)
            patient = client.find_by_identifier(ident)
            if patient is None:
                print(f"  NOT FOUND  {ident}                ")
                not_found += 1
            else:
                writer.writerow(extract_row(patient, args.id_type))
                found += 1

    print(f"\nWritten {found} rows to {out_path}  (not found: {not_found})")


if __name__ == "__main__":
    main()
