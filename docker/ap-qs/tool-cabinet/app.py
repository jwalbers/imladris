"""
tool-cabinet — Imladris Lab Tool Cabinet
Network Connectivity Simulator: controls outbound iptables rules to simulate
WAN outages to AdvaPACS cloud while the gateway remains fully running.

Requires:
  network_mode: host   (shares WSL2 root netns with advapacs-gw)
  cap_add: [NET_ADMIN] (permission to run iptables)
  /var/run/docker.sock (read container status)
"""

import datetime
import ipaddress
import logging
import os
import socket
import subprocess
from contextlib import asynccontextmanager
from pathlib import Path

import docker
import httpx
import pydicom
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

logging.getLogger("pynetdicom").setLevel(logging.WARNING)

PACS_URL         = os.getenv("PACS_URL", "http://localhost:8043")
PACS_USER        = os.getenv("PACS_USER", "admin")
PACS_PASSWORD    = os.getenv("PACS_PASSWORD", "admin")
GATEWAY_CONTAINER = os.getenv("GATEWAY_CONTAINER", "imladris-advapacs-gw")
ADVAPACS_HOSTS   = [h.strip() for h in os.getenv(
    "ADVAPACS_HOSTS", "usa1.api.dicomweb.advapacs.com"
).split(",") if h.strip()]

FHIR_BASE_URL    = os.getenv("FHIR_BASE_URL", "https://usa1.api.integration.advapacs.com/fhir/R5")
FHIR_KEY_ID      = os.getenv("FHIR_KEY_ID", "")
FHIR_KEY_SECRET  = os.getenv("FHIR_KEY_SECRET", "")

_profile: str = "online"
_blocked_ips: set[str] = set()

# ── Models ────────────────────────────────────────────────────────────────────

class ServiceRequestInput(BaseModel):
    patient_id:     str = "XP92EU"
    patient_name:   str = "Lethabo^Tau"   # family^given
    dob:            str = "19860101"       # YYYYMMDD
    sex:            str = "M"             # M/F/U
    procedure_desc: str = "X-ray of apical lordotic chest"
    modality:       str = "CR"
    accession:      str = ""              # blank = auto-generate
    fhir_base:      str = FHIR_BASE_URL
    key_id:         str = FHIR_KEY_ID
    key_secret:     str = FHIR_KEY_SECRET


class FhirOrdersRequest(BaseModel):
    fhir_base:   str = FHIR_BASE_URL
    key_id:      str = FHIR_KEY_ID
    key_secret:  str = FHIR_KEY_SECRET
    status:      str = "draft"    # draft = scheduled (pre-acquisition) in AdvaPACS
    modality:    str = ""         # blank = all modalities


# ── FHIR helpers ─────────────────────────────────────────────────────────────

_KNOWN_MODALITIES = frozenset(
    {"AR", "AS", "ASMT", "AU", "BDUS", "BI", "BMD", "CD", "CF", "CP", "CR",
     "CS", "CT", "CTPROTOCOL", "DD", "DF", "DG", "DM", "DS", "DX", "EC",
     "ECG", "EPS", "ES", "FA", "FID", "FS", "GM", "HC", "HD", "IO", "IVOCT",
     "IVUS", "KER", "KO", "LEN", "LS", "MG", "MR", "MS", "NM", "OAM", "OCT",
     "OP", "OPM", "OPR", "OPT", "OPV", "OSS", "OT", "PLAN", "PR", "PT",
     "PX", "REG", "RESP", "RF", "RG", "RTDOSE", "RTIMAGE", "RTPLAN",
     "RTRECORD", "RTSTRUCT", "RWV", "SEG", "SM", "SMR", "SR", "SRF", "ST",
     "STAIN", "TG", "US", "VA", "XA", "XC"}
)

_AET_TO_MODALITY = {
    "IML_CR_01": "CR",
    "IML_US_01": "US",
    "IML_CT_01": "CT",
    "IML_MR_01": "MR",
    "IML_RF_01": "RF",
}


def _extract_station_aet(device: dict) -> str:
    """Extract DICOM Station AE Title (code 110119) from a FHIR Device resource."""
    for ident in device.get("identifier", []):
        if any(c.get("code") == "110119"
               for c in ident.get("type", {}).get("coding", [])):
            return ident.get("value", "")
    return ""


# ── FHIR ServiceRequest sender ────────────────────────────────────────────────

def _post_service_request(req: ServiceRequestInput) -> dict:
    base       = (req.fhir_base or FHIR_BASE_URL).rstrip("/")
    key_id     = req.key_id     or FHIR_KEY_ID
    key_secret = req.key_secret or FHIR_KEY_SECRET
    headers = {
        "Authorization": f"ID={key_id},Secret={key_secret}",
        "Accept":        "application/fhir+json",
        "Content-Type":  "application/fhir+json",
    }

    ts        = datetime.datetime.now().strftime("%m%d%H%M%S")
    accession = req.accession or f"TC-{ts}"
    study_uid = pydicom.uid.generate_uid()

    # ── Find or create Patient ──────────────────────────────────────────
    patient_uuid = None
    try:
        r = httpx.get(f"{base}/Patient", params={"identifier": req.patient_id},
                      headers=headers, timeout=10, follow_redirects=True)
        entries = r.json().get("entry", []) if r.status_code == 200 else []
        if entries:
            patient_uuid = entries[0]["resource"]["id"]
        else:
            parts  = req.patient_name.split("^", 1)
            family = parts[0].strip()
            given  = [parts[1].strip()] if len(parts) > 1 and parts[1].strip() else []
            gender = {"M": "male", "F": "female"}.get(req.sex.upper(), "unknown")
            dob    = req.dob
            birth  = f"{dob[:4]}-{dob[4:6]}-{dob[6:]}" if len(dob) == 8 else ""
            pt = {
                "resourceType": "Patient",
                "identifier":   [{"system": "http://openmrs.org/identifier", "value": req.patient_id}],
                "name":         [{"family": family, "given": given}],
                "gender":       gender,
            }
            if birth:
                pt["birthDate"] = birth
            r2 = httpx.post(f"{base}/Patient", json=pt, headers=headers,
                            timeout=10, follow_redirects=True)
            if r2.status_code in (200, 201):
                patient_uuid = r2.json().get("id")
            else:
                return {"ok": False, "error": f"Patient create failed: HTTP {r2.status_code}  {r2.text[:200]}"}
    except Exception as e:
        return {"ok": False, "error": f"Patient lookup/create error: {e}"}

    # ── POST ServiceRequest ─────────────────────────────────────────────
    resource = {
        "resourceType": "ServiceRequest",
        "status":  "draft",
        "intent":  "order",
        "subject": {"reference": f"Patient/{patient_uuid}"},
        "code":    {"concept": {"coding": [{"display": req.procedure_desc}]}},
        "orderDetail": [{
            "parameter": [{
                "code": {"coding": [{
                    "system": "http://dicom.nema.org/resources/ontology/DCM",
                    "code":   "modality",
                }]},
                "valueString": req.modality,
            }]
        }],
        "identifier": [
            {
                "type": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/v2-0203", "code": "ACSN"}]},
                "value": accession,
            },
            {"system": "urn:dicom:uid", "value": f"urn:oid:{study_uid}"},
        ],
    }

    try:
        r3 = httpx.post(f"{base}/ServiceRequest", json=resource, headers=headers,
                        timeout=15, follow_redirects=True)
        if r3.status_code in (200, 201):
            sr_id = r3.json().get("id", "")
            return {"ok": True, "accession": accession, "study_uid": study_uid,
                    "patient_uuid": patient_uuid, "fhir_id": sr_id}
        return {"ok": False, "error": f"HTTP {r3.status_code}  {r3.text[:300]}",
                "accession": accession, "study_uid": study_uid}
    except Exception as e:
        return {"ok": False, "error": str(e), "accession": accession, "study_uid": study_uid}


# ── AdvaPACS FHIR orders query ────────────────────────────────────────────────

def _query_fhir_orders(req: FhirOrdersRequest) -> dict:
    url = f"{(req.fhir_base or FHIR_BASE_URL).rstrip('/')}/ServiceRequest"
    key_id     = req.key_id     or FHIR_KEY_ID
    key_secret = req.key_secret or FHIR_KEY_SECRET
    params: dict = {"_count": "200"}
    if req.status:
        params["status"] = req.status
    headers = {
        "Authorization": f"ID={key_id},Secret={key_secret}",
        "Accept": "application/fhir+json",
    }
    try:
        r = httpx.get(url, params=params, headers=headers, timeout=15,
                      follow_redirects=True)
        if r.status_code != 200:
            return {"ok": False, "error": f"HTTP {r.status_code}: {r.text[:300]}", "orders": []}

        bundle = r.json()
        entries = bundle.get("entry", [])
        base = (req.fhir_base or FHIR_BASE_URL).rstrip("/")
        device_cache: dict[str, dict] = {}
        orders = []
        for e in entries:
            sr = e.get("resource", {})

            # Modality: orderDetail[].parameter[].code.coding[0].code == "modality"
            modality_val = ""
            for od in sr.get("orderDetail", []):
                for p in od.get("parameter", []):
                    codings = p.get("code", {}).get("coding", [])
                    if any(c.get("code") == "modality" for c in codings):
                        modality_val = p.get("valueString", "")

            if req.modality and modality_val.upper() != req.modality.upper():
                continue

            # Accession: identifier with type.coding[0].code == "ACSN"
            # Study UID: identifier with system == "urn:dicom:uid" (value = "urn:oid:1.2...")
            accession = ""
            study_uid = ""
            for ident in sr.get("identifier", []):
                if ident.get("system") == "urn:dicom:uid":
                    study_uid = ident.get("value", "").removeprefix("urn:oid:")
                else:
                    type_code = (ident.get("type", {}).get("coding", [{}])[0]
                                 .get("code", ""))
                    if type_code == "ACSN":
                        accession = ident.get("value", "")

            # Procedure description: code.concept.coding[0].display
            proc_desc = (sr.get("code", {})
                           .get("concept", {})
                           .get("coding", [{}])[0]
                           .get("display", ""))

            # Patient: subject.display if present, else extract ID from reference
            subj = sr.get("subject", {})
            patient = subj.get("display") or subj.get("reference", "").split("/")[-1]

            # Performer Device (station) — fetch once per unique Device reference
            device_ref = ""
            device_raw = None
            performers = sr.get("performer", [])
            if performers:
                device_ref = performers[0].get("reference", "")
            if device_ref:
                if device_ref not in device_cache:
                    try:
                        dr = httpx.get(f"{base}/{device_ref}", headers=headers,
                                       timeout=10, follow_redirects=True)
                        device_cache[device_ref] = dr.json() if dr.status_code == 200 else {}
                    except Exception:
                        device_cache[device_ref] = {}
                device_raw = device_cache[device_ref]

            station_aet = _extract_station_aet(device_raw) if device_raw else ""

            # Fall back to AE-title map when AdvaPACS echoes the parameter code
            # name ("modality") as the valueString instead of the value ("CR").
            if modality_val not in _KNOWN_MODALITIES:
                modality_val = _AET_TO_MODALITY.get(station_aet, modality_val)

            orders.append({
                "id":           sr.get("id", ""),
                "status":       sr.get("status", ""),
                "modality":     modality_val,
                "accession":    accession,
                "study_uid":    study_uid,
                "patient":      patient,
                "procedure":    proc_desc,
                "occurrence":   sr.get("occurrenceDateTime", ""),
                "station_aet":  station_aet,
                "device_ref":   device_ref,   # not shown in table; used for first_device_raw lookup
            })

        statuses_seen = list({o["status"] for o in orders})
        first_raw = entries[0]["resource"] if entries else None
        # Include first Device resource so we can see the station/AET structure
        first_device_ref = orders[0]["device_ref"] if orders else ""
        first_device_raw = device_cache.get(first_device_ref) if first_device_ref else None
        return {"ok": True, "total": bundle.get("total", len(orders)),
                "returned": len(orders), "statuses_seen": statuses_seen,
                "orders": orders, "first_raw": first_raw,
                "first_device_raw": first_device_raw}
    except Exception as ex:
        return {"ok": False, "error": str(ex), "orders": []}


# ── Startup: recover state from existing iptables rules ──────────────────────

def _load_existing_rules() -> None:
    global _blocked_ips, _profile
    try:
        result = subprocess.run(
            ["iptables-save", "-t", "filter"],
            capture_output=True, text=True, check=True,
        )
        for line in result.stdout.splitlines():
            # Match rules in OUTPUT (host-networked) and DOCKER-USER (bridge-networked)
            if ("-A OUTPUT" in line or "-A DOCKER-USER" in line) and "--dport 443" in line and "-j REJECT" in line:
                for part in line.split():
                    if "/" in part:
                        try:
                            net = ipaddress.ip_network(part, strict=False)
                            ip = str(net.network_address)
                            if not ipaddress.ip_address(ip).is_private:
                                _blocked_ips.add(ip)
                        except ValueError:
                            pass
        if _blocked_ips:
            _profile = "offline"
    except Exception:
        pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    _load_existing_rules()
    yield


app = FastAPI(title="Imladris Lab Tool Cabinet", lifespan=lifespan)
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")


# ── Network utilities ─────────────────────────────────────────────────────────

def _resolve_fqdns(fqdns: list[str]) -> set[str]:
    ips: set[str] = set()
    for fqdn in fqdns:
        try:
            for info in socket.getaddrinfo(fqdn, 443, type=socket.SOCK_STREAM):
                addr = info[4][0]
                if not ipaddress.ip_address(addr).is_private:
                    ips.add(addr)
        except OSError:
            pass
    return ips


def _scan_https_connections() -> set[str]:
    """Return public IPs with established HTTPS (port 443) connections in this netns."""
    ips: set[str] = set()
    for proc_path in ["/proc/net/tcp6", "/proc/net/tcp"]:
        try:
            lines = Path(proc_path).read_text().splitlines()[1:]
            for line in lines:
                parts = line.split()
                if len(parts) < 4 or parts[3] != "01":   # 01 = ESTABLISHED
                    continue
                remote = parts[2]
                addr_hex, port_hex = remote.rsplit(":", 1)
                if int(port_hex, 16) != 443:
                    continue
                try:
                    # /proc/net/tcp6: 32-hex IPv4-mapped; /proc/net/tcp: 8-hex IPv4
                    raw = addr_hex[-8:]                   # last 8 hex = IPv4 part
                    ip_bytes = bytes.fromhex(raw)[::-1]   # little-endian → network order
                    addr = str(ipaddress.IPv4Address(ip_bytes))
                    if not ipaddress.ip_address(addr).is_private:
                        ips.add(addr)
                except Exception:
                    pass
        except OSError:
            pass
    return ips


def _iptables(action: str, ip: str) -> None:
    # OUTPUT covers host-networked containers (advapacs-gateway).
    # DOCKER-USER covers bridge-networked containers (orthanc-pacs, etc.).
    for chain in ("OUTPUT", "DOCKER-USER"):
        r = subprocess.run(
            ["iptables", action, chain,
             "-d", ip, "-p", "tcp", "--dport", "443", "-j", "REJECT"],
            capture_output=True,
        )
        if r.returncode != 0 and action != "-D":
            raise subprocess.CalledProcessError(r.returncode, r.args, r.stdout, r.stderr)


# ── Service queries ───────────────────────────────────────────────────────────

def _pacs_stats() -> dict:
    try:
        r = httpx.get(
            f"{PACS_URL}/statistics",
            auth=(PACS_USER, PACS_PASSWORD),
            timeout=3,
        )
        s = r.json()
        return {
            "studies": s.get("CountStudies", 0),
            "instances": s.get("CountInstances", 0),
            "ok": True,
        }
    except Exception:
        return {"studies": "—", "instances": "—", "ok": False}


def _gw_status() -> str:
    try:
        return docker.from_env().containers.get(GATEWAY_CONTAINER).status
    except Exception:
        return "unknown"


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html", {
        "profile":     _profile,
        "blocked_ips": sorted(_blocked_ips),
        "pacs":        _pacs_stats(),
        "gw_status":   _gw_status(),
    })


@app.post("/profile/offline")
async def go_offline():
    global _profile, _blocked_ips
    ips = _resolve_fqdns(ADVAPACS_HOSTS) | _scan_https_connections()
    errors = []
    for ip in ips:
        if ip not in _blocked_ips:
            try:
                _iptables("-I", ip)
                _blocked_ips.add(ip)
            except subprocess.CalledProcessError as e:
                errors.append(f"{ip}: {e.stderr.decode().strip()}")
    _profile = "offline"
    return JSONResponse({
        "profile":     _profile,
        "blocked_ips": sorted(_blocked_ips),
        "errors":      errors,
    })


@app.post("/profile/online")
async def go_online():
    global _profile, _blocked_ips
    errors = []
    for ip in list(_blocked_ips):
        try:
            _iptables("-D", ip)
            _blocked_ips.discard(ip)
        except subprocess.CalledProcessError as e:
            errors.append(f"{ip}: {e.stderr.decode().strip()}")
    _profile = "online"
    return JSONResponse({
        "profile":     _profile,
        "blocked_ips": sorted(_blocked_ips),
        "errors":      errors,
    })


@app.get("/status")
async def status_json():
    return JSONResponse({
        "profile":     _profile,
        "blocked_ips": sorted(_blocked_ips),
        "pacs":        _pacs_stats(),
        "gw_status":   _gw_status(),
    })


@app.post("/fhir/sr")
def post_service_request(req: ServiceRequestInput):
    return JSONResponse(_post_service_request(req))


@app.post("/fhir/orders")
def fhir_orders(req: FhirOrdersRequest):
    return JSONResponse(_query_fhir_orders(req))
