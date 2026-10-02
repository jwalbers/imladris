# MinXray wireless detector simulator

Simulates a MinXray CMDR wireless DR station on the Qure.ai field laptop. A real
system runs OR Technology's **dicomPACS DX-R** acquisition software with a
**CareRay CareView 1500Cw** panel (FDA K201575). This simulator plays the same
DICOM role against the local Qure.ai stack:

```
qTrack "Register" ──HTTP POST /patient/add──▶ MWL server (qureai/dicom-scp)
                                                  │ ▲
                              C-FIND (worklist) ◀─┘ │ MPPS N-CREATE "IN PROGRESS" / N-SET "COMPLETED"
                                                  ▼ │
                                          minxray-sim ──C-STORE DX──▶ dcmio :5252 ──▶ qureapi ──▶ qXR (GPU)
```

Source images are public chest X-ray PNGs (e.g. the NCR/NIH library in GCS).
They are converted per [docs/minxray-detector-specs.md](../docs/minxray-detector-specs.md):
resampled into the 2304×2816 @ 0.154 mm panel, given collimation, MTF blur,
Poisson and electronic noise, and written as **DX For Presentation, MONOCHROME2,
16-bit**. Every image is marked synthetic (`ImageType DERIVED\SECONDARY`, with a
`DerivationDescription` naming the source PNG and parameters), and the
Manufacturer/Model tags say "simulated".

## Quick start (inside the Qure docker network)

The clone's Qure stack (`platform`) must be running.

```powershell
cd C:\Dev\git\imladris\minxray-sim
# put source PNGs in .\library  (see "Source images")
docker compose build
docker compose run --rm minxray-sim worklist                 # what qTrack has scheduled
docker compose run --rm minxray-sim capture --index 0        # expose row 0 with a random library PNG
docker compose run --rm minxray-sim capture --accession ACC123 --image /library/00000001_000.png --dose 0.8
```

Every sent instance is also saved to `.\output\`.

Running on the host instead (venv): `python minxray_sim.py worklist`. The defaults
target `127.0.0.1:9003` (MWL) and `127.0.0.1:5252` (dcmio).

| Command | Does |
|---|---|
| `worklist [--station MIX] [--date YYYYMMDD] [--modality DX]` | MWL C-FIND, prints the scheduled items |
| `capture (--index N \| --accession A \| --patient-id P) [--image PNG]` | MPPS IN PROGRESS → build DX from the worklist item → C-STORE → MPPS COMPLETED |
| `convert PNG OUT.dcm [--patient-name ...]` | Offline conversion only |

Simulation options, shared by `capture` and `convert`: `--panel {wireless154,toshiba140,enduras120}`,
`--dose`, `--seed`, `--anatomy-fraction`, `--presentation {presentation,processing}`,
`--defects`, `--image-type-original`.

## Enabling qTrack's worklist mode (one-time, in the clone)

qTrack only pushes registered patients to the MWL server, and shows the MPPS
progress states (REGISTERED / IN PROGRESS / COMPLETED / DISCONTINUED), when
the frontend flag **`NEXT_PUBLIC_IS_MWL_ENABLED`** is `"true"`. It is off in
this install. On-prem, the frontend reads flags from
`window.__RUNTIME_CONFIG__`, which is set by `runtimeConfig.js`. That file is
bind-mounted into `qure-app-frontend`, so no restart is needed:

1. Edit `%USERPROFILE%\qure-dev\qureapp\runtimeConfig.js`. This is the clone's copy; leave the `qure` user's copy alone.
2. In the `window.__RUNTIME_CONFIG__` object, add `NEXT_PUBLIC_IS_MWL_ENABLED: "true"`. If
   `NEXT_PUBLIC_DISABLE_MWL_CALL` is present, make sure it isn't `"true"`.
3. Hard-refresh qTrack (Ctrl+F5), register a patient, then run `worklist`. The patient should appear.

## What the reverse engineering found (clone, 2026-09-30)

- **MWL server** (`mwl`, host `:9003` → container `:222`; HTTP API host `:9002`):
  - Accepts any calling or called AE title.
  - Supports MWL C-FIND and MPPS, **Implicit VR LE only**.
  - Items created by the installer's E2E tests use **Modality `DX`, ScheduledStationAETitle `MIX`**.
  - qTrack registers patients over HTTP: `POST <host>:9002/patient/add` and `/patient/upsert`, body `{payload: {...patient}}`.
- **MPPS caveat:** on N-CREATE, the MWL server calls back to the platform API (`POST /patients/<id>/`
  with `{"additional":{"mpps_progress":"IN PROGRESS"}}`). For the E2E test patients that call returned
  **HTTP 403**, and the server then **never answers the N-CREATE**. The simulator gives up after
  `MPPS_TIMEOUT` (10 s) and still stores the image. Still to be checked with a patient registered in qTrack.
- **dcmio gateway** (`:5252`):
  - Accepts any AE title.
  - Accepts DX For Presentation, DX For Processing, CR and Secondary Capture, in Explicit/Implicit VR LE,
    JPEG Lossless, JPEG 2000 Lossless and RLE.
  - Pipeline: filter → validate → upload to platform API (≈2 s) → qXR → publish.
  - The synthetic DX (`DERIVED\SECONDARY`, simulated manufacturer) **passes the filter**.
  - `Enabled publishers: []`: results currently go nowhere outside qTrack. The AdvaPACS gateway will be added here.
- **qXR** rejects non-anatomical test images with `UnsupportedScanError: Unsupported anatomy`, so format
  problems and content problems are easy to tell apart.

## Source images

`library/` and `output/` are git-ignored. Source images are the **TB Chest
Radiography Database** set from `imladris-data` (raw tier, public research
images, PNG named `Normal-N.png` / `Tuberculosis-N.png`), kept in their label folders:

```powershell
cd C:\Dev\git\imladris\minxray-sim
gcloud storage ls gs://imladris-raw/tb-cxr/set-1/Tuberculosis/ | Select-Object -First 5
gcloud storage cp "gs://imladris-raw/tb-cxr/set-1/Normal/Normal-1.png"             library\Normal\
gcloud storage cp "gs://imladris-raw/tb-cxr/set-1/Tuberculosis/Tuberculosis-1.png" library\Tuberculosis\
```

Per-image metadata for each class is in `gs://imladris-raw/tb-cxr/set-1/{Normal,Tuberculosis}.metadata.xlsx`.

Then `capture --label Tuberculosis` (or `--label Normal`) picks a random image of that class.
PNG and JPEG work, 8- or 16-bit grayscale. Each DICOM's `DerivationDescription` records the source as
`<label>/<file> (sha256 …)`, so any capture traces back to the exact library file
by content hash, the same scheme `imladris-data` uses for its manifests.

## Open items

- **Conversion bias on qXR TB score (found 2026-10-01).** For the same source image
  (`Normal/Normal-1500.png`, patient RQ23Z1), qXR on the direct PNG import gave Abnormal / **TB 0.28 (negative)**,
  while the simulator capture gave Abnormal / **TB 0.56 (presumptive)**. The pipeline (noise, MTF blur,
  log mapping, collimation, 16-bit) shifts the TB score up. Run a batch A/B (direct vs simulated, Normal and TB
  sets) and tune before treating simulator qXR scores as meaningful. Until then, label results "sample only".
  Confirmed same source: direct import corr +1.000, simulator anatomy crop +0.998, matching sha256.
- **qTrack drops the synthetic marker.** qTrack re-encodes received images as lossy JPEG baseline (q90) and
  **overwrites `DerivationDescription`** with its compression note, so the "SYNTHETIC … sha256" provenance is lost
  in qTrack's copy and in anything exported from it (e.g. to AdvaPACS). Only `output/` keeps it. Put the marker
  somewhere qTrack preserves as well (e.g. `ImageComments`, `SeriesDescription` or a private tag), and check the export.

- Replace the guessed tag values once the dicomPACS DX-R conformance statement arrives
  (request it from Qure/MinXray): PhotometricInterpretation, BitsStored, For Presentation vs For Processing, Manufacturer strings.
- MPPS round trip with a qTrack-registered patient; fix or report the 403 callback.
- A simple "capture" UI (e.g. a small web page) instead of the CLI, for demos.
- Later: run on a separate device over Wi-Fi to exercise the TP-Link "retrofit" network path.
