# IMLADRIS PACS adapter

Sends each completed qTrack/qXR study to the laptop's AdvaPACS gateway as one
consistent DICOM study. It is arrows ⑬–⑭ in
[docs/qure-field-laptop-workflow.drawio](../../docs/qure-field-laptop-workflow.drawio).

| Object | Source |
|---|---|
| Primary DX | MinXray simulator's **lossless** original (`minxray-sim/output/`, matched by SOP Instance UID). Falls back to qTrack's stored copy (lossy JPEG) for non-simulator studies |
| qXR secondary captures (with / without sidebar) | Qure filestore (`prod-data` volume, read-only) |
| qXR Basic Text SR | Qure filestore |
| qXR Encapsulated PDF report | Qure filestore |

**Normalization** applies the lessons from the first manual AdvaPACS uploads:
- invalid UIDs remapped deterministically (AdvaPACS silently drops them),
- accession ≤ 16 characters,
- one patient module on every object (name as Family^Given, sex and DOB from the platform DB),
- study date, time and description copied from the primary,
- UTF-8 (`ISO_IR 192`),
- the synthetic marker in `ImageComments` on the images.

Normalized copies of everything sent are kept in `output/` (git-ignored).

## Setup

- **Database:** read-only role `imladris_ro` in the clone's platform database, with SELECT on 5 tables
  (`portal_manager_patient`, `portal_manager_patient_image_studies`, `image_manager_imagestudy`,
  `image_manager_imageseries`, `image_manager_image`). Its password goes in the git-ignored `.env`
  (see `.env.example`). Remove the role with `DROP ROLE imladris_ro`.
- **AdvaPACS portal:** Remote AE `QURE01_ADP_01`, host = laptop IP, port 4243 (placeholder: the adapter
  only sends and never listens), **Allow IP Mismatch** on, and accepted as a calling AE on `QURE01_GW_01`.
- Requires the Qure stack (`platform_default` network) and the `advapacs-gateway` container.

## Use

```powershell
cd C:\Dev\git\imladris\qure\pacs-adapter
docker compose up -d                                             # watch: studies completed after first start
docker compose logs -f
docker compose run --rm pacs-adapter list                        # completed studies + what was sent
docker compose run --rm pacs-adapter send --patient-id AZ1234 --dry-run   # assemble + normalize, no send
docker compose run --rm pacs-adapter send --patient-id AZ1234             # (re)send one patient
```

A study counts as complete when qTrack marks its image `PROCESSED` and the SC, SR and PDF exist.
After `READY_TIMEOUT_SECONDS` (300) it sends whatever exists. Sent studies are recorded in `state/sent.json`.

With the adapter running, turn off the MinXray agent's direct forward (empty `FORWARD_TO` in
`minxray-sim/.env`), so AdvaPACS gets one primary per study.

## Later

Ask Qure about a supported **dcmio DICOM publisher** for qXR results. The adapter could then receive
studies over DICOM instead of reading their database and filestore.
