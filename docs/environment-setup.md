# Imladris — Environment Setup

Prerequisites and configuration for running the Imladris Virtual Integration Lab
on macOS and Windows 11.

**Primary deployment host:** Windows 11 machine ("BESSIE") running all Docker
services. macOS used for development only.

---

## macOS

### Required software

| Tool | Version | Install |
|------|---------|---------|
| Docker Desktop | Latest | https://www.docker.com/products/docker-desktop |
| Java 11 (Temurin) | 11.x | `brew install --cask temurin@11` |
| Maven | 3.8+ | `brew install maven` |
| Python | 3.11+ | `brew install python@3.11` |
| Git | Any | Included with Xcode CLT |

> **Java version note:** OpenMRS SDK requires Java 11. Java 18+ is incompatible
> with Infinispan 13 used by the PIH distribution. If you have multiple JDKs,
> activate Java 11 before starting OpenMRS:
> ```bash
> export JAVA_HOME=$(/usr/libexec/java_home -v 11)
> ```
> Add this to your shell profile or run it in the Maven terminal each session.

### Python virtual environment

```bash
cd ~/git/PIH/imladris
python3 -m venv .imladris_venv
source .imladris_venv/bin/activate
pip install pynetdicom pydicom requests flask numpy pandas pillow ffmpeg-python pylibjpeg pylibjpeg-libjpeg
```

### OpenMRS SDK setup

```bash
export JAVA_HOME=$(/usr/libexec/java_home -v 11)
cd ~/git/PIH/imladris/openmrs/openmrs-distro-zl
mvn openmrs-sdk:run -DserverId=imladris01
```

Wait for: `INFO: Server startup in [N] milliseconds`
Verify: http://localhost:8080/openmrs (admin / Admin123)

### /etc/hosts (optional)

Adding `imladris` as a localhost alias makes browser bookmarks and
1Password credential matching cleaner:

```bash
sudo sh -c 'echo "127.0.0.1  imladris" >> /etc/hosts'
```

Then all services are reachable as `http://imladris:<port>` in addition to
`http://localhost:<port>`.

### Docker stack

```bash
cd ~/git/PIH/imladris/docker/ap-qs   # or op-qs for local Orthanc mode
docker compose up -d
```

See [Switching between op-qs and ap-qs configurations](#switching-between-op-qs-and-ap-qs-configurations) below.

---

## Windows 11

### Recommended shell: Git Bash (Git for Windows) + MSYS2 for extras

**Primary shell: Git Bash (Git for Windows)**

Git for Windows bundles Git, Bash, OpenSSH, and common POSIX utilities
(including `date`, `curl`, `python3` passthrough) in a single installer with
no extra configuration. It integrates cleanly with VSCode's integrated terminal
and IntelliJ's terminal.

- Download: https://git-scm.com/download/win
- During install: choose **"Git from the command line and also from 3rd-party software"**
  and **"Use Windows' default console window"** (works well in VSCode/IntelliJ terminals)

**Supplemental packages: MSYS2 + pacman**

When you need a POSIX package not included in Git for Windows (e.g. `ffmpeg`),
install it via MSYS2 and add it to your `PATH`:

```bash
# In MSYS2 terminal
pacman -S mingw-w64-x86_64-ffmpeg

# Then add to PATH in Git Bash (add to ~/.bashrc for permanence)
export PATH="/c/msys64/mingw64/bin:$PATH"
```

This hybrid — Git Bash as the daily driver, MSYS2/pacman as the package manager —
avoids MSYS2's Docker volume mount path-translation quirks while still giving
access to the full MSYS2 package ecosystem.

> **WSL2 alternative:** If you want a full Linux environment on Windows, WSL2 with
> Ubuntu + VSCode's WSL Remote extension is an excellent option. Docker Desktop's
> WSL2 backend integrates natively. Recommended if you're doing heavier development
> work on Windows rather than just running the demo stack.

### Required software

| Tool | Version | Install |
|------|---------|---------|
| Docker Desktop | Latest | https://www.docker.com/products/docker-desktop — enable WSL2 backend |
| Java 11 (Temurin) | 11.x | https://adoptium.net — select **Temurin 11 (LTS)**, Windows x64 MSI |
| Maven | 3.8+ | https://maven.apache.org/download.cgi — add `bin/` to `PATH` |
| Python | 3.11+ | https://www.python.org/downloads/ — check **"Add Python to PATH"** during install |
| Git for Windows | Latest | https://git-scm.com/download/win |
| VSCode | Latest | https://code.visualstudio.com |

### Java 11 configuration

After installing Temurin 11, set `JAVA_HOME` permanently so Maven uses it:

1. Open **System Properties → Advanced → Environment Variables**
2. Add/edit **System variable** `JAVA_HOME` = `C:\Program Files\Eclipse Adoptium\jdk-11.x.x.x-hotspot`
   (adjust path to match your install)
3. Ensure `%JAVA_HOME%\bin` is on your `PATH`

Verify in Git Bash:
```bash
java -version   # should show openjdk 11
mvn -version    # should show Java 11
```

> If you have multiple JDKs installed, set `JAVA_HOME` temporarily in Git Bash
> before running Maven:
> ```bash
> export JAVA_HOME="C:/Program Files/Eclipse Adoptium/jdk-11.x.x.x-hotspot"
> ```

### Python virtual environment

In Git Bash:
```bash
cd ~/git/PIH/imladris
python -m venv .imladris_venv
source .imladris_venv/Scripts/activate      # note: Scripts/ not bin/ on Windows
pip install pynetdicom pydicom requests flask numpy pandas pillow ffmpeg-python pylibjpeg pylibjpeg-libjpeg
```

### Docker Desktop configuration

1. Enable the **WSL2 backend** (Settings → General → Use WSL2 based engine) —
   this gives significantly better I/O performance for volume mounts
2. Enable **"Expose daemon on tcp://localhost:2375"** only if needed for remote tooling
3. In Settings → Resources → WSL Integration, enable integration for your distro
   if using WSL2

> `host.docker.internal` resolves to the host IP automatically in Docker Desktop
> for Windows — the same as macOS. No extra configuration needed.

### hosts file (optional)

The Windows hosts file is `C:\Windows\System32\drivers\etc\hosts`. Edit it as
Administrator (open Notepad as Administrator, then File → Open):

```
127.0.0.1  imladris
```

Then `http://imladris:<port>` works in the browser the same as on macOS.

### OpenMRS SDK

In Git Bash (with JAVA_HOME set to Java 11):
```bash
cd ~/git/PIH/imladris/openmrs/openmrs-distro-zl
mvn openmrs-sdk:run -DserverId=imladris01
```

Wait for: `INFO: Server startup in [N] milliseconds`
Verify: http://localhost:8080/openmrs (admin / Admin123)

### Docker stack

In Git Bash:
```bash
cd ~/git/PIH/imladris/docker/ap-qs   # or op-qs / op-qs-local — see switching guide below
docker compose up -d
```

### Teardown — worklist reset command on Windows

The teardown step that resets the order poller state uses `$(date -u ...)` shell
substitution, which works in Git Bash. If you are running from PowerShell or
cmd.exe instead, use this equivalent:

**Git Bash (recommended):**
```bash
docker exec imladris-sidecar sh -c \
  'echo "{\"last_polled\": \"$(date -u +%Y-%m-%dT%H:%M:%S.000+00:00)\"}" \
  > /data/order_poller_state.json'
```

**PowerShell alternative:**
```powershell
$ts = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ss.000+00:00")
docker exec imladris-sidecar sh -c "echo `"{`"last_polled`": `"$ts`"}`" > /data/order_poller_state.json"
```

### Demo admin tools

The Python tools in `tools/` work identically on Windows — run from Git Bash
with the venv activated:

```bash
source .imladris_venv/Scripts/activate
python tools/clear_demo_orders.py --dry-run
python tools/clear_demo_orders.py
python tools/clear_hl7_queue.py
```

---

## Switching between op-qs and ap-qs configurations

Two Docker Compose stacks live under `docker/`:

| Config | Directory | PACS | OHIF points at |
|--------|-----------|------|----------------|
| **op-qs-local** | `docker/op-qs/` + `docker/op-qs-local/` | Orthanc (local volume) | `http://localhost:8044` (direct, no HAProxy) |
| **op-qs** | `docker/op-qs/` | Orthanc (local volume) | `orthanc-p.imladrislab.org` (via HAProxy) |
| **ap-qs** | `docker/ap-qs/` | AdvaPACS (cloud) | `advapacs-p.imladrislab.org` |

Use **op-qs-local** when running OHIF on BESSIE directly — bypasses HAProxy entirely
and avoids Realtek NIC lockups under heavy DICOM frame load (large uncompressed studies).
Use **op-qs** when reviewing from another machine on the network via `ohif.imladrislab.org`.
Use **ap-qs** for full demo and production flows.

### Rules

1. **Never stop lesotho-emr** during a switch — it is a separate Docker Compose
   project and must stay running.
2. **Only one of op-qs / ap-qs should be up at a time** — both bind port 3000 (OHIF)
   and port 8043 (Orthanc PACS).
3. **Orthanc data persists** — the `pacs-data` volume survives `down` and is
   available the next time op-qs is started.
4. **`.env`** must be present in both `docker/op-qs/` and `docker/ap-qs/` (copy
   manually; never commit).
5. **OHIF app-config.js** is pre-configured per stack — no edits needed when switching.

### Switch from ap-qs → op-qs-local (local Orthanc, no HAProxy — use on BESSIE directly)

```powershell
cd docker/ap-qs
docker compose down
cd ..
docker compose -f op-qs/docker-compose.yml -f op-qs-local/docker-compose.yml up -d
```

### Switch from ap-qs → op-qs (local Orthanc, OHIF via HAProxy — use from other machines)

```powershell
cd docker/ap-qs
docker compose down
cd ../op-qs
docker compose up -d
```

### Switch from op-qs → ap-qs (cloud AdvaPACS)

```powershell
cd docker/op-qs
docker compose down
cd ../ap-qs
docker compose up -d
```

### Verify after switch

```powershell
# Confirm active containers
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
# OHIF should be visible at http://localhost:3000
# Orthanc PACS (op-qs only) at http://localhost:8043
```

---

## Service URLs (all platforms)

| Service | URL | Credentials |
|---------|-----|-------------|
| OpenMRS | http://imladris:8080/openmrs | admin / Admin123 |
| Orthanc modality | http://imladris:8042 | admin / admin |
| Orthanc PACS | http://imladris:8043 | admin / admin |
| OHIF Viewer | http://imladris:3000 | — |
| Modality console | http://imladris:5001 | — |
| PACS DICOMweb proxy | http://imladris:8044 | — |
| MySQL | imladris:3306 | openmrs / openmrs |

---

## Claude Code memory sync

Claude Code stores per-project memory locally. To preserve it across machines,
sync the memory directory to/from the repo before committing or after cloning.

**macOS (Git Bash):**
```bash
# Save memory to repo
rsync -av ~/.claude/projects/-Users-$(whoami)-git-PIH-imladris/memory/ memory/

# Restore memory from repo
rsync -av memory/ ~/.claude/projects/-Users-$(whoami)-git-PIH-imladris/memory/
```

**Windows (PowerShell):**
```powershell
$mem = "$env:USERPROFILE\.claude\projects\c--Users-$env:USERNAME-git-PIH-imladris\memory"

# Save memory to repo
Copy-Item -Recurse -Force "$mem\*" "memory\"

# Restore memory from repo
Copy-Item -Recurse -Force "memory\*" "$mem\"
```

The project key in Claude's memory directory is derived from the absolute path
of the repo root. On Windows it will be
`c--Users-<username>-git-PIH-imladris`; adjust if your clone lives elsewhere.
