"""
hl7_order_test.py — create an AdvaPACS order via HL7 ORM^O01 (gateway's inbound
HL7 service, MLLP), then image it with the modality console's acquisition code.

Counterpart of worklist_status_test.py (FHIR orders): HL7-created orders take
the inbound service's "AdvaPACS Worklist Status" setting, so this shows whether
that route lands studies on the reading board.

Message layout per docs.advapacs.com/interfaces/hl7/workflows/procedure_scheduled:
accession OBR-18 (<= 16 chars), placer ORC-2/OBR-2, filler ORC-3/OBR-3,
Study Instance UID ZDS-1, modality OBR-24, ORC-1 NW, ORC-5 SC, time ORC-7.4.

Run inside the sidecar container:
  docker exec -i imladris-sidecar python - < tools/hl7_order_test.py
Options: --host host.docker.internal --port 2576 --patient WCELUK --modality CR --no-image
         --complete-accession ACC --study-uid UID   (send ORM^O01 XO/CM: mark that order
                                                     completed; AdvaPACS finds it by ZDS-1)
"""

import argparse
import secrets
import socket
import sys
import time
from datetime import datetime

import httpx
from pydicom.uid import generate_uid

sys.path.insert(0, "/app")
import order_poller as op
import modality_console_web as mcw

ap = argparse.ArgumentParser()
ap.add_argument("--host", default="host.docker.internal")
ap.add_argument("--port", type=int, default=2576)
ap.add_argument("--patient", default="WCELUK")
ap.add_argument("--issuer", default="PIH_A")
ap.add_argument("--modality", default="CR")
ap.add_argument("--procedure", default="Chest, 1 view (X-ray)")
ap.add_argument("--no-image", action="store_true", help="send the order only")
ap.add_argument("--complete-accession", help="complete an order created by this script (XO/CM)")
ap.add_argument("--study-uid", help="its Study Instance UID (ZDS-1), required with --complete-accession")
a = ap.parse_args()
if a.complete_accession and not a.study_uid:
    sys.exit("--complete-accession needs --study-uid")

# Demographics from the AdvaPACS Patient (same patient the images will carry)
client = httpx.Client(headers=op._fhir_headers())
base = op.FHIR_BASE_URL.rstrip("/")
pat = next((e["resource"] for e in client.get(f"{base}/Patient", params={"_count": "500"}, timeout=30)
            .json().get("entry", [])
            if any(i.get("value") == a.patient for i in e["resource"].get("identifier", []))), None)
if not pat:
    sys.exit(f"No AdvaPACS Patient with identifier {a.patient}")
n = (pat.get("name") or [{}])[0]
family, given = n.get("family", ""), " ".join(n.get("given", []))
dob = (pat.get("birthDate") or "").replace("-", "")
sex = {"male": "M", "female": "F"}.get(pat.get("gender", ""), "U")

now = datetime.now()
ts = now.strftime("%Y%m%d%H%M%S")
accession = a.complete_accession or ("HL7" + secrets.token_hex(6))   # 15 chars, marks it as a test
placer, filler = "P" + accession, "F" + accession
study_uid = a.study_uid or generate_uid()
control, status = ("XO", "CM") if a.complete_accession else ("NW", "SC")
code = a.procedure.replace(" ", "_").upper()[:20]

segs = [
    f"MSH|^~\\&|IMLADRIS|BOPHELONG|ADVAPACS|ADVAPACS|{ts}||ORM^O01|{secrets.token_hex(8)}|P|2.5.1",
    f"PID|1||{a.patient}^^^{a.issuer}||{family}^{given}||{dob}|{sex}",
    "PV1|1|O",
    f"ORC|{control}|{placer}|{filler}||{status}||^^^{ts}|||||",
    f"OBR|1|{placer}|{filler}|{code}^{a.procedure}^L|||{ts}|||||||||||{accession}|{accession}|{accession}||||{a.modality}|||^^^{ts}",
    f"ZDS|{study_uid}^^Application^DICOM",
]
msg = "\r".join(segs) + "\r"
print("ORM^O01:\n  " + "\n  ".join(segs))

with socket.create_connection((a.host, a.port), timeout=15) as s:
    s.sendall(b"\x0b" + msg.encode() + b"\x1c\x0d")
    ack = s.recv(65536).decode(errors="replace").strip("\x0b\x1c\r")
print("ACK:\n  " + ack.replace("\r", "\n  "))
if "|AA|" not in ack and "|CA|" not in ack:
    sys.exit("Order not accepted")
if a.no_image or a.complete_accession:
    sys.exit(0)

time.sleep(5)
entry = {
    "patient_id": a.patient, "patient_name_dicom": f"{family}^{given}", "dob": dob,
    "sex": sex if sex != "U" else "", "accession": accession, "procedure": a.procedure,
    "modality": a.modality, "study_uid": study_uid, "scheduled": now.strftime("%Y-%m-%d"),
}
print(f"Acquired: {mcw._acquire_and_send(entry)}")
print(f"\nAccession {accession}: check the AdvaPACS boards and "
      f"https://reports.imladrislab.org/a/{accession}")
