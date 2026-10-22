# Qure.ai laptop as an IMLADRIS lab resource

Configuration of the Qure.ai field laptop (qTrack / qXR, MinXray DX simulator,
AdvaPACS connector) as seen from the IMLADRIS lab, and the recommended Windows
Firewall policy. Integration details (qTrack, qXR, the simulator, the PACS
adapter) are in [../qure-integration/](../qure-integration/) and
[../qure-app/README.md](../qure-app/README.md); this document covers the
laptop's place on the lab network.

Status: 2026-10-21. Laptop in the Wisconsin lab; remote access in use by the team.

## Identity

| | |
|---|---|
| Hostname | `DESKTOP-GDVLT6A` |
| Address | **192.168.3.70**, DHCP reservation on the Wisconsin LAN (192.168.3.0/24) |
| OS | Windows 11 Pro (RDP host enabled) |
| Container runtime | Docker Desktop (WSL2) |
| Windows accounts | `qure`: the installed Qure.ai stack, left untouched. `dev`: the lab clone of the stack, used for demos and remote access |
| Timezone | GMT+2 (Lesotho/Rwanda). qTrack writes DICOM study times without a timezone; see [the timezone issue](../../issues/advapacs-study-time-shift-no-dicom-timezone.md) |

## What runs on it

| Component | Role | DICOM AE / port |
|---|---|---|
| Qure.ai App stack (qTrack, qXR on the local GPU) | Patient registration, AI reading, results UI | App UI :3000 |
| Qure MWL server (`mwl`) | Worklist for the detector console | station `MIX`, DICOM :9003, HTTP :9002 |
| Qure DCMIO gateway | Receives images, runs qXR | AE `QUREAI`, :5252; config UI :7000 |
| MinXray DX simulator / modality agent | Images each patient qTrack schedules | queries `MIX` on the MWL, stores to DCMIO |
| Laptop AdvaPACS gateway | Store-and-forward to AdvaPACS cloud | Local AE `QURE01_GW_01`, :11112 |
| PACS adapter | Sends each completed study (primary DX, qXR SC/OT overlay, SR, encapsulated PDF) to AdvaPACS | calling AE `QURE01_ADP_01` |
| qTrack cloud sync | Pushes studies to the qTrack cloud workspace | outbound HTTPS |

Workflow: register in qTrack → the simulator images the patient → qXR runs on the
laptop → results in qTrack → qTrack cloud sync, and the PACS adapter sends the
study to AdvaPACS through the laptop gateway. In AdvaPACS these studies arrive
without a prior order, so AdvaPACS creates the order and puts the study on the
**Unread** board as **Ready to Report**.

## Remote access (team)

- **https://qure.imladrislab.org/**, PIH Entra sign-in, then straight onto the `dev`
  desktop. Also a tile on the IMLADRIS landing page.
- Path: Wisconsin pfSense HAProxy → Apache Guacamole on the lab VM
  (`imladris.lan.fastpilot.com`, 192.168.3.66, `docker/guacamole`) → RDP to
  192.168.3.70:3389 as `dev`, NLA.
- Users never see the Windows password: it lives only in the Guacamole connection.
  Copy out of the laptop is disabled; paste in works; sessions are recorded.
- Windows allows one interactive session. Guacamole allows a new connection to
  take over a stale one (max 2 connections, no per-user limit).
- Admin: `ssh -L 8096:localhost:8096 imladris.lan.fastpilot.com`, then
  http://localhost:8096/ as `guacadmin` (Settings → Active Sessions to clear a stuck session).
- To change the Windows account Guacamole uses: set `QURE_RDP_USER` / `QURE_RDP_PASSWORD`
  in the lab VM's `docker/guacamole/.env` and rerun `./setup.sh`.

## Network exposure today

Docker Desktop publishes the stack's ports on all interfaces, and its own
firewall rule allows them from anywhere. Ports confirmed reachable from the LAN
(2026-10-20): 3389, 3000, **7000**, **9002**, 9003, 5252, 11112, 8085. By the
stack's compose file, the following are also published and unprotected:
Postgres 5432/5433/5435, Redis 6379, Jupyter 5888/7888, API 8080/8081, cathode
8180, nginx 2001, metabase 3099, countly 5520.

7000 (DCMIO configuration) and 9002 (MWL patient registration) answer without
authentication. The `dev` password is a shared demo password. That is acceptable on a
trusted home LAN, but not on clinic Wi-Fi, so the policy below closes all of it.

## Recommended firewall policy

| Ports | Service | Allowed from |
|---|---|---|
| 3389 | Remote Desktop | lab VM 192.168.3.66 (Guacamole), EILEEN 192.168.3.5 (admin) |
| 9003, 5252 | MWL DICOM, DCMIO C-STORE | lab VM (a future second lab MinXray modality) |
| 3000, 8080, 8081, 2001 | Qure.ai App UI and the APIs its browser code calls | the laptop only; in the field, the clinic subnet (`-FieldLan`) |
| 7000, 7888, 9002, 5888, 8180, 3099, 5520, 5432, 5433, 5435, 6379, 11112, 8085 | admin UIs, databases, internal services, the laptop gateway | the laptop only |
| ICMP echo | ping | 192.168.3.0/24 (monitoring) |

"The laptop only" means loopback plus Docker/WSL internal addresses (172.16.0.0/12).
Container-to-container traffic (simulator → MWL/DCMIO, adapter → gateway) stays
on the Docker network and is unaffected. Outbound traffic is not restricted: the
laptop needs HTTPS to AdvaPACS (`*.advapacs.com`, gateway push), the qTrack cloud,
Docker Hub and Windows Update.

Why block rules: Docker Desktop's inbound **allow** rule for its backend program
covers every published port, and an extra allow rule can't narrow it. In Windows
Firewall a **block** rule wins over any allow, so each group blocks every remote
address *except* its allowlist. Rules apply to all profiles, because Windows can
re-classify the LAN as Public after a router change.

### Script

[`Set-ImladrisFirewall.ps1`](Set-ImladrisFirewall.ps1), run from an elevated
PowerShell on the laptop. It is idempotent (it recreates the `IMLADRIS` rule group)
and reversible (`-Remove`).

```powershell
cd <repo>\qure\qure-laptop
powershell -ExecutionPolicy Bypass -File .\Set-ImladrisFirewall.ps1              # lab
powershell -ExecutionPolicy Bypass -File .\Set-ImladrisFirewall.ps1 -FieldLan 192.168.8.0/24   # field
powershell -ExecutionPolicy Bypass -File .\Set-ImladrisFirewall.ps1 -Remove      # undo
Get-NetFirewallRule -Group IMLADRIS | Format-Table DisplayName, Action, Enabled
```

Parameters: `-LabVm` (default 192.168.3.66), `-AdminHosts` (default 192.168.3.5),
`-FieldLan` (subnet for tablets, empty in the lab).

### Verify after applying

From the lab VM (should be **open**: 3389, 9003, 5252; everything else closed):

```bash
for p in 3389 9003 5252 3000 7000 9002 5432 6379 11112; do
  timeout 3 bash -c "exec 3<>/dev/tcp/192.168.3.70/$p" 2>/dev/null && echo "$p open" || echo "$p closed"; done
```

From EILEEN: 3389 open, the rest closed. On the laptop itself, http://localhost:3000
still works and the end-to-end flow (register → image → qXR → AdvaPACS) runs as
before. Then check https://qure.imladrislab.org/ still connects.

If a port the policy closes turns out to be needed from another host, add that host
to the matching group in the script rather than deleting rules.

## Related

- Lab-side setup: `imladris/docker/guacamole/` (remote access), `imladris/docker/ap-qs/`
  (landing tile, report console that shows these studies once in AdvaPACS).
- AdvaPACS findings from this work: `imladris/issues/advapacs-*.md`.
