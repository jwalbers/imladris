#!/usr/bin/env python3
"""
POST a FHIR ServiceRequest to AdvaPACS — demonstrates the correct payload shape.

AdvaPACS uses FHIR R5 with two non-obvious requirements vs. a standard OpenMRS
ServiceRequest:

  1. orderDetail modality  — must use the AdvaPACS-specific coding system and
                             carry the modality code in "valueString", NOT in the
                             DICOM ontology coding:

       ✗ OpenMRS emits:
           "parameter": [{"code": {"coding": [
               {"system": "http://dicom.nema.org/resources/ontology/DCM", "code": "CR"}
           ]}}]

       ✓ AdvaPACS requires:
           "parameter": [{"code": {"coding": [
               {"system": "http://advapacs.com/fhir/servicerequest-orderdetail-parameter-code",
                "code":  "modality"}
           ]}, "valueString": "CR"}]

  2. code field shape  — FHIR R5 uses CodeableReference; the CodeableConcept must
                         be wrapped in a "concept" key:

       ✗ FHIR R4 / OpenMRS:
           "code": {"coding": [...], "text": "..."}

       ✓ FHIR R5 / AdvaPACS:
           "code": {"concept": {"coding": [...], "text": "..."}}

Usage:
  python tools/test_fhir_service_request.py             # POST corrected payload
  python tools/test_fhir_service_request.py --compare   # POST both (corrected + raw)

Credentials: set ADVAPACS_KEY_ID / ADVAPACS_SECRET in environment,
             or place in docker/ap-qs/.env.

Requires: pip install httpx python-dotenv
"""

import argparse
import json
import os
import sys
from pathlib import Path

try:
    import httpx
except ImportError:
    sys.exit("pip install httpx")

# ── Credentials ───────────────────────────────────────────────────────────────

_env_file = Path(__file__).parent.parent / "docker" / "ap-qs" / ".env"
if _env_file.exists():
    try:
        from dotenv import dotenv_values
        for k, v in dotenv_values(_env_file).items():
            os.environ.setdefault(k, v or "")
    except ImportError:
        for line in _env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

KEY_ID = os.getenv("ADVAPACS_KEY_ID", "")
SECRET = os.getenv("ADVAPACS_SECRET", "")
BASE   = "https://usa1.api.integration.advapacs.com/fhir/R5"

if not KEY_ID or not SECRET:
    sys.exit("ADVAPACS_KEY_ID / ADVAPACS_SECRET not set (check docker/ap-qs/.env)")


def _headers() -> dict:
    return {
        "Authorization": f"ID={KEY_ID},Secret={SECRET}",
        "Content-Type":  "application/fhir+json",
        "Accept":        "application/fhir+json",
    }


# ── Payload A: CORRECTED — what AdvaPACS actually accepts ─────────────────────
#
# Changes from raw OpenMRS output:
#   [1] orderDetail: AdvaPACS-specific coding system; modality value in valueString
#   [2] code: FHIR R5 CodeableReference shape — CodeableConcept wrapped in "concept"

CORRECTED_SR = {
    "resourceType": "ServiceRequest",
    "identifier": [
        {
            "use": "usual",
            "type": {
                "coding": [{
                    "system":  "http://terminology.hl7.org/CodeSystem/v2-0203",
                    "code":    "PLAC",
                    "display": "Placer Identifier",
                }]
            },
            "value":  "ORD-1004",
            "system": "http://www.pih.org/identifiers/lesotho/radiology-order-number",
        },
        {
            "system": "http://www.pih.org/identifiers/lesotho/radiology-accession-number",
            "value":  "ORD-1004",
            "type": {
                "coding": [{
                    "system": "http://terminology.hl7.org/CodeSystem/v2-0203",
                    "code":   "ACSN",
                }]
            },
        },
    ],
    "status": "draft",
    "intent": "order",

    # [2] FHIR R5 CodeableReference — wrap CodeableConcept in "concept"
    "code": {
        "concept": {
            "coding": [
                {"system": "http://loinc.org",       "code": "36554-4"},
                {"system": "http://snomed.info/sct", "code": "399208008"},
            ],
            "text": "Chest, 1 view (X-ray)",
        }
    },

    "subject": {
        "reference": "Patient/e0f26dd1-1850-4a32-b994-735ac97d50ab",
        "display":   "Bobby Dylan",
    },
    "occurrenceDateTime": "2026-08-17T14:11:09-04:00",

    # [1] AdvaPACS modality: proprietary coding system; modality code in valueString
    "orderDetail": [{
        "parameter": [{
            "code": {
                "coding": [{
                    "system": "http://advapacs.com/fhir/servicerequest-orderdetail-parameter-code",
                    "code":   "modality",
                }]
            },
            "valueString": "CR",
        }]
    }],
}


# ── Payload B: RAW OpenMRS output — fails with "Missing required modality" ────
#
# Errors:
#   [1] orderDetail uses the DICOM ontology coding system; AdvaPACS does not
#       recognise it → OperationOutcome: "Missing required modality from orderDetail"
#   [2] code uses FHIR R4 CodeableConcept directly; R5 expects {"concept": {...}}

RAW_SR = {
    "resourceType": "ServiceRequest",
    "identifier": [
        {
            "use": "usual",
            "type": {
                "coding": [{
                    "system":  "http://terminology.hl7.org/CodeSystem/v2-0203",
                    "code":    "PLAC",
                    "display": "Placer Identifier",
                }]
            },
            "value":  "ORD-1003",
            "system": "http://www.pih.org/identifiers/lesotho/radiology-order-number",
        },
        {
            "system": "http://www.pih.org/identifiers/lesotho/radiology-accession-number",
            "value":  "ORD-1003",
            "type": {
                "coding": [{
                    "system": "http://terminology.hl7.org/CodeSystem/v2-0203",
                    "code":   "ACSN",
                }]
            },
        },
    ],
    "status": "draft",
    "intent": "order",

    # [2] FHIR R4 CodeableConcept — missing "concept" wrapper required by R5
    "code": {
        "coding": [
            {"system": "http://loinc.org",       "code": "36554-4"},
            {"system": "http://snomed.info/sct", "code": "399208008"},
        ],
        "text": "Chest, 1 view (X-ray)",
    },

    "subject": {
        "reference": "Patient/e0f26dd1-1850-4a32-b994-735ac97d50ab",
        "display":   "Bobby Dylan",
    },
    "occurrenceDateTime": "2026-08-17T14:11:09-04:00",

    # [1] DICOM ontology system — AdvaPACS does not recognise this as a modality
    "orderDetail": [{
        "parameter": [{
            "code": {
                "coding": [{
                    "system": "http://dicom.nema.org/resources/ontology/DCM",
                    "code":   "CR",
                }]
            }
        }]
    }],
}


# ── HTTP helper ───────────────────────────────────────────────────────────────

def post_sr(label: str, payload: dict) -> None:
    print(f"\n{'='*70}")
    print(f"  {label}")
    print(f"  POST {BASE}/ServiceRequest")
    print(f"{'='*70}")
    print("Request body:")
    print(json.dumps(payload, indent=2))
    print()

    try:
        r = httpx.post(
            f"{BASE}/ServiceRequest",
            json=payload,
            headers=_headers(),
            timeout=20,
        )
        print(f"HTTP {r.status_code}  {r.reason_phrase}")
        for k in ("content-type", "location", "x-request-id", "www-authenticate"):
            if k in r.headers:
                print(f"  {k}: {r.headers[k]}")
        print("Response body:")
        try:
            print(json.dumps(r.json(), indent=2))
        except Exception:
            print(r.text[:2000])
    except Exception as exc:
        print(f"Request error: {exc}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--compare", action="store_true",
                    help="Also POST the raw OpenMRS payload to show the failure")
    args = ap.parse_args()

    post_sr("CORRECTED ServiceRequest (AdvaPACS R5)", CORRECTED_SR)

    if args.compare:
        post_sr("RAW OpenMRS ServiceRequest (fails — DICOM orderDetail + R4 code)", RAW_SR)

    print()


if __name__ == "__main__":
    main()
