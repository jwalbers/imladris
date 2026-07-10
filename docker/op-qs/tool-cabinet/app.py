"""
tool-cabinet — Imladris Lab Tool Cabinet
Network Connectivity Simulator: controls outbound iptables rules to simulate
WAN outages to AdvaPACS cloud while the gateway remains fully running.

Requires:
  network_mode: host   (shares WSL2 root netns with advapacs-gw)
  cap_add: [NET_ADMIN] (permission to run iptables)
  /var/run/docker.sock (read container status)
"""

import ipaddress
import os
import socket
import subprocess
from contextlib import asynccontextmanager
from pathlib import Path

import docker
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

PACS_URL         = os.getenv("PACS_URL", "http://localhost:8043")
PACS_USER        = os.getenv("PACS_USER", "admin")
PACS_PASSWORD    = os.getenv("PACS_PASSWORD", "admin")
GATEWAY_CONTAINER = os.getenv("GATEWAY_CONTAINER", "imladris-advapacs-gw")
ADVAPACS_HOSTS   = [h.strip() for h in os.getenv(
    "ADVAPACS_HOSTS", "usa1.api.dicomweb.advapacs.com"
).split(",") if h.strip()]

_profile: str = "online"
_blocked_ips: set[str] = set()


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
