# Qure.ai App — On-Prem Install Analysis (IMLADRIS lab laptop)

Analysis of the Qure.ai App on-prem bundle installed on the lab laptop
`DESKTOP-GDVLT6A`, as a basis for wiring a containerized MinXray wireless
DICOM detector into qXR. See also [../qure-minxray-reference.md](../qure-minxray-reference.md)
and [../qure-doc.md](../qure-doc.md).

Status: **analysis in progress** (started 2026-09-30). The stack is **running under
the `qure` Windows user** (see [Current state](#current-state-of-this-laptop)).

## Laptop role in the lab

The full IMLADRIS lab stays on **imladrislab.org**. This laptop runs only:

- the Qure.ai App docker stack (qTrack / qXR), under the `qure` user
- a **MinXray detector simulator** (planned): it sends DX studies to the Qure dcmio gateway and queries the MWL
- an **AdvaPACS gateway** (planned): it forwards studies from Qure.ai App (qTrack) to AdvaPACS

Lab work runs against a **clone of the stack under the `dev` user**, so the `qure` install stays
untouched. See [clone/README.md](clone/README.md).

## Install layout

| Path | Contents |
|---|---|
| `C:\Users\qure\AppData\Local\Programs\Qure.ai\` | `Qure.ai.exe` — Electron installer/launcher (build dated 2025-06-24) |
| `C:\Users\qure\AppData\Local\Qure.ai\qureapp\` | docker-compose stack, `*.env` files, DCMIO `conf.json`, account bootstrap scripts |
| `C:\Users\qure\AppData\Local\Qure.ai\scripts\` | PowerShell install/post-install/backup/retrofit scripts |
| `C:\Users\qure\AppData\Local\Qure.ai\dockerCreds.enc.json` | Encrypted Docker Hub pull credentials for the private `qureai/*` images |
| `qureapp\trialpreprodtesting-V3\` | Older/alternate copy of the same config set (pre-prod trial profile) |

Compose variants in `qureapp\`:

- `docker-compose.yml` — **current** stack (platform + cathode + dcmio + MWL + metabase + countly).
- `docker-compose-blaze.yml` — older layout: adds `apihub`, `qtrack-frontend`, `apihub_sync`;
  pins `qxr_checkpoints:3.1.28_blaze`, `dicom-scp:0.2.6_hotfix_11`; no cathode, no translations container.
- `Untitled` — an earlier draft of `docker-compose.yml` (no translations mounts, no job scheduler).

## How the installer deploys

The installer does **not** use Docker Desktop's Windows engine. It uses `wsl -u root docker-compose -p platform …`,
so it expects a default WSL distro (Ubuntu) that has Docker engine, python3 and pip.
Sequence from `scripts\post\setup_onprem.ps1`:

1. Install python3/pip/requests/dotenv in WSL (also overwrites `/etc/resolv.conf` with 8.8.8.8).
2. `Get-Config` — pull the site config from `https://infra-api.qure.ai/qureapp/config/` with
   `QAuth-User/Number/Token` headers, and save it as `account_crud\infra.json`. Then run
   `createStartupJson.py`, which produces `startup.json` (account, license, `dcmioConfig`, `gatewayURL`).
   **This means the first install needs internet and Qure-issued credentials.**
3. `set_apihub_env.py` rewrites env files.
4. `docker-compose up -d` (project `platform`).
5. Create the Postgres DBs `dcmio`, `apihub`, `platform` (plus `metabasedb` in `createDBs.ps1`).
6. Django migrations (qureapi, apihub).
7. `createAccountPlatform.py`, which creates the user/org/API token and injects the token into
   `srcConfig` (qXR TB app) and `dcmioConfig.api.token`.
8. `createAccountPortals.py` (apihub).
9. **`SetGatewayConfig.py`**, which POSTs `startup.json["dcmioConfig"]` to `http://<gatewayURL>/config/`.
   **This is the step that configures the DICOM gateway.**
10. `updateENVs.py` / `updatePlaywrightEnvs.py` write the sync and bearer tokens into the env files.
11. `docker-compose up -d` again, optional Teleport remote-access agent, optional Playwright smoke tests.

`scripts\post\customConfiguration.ps1` then runs `qureapp\customConfiguration.py` inside `qureapi`.
It sets the TB worklist filters and tags, adds the saved filters (AI Positive/Negative, TB Presumptive),
turns on dynamic PDF reports and the metabase TB dashboard (id 9), and activates the `xray` license
from `startup.json`.

## Services and ports (docker-compose.yml)

DICOM-relevant services are **bold**.

| Service (container) | Image | Host port → container | Role |
|---|---|---|---|
| **dcmio_dicom_server** | `qureai/dcmio:${DCMIO_TAG}` | **5252 → 5252** | DICOM C-STORE SCP. The modality/detector sends images here |
| **dcmio_web_server** | `qureai/dcmio` | 7000 → 80, 7888 → 8888 | DCMIO gateway web/config API (`/config/`) and Jupyter |
| **dcmio_worker** | `qureai/dcmio` | — | Filters and uploads studies to the platform API, publishes results |
| **mwl_server** (`mwl`) | `qureai/dicom-scp:${MWL_TAG}` | **9003 → 222** (DICOM), 9002 → 4000 (HTTP) | Modality Worklist SCP (C-FIND). The detector console queries worklist here |
| mwl_postgres | postgres:14.4 | 5435 → 5432 | MWL database |
| qure-api (`qureapi`) | `qureai/qure_platform_api:${TAG}` | 8080 | Platform API (Django/gunicorn) |
| qure-api-ws | same | 8081 | Websocket server |
| qure-api-worker-common, -workflow, -job-scheduler | same | — | Background workers and schedulers |
| qure-api-notebook | same | 5888 → 8888 | Jupyter shell_plus (admin) |
| cathode-api / cathode-worker(-common) | `qureai/cathode:${CATHODE_TAG}` | 8180 → 8080 | AI inference service. `cathode-worker` reserves **1 NVIDIA GPU** for `process_image` jobs |
| cxr_checkpoints | `qureai/qxr_checkpoints:${CHECKPOINTS_TAG}` | — | qXR model weights volume |
| output_generation_api | `qureai/sc_generation_api` | — | Secondary capture / report rendering |
| frontend | `qureai/qureapp:${FRONTEND_TAG}` | **3000** | Qure.ai App web UI |
| nginx | `qureai/nginx:qureapp_CORS` | 2001 → 80 | Static/data proxy |
| postgres / cathode-postgres | postgres:14.4 | 5432 / 5433 | Platform DB / cathode DB |
| django_channel | redis:6.2-alpine | 6379 | Channels backend |
| qsync | `qure_platform_api` `send` | — | Cloud sync to Qure (uses `qremote-firebase.json`) |
| metabase | `qureai/metabase:v4.1.6` | 3099 → 3000 | TB dashboards |
| edge-server | `qureai/countly:1.4` | 5520 → 3000 | Countly analytics |
| playwright | `qureai/playwright` | host network | Install smoke tests |
| translations_container | `qureai/translation_assets` | — | i18n assets volume |

The external volumes `prod-data`, `psql-data`, `psql-data-mwl`, `cathode-psql-data`, `dcmio_data`
must exist before `up`. The installer creates them.

## DICOM wiring for the MinXray detector (working hypothesis)

```
MinXray detector container ──C-FIND──▶ mwl_server        :9003  (MWL SCP)
                           ──C-STORE─▶ dcmio_dicom_server :5252  (Storage SCP)
                                          │
                              dcmio_worker → qureapi :8080 → cathode (qXR on GPU)
                                          │
                              results → frontend :3000 / optional publish back via DICOM (dcmioConfig.publishers)
```

The detector's AE titles, the called/calling AE whitelist, filters and publishers all live in
files that were **not** examined (see below):

- `qureapp\conf.json` is mounted into all three dcmio containers at `/srv/dcmio/conf.json`.
- `account_crud\startup.json` → `dcmioConfig` is POSTed to the gateway at install time. Its structure
  (`api`, `filter`, `upload`, `publishers`, `sync`) is described in
  [../qure-minxray-reference.md §4](../qure-minxray-reference.md).
- `dcmio.env` and `mwl.env` hold the AE title, port and DB settings for dcmio and MWL.

## Config file inventory

| File | Sensitive? | In repo? | Notes |
|---|---|---|---|
| `docker-compose.yml`, `docker-compose-blaze.yml`, `Untitled` | Low: contains a Jupyter password hash and the default MWL postgres password | No (pending decision) | Service topology above |
| `customConfiguration.py` | No | No (pending decision) | Worklist/filter/license customization |
| `account_crud\*.py` | Low: test-account default passwords in the `createTest*` scripts | No (pending decision) | Bootstrap logic summarized above |
| `conf.json` | **Unknown, not read** | No | **DCMIO gateway config: key file for the DICOM wiring** |
| `account_crud\startup.json` | **Yes**: account password, license, sync tokens | No | Contains `dcmioConfig` and `gatewayURL` |
| `.env`, `platform.env`, `cathode.env`, `dcmio.env`, `mwl.env`, `apihub.env`, `metabase.env`, `countly.env`, `frontend.env`, `playwright.env` | **Yes**: DB passwords, API/sync tokens | No | `dcmio.env` and `mwl.env` needed for AE/port config |
| `runtimeConfig.js` | Unknown, not read | No | Frontend runtime config (API URLs) |
| `qremote-firebase.json` | **Yes**: Firebase service-account key | No | Never commit |
| `..\dockerCreds.enc.json` | **Yes** | No | Never commit |
| `metabase\metabase.json` (730 KB) | Unknown | No | Dashboard definitions |
| `scripts\**` | Low: some hardcoded vendor defaults (metabase DB user, retrofit Wi-Fi) | No (pending decision) | Install flow above |

## Current state of this laptop

Checked 2026-09-30:

- The Qure stack **is running** when logged in as the `qure` user. Docker Desktop and WSL distros are
  per Windows user. From the `dev` account, Docker Desktop (28.5.2, NVIDIA runtime available) shows no
  containers, and WSL lists only `docker-desktop`. The `qure` user's own WSL distro runs the
  `platform` compose project.
- `scripts\post\utils\run_post_installer.ps1` **resets** the install: it runs `compose down`, removes
  **all** docker volumes, and deletes the `~/.qure/*.json` markers. Don't run it by accident.
- The "retrofit" scripts (`setupRetrofit.ps1`, `retrofit.py`, `qRetrofit.exe`) set up a TP-Link USB Wi-Fi
  adapter and router so tablets can reach the app on :3000. They handle remote access and are not
  DICOM related.

## Open items

- [ ] Decide how the sensitive config files are captured: local-only (gitignored), private repo
      (`imladris-personal`?), or sanitized templates made by the file owner.
- [ ] Get `conf.json`, `dcmio.env` and `mwl.env` contents (sanitized) to document the AE titles and ports.
- [ ] Get the MinXray detector DICOM conformance statement: supported SOP classes (DX For Presentation/Processing),
      MWL query keys, and transfer syntaxes.
- [ ] Work out how components run from the `dev` account can reach the `qure` user's stack. Check which host ports
      (5252, 9003, 3000, 7000) are published on localhost or the LAN while `qure` is logged in.
- [ ] Build the MinXray simulator (a pynetdicom SCU: MWL C-FIND → DX C-STORE). Check whether
      `docker/*/qure-sim/` already does part of this.
- [ ] Install the AdvaPACS gateway and add a dcmio publisher (or qTrack forwarding rule) that points at it.
- [ ] Add the latest Qure.ai App and qXR docs to the repo (Jim).
