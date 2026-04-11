"""
clear_hl7_queue.py — Clear all pending HL7 messages from the OpenMRS queue.

The OpenMRS HL7 REST endpoint is write-only (no list/delete support), so
this script connects directly to MySQL via the imladris-mysql container.

Usage
-----
    python tools/clear_hl7_queue.py
    python tools/clear_hl7_queue.py --dry-run

Environment (or edit defaults below)
--------------------------------------
    MYSQL_CONTAINER   imladris-mysql
    MYSQL_USER        openmrs
    MYSQL_PASSWORD    openmrs
    MYSQL_DATABASE    openmrs
"""

import argparse
import subprocess
import sys

MYSQL_CONTAINER = "imladris-mysql"
MYSQL_USER      = "openmrs"
MYSQL_PASSWORD  = "openmrs"
MYSQL_DATABASE  = "openmrs_imladris01"


def mysql(sql: str) -> str:
    result = subprocess.run(
        [
            "docker", "exec", MYSQL_CONTAINER,
            "mysql",
            f"-u{MYSQL_USER}",
            f"-p{MYSQL_PASSWORD}",
            "--batch", "--skip-column-names",
            MYSQL_DATABASE,
            "-e", sql,
        ],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip())
    return result.stdout.strip()


def main():
    parser = argparse.ArgumentParser(description="Clear the OpenMRS HL7 inbound queue.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be deleted without making changes")
    args = parser.parse_args()

    # Show current queue state
    try:
        rows = mysql(
            "SELECT message_state, COUNT(*) FROM hl7_in_queue GROUP BY message_state;"
        )
    except RuntimeError as e:
        print(f"ERROR connecting to MySQL: {e}", file=sys.stderr)
        sys.exit(1)

    if rows:
        print("Current HL7 queue:")
        for line in rows.splitlines():
            state, count = line.split("\t")
            state_label = {
                "0": "PENDING",
                "1": "PROCESSING",
                "2": "PROCESSED",
                "3": "ERROR",
            }.get(state, state)
            print(f"  {state_label:<12} {count}")
    else:
        print("HL7 queue is already empty.")
        return

    total = mysql("SELECT COUNT(*) FROM hl7_in_queue;")
    print(f"\n{'[DRY RUN] Would delete' if args.dry_run else 'Deleting'} {total} message(s) ...")

    if not args.dry_run:
        mysql("DELETE FROM hl7_in_queue;")
        remaining = mysql("SELECT COUNT(*) FROM hl7_in_queue;")
        print(f"Done. {remaining} message(s) remaining.")


if __name__ == "__main__":
    main()
