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

*Add new issues below in the same format.*
