#!/usr/bin/env python3
"""
seed_staff.py — Create fictional Botsabelo Hospital staff in OpenMRS.

Creates each staff member as:
  1. Person (name, gender, birthdate)
  2. User (username, password, roles)
  3. Provider (linked to person, provider role, identifier)

Usage:
    python tools/seed_staff.py [options]
    python tools/seed_staff.py --dry-run
    python tools/seed_staff.py --url http://localhost:8080/openmrs
"""

import argparse
import json
import sys

import requests
from requests.auth import HTTPBasicAuth

# ---------------------------------------------------------------------------
# Staff roster
# ---------------------------------------------------------------------------

STAFF = [
    {
        "given_name":   "Naledi",
        "family_name":  "Mokoena",
        "gender":       "F",
        "birthdate":    "1982-03-15",
        "username":     "dr.mokoena",
        "password":     "Botsabelo1!",
        "provider_id":  "BOT-CLIN-001",
        "description":  "Clinician — primary care physician, places radiology orders",
        "roles": [
            "Application Role: clinical",        # clinical access
            "Application Role: physician",        # physician apps
            "Authenticated",
            "Provider",                          # required for emr-api getProvidersByPerson()
        ],
        "provider_role": "Clinician",
    },
    {
        "given_name":   "Mpho",
        "family_name":  "Dlamini",
        "gender":       "M",
        "birthdate":    "1990-07-22",
        "username":     "mpho.dlamini",
        "password":     "Botsabelo1!",
        "provider_id":  "BOT-RADT-001",
        "description":  "Radiology Technician — operates modality, performs FASH ultrasound and CXR",
        "roles": [
            "Application Role: radiologyTechnician",
            "Authenticated",
            "Provider",
        ],
        "provider_role": "Radiology Technician",
    },
    {
        "given_name":   "Lerato",
        "family_name":  "Tau",
        "gender":       "F",
        "birthdate":    "1978-11-04",
        "username":     "dr.tau",
        "password":     "Botsabelo1!",
        "provider_id":  "BOT-RAD-001",
        "description":  "Radiologist — reads and reports on FASH ultrasound and CXR studies in OHIF",
        "roles": [
            "Application Role: radiology",
            "Application Role: physician",
            "Authenticated",
            "Provider",
        ],
        "provider_role": "Physician",   # closest match — no standalone Radiologist role
    },
    {
        "given_name":   "Thabiso",
        "family_name":  "Nkosi",
        "gender":       "M",
        "birthdate":    "1985-05-30",
        "username":     "thabiso.nkosi",
        "password":     "Botsabelo1!",
        "provider_id":  "BOT-ARCH-001",
        "description":  "Archivist / Registration clerk — registers patients, manages records",
        "roles": [
            "Application Role: archivistClerk",
            "Application Role: checkIn",
            "Authenticated",
            "Provider",
        ],
        "provider_role": "Archivist/Clerk",
    },
]

# ---------------------------------------------------------------------------
# OpenMRS REST client
# ---------------------------------------------------------------------------

class OpenMRSClient:
    def __init__(self, base_url: str, user: str, password: str):
        self.base = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.auth = HTTPBasicAuth(user, password)
        self.session.headers["Content-Type"] = "application/json"

    def get(self, path: str, **params):
        r = self.session.get(f"{self.base}{path}", params=params)
        r.raise_for_status()
        return r.json()

    def post(self, path: str, body: dict):
        r = self.session.post(f"{self.base}{path}", json=body)
        r.raise_for_status()
        return r.json()

    def role_uuid(self, display: str) -> str | None:
        data = self.get("/ws/rest/v1/role")
        for role in data.get("results", []):
            if role["display"].lower() == display.lower():
                return role["uuid"]
        return None

    def all_roles(self) -> dict[str, str]:
        """Return {display: uuid} for all roles."""
        data = self.get("/ws/rest/v1/role")
        return {r["display"]: r["uuid"] for r in data.get("results", [])}

    def all_provider_roles(self) -> dict[str, str]:
        data = self.get("/ws/rest/v1/providerrole", v="full")
        return {r["display"]: r["uuid"] for r in data.get("results", [])}

    def create_person(self, staff: dict) -> str:
        payload = {
            "names": [{"givenName": staff["given_name"], "familyName": staff["family_name"], "preferred": True}],
            "gender": staff["gender"],
            "birthdate": staff["birthdate"],
            "birthdateEstimated": False,
        }
        result = self.post("/ws/rest/v1/person", payload)
        return result["uuid"]

    def create_user(self, person_uuid: str, staff: dict, role_uuids: list[str]) -> str:
        payload = {
            "username": staff["username"],
            "password": staff["password"],
            "person": person_uuid,
            "roles": [{"uuid": u} for u in role_uuids],
            "userProperties": {"defaultLocale": "en"},
        }
        result = self.post("/ws/rest/v1/user", payload)
        return result["uuid"]

    def create_provider(self, person_uuid: str, staff: dict, provider_role_uuid: str | None) -> str:
        payload = {
            "person": person_uuid,
            "identifier": staff["provider_id"],
        }
        if provider_role_uuid:
            payload["providerRole"] = provider_role_uuid
        result = self.post("/ws/rest/v1/provider", payload)
        return result["uuid"]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Seed Botsabelo staff into OpenMRS")
    parser.add_argument("--url",      default="http://localhost:8080/openmrs")
    parser.add_argument("--user",     default="admin")
    parser.add_argument("--password", default="Admin123")
    parser.add_argument("--dry-run",  action="store_true",
                        help="Print payloads without creating anything")
    args = parser.parse_args()

    client = OpenMRSClient(args.url, args.user, args.password)

    print("Fetching roles and provider roles from OpenMRS…")
    all_roles = client.all_roles()
    all_prov_roles = client.all_provider_roles()
    print(f"  {len(all_roles)} roles,  {len(all_prov_roles)} provider roles")

    created, failed = 0, 0

    for staff in STAFF:
        label = f"{staff['given_name']} {staff['family_name']} (@{staff['username']})"
        print(f"\n── {label}")
        print(f"   Role: {staff['description']}")

        # Resolve role UUIDs
        role_uuids = []
        for role_name in staff["roles"]:
            uuid = all_roles.get(role_name)
            if uuid:
                role_uuids.append(uuid)
            else:
                print(f"   WARNING: role not found: {role_name!r} — skipping it")

        # Resolve provider role UUID
        prov_role_uuid = all_prov_roles.get(staff["provider_role"])
        if not prov_role_uuid:
            print(f"   WARNING: provider role not found: {staff['provider_role']!r} — provider created without role")

        if args.dry_run:
            print(f"   DRY-RUN: would create person + user + provider")
            print(f"   roles: {[r for r in staff['roles'] if all_roles.get(r)]}")
            print(f"   provider_role: {staff['provider_role']} ({prov_role_uuid})")
            continue

        try:
            person_uuid = client.create_person(staff)
            print(f"   Person  ✓  {person_uuid}")

            user_uuid = client.create_user(person_uuid, staff, role_uuids)
            print(f"   User    ✓  {user_uuid}  (username: {staff['username']})")

            prov_uuid = client.create_provider(person_uuid, staff, prov_role_uuid)
            print(f"   Provider ✓  {prov_uuid}  (id: {staff['provider_id']})")

            created += 1

        except requests.HTTPError as e:
            body = e.response.text if e.response is not None else str(e)
            print(f"   FAIL: {e} — {body[:300]}", file=sys.stderr)
            failed += 1

    if not args.dry_run:
        print(f"\nDone. Created: {created}, Failed: {failed}")
    else:
        print(f"\nDry run complete — {len(STAFF)} staff members defined.")
        print("\nCredentials summary:")
        print(f"  {'Username':<20} {'Password':<15} {'Role'}")
        print(f"  {'-'*20} {'-'*15} {'-'*30}")
        for s in STAFF:
            print(f"  {s['username']:<20} {s['password']:<15} {s['description'].split('—')[0].strip()}")


if __name__ == "__main__":
    main()
