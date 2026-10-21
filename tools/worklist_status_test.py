"""
worklist_status_test.py — which AdvaPACS worklist board does an ordered study land on?

Creates a FHIR ServiceRequest with a chosen initial status (the sidecar's order
poller always uses "draft"), then images it exactly as the modality console's
Image Patient does (same code, same Bophelong source image, same gateway).
Afterwards, look the accession up on the AdvaPACS worklist boards and in the
report console.

Run inside the sidecar container (it has the FHIR credentials, the hospital
records and the console code):

  docker exec -i imladris-sidecar python - --status active < tools/worklist_status_test.py

Options: --status draft|active|completed   --patient WCELUK   --modality CR
         --no-performer  (omit the station Device, like orders from the PIH OpenMRS integration)
         --complete      (complete the order after imaging, as the console's Complete Order does)
         --mark-dicom    (send the image with EMPTY top-level PatientID / AccessionNumber, the values
                          only in OtherPatientIDsSequence / RequestAttributesSequence, as the PIH
                          OpenMRS integration's sender did; qure-sim copy off)
"""

import argparse
import secrets
import sys
import time
from datetime import datetime, timezone

import httpx
from pydicom.uid import generate_uid

sys.path.insert(0, "/app")
import order_poller as op            # FHIR helpers and settings
import modality_console_web as mcw   # the console's acquisition code

ap = argparse.ArgumentParser()
ap.add_argument("--status", default="active", choices=["draft", "active", "completed"])
ap.add_argument("--patient", default="WCELUK")
ap.add_argument("--modality", default="CR")
ap.add_argument("--procedure", default="Chest, 1 view (X-ray)")
ap.add_argument("--no-performer", action="store_true")
ap.add_argument("--complete", action="store_true")
ap.add_argument("--mark-dicom", action="store_true")
a = ap.parse_args()

client = httpx.Client(headers=op._fhir_headers())
base = op.FHIR_BASE_URL.rstrip("/")

# AdvaPACS Patient for the Bophelong patient ID (scan: AdvaPACS rejects ?identifier=)
pat = next((e["resource"] for e in client.get(f"{base}/Patient", params={"_count": "500"}, timeout=30)
            .json().get("entry", [])
            if any(i.get("value") == a.patient for i in e["resource"].get("identifier", []))), None)
if not pat:
    sys.exit(f"No AdvaPACS Patient with identifier {a.patient}")
n = (pat.get("name") or [{}])[0]

aet = op._MODALITY_AET.get(a.modality, op._MODALITY_AET["CR"])
device = op._find_device_uuid(client, aet)
accession = "WST" + secrets.token_hex(6)          # 15 chars, marks it as a test
study_uid = generate_uid()

sr = {
    "resourceType": "ServiceRequest",
    "status": a.status,
    "intent": "order",
    "subject": {"reference": f"Patient/{pat['id']}"},
    "code": {"concept": {"coding": [{"system": "http://openmrs.org/concept",
                                     "code": a.procedure.replace(" ", "_").upper(),
                                     "display": a.procedure}], "text": a.procedure}},
    "occurrenceDateTime": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "orderDetail": [{"parameter": [{"code": {"coding": [{
        "system": "http://advapacs.com/fhir/servicerequest-orderdetail-parameter-code",
        "code": "modality"}]}, "valueString": a.modality}]}],
    "identifier": [
        {"system": "http://imladrislab.org/accession-number",
         "type": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/v2-0203", "code": "ACSN"}]},
         "value": accession},
        {"system": "urn:dicom:uid", "value": f"urn:oid:{study_uid}"},
    ],
}
if device and not a.no_performer:
    sr["performer"] = [{"reference": f"Device/{device}"}]

r = client.post(f"{base}/ServiceRequest", json=sr, timeout=15)
print(f"ServiceRequest status={a.status}: HTTP {r.status_code}  id={r.json().get('id') if r.is_success else r.text[:200]}")
if not r.is_success:
    sys.exit(1)
time.sleep(3)

entry = {
    "patient_id": a.patient,
    "patient_name_dicom": f"{n.get('family', '')}^{' '.join(n.get('given', []))}",
    "dob": (pat.get("birthDate") or "").replace("-", ""),
    "sex": {"male": "M", "female": "F"}.get(pat.get("gender", ""), ""),
    "accession": accession,
    "procedure": a.procedure,
    "modality": a.modality,
    "study_uid": study_uid,
    "scheduled": datetime.now().strftime("%Y-%m-%d"),
}
if a.mark_dicom:
    from pydicom.dataset import Dataset
    from pydicom.sequence import Sequence
    import dicom_client as dc
    dc.ENABLE_QURE = False
    _send = dc.cstore_to

    def _issuer(ns):
        i = Dataset(); i.LocalNamespaceEntityID = ns; return i

    def mark_style(datasets, *args, **kw):
        for ds in datasets:
            other = Dataset()
            other.PatientID = ds.PatientID
            other.IssuerOfPatientID = ds.get("IssuerOfPatientID", "PIH_A")
            ds.OtherPatientIDsSequence = Sequence([other])
            req = Dataset()
            req.AccessionNumber = ds.AccessionNumber
            req.IssuerOfAccessionNumberSequence = Sequence([_issuer("PIH_A")])
            req.RequestedProcedureDescription = a.procedure
            ds.RequestAttributesSequence = Sequence([req])
            ds.IssuerOfAccessionNumberSequence = Sequence([_issuer("PIH_A")])
            ds.PatientID = ""
            ds.AccessionNumber = ""
            if "IssuerOfPatientID" in ds:
                del ds.IssuerOfPatientID
        return _send(datasets, *args, **kw)

    dc.cstore_to = mark_style
    print("DICOM: top-level PatientID and AccessionNumber EMPTY; values only in sequences")

res = mcw._acquire_and_send(entry)
print(f"Acquired: {res}")
if a.complete:
    time.sleep(20)   # let the study arrive and link, like a tech doing QA
    mcw._order_states.setdefault(accession, {})["sr_id"] = r.json()["id"]
    print(f"Order completed: {mcw._complete_order(accession)}")
print(f"\nAccession {accession}: check the AdvaPACS boards (Unread / Drafts / ...) and "
      f"https://reports.imladrislab.org/a/{accession}")
