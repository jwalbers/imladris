# Imladris Lab — Admin Troubleshooting Guide

Running log of confirmed failure modes, how to spot them, and how to fix them.

---

## Issue: Services unreachable after Windows Update forced reboot

**Affected services:** Any container using `network_mode: host` (currently: `tool-cabinet`, `advapacs-gateway`)  
**First observed:** 2026-07-15

### Background

On Windows, Docker Desktop runs containers inside a WSL2 VM. Containers with
`network_mode: host` bind to the WSL2 VM's network rather than Windows directly.
Docker Desktop bridges the gap using `netsh interface portproxy` rules that
forward traffic from the Windows host IP → WSL2 VM IP. A forced reboot (Windows
Update, power loss) can drop these proxy rules without recreating them on
startup, leaving the containers healthy internally but invisible from the LAN
and from HAProxy.

### Symptoms

- `imladrislab.org` (or subdomains like `tools.imladrislab.org`) returns
  `ERR_HTTP2_SERVER_REFUSED_STREAM` in the browser
- HAProxy stats page shows the backend as red / DOWN
- Container logs look healthy — Uvicorn showing 200 OK on `/status`
- `docker ps` shows the container running but **no port mappings** (expected
  for `network_mode: host` — not the problem)
- `curl http://192.168.1.10:<port>/status` from the Windows host fails with
  "Unable to connect to the remote server"

### Confirmation

```powershell
netsh interface portproxy show v4tov4
```

If the port for the broken service is **missing** from the table, the proxy
rule was dropped. A healthy lab should show entries for every
`network_mode: host` service port (5002 for tool-cabinet, etc.).

### Immediate remedy

1. Find the current WSL2 VM IP from the existing portproxy table (or via
   `wsl hostname -I`). It looks like `172.29.x.x`.

2. Re-add the missing portproxy rule:

```powershell
netsh interface portproxy add v4tov4 `
    listenport=5002 listenaddress=0.0.0.0 `
    connectport=5002 connectaddress=<WSL2-IP>
```

3. Verify the firewall rule exists (Windows Update can also reset custom rules):

```powershell
Get-NetFirewallRule | Where-Object { $_.LocalPort -like "*5002*" }
```

If missing, re-add it:

```powershell
New-NetFirewallRule -DisplayName "Tool Cabinet 5002" `
    -Direction Inbound -Protocol TCP -LocalPort 5002 `
    -Action Allow -Profile Any
```

This checks all firewall rules... which can get removed after a Windows update.

```powershell
Get-NetFirewallRule -Direction Inbound -Action Allow |
    Get-NetFirewallPortFilter |
    Where-Object { $_.LocalPort -in @('80','443','8080','8090','8091','3000','8043','8044','5002') } |
    Select-Object LocalPort
```

This checks to see if the advapacs proxy is still connected to AdvaPACS:

```powershell
PS C:\WINDOWS\system32> netsh interface portproxy show v4tov4
```
Should return:

```
Listen on ipv4:             Connect to ipv4:

Address         Port        Address         Port
--------------- ----------  --------------- ----------
0.0.0.0         8085        172.29.215.115  8085
```


4. Confirm: `curl http://192.168.1.10:5002/status` should return 200.

### Recovery script

A one-shot recovery script lives in
`imladris-personal/processes/restore-portproxy.ps1` (TODO: create this).
It re-applies all portproxy entries and firewall rules for every
`network_mode: host` service. Run it after any forced reboot before
checking individual services.

### Longer-term mitigations

| Option | Effort | Notes |
|---|---|---|
| **Disable auto-reboot on Windows Update** | Low | `Settings → Windows Update → Advanced Options → Active Hours` — set a wide active window so updates install but reboot is deferred until you choose |
| **Create restore-portproxy.ps1 script** | Low | Idempotent script that re-adds all portproxy + firewall rules; add to lab startup checklist |
| **Switch tool-cabinet off `network_mode: host`** | Medium | Use explicit `ports:` mapping instead; survives reboots cleanly. Only needed if iptables/NET_ADMIN access to WSL2 netns is actively used — verify before switching |
| **Task Scheduler startup trigger** | Medium | Run restore-portproxy.ps1 on system startup via Task Scheduler to automate recovery |

---

## Issue: All backends unreachable from HAProxy after pfSense hardware swap

**Affected services:** All HAProxy backends (OpenMRS, SAML SP, Orthanc, Tool Cabinet)
**First observed:** 2026-07-19

### Background

When pfSense hardware is replaced and its config backup is restored, the LAN adapter
on BESSIE sees a new gateway MAC address. Windows Network Location Awareness (NLA)
treats this as an unknown network and reclassifies the LAN adapter from **Private**
to **Public**. The Public firewall profile silently blocks all unsolicited inbound
TCP connections — including HAProxy backend connections from pfSense — even when
explicit `Profile: Any` allow rules exist for those ports.

ICMP (ping) is also blocked inbound on Public profile by default, which masked the
problem: pfSense could send packets out igb1, but BESSIE returned no replies.

### Symptoms

- `imladrislab.org` returns `503 No server is available` from HAProxy
- HAProxy stats show all backends **UP** (health checks disabled — no check)
- LAN IP access works fine: `curl http://192.168.1.10:8091/` from BESSIE succeeds
- pfSense Diagnostics curl to any backend IP hangs indefinitely
- `tcpdump` on pfSense igb1 shows ICMP echo requests leaving but no replies
- pfSense cannot ping BESSIE **or** any other LAN host (192.168.1.11, etc.)

### Confirmation

From pfSense Diagnostics -> Command Prompt:

```sh
ping -c 4 192.168.1.10   # 100% packet loss
curl -sv http://192.168.1.10:8091/ 2>&1 | head -5   # hangs
```

From BESSIE:

```powershell
Get-NetConnectionProfile | Select-Object Name, NetworkCategory, InterfaceAlias
# NetworkCategory will show: Public
```

### Immediate remedy

From BESSIE (as Administrator):

```powershell
Set-NetConnectionProfile -InterfaceAlias "Ethernet" -NetworkCategory Private
```

HAProxy backends become reachable immediately -- no restart required.

Also add ICMP allow rule if missing (needed for pfSense diagnostics):

```powershell
New-NetFirewallRule -DisplayName "Imladris pfSense ICMPv4" `
    -Protocol ICMPv4 -IcmpType 8 -Direction Inbound -Action Allow -Profile Any
```

### Recovery script

`restore-portproxy.ps1` now includes both fixes. Run it after any hardware swap
on either BESSIE or pfSense.

### Why this happens

Windows NLA identifies a network by its gateway MAC address. When pfSense hardware
changes, the gateway MAC changes. Windows sees a "new" network and defaults to
Public (untrusted) classification. The fix is sticky -- once set to Private it
stays until the next hardware change triggers reclassification.

### Longer-term mitigations

| Option | Effort | Notes |
|---|---|---|
| **Run restore-portproxy.ps1 after any hardware swap** | Low | Now covers network profile check and ICMP rule |
| **Set via Group Policy** | Medium | Can force Private profile for specific subnets regardless of gateway MAC |
| **Static gateway MAC (pfSense)** | Low | Pin a virtual MAC on pfSense's igb1 in the NIC settings -- survives board swaps |

---

## Issue: AdvaPACS gateway DICOM C-STORE failing ("Cannot associate")

**Affected services:** Modality sidecar → AdvaPACS gateway DICOM path  
**First observed:** 2026-07-19 (after host hardware swap)

### Background

The AdvaPACS gateway (`imladris-advapacs-gw`) is a Spring Boot / dcm4che application
that authenticates to the AdvaPACS cloud on startup and then accepts DICOM C-STORE
connections from local modalities. Several distinct failure modes can cause
"Cannot associate with ADVAPACS_GW_01@host.docker.internal:11112" in the sidecar.

### Failure modes and fixes (work through in order)

#### 1. Gateway 401 — stale registration

**Symptom:** `docker logs imladris-advapacs-gw` shows repeated 401 errors from
`https://usa1.api.gateway.advapacs.com/auth/token` immediately on startup.

**Key finding: Re-keying (Regenerate Key) never fixes a non-functional gateway.**
You must delete and recreate the gateway registration on `pih.advapacs.com`.

**Procedure (preferred — no spare gateway required):**
1. Create a **new** gateway registration on `pih.advapacs.com` (e.g. a second `advapacs-gw-01`
   entry or a temporary name). Copy its KEY_ID and SECRET immediately — shown once only.
2. Re-bind the Local AE (`advapacs-gw-AE-01`) to point to the new gateway.
3. **Now** delete the old gateway — the Local AE is no longer bound to it.
4. Rename the new gateway to `advapacs-gw-01` if desired.
5. Update `.env`: `ADVAPACS_GW_KEY_ID` and `ADVAPACS_GW_SECRET`.
6. `docker compose up -d --force-recreate advapacs-gateway`

**Alternative (requires a spare gateway):**
Keep a permanently configured spare gateway (`advapacs-gw-02`) with no Local AE bound to it.
Re-bind the Local AE to `advapacs-gw-02`, delete `advapacs-gw-01`, recreate it, re-bind
the Local AE back. Useful if you cannot create a new gateway entry mid-procedure.

**Note:** Accepted Calling AEs are a property of the **Local AE** (`advapacs-gw-AE-01`),
not the gateway. They survive gateway recreation — no need to re-add them.

#### 2. Registration state lost on container recreation

**Symptom:** Gateway was working, then `--force-recreate` causes 401 again.

**Root cause:** The gateway stores its device ID and Derby DB in
`/opt/AdvaHealthSolutions/AdvaPACSGateway` inside the container. Without a named
volume, `--force-recreate` wipes this directory and the cloud rejects the new device ID.

**Fix:** The `docker-compose.yml` now mounts a named volume at that path:
```yaml
volumes:
  - advapacs-gw-data:/opt/AdvaHealthSolutions/AdvaPACSGateway
```
With the volume in place, `--force-recreate` is safe. The Hibernate error
`Sequence 'MCID_SEQ' already exists` will appear in logs after every force-recreate
— this is **harmless and expected**. Ignore it.

#### 3. DICOM associations aborted ("Association Aborted" / "calling-AE-title-not-recognized")

**Symptom:** Gateway is Online (no 401), but sidecar logs show:
```
Association Aborted
Cannot associate with ADVAPACS_GW_01@host.docker.internal:11112
```

**Root cause:** The Local AE's Accepted Calling AEs list does not include the
sidecar's AE title (`IML_CR_01`). Accepted Calling AEs are a property of the
**Local AE** (not the gateway) and survive gateway recreation. However, if the
lab has been moved to a new subnet or site configuration was changed (e.g. Wisconsin
migration), the AE titles in the list may no longer match the current sidecar config.

**Fix:**
1. On `pih.advapacs.com` → Local AE `advapacs-gw-AE-01` → Accepted Calling AEs:
   add `IML_CR_01` (and any other modality AE titles that need access).
2. `docker compose up -d --force-recreate advapacs-gateway` to pull updated config.
3. If still failing: use the **Restart** option in the gateway's portal menu
   (same menu as Reconfigure / Regenerate Key). This triggers a cloud-side config
   push. Cause/effect uncertain but harmless and sometimes resolves residual issues.

### General notes

- **After any portal config change** (Accepted Calling AEs, Remote AE IPs, etc.),
  the gateway must be force-recreated to fetch the new config from the cloud.
- **Cloud-side "Restart"** (portal menu): triggers a config sync from the cloud.
  Use after config changes if force-recreate alone doesn't resolve association issues.
- **Always use `--force-recreate`**, never `docker compose restart`. Plain restart
  preserves the Derby DB but prevents schema re-init; with the volume in place,
  force-recreate is always safe.
- Gateway logs (`docker logs imladris-advapacs-gw`) are minimal by design.
  The only meaningful log entry is the 401 error. Association rejections are not
  logged locally — check the portal's server-side logs for `advapacs-gw-01`.

### Recovery script

`restore-portproxy.ps1` restores portproxy rules for port 11112 (DICOM) and 8085
(DICOMweb). Run after any forced reboot or WSL2 IP change.

---

*Add new issues below in the same format.*
