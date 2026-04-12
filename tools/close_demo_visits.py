"""
close_demo_visits.py — Close all open patient visits in OpenMRS.

The PIH EMR ZL configuration does not expose an "End Visit" button in the
UI, so this script closes open visits via the REST API.

Usage
-----
    python tools/close_demo_visits.py
    python tools/close_demo_visits.py --patient 7RHG9J   # one patient only
    python tools/close_demo_visits.py --dry-run

Environment (or edit defaults below)
--------------------------------------
    OPENMRS_URL       http://localhost:8080/openmrs
    OPENMRS_USER      admin
    OPENMRS_PASSWORD  Admin123
"""

import argparse
import os
import sys
from datetime import datetime, timezone

import requests

OPENMRS_URL      = os.getenv("OPENMRS_URL",      "http://localhost:8080/openmrs")
OPENMRS_USER     = os.getenv("OPENMRS_USER",     "admin")
OPENMRS_PASSWORD = os.getenv("OPENMRS_PASSWORD", "Admin123")


def session() -> requests.Session:
    s = requests.Session()
    s.auth = (OPENMRS_USER, OPENMRS_PASSWORD)
    s.headers["Accept"] = "application/json"
    s.headers["Content-Type"] = "application/json"
    return s


def fetch_open_visits(sess: requests.Session, patient_id: str | None) -> list[dict]:
    """Fetch all open (no stopDatetime) visits, optionally filtered to one patient."""
    params = {"includeInactive": "false", "v": "default", "limit": 100}
    if patient_id:
        # Resolve patient UUID from identifier first
        r = sess.get(
            f"{OPENMRS_URL}/ws/rest/v1/patient",
            params={"identifier": patient_id, "v": "default"},
            timeout=10,
        )
        r.raise_for_status()
        results = r.json().get("results", [])
        if not results:
            print(f"  No patient found with ID '{patient_id}'", file=sys.stderr)
            return []
        patient_uuid = results[0]["uuid"]
        params["patient"] = patient_uuid

    visits, start = [], 0
    while True:
        params["startIndex"] = start
        r = sess.get(f"{OPENMRS_URL}/ws/rest/v1/visit", params=params, timeout=10)
        r.raise_for_status()
        batch = r.json().get("results", [])
        visits.extend(batch)
        if len(batch) < 100:
            break
        start += 100
    # Belt-and-suspenders: API sometimes returns closed visits despite includeInactive=false
    return [v for v in visits if not v.get("stopDatetime")]


def close_visit(sess: requests.Session, uuid: str, stop_time: str, dry_run: bool) -> bool:
    if dry_run:
        return True
    r = sess.post(
        f"{OPENMRS_URL}/ws/rest/v1/visit/{uuid}",
        json={"stopDatetime": stop_time},
        timeout=10,
    )
    return r.status_code in (200, 201)


def main():
    parser = argparse.ArgumentParser(description="Close all open OpenMRS visits for demo reset.")
    parser.add_argument("--patient", type=str, default=None,
                        help="Limit to one patient by OpenMRS ID (e.g. 7RHG9J)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be closed without making changes")
    args = parser.parse_args()

    sess = session()
    stop_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000")

    scope = f"patient {args.patient}" if args.patient else "all patients"
    print(f"Fetching open visits for {scope} ...")

    try:
        visits = fetch_open_visits(sess, args.patient)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    if not visits:
        print("No open visits found.")
        return

    print(f"Found {len(visits)} open visit(s).")
    if args.dry_run:
        print("[DRY RUN] Would close:")

    closed = failed = 0
    for v in visits:
        uuid    = v.get("uuid", "")
        patient = (v.get("patient") or {}).get("display", "?")
        vtype   = (v.get("visitType") or {}).get("display", "?")
        started = (v.get("startDatetime") or "")[:16]
        label   = f"{started}  {patient}  —  {vtype}  [{uuid[:8]}]"

        if close_visit(sess, uuid, stop_time, args.dry_run):
            print(f"  {'[dry-run]' if args.dry_run else 'closed  '}  {label}")
            closed += 1
        else:
            print(f"  FAILED    {label}")
            failed += 1

    action = "Would close" if args.dry_run else "Closed"
    print(f"\n{action} {closed} visit(s).{' ' + str(failed) + ' failed.' if failed else ''}")


if __name__ == "__main__":
    main()
