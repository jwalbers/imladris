# Imladris — End-to-End Demo Walkthrough

Full pipeline: OpenMRS radiology orders → modality worklist → DICOM acquisition →
Orthanc PACS → OHIF viewer → AdvaPACS cloud PACS.

See [environment-setup.md](environment-setup.md) for prerequisites and first-time setup.

---

## Service URLs

| Service | URL | Credentials |
|---------|-----|-------------|
| OpenMRS | http://localhost:8080/openmrs | admin / Admin123 |
| Orthanc modality (IML_CR_01 / IML_US_01) | http://localhost:8042 | admin / admin |
| Orthanc PACS (IML_PACS_01) | http://localhost:8043 | admin / admin |
| OHIF Viewer | http://localhost:3000 | — |
| Modality console | http://localhost:5001 | — |

---

## Step 1 — Start OpenMRS

In a dedicated terminal (keep it running throughout the demo):

```bash
export JAVA_HOME=$(/usr/libexec/java_home -v 11)
cd ~/git/Fastpilot/imladris/openmrs/openmrs-distro-zl
mvn openmrs-sdk:run -DserverId=imladris01
```

Wait for `Server startup in [N] milliseconds`, then verify http://localhost:8080/openmrs.

---

## Step 2 — Start the Docker stack

```bash
cd ~/git/Fastpilot/imladris/docker
docker compose down && docker compose --profile full up -d
docker ps --format "table {{.Names}}\t{{.Status}}"
```

All six containers should show **Up**:
`imladris-mysql`, `imladris-modality`, `imladris-pacs`, `imladris-pacs-proxy`,
`imladris-ohif`, `imladris-sidecar`

---

## Step 3 — Reset the order poller

Stamps the poller's last-seen time to now so it only picks up orders placed during this demo:

```bash
docker exec imladris-sidecar sh -c \
  'echo "{\"last_polled\": \"$(date -u +%Y-%m-%dT%H:%M:%S.000+00:00)\"}" \
  > /data/order_poller_state.json'
```

---

## Step 4 — Place radiology orders in OpenMRS

1. Open http://localhost:8080/openmrs
2. Find or register a patient — use a Bophelong patient ID from
   `imladris-bophelong/patients/dicom/xray/` (e.g. `0EGXAX`, `01JCJ8`)
3. Place a **Chest X-Ray** order → sidecar routes as CR → `IML_CR_01`
4. Place an **Ultrasound** order → sidecar routes as US → `IML_US_01`

The order poller runs every 10 seconds in demo mode. Worklist entries appear at
http://localhost:5001 shortly after the orders are saved.

---

## Step 5 — Acquire studies from the modality console

1. Open http://localhost:5001
2. Click **Refresh Worklist** — pending orders appear
3. Click **Acquire & Send** for the X-ray order
   → DICOM file from `patients/dicom/xray/<patient-id>/` sent as `IML_CR_01`
4. Click **Acquire & Send** for the ultrasound order
   → DICOM file from `patients/dicom/ultrasound_cine/<patient-id>/` sent as `IML_US_01`

Studies are C-STOREd to `orthanc-modality`, which forwards to `orthanc-pacs` (IML_PACS_01).

---

## Step 6 — View studies in OHIF

Open http://localhost:3000 — both studies appear in the study list. Click either to view.

---

## Step 7 — Push studies to AdvaPACS

**Automatic:** ~60 seconds after acquisition the Lua script in `orthanc-pacs` fires
`OnStableStudy` and STOW-RSes the study to AdvaPACS automatically.

**Manual trigger** (for immediate testing):

```bash
# List studies in orthanc-pacs
curl -s -u admin:admin http://localhost:8043/studies | python3 -m json.tool

# Push a specific study to AdvaPACS
curl -u admin:admin -X POST http://localhost:8043/dicom-web/servers/AdvaPACS/stow \
     -H "Content-Type: application/json" \
     -d '{"Resources":["<study-id>"]}'
```

Studies should appear in the AdvaPACS web UI with accession numbers (`BPH-<patient-id>`
as fallback; real OpenMRS accession number when going through the full sidecar workflow).

Check `orthanc-pacs` logs if a study doesn't appear:

```bash
docker logs imladris-pacs 2>&1 | tail -20
```

> **AdvaPACS Validation Queue note:** Studies without an AccessionNumber are accepted
> by STOW-RS (returns HTTP 200) but routed to a Validation Queue rather than the main
> study list. QIDO-RS returns empty `[]` for queued studies. The `retag.py` script sets
> `BPH-{PatientID}` as a fallback accession number to prevent this.

---

## Teardown

```bash
# Clear OpenMRS radiology orders so next demo starts clean
cd ~/git/Fastpilot/imladris
source .imladris_venv/bin/activate
python tools/clear_demo_orders.py

# Stop the Docker stack
cd docker && docker compose --profile full down

# Stop OpenMRS — Ctrl+C in its terminal, then wait for clean shutdown
```

---

## Smoke test (no OpenMRS required)

To verify the DICOM → Orthanc → AdvaPACS path without OpenMRS:

```bash
# Upload a retagged study directly to the modality
curl -u admin:admin -X POST http://localhost:8042/instances \
     --data-binary @/Users/jalbers/git/Fastpilot/imladris-bophelong/patients/dicom/xray/0EGXAX/XRAY_0EGXAX.dcm

# Note ParentStudy ID from the response, C-STORE to IML_PACS_01
curl -u admin:admin -X POST http://localhost:8042/modalities/IML_PACS_01/store \
     -d '["<ParentStudy-ID>"]'

# Push from orthanc-pacs to AdvaPACS
curl -u admin:admin -X POST http://localhost:8043/dicom-web/servers/AdvaPACS/stow \
     -H "Content-Type: application/json" \
     -d '{"Resources":["<ParentStudy-ID>"]}'
```
