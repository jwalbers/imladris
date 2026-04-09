# Imladris Modality Sidecar

Bridges OpenMRS and the Orthanc-based DICOM stack. Replaces Mirth Connect for
lab purposes with a lightweight Python service.

## Services (run in one container)

| Component | File | Role |
|-----------|------|------|
| HL7 bridge | `hl7_bridge.py` | MLLP server + Orthanc PACS watcher |
| MWL manager | `mwl_manager.py` | Creates/removes DICOM worklist files |
| Acquisition loop | `acquisition_loop.py` | Polls MWL, auto-forwards studies to PACS |
| GUI console | `modality_console.py` | wxPython desktop app (runs natively, not in container) |

## Message flow

```
OpenMRS (radiologyapp)
  │
  │  ORM^O01 (new order) via MLLP :2575
  ▼
hl7_bridge.py  ──►  mwl_manager.py writes <accession>.wl to /worklist volume
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

Cancel orders (`ORC-1 = CA/DC`) delete the worklist file before acquisition.

## Worklist sharing

`orthanc-modality` and the sidecar share a Docker named volume (`worklist-data`)
mounted at `/worklist` in both containers.  The Orthanc Worklist plugin
(`"Worklists": { "Enable": true, "Database": "/worklist" }` in `modality.json`)
reads `.wl` files from this folder and serves them via DICOM C-FIND.

## OpenMRS configuration

In the OpenMRS admin panel, configure the HL7 sender to point at the sidecar:

- **Host:** `localhost` (SDK) or `imladris-sidecar` (Docker)
- **Port:** `2575`

The sidecar sends ORU results back to OpenMRS on port `8066` (OpenMRS HL7
Listener module default).

## Running

The container entrypoint is `main.py`, which starts:
- The HL7 bridge as an asyncio event loop (main thread)
- The acquisition loop as a daemon thread

```bash
# Start the full stack (requires OpenMRS):
docker compose --profile full up -d

# Logs:
docker logs -f imladris-sidecar
```

The sidecar is gated behind the `full` Docker Compose profile because it
requires a running OpenMRS instance for HL7 order intake.

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MLLP_PORT` | `2575` | Inbound MLLP listen port |
| `OPENMRS_HL7_HOST` | `openmrs` | OpenMRS HL7 listener host |
| `OPENMRS_HL7_PORT` | `8066` | OpenMRS HL7 listener port |
| `PACS_URL` | `http://orthanc-pacs:8042` | Orthanc PACS REST base URL |
| `PACS_USER` / `PACS_PASSWORD` | `admin` / `admin` | Orthanc credentials |
| `WL_FOLDER` | `/worklist` | Path to DICOM worklist folder |
| `CHANGE_POLL_SEC` | `15` | Orthanc PACS change poll interval |
| `ORTHANC_URL` | `http://orthanc-modality:8042` | Modality Orthanc REST URL |
| `MODALITY_AET` | `MODALITY_SIM` | Modality AE title |
| `CLOUD_PACS_AE` | `CLOUD_PACS` | PACS AE title for C-STORE |
| `POLL_INTERVAL_MINUTES` | `5` | Acquisition loop poll interval |

## HL7 message support

| Message | Direction | Handled |
|---------|-----------|---------|
| ORM^O01 (NW — new order) | OpenMRS → sidecar | Creates MWL entry |
| ORM^O01 (CA/DC — cancel) | OpenMRS → sidecar | Deletes MWL entry |
| ORU^R01 (study available) | sidecar → OpenMRS | Sent on StableStudy event |

ACK is returned for every inbound message.  Unrecognised message types
receive AA (application accept) and are logged but otherwise ignored.
