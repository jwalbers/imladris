"""
clear_demo_orders.py — Purge all radiology orders for demo reset.

Two-phase approach:
  1. REST API: void any active/non-voided radiology orders (soft delete)
  2. MySQL:    hard-purge ALL radiology orders (voided or not) so they
               disappear completely from the patient order list

The OpenMRS REST endpoint does not return voided records, so MySQL is
required for the full purge.

Usage
-----
    python tools/clear_demo_orders.py
    python tools/clear_demo_orders.py --days 3
    python tools/clear_demo_orders.py --dry-run
    python tools/clear_demo_orders.py --patient 7RHG9J   # one patient only

Environment (or edit defaults below)
--------------------------------------
    OPENMRS_URL        http://localhost:8080/openmrs
    OPENMRS_USER       admin
    OPENMRS_PASSWORD   Admin123
    MYSQL_CONTAINER    imladris-mysql
    MYSQL_DB           openmrs_imladris01
"""

import argparse
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import requests

OPENMRS_URL      = os.getenv("OPENMRS_URL",      "http://localhost:8080/openmrs")
OPENMRS_USER     = os.getenv("OPENMRS_USER",     "admin")
OPENMRS_PASSWORD = os.getenv("OPENMRS_PASSWORD", "Admin123")

MYSQL_CONTAINER  = os.getenv("MYSQL_CONTAINER",  "imladris-mysql")
MYSQL_USER       = "openmrs"
MYSQL_PASSWORD   = "openmrs"
MYSQL_DB         = os.getenv("MYSQL_DB",         "openmrs_imladris01")

LOOKBACK_DAYS_DEFAULT = 7


# ── REST helpers ──────────────────────────────────────────────────────

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


def fetch_active_orders(sess: requests.Session, days: int) -> list[dict]:
    """Fetch non-voided orders activated in the last N days via REST."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime(
        "%Y-%m-%dT%H:%M:%S.000%z"
    )
    orders, start = [], 0
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


def purge_order(sess: requests.Session, uuid: str, dry_run: bool) -> bool:
    """Hard-purge an order via REST (goes through service layer, clears Hibernate cache)."""
    if dry_run:
        return True
    r = sess.delete(
        f"{OPENMRS_URL}/ws/rest/v1/order/{uuid}",
        params={"purge": "true"},
        timeout=10,
    )
    return r.status_code in (200, 204)


# ── MySQL helpers ─────────────────────────────────────────────────────

def mysql(sql: str) -> str:
    result = subprocess.run(
        ["docker", "exec", MYSQL_CONTAINER,
         "mysql", f"-u{MYSQL_USER}", f"-p{MYSQL_PASSWORD}",
         "--batch", "--skip-column-names", MYSQL_DB, "-e", sql],
        capture_output=True, text=True,
    )
    # MySQL emits a password-on-CLI warning to stderr even on success
    stderr = result.stderr.strip()
    real_errors = [l for l in stderr.splitlines() if "warning" not in l.lower()]
    if result.returncode != 0 or real_errors:
        raise RuntimeError("\n".join(real_errors) or stderr)
    return result.stdout.strip()


def fetch_voided_uuids_from_mysql(days: int, patient_id: str | None) -> list[str]:
    """Return UUIDs of voided radiology orders — invisible to REST but purgeable via REST."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    patient_filter = ""
    if patient_id:
        patient_filter = f"""
          AND o.patient_id = (
            SELECT patient_id FROM patient_identifier
            WHERE identifier = '{patient_id}' LIMIT 1
          )"""
    rows = mysql(f"""
        SELECT o.uuid FROM orders o
        JOIN order_type ot ON o.order_type_id = ot.order_type_id
        WHERE o.voided = 1
          AND (ot.name LIKE '%radiology%' OR ot.name LIKE '%Radiology%'
               OR ot.name LIKE '%test%'   OR ot.name LIKE '%Test%')
          AND o.date_activated >= '{cutoff}'
          {patient_filter};
    """)
    return [r.strip() for r in rows.splitlines() if r.strip()]


def mysql_fallback_purge(days: int, patient_id: str | None) -> int:
    """Last-resort MySQL hard-delete for any rows REST purge couldn't reach."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    patient_filter = ""
    if patient_id:
        patient_filter = f"""
          AND o.patient_id = (
            SELECT patient_id FROM patient_identifier
            WHERE identifier = '{patient_id}' LIMIT 1
          )"""

    count = mysql(f"""
        SELECT COUNT(*) FROM orders o
        JOIN order_type ot ON o.order_type_id = ot.order_type_id
        WHERE (ot.name LIKE '%radiology%' OR ot.name LIKE '%Radiology%'
               OR ot.name LIKE '%test%' OR ot.name LIKE '%Test%')
          AND o.date_activated >= '{cutoff}'
          {patient_filter};
    """).strip()

    if count == "0":
        return 0

    print(f"  MySQL fallback: removing {count} remaining row(s) ...")
    mysql(f"""
        DELETE r FROM emr_radiology_order r
        JOIN test_order t ON r.order_id = t.order_id
        JOIN orders o ON t.order_id = o.order_id
        JOIN order_type ot ON o.order_type_id = ot.order_type_id
        WHERE (ot.name LIKE '%radiology%' OR ot.name LIKE '%Radiology%'
               OR ot.name LIKE '%test%' OR ot.name LIKE '%Test%')
          AND o.date_activated >= '{cutoff}'
          {patient_filter};
    """)
    mysql(f"""
        DELETE t FROM test_order t
        JOIN orders o ON t.order_id = o.order_id
        JOIN order_type ot ON o.order_type_id = ot.order_type_id
        WHERE (ot.name LIKE '%radiology%' OR ot.name LIKE '%Radiology%'
               OR ot.name LIKE '%test%' OR ot.name LIKE '%Test%')
          AND o.date_activated >= '{cutoff}'
          {patient_filter};
    """)
    mysql(f"""
        DELETE o FROM orders o
        JOIN order_type ot ON o.order_type_id = ot.order_type_id
        WHERE (ot.name LIKE '%radiology%' OR ot.name LIKE '%Radiology%'
               OR ot.name LIKE '%test%' OR ot.name LIKE '%Test%')
          AND o.date_activated >= '{cutoff}'
          {patient_filter};
    """)
    return int(count)


# ── Main ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Purge radiology orders from OpenMRS for demo reset."
    )
    parser.add_argument("--days",    type=int, default=LOOKBACK_DAYS_DEFAULT,
                        help=f"Look back N days (default: {LOOKBACK_DAYS_DEFAULT})")
    parser.add_argument("--patient", type=str, default=None,
                        help="Limit to one patient by OpenMRS ID (e.g. 7RHG9J)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be deleted without making changes")
    args = parser.parse_args()

    sess = session()

    print(f"Connecting to {OPENMRS_URL} ...")
    try:
        radiology_uuid = find_radiology_order_type_uuid(sess)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    # ── Phase 1: purge active orders via REST (?purge=true) ──────────
    print(f"\nPhase 1 — purge active orders via REST (last {args.days} day(s)) ...")
    try:
        all_orders = fetch_active_orders(sess, args.days)
    except Exception as e:
        print(f"  ERROR fetching orders: {e}", file=sys.stderr)
        sys.exit(1)

    active_orders = [
        o for o in all_orders
        if (o.get("orderType") or {}).get("uuid") == radiology_uuid
        and not o.get("voided")
        and (not args.patient or
             args.patient.upper() in (o.get("patient") or {}).get("display", "").upper())
    ]

    print(f"  Found {len(active_orders)} active radiology order(s).")
    purged_rest = failed = 0
    for o in active_orders:
        uuid      = o.get("uuid", "")
        patient   = (o.get("patient") or {}).get("display", "?")
        concept   = (o.get("concept") or {}).get("display", "?")
        activated = o.get("dateActivated", "")[:16]
        label = f"{activated}  {patient}  —  {concept}  [{uuid[:8]}]"
        if purge_order(sess, uuid, args.dry_run):
            print(f"  {'[dry-run]' if args.dry_run else 'purged  '}  {label}")
            purged_rest += 1
        else:
            print(f"  FAILED    {label}")
            failed += 1

    # ── Phase 2: purge voided orders via REST (UUID from MySQL) ──────
    print(f"\nPhase 2 — purge previously-voided orders via REST ...")
    try:
        voided_uuids = fetch_voided_uuids_from_mysql(args.days, args.patient)
    except RuntimeError as e:
        print(f"  ERROR querying MySQL: {e}", file=sys.stderr)
        voided_uuids = []

    print(f"  Found {len(voided_uuids)} voided order(s) to purge.")
    purged_voided = 0
    for uuid in voided_uuids:
        if purge_order(sess, uuid, args.dry_run):
            print(f"  {'[dry-run]' if args.dry_run else 'purged  '}  [{uuid[:8]}]")
            purged_voided += 1
        else:
            print(f"  FAILED (REST)  [{uuid[:8]}] — will fall back to MySQL")

    # ── Phase 3: MySQL fallback for anything REST couldn't reach ─────
    print(f"\nPhase 3 — MySQL fallback for any remaining rows ...")
    try:
        mysql_count = 0 if args.dry_run else mysql_fallback_purge(args.days, args.patient)
        if mysql_count == 0:
            print("  Nothing remaining — cache-safe purge complete.")
    except RuntimeError as e:
        print(f"  ERROR: {e}", file=sys.stderr)
        print("  Orders may still appear in OpenMRS UI until server restart.")

    # ── Summary ───────────────────────────────────────────────────────
    action = "Would purge" if args.dry_run else "Purged"
    total = purged_rest + purged_voided
    print(f"\n{action} {total} order(s) via REST ({purged_rest} active + {purged_voided} voided).")
    if failed:
        print(f"  {failed} REST purge(s) failed — check logs.")


if __name__ == "__main__":
    main()
