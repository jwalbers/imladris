# Imladris Modality Sidecar

Bridges OpenMRS and the Orthanc-based DICOM stack. Replaces Mirth Connect for
radiology order routing with a lightweight Python service.

## Services (run in one container)

| Component | File | Role |
|-----------|------|------|
| Order poller | `order_poller.py` | Polls OpenMRS REST API for new radiology orders → creates MWL entries |
| MWL manager | `mwl_manager.py` | Creates/removes DICOM worklist files |
| Acquisition loop | `acquisition_loop.py` | Polls MWL, auto-forwards studies to PACS |
| PACS watcher | `hl7_bridge.py` | Watches Orthanc PACS for completed studies → sends ORU^R01 to OpenMRS |
| GUI console | `modality_console.py` | wxPython desktop app (runs natively, not in container) |

## Message flow

```
OpenMRS (radiologyapp creates order in DB)
  │
  │  REST GET /ws/rest/v1/order?orderType=...&activatedOnOrAfterDate=...
  ▼
order_poller.py  ──►  mwl_manager.py writes <accession>.wl to /worklist volume
                                       │
                         orthanc-modality serves it via DICOM C-FIND MWL
                                       │
                         Modality acquires images, C-STOREs to orthanc-pacs
                                       │
  hl7_bridge.py polls /changes on orthanc-pacs (every 15 s)
  StableStudy event detected
  │
  │  ORU^R01 (study available) via MLLP → OpenMRS :8066
  ▼
OpenMRS (study result received)
```

Discontinue orders (`action = DISCONTINUE`) delete the worklist file before acquisition.

## Worklist sharing

`orthanc-modality` and the sidecar share a Docker named volume (`worklist-data`)
mounted at `/worklist` in both containers.  The Orthanc Worklist plugin
(`"Worklists": { "Enable": true, "Database": "/worklist" }` in `modality.json`)
reads `.wl` files from this folder and serves them via DICOM C-FIND.

## Order poller state

The order poller persists the last-seen `dateActivated` timestamp to
`/data/order_poller_state.json` (Docker volume `sidecar-data`) so restarts
do not replay old orders.

Set `RADIOLOGY_ORDER_TYPE_UUID` explicitly if auto-discovery picks the wrong
order type.  Auto-discovery queries `/ws/rest/v1/ordertype` and selects the
first entry with "radiology" in the name, falling back to "test" order type.

## Running

```bash
# Start the full stack (requires OpenMRS):
docker compose --profile full up -d

# Logs:
docker logs -f imladris-sidecar
```

The sidecar is gated behind the `full` Docker Compose profile because it
requires a running OpenMRS instance for order intake.

## Environment variables

### Order poller

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENMRS_URL` | `http://openmrs:8080/openmrs` | OpenMRS base URL |
| `OPENMRS_USER` | `admin` | OpenMRS REST username |
| `OPENMRS_PASSWORD` | `Admin123` | OpenMRS REST password |
| `RADIOLOGY_ORDER_TYPE_UUID` | _(auto)_ | UUID of radiology order type; auto-discovered if blank |
| `ORDER_POLL_SEC` | `30` | Seconds between REST polls |
| `ORDER_STATE_FILE` | `/data/order_poller_state.json` | Persisted last-polled timestamp |

### PACS change watcher

| Variable | Default | Description |
|----------|---------|-------------|
| `PACS_URL` | `http://orthanc-pacs:8042` | Orthanc PACS REST base URL |
| `PACS_USER` / `PACS_PASSWORD` | `admin` / `admin` | Orthanc credentials |
| `CHANGE_POLL_SEC` | `15` | Orthanc PACS change poll interval |
| `OPENMRS_HL7_HOST` | `openmrs` | OpenMRS HL7 listener host |
| `OPENMRS_HL7_PORT` | `8066` | OpenMRS HL7 listener port |

### Acquisition loop

| Variable | Default | Description |
|----------|---------|-------------|
| `ORTHANC_URL` | `http://orthanc-modality:8042` | Modality Orthanc REST URL |
| `MODALITY_AET` | `MODALITY_SIM` | Modality AE title |
| `CLOUD_PACS_AE` | `CLOUD_PACS` | PACS AE title for C-STORE |
| `POLL_INTERVAL_MINUTES` | `5` | Acquisition loop poll interval |
| `WL_FOLDER` | `/worklist` | Path to DICOM worklist folder |
