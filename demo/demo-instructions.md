# Demo Startup — Imladris Virtual Integration Lab

## Prerequisites

### Confirm a clean teardown of any prior demos (end of this doc)

- Make sure all containers stopped and removed.
```
docker ps
```
else shut down the stack again

```bash
cd ~/git/Fastpilot/imladris/docker
docker compose --profile full down
```
Send a Ctrl-C if this appears to hang, then
```
docker ps
```
to confirm there are no zombies.

- Docker Desktop running
- Java 11 active (`export JAVA_HOME=$(/usr/libexec/java_home -v 11)`)

---

## Step 1 — Start Docker stack

```bash
cd ~/git/Fastpilot/imladris/docker
docker compose --profile full up -d
```

Services started:

| Service | name | URL |
|---------|------|-----|
| MySQL 8.0 | imladris-mysql | http:localhost:3306 |
| Orthanc modality (MWL + simulator) | imladris-modality | http://localhost:8042 |
| Orthanc cloud PACS | imladris-pacs | http://localhost:8043 |
| OHIF viewer | imladris-ohif | http://localhost:3000 |
| Modality console | http://localhost:5001 |
| PACS Proxy | imladris-pacs-proxy | http://localhost:8044 |
| IMLADRIS sidecar for the modalities | imladris-sidecar | http://localhost:5001 |

---

## Step 2 — Start OpenMRS

```bash
export JAVA_HOME=$(/usr/libexec/java_home -v 11)
cd ~/git/Fastpilot/imladris/openmrs/openmrs-distro-zl
mvn openmrs-sdk:run -DserverId=imladris01
```
This can take a minute or two, so start this before the demo.

Wait for: `INFO: Server startup in [N] milliseconds`  
Verify: http://localhost:8080/openmrs (login: admin / Admin123)

---

## Step 3 — Clear stale worklist entries

```bash
# Remove any leftover .wl files
docker exec imladris-modality sh -c "rm -f /worklist/*.wl"

# Reset order poller state to now so prior orders don't replay
docker exec imladris-sidecar sh -c \
  'echo "{\"last_polled\": \"$(date -u +%Y-%m-%dT%H:%M:%S.000+00:00)\"}" \
  > /data/order_poller_state.json'
```

---

## Step 4 — Verify sidecar is running

```bash
docker logs imladris-sidecar --tail 20
```

Look for:
- `Order poller starting`
- `PACS change watcher started`
- `Modality console starting on port 5001`

---

## Step 5 — Confirm clean state

- **OHIF** (http://localhost:3000) — no studies visible
- **Modality console** (http://localhost:5001) — worklist empty
- **Orthanc modality** (http://localhost:8042) — no studies, worklist empty
- **Orthanc PACS** (http://localhost:8043) — no studies
- **OpenMRS HL7 queue** (http://localhost:8080/openmrs/admin/hl7/hl7InQueuePending.htm) — no queued messages

---
## Step 6 - Set up the large display for the demo or video.

Create browser windows for each UI and log in to OpenMRS as dr.mokoena.  Create another browser instance so you can log in as admin and show the [(HL7 Queued Messages)(http://localhost:8080/openmrs/admin/hl7/hl7InQueuePending.htm)]

This is a good layout, with the team collab / confluence / jira window in upper left and the admin HL7 window at lower right.

![Demo start](screenshots/demo_start_screen_layout.png)

---
## Demo workflow

1. **OpenMRS** — log in as dr.mokoena, open patient, place US and CR radiology orders for 7RHG9J, Tsepang Molapo.
2. **Modality console** (http://localhost:5001) — order appears within ~10 sec, click **Image the Patient**
3. **Orthanc modality** (http://localhost:8042) — study appears
4. **OHIF** (http://localhost:3000) — study appears in PACS within ~15 sec
5. **OpenMRS HL7 queue** (http://localhost:8080/openmrs/admin/hl7/hl7InQueuePending.htm) — ORU^R01 result message arrives within ~15 sec of study reaching PACS

---

## Teardown

**1. Delete all studies from Orthanc PACS** (http://localhost:8043) via the web UI.
OHIF studies clear automatically on next stack restart — no manual OHIF cleanup needed.


**2. Reset the worklist and order poller state:**

```bash
# Remove .wl files
docker exec imladris-modality sh -c "rm -f /worklist/*.wl"

# Reset order poller state to now so prior orders don't replay on next startup
docker exec imladris-sidecar sh -c \
  'echo "{\"last_polled\": \"$(date -u +%Y-%m-%dT%H:%M:%S.000+00:00)\"}" \
  > /data/order_poller_state.json'
```

**3. Clear out all demo orders:***
```
source .imladris_venv/bin/activate
python tools/clear_demo_orders.py
```

**4. Clear out all OpenMRS orders:***

```
source .imladris_venv/bin/activate
python tools/clear_hl7_queue.py
```


**5. Shut down the stack:**

```bash
cd ~/git/Fastpilot/imladris/docker
docker compose --profile full down
```

**6. Stop OpenMRS** — `Ctrl+C` in the Maven terminal.

---

## Demo polling intervals (already configured)

Polling has been shortened for demo responsiveness.
To restore production settings after the demo, edit `docker/docker-compose.yml`:

```yaml
POLL_INTERVAL_MINUTES: 5    # restore from 0.25
ORDER_POLL_SEC: 30           # restore from 10
```

Then restart the sidecar:

```bash
docker compose --profile full up -d modality-sidecar
```
