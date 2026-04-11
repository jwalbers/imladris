"""
clear_demo_orders.py — Void all pending radiology orders in OpenMRS.

Use before a demo to ensure the sidecar starts with a clean worklist.
Queries orders activated in the last N days, filters to radiology orders,
and voids each one via DELETE.

Usage
-----
    python tools/clear_demo_orders.py
    python tools/clear_demo_orders.py --days 3
    python tools/clear_demo_orders.py --dry-run

Environment (or edit defaults below)
--------------------------------------
    OPENMRS_URL       http://localhost:8080/openmrs
    OPENMRS_USER      admin
    OPENMRS_PASSWORD  Admin123
"""

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone

import requests

OPENMRS_URL      = os.getenv("OPENMRS_URL",      "http://localhost:8080/openmrs")
OPENMRS_USER     = os.getenv("OPENMRS_USER",     "admin")
OPENMRS_PASSWORD = os.getenv("OPENMRS_PASSWORD", "Admin123")

LOOKBACK_DAYS_DEFAULT = 7


def session() -> requests.Session:
    s = requests.Session()
    s.auth = (OPENMRS_USER, OPENMRS_PASSWORD)
    s.headers["Accept"] = "application/json"
    return s


def find_radiology_order_type_uuid(sess: requests.Session) -> str:
    r = sess.get(f"{OPENMRS_URL}/ws/rest/v1/ordertype", params={"v": "full"}, timeout=10)
    r.raise_for_status()
    for ot in r.json().get("results", []):
        if "radiology" in ot.get("name", "").lower():
            print(f"  Radiology order type: '{ot['name']}'  uuid={ot['uuid']}")
            return ot["uuid"]
    for ot in r.json().get("results", []):
        if "test" in ot.get("name", "").lower():
            print(f"  Falling back to order type: '{ot['name']}'  uuid={ot['uuid']}")
            return ot["uuid"]
    raise RuntimeError("Cannot find radiology or test order type in OpenMRS")


def fetch_recent_orders(sess: requests.Session, days: int) -> list[dict]:
    """Fetch all orders activated in the last N days (no orderType filter —
    PIH OpenMRS rejects orderType without a patient parameter)."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime(
        "%Y-%m-%dT%H:%M:%S.000%z"
    )
    orders = []
    start = 0
    while True:
        r = sess.get(
            f"{OPENMRS_URL}/ws/rest/v1/order",
            params={"v": "full", "limit": 100, "startIndex": start,
                    "activatedOnOrAfterDate": cutoff},
            timeout=15,
        )
        r.raise_for_status()
        batch = r.json().get("results", [])
        orders.extend(batch)
        if len(batch) < 100:
            break
        start += 100
    return orders


def void_order(sess: requests.Session, uuid: str, dry_run: bool) -> bool:
    if dry_run:
        return True
    r = sess.delete(
        f"{OPENMRS_URL}/ws/rest/v1/order/{uuid}",
        params={"reason": "Demo reset"},
        timeout=10,
    )
    return r.status_code in (200, 204)


def main():
    parser = argparse.ArgumentParser(description="Void pending radiology orders for demo reset.")
    parser.add_argument("--days",    type=int, default=LOOKBACK_DAYS_DEFAULT,
                        help=f"Look back N days (default: {LOOKBACK_DAYS_DEFAULT})")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would be voided without making changes")
    args = parser.parse_args()

    sess = session()

    print(f"Connecting to {OPENMRS_URL} ...")
    try:
        radiology_uuid = find_radiology_order_type_uuid(sess)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Fetching orders activated in the last {args.days} day(s) ...")
    try:
        all_orders = fetch_recent_orders(sess, args.days)
    except Exception as e:
        print(f"ERROR fetching orders: {e}", file=sys.stderr)
        sys.exit(1)

    radiology_orders = [
        o for o in all_orders
        if (o.get("orderType") or {}).get("uuid") == radiology_uuid
        and not o.get("dateStopped")
        and not o.get("voided")
    ]

    print(f"Found {len(all_orders)} total orders → {len(radiology_orders)} active radiology orders.")

    if not radiology_orders:
        print("Nothing to void.")
        return

    if args.dry_run:
        print("\n[DRY RUN] Would void:")

    voided = 0
    failed = 0
    for o in radiology_orders:
        uuid      = o.get("uuid", "")
        patient   = (o.get("patient") or {}).get("display", "?")
        concept   = (o.get("concept") or {}).get("display", "?")
        activated = o.get("dateActivated", "")[:16]
        label = f"  {activated}  {patient}  —  {concept}  [{uuid[:8]}]"

        if void_order(sess, uuid, args.dry_run):
            print(f"{'  [dry-run]' if args.dry_run else '  voided '}  {label}")
            voided += 1
        else:
            print(f"  FAILED   {label}")
            failed += 1

    action = "Would void" if args.dry_run else "Voided"
    print(f"\n{action} {voided} order(s).{' ' + str(failed) + ' failed.' if failed else ''}")


if __name__ == "__main__":
    main()
