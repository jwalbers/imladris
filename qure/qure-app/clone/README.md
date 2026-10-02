# Cloning the Qure.ai stack from the `qure` user to `dev`

This runs a copy of the Qure.ai App stack under the `dev` Windows user, so lab work
(MinXray simulator, AdvaPACS gateway) can't break the working install under `qure`.

This is a **clone, not a reinstall**. Rerunning the Qure installer would register
again with `infra-api.qure.ai` and could rotate the tokens that the `qure` install depends on.

| File | Run as | Purpose |
|---|---|---|
| [Export-QureStack.ps1](Export-QureStack.ps1) | `qure` | `docker save` the images, tar the named volumes, write `manifest.json` |
| [Import-QureStack.ps1](Import-QureStack.ps1) | `dev` | `docker load`, restore the volumes, copy `qureapp\` config, add the override |
| [docker-compose.dev-override.yml](docker-compose.dev-override.yml) | — | Disables `qsync`, `edge-server` and `playwright` in the clone |

## Steps

1. **Log in as `qure`.** Check that the stack is up (`wsl -u root docker ps`), then run from an
   ordinary PowerShell:
   ```powershell
   powershell -ExecutionPolicy Bypass -File C:\Dev\git\imladris\qure\qure-app\clone\Export-QureStack.ps1
   ```
   This writes to `C:\QureTransfer\`. It stops the containers briefly while the volumes are
   archived, then restarts them.
2. **Log out of `qure`.** Logging out fully, not just switching user, stops that user's stack
   and frees the ports.
3. **As `dev`**, with Docker Desktop running:
   ```powershell
   powershell -ExecutionPolicy Bypass -File C:\Dev\git\imladris\qure\qure-app\clone\Import-QureStack.ps1
   cd $env:USERPROFILE\qure-dev\qureapp
   docker compose -p platform -f docker-compose.yml -f docker-compose.dev-override.yml up -d
   ```
4. Open http://localhost:3000 and log in with the same account as the `qure` install.

## Troubleshooting the export

- **`docker ... failed` right away / "docker-desktop WSL2 distribution" message:** `wsl -u root -e docker` isn't
  reaching the distro the Qure installer used. Run `wsl -l -v` as `qure` and note which distro is the default (`*`).
  Paste the output, the export error, and the result of `wsl -u root -e docker ps` into the Claude session.
- **"No containers found for compose project 'platform'":** the stack isn't up yet, or it uses a different project
  name. Run `wsl -u root -e docker ps --format "{{.Names}} {{.Labels}}"` and look for `com.docker.compose.project=`.
- **Script blocked by execution policy:** keep the `powershell -ExecutionPolicy Bypass -File ...` form shown above.
  It affects only that one run.

## Rules

- **One stack at a time.** Both stacks bind the same host ports (3000, 5252, 5432, 8080, 9003 and others)
  and share the GPU. Log out `qure` before starting the clone, and stop the clone
  (`docker compose -p platform stop`) before logging in as `qure`.
- The cloned config in `%USERPROFILE%\qure-dev\qureapp` contains credentials. **Never copy it into a git repo.**
- `C:\QureTransfer\` also holds credentials, inside the database volumes. Delete it once the clone works.
- The clone is a snapshot. To refresh it, rerun the export, then run the import with `-Force`.

## First clone: 2026-09-30

- Export: 14 images (41 GB `images.tar`), 12 volumes (26 GB of it `platform_xray-checkpoints`).
- Import and `up` succeeded under `dev`. All 23 containers run. Ports 3000, 8080, 7000, 5252, 9002, 9003 and 3099 answer.
  - Frontend `:3000` redirects (308) to `/patients` → 200.
  - API `:8080` and nginx `:2001` return 401 (auth required).
  - dcmio web `:7000` returns 200.
- GPU is visible in `cathode-worker`: NVIDIA RTX 1000 Ada Laptop, 6 GB.
- Expected noise, not errors:
  - `translations_container` exits 0 after copying assets, and `restart: always` loops it.
  - `qureapi` warns `FERNET_KEY not configured`. That affects only ACR registration encryption.
- Fix applied during the first run: the export's volume-listing template originally contained `"volume"`. Windows
  PowerShell 5.1 strips embedded double quotes from native-command arguments, so the template broke. The filtering
  now happens in PowerShell instead.

## Not verified yet

- Logging in to the app at http://localhost:3000 with the `qure` account, and whether earlier studies show up.
- An end-to-end qXR inference run: send a test CXR to `localhost:5252` and see a result.

- The license is tied to `machine_identifier`. It should validate on the same machine, but this hasn't been
  checked against Qure's terms.
- Whether any other service calls Qure's cloud, e.g. license renewal or the job scheduler. Check the cloned
  `*.env` files for `qure.ai` URLs.
- Whether `conf.json` / `dcmioConfig` points the dcmio upload at a LAN IP instead of `localhost`.
  The clone would still work, but the IP would need updating if the laptop's address changes.
- GPU passthrough for `cathode-worker` under Docker Desktop. The NVIDIA runtime is present, but inference hasn't been tested.
