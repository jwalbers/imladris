#!/usr/bin/env python3
"""
seed_patients.py — Load botsabelo_census_v2.csv into OpenMRS via REST API.

Generates ZL EMR ID identifiers for each patient (6 alphanumeric chars,
base-30 alphabet omitting B I O Q S Z, last char is LuhnMod30 check digit),
ignoring the source Patient_ID column.

Usage:
    python tools/seed_patients.py [options]

    python tools/seed_patients.py --dry-run
    python tools/seed_patients.py --id-type "ZL EMR ID" --location "Botsabelo"
"""

import argparse
import csv
import json
import random
import re
import sys
from datetime import date
from pathlib import Path

import requests
from requests.auth import HTTPBasicAuth

# ---------------------------------------------------------------------------
# LuhnMod30
# ---------------------------------------------------------------------------

# OpenMRS / PIH standard LuhnMod30 character table (30 chars, no B I O Q S Z)
_LUHN_CHARS = "0123456789ACDEFGHJKLMNPRTUVWXY"
_LUHN_MAP = {ch: i for i, ch in enumerate(_LUHN_CHARS)}


def _luhn_check_char(base: str) -> str:
    """Return the LuhnMod30 check character for *base* (uppercase, no dashes)."""
    total = 0
    double_next = True   # rightmost base char is doubled (OpenMRS convention)
    for ch in reversed(base.upper()):
        val = _LUHN_MAP[ch]
        if double_next:
            val *= 2
            if val >= 30:
                val -= 29
        total += val
        double_next = not double_next
    check_index = (30 - (total % 30)) % 30
    return _LUHN_CHARS[check_index]


def generate_zl_id() -> str:
    """Generate a ZL EMR ID: 5 random Luhn30 chars + 1 LuhnMod30 check char.

    Format: XXXXXC  (6 alphanumeric chars, base-30 alphabet, no B I O Q S Z)
    The check character is computed over the first 5 characters.
    30^5 = 24,300,000 possible base identifiers.
    """
    base = "".join(random.choices(_LUHN_CHARS, k=5))
    check = _luhn_check_char(base)
    return base + check


def validate_zl_id(identifier: str) -> bool:
    """Return True if the identifier passes ZL EMR ID format + LuhnMod30 validation."""
    if not re.match(r"^[A-Z0-9]{6}$", identifier.upper()):
        return False
    identifier = identifier.upper()
    # Reject chars outside Luhn30 alphabet (B I O Q S Z)
    if any(ch not in _LUHN_MAP for ch in identifier):
        return False
    return _luhn_check_char(identifier[:5]) == identifier[5]


# ---------------------------------------------------------------------------
# OpenMRS REST helpers
# ---------------------------------------------------------------------------

class OpenMRSClient:
    def __init__(self, base_url: str, user: str, password: str):
        self.base = base_url.rstrip("/")
        self.auth = HTTPBasicAuth(user, password)
        self.session = requests.Session()
        self.session.auth = self.auth
        self.session.headers["Content-Type"] = "application/json"

    def get(self, path: str, **params):
        r = self.session.get(f"{self.base}{path}", params=params)
        r.raise_for_status()
        return r.json()

    def post(self, path: str, body: dict):
        r = self.session.post(f"{self.base}{path}", data=json.dumps(body))
        r.raise_for_status()
        return r.json()

    # -- Discovery -----------------------------------------------------------

    def list_identifier_types(self) -> list[dict]:
        data = self.get("/ws/rest/v1/patientidentifiertype")
        return data.get("results", [])

    def find_identifier_type(self, name_hint: str) -> dict | None:
        """Find identifier type whose name contains *name_hint* (case-insensitive)."""
        hint = name_hint.lower()
        for t in self.list_identifier_types():
            if hint in t["display"].lower():
                return t
        return None

    def list_locations(self) -> list[dict]:
        data = self.get("/ws/rest/v1/location", tag="Login Location")
        results = data.get("results", [])
        if not results:
            data = self.get("/ws/rest/v1/location")
            results = data.get("results", [])
        return results

    def find_location(self, name_hint: str) -> dict | None:
        hint = name_hint.lower()
        for loc in self.list_locations():
            if hint in loc["display"].lower():
                return loc
        return None

    # -- Patient creation ----------------------------------------------------

    def create_patient(self, payload: dict) -> dict:
        return self.post("/ws/rest/v1/patient", payload)


# ---------------------------------------------------------------------------
# CSV parsing
# ---------------------------------------------------------------------------

def parse_name(full_name: str) -> tuple[str, str]:
    """Split 'Given Family' → (givenName, familyName). Last word = family."""
    parts = full_name.strip().split()
    if len(parts) == 1:
        return parts[0], "Unknown"
    return " ".join(parts[:-1]), parts[-1]


def estimate_birthdate(age: int) -> str:
    """Return ISO birthdate as Jan 1, (current_year - age)."""
    year = date.today().year - age
    return f"{year}-01-01"


def gender_char(raw: str) -> str:
    g = raw.strip().upper()
    if g in ("M", "MALE"):
        return "M"
    if g in ("F", "FEMALE"):
        return "F"
    return "U"


def load_csv(csv_path: Path) -> list[dict]:
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return list(reader)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def build_patient_payload(
    row: dict,
    identifier: str,
    id_type_uuid: str,
    location_uuid: str,
) -> dict:
    given, family = parse_name(row["Name"])
    gender = gender_char(row["Gender"])
    birthdate = estimate_birthdate(int(row["Age"]))
    district = row.get("District", "").strip()

    payload: dict = {
        "person": {
            "names": [
                {
                    "givenName": given,
                    "familyName": family,
                    "preferred": True,
                }
            ],
            "gender": gender,
            "birthdate": birthdate,
            "birthdateEstimated": True,
        },
        "identifiers": [
            {
                "identifier": identifier,
                "identifierType": id_type_uuid,
                "location": location_uuid,
                "preferred": True,
            }
        ],
    }

    if district:
        payload["person"]["addresses"] = [
            {"countyDistrict": district, "country": "Lesotho", "preferred": True}
        ]

    return payload


def pick_or_prompt(items: list[dict], label: str, name_hint: str | None) -> dict:
    """Return a single item from *items*, filtering by *name_hint* or prompting."""
    if name_hint:
        hint = name_hint.lower()
        filtered = [x for x in items if hint in x["display"].lower()]
        if len(filtered) == 1:
            return filtered[0]
        if len(filtered) > 1:
            items = filtered  # narrow the list before prompting

    if len(items) == 1:
        return items[0]

    print(f"\n{len(items)} Available {label}s:")
    for i, item in enumerate(items):
        print(f"  [{i}] {item['display']}  ({item['uuid']})")
    while True:
        try:
            choice = int(input(f"Select {label} (0-{len(items)-1}): "))
            return items[choice]
        except (ValueError, IndexError):
            print("  Invalid choice, try again.")


def main():
    parser = argparse.ArgumentParser(description="Seed OpenMRS patients from CSV")
    parser.add_argument("--url", default="http://localhost:8080/openmrs",
                        help="OpenMRS base URL")
    parser.add_argument("--user", default="admin", help="OpenMRS username")
    parser.add_argument("--password", default="Admin123", help="OpenMRS password")
    parser.add_argument("--csv", default="botsabelo_census_v2.csv",
                        help="Path to census CSV file")
    parser.add_argument("--id-type", default=None,
                        help="Identifier type name hint (auto-discovered if omitted)")
    parser.add_argument("--location", default=None,
                        help="Location name hint (auto-discovered if omitted)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print payloads without creating patients")
    parser.add_argument("--map-ids", action="store_true",
                        help="Print a CSV map of original CSV ids to generated ids")
    args = parser.parse_args()

    id_map = {}
    csv_path = Path(args.csv)
    if not csv_path.exists():
        sys.exit(f"CSV not found: {csv_path}")

    rows = load_csv(csv_path)
    print(f"Loaded {len(rows)} rows from {csv_path}")

    client = OpenMRSClient(args.url, args.user, args.password)

    # -- Resolve identifier type -------------------------------------------
    id_types = client.list_identifier_types()
    if not id_types:
        sys.exit("No patient identifier types found in OpenMRS. Is it running?")

    id_type = pick_or_prompt(id_types, "identifier type", args.id_type)
    print(f"Using identifier type: {id_type['display']}  ({id_type['uuid']})")

    # -- Resolve location ---------------------------------------------------
    locations = client.list_locations()
    if not locations:
        sys.exit("No locations found in OpenMRS.")

    location = pick_or_prompt(locations, "location", args.location)
    print(f"Using location:        {location['display']}  ({location['uuid']})")

    # -- Generate identifiers (collision-safe within this run) --------------
    used_ids: set[str] = set()

    def fresh_zl_id() -> str:
        for _ in range(1000):
            candidate = generate_zl_id()
            if candidate not in used_ids:
                used_ids.add(candidate)
                return candidate
        raise RuntimeError("Could not generate a unique ZL EMR ID after 1000 tries")

    # -- Create patients ----------------------------------------------------
    created, failed = 0, 0
    dry_run_path = Path("seed_dry_run.json")

    with (open(dry_run_path, "w") if args.dry_run else open("/dev/null", "w")) as dry_run_outf:
        for i, row in enumerate(rows, start=1):
            identifier = fresh_zl_id()
            payload = build_patient_payload(
                row,
                identifier=identifier,
                id_type_uuid=id_type["uuid"],
                location_uuid=location["uuid"],
            )

            id_map[row["Patient_ID"]] = identifier
            label = f"[{i:02d}/{len(rows)}] {row['Name']} → {identifier}"

            if args.dry_run:
                dry_run_outf.write(f"DRY-RUN {label}\n")
                dry_run_outf.write(f"         payload: {json.dumps(payload, indent=2)}\n")
                continue

            for attempt in range(5):
                try:
                    result = client.create_patient(payload)
                    uuid = result.get("uuid", "?")
                    print(f"  OK  {label}  (uuid={uuid})")
                    created += 1
                    break
                except requests.HTTPError as e:
                    body = e.response.text if e.response is not None else str(e)
                    is_dupe = e.response is not None and e.response.status_code in (400, 409) \
                              and "identifier" in body.lower()
                    if is_dupe and attempt < 4:
                        identifier = fresh_zl_id()
                        payload["identifiers"][0]["identifier"] = identifier
                        label = f"[{i:02d}/{len(rows)}] {row['Name']} → {identifier}"
                        print(f"  DUP retry {attempt+1}: {label}", file=sys.stderr)
                    else:
                        print(f"  FAIL {label}: {e} — {body[:200]}", file=sys.stderr)
                        failed += 1
                        break

    if args.dry_run:
        print(f"Dry-run output written to {dry_run_path}")
    else:
        print(f"\nDone. Created: {created}, Failed: {failed}")

    if args.map_ids:
        for k, v in sorted(id_map.items()):
            print(f"{k},{v}")


if __name__ == "__main__":
    main()
