#!/usr/bin/env python3
"""
delete_patients.py — Delete OpenMRS patients by identifier, read from a text file.

Reads one patient identifier per line, looks each up via the OpenMRS REST API,
and deletes (purges) the matching patient record.

Usage:
    python tools/delete_patients.py <id-file> [options]

    python tools/delete_patients.py old_ids.txt
    python tools/delete_patients.py old_ids.txt --dry-run
    python tools/delete_patients.py old_ids.txt --no-purge   # void instead of purge
"""

import argparse
import sys
from pathlib import Path

import requests
from requests.auth import HTTPBasicAuth


class OpenMRSClient:
    def __init__(self, base_url: str, user: str, password: str):
        self.base = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.auth = HTTPBasicAuth(user, password)
        self.session.headers["Content-Type"] = "application/json"

    def find_patient_by_identifier(self, identifier: str) -> dict | None:
        """Return the patient resource for *identifier*, or None if not found."""
        r = self.session.get(
            f"{self.base}/ws/rest/v1/patient",
            params={"identifier": identifier, "v": "default"},
        )
        r.raise_for_status()
        results = r.json().get("results", [])
        if not results:
            return None
        if len(results) > 1:
            # Shouldn't happen with a unique identifier type, but be safe
            raise ValueError(
                f"Identifier {identifier!r} matched {len(results)} patients"
            )
        return results[0]

    def delete_patient(self, uuid: str, purge: bool = True):
        """Delete (or void) a patient by UUID."""
        params = {"purge": "true"} if purge else {}
        r = self.session.delete(f"{self.base}/ws/rest/v1/patient/{uuid}", params=params)
        r.raise_for_status()


def load_ids(path: Path) -> list[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in lines if line.strip() and not line.startswith("#")]


def main():
    parser = argparse.ArgumentParser(description="Delete OpenMRS patients by identifier")
    parser.add_argument("id_file", help="Text file with one patient identifier per line")
    parser.add_argument("--url", default="http://localhost:8080/openmrs",
                        help="OpenMRS base URL")
    parser.add_argument("--user", default="admin", help="OpenMRS username")
    parser.add_argument("--password", default="Admin123", help="OpenMRS password")
    parser.add_argument("--dry-run", action="store_true",
                        help="Look up patients but do not delete them")
    parser.add_argument("--no-purge", action="store_true",
                        help="Void patients instead of purging (soft delete)")
    args = parser.parse_args()

    id_file = Path(args.id_file)
    if not id_file.exists():
        sys.exit(f"File not found: {id_file}")

    ids = load_ids(id_file)
    if not ids:
        sys.exit("No identifiers found in file.")

    purge = not args.no_purge
    action = "DRY-RUN" if args.dry_run else ("PURGE" if purge else "VOID")
    print(f"Loaded {len(ids)} identifiers from {id_file}  [{action}]")

    client = OpenMRSClient(args.url, args.user, args.password)

    deleted, not_found, failed = 0, 0, 0

    for i, identifier in enumerate(ids, start=1):
        prefix = f"[{i:03d}/{len(ids)}] {identifier}"
        try:
            patient = client.find_patient_by_identifier(identifier)
            if patient is None:
                print(f"  NOT FOUND  {prefix}")
                not_found += 1
                continue

            uuid = patient["uuid"]
            display = patient.get("display", uuid)

            if args.dry_run:
                print(f"  FOUND      {prefix}  →  {display}  (uuid={uuid})")
                continue

            client.delete_patient(uuid, purge=purge)
            print(f"  {action:<10} {prefix}  →  {display}")
            deleted += 1

        except ValueError as e:
            print(f"  ERROR      {prefix}: {e}", file=sys.stderr)
            failed += 1
        except requests.HTTPError as e:
            body = e.response.text if e.response is not None else str(e)
            print(f"  ERROR      {prefix}: {e} — {body[:200]}", file=sys.stderr)
            failed += 1

    print(f"\nDone. {'Found' if args.dry_run else action}: {deleted}, "
          f"Not found: {not_found}, Errors: {failed}")


if __name__ == "__main__":
    main()
