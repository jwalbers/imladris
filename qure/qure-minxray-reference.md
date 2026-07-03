# IMLADRIS Lab: Qure.ai / MinXray Integration Reference

**Imaging Lab for Digital Radiography Information Systems (IMLADRIS)**
**Document type:** Integration Reference
**Scope:** MinXray CMDR.T.120.60.S · MinXray DX-R · Qure.ai App · qXR · qTrack · PIH PACS
**Status:** Draft — synthesized from public documentation and vendor sources

---

## 1. Overview

This document describes the software architecture, data flows, and deployment
topology for integrating MinXray portable digital radiography systems with
Qure.ai's AI-powered chest X-ray interpretation (qXR) and care coordination
platform (qTrack), and how these connect to the PIH PACS.

It is intended to inform IMLADRIS lab simulator design, integration test
planning, and configuration of a Qure.ai App laptop node within the test lab.

### 1.1 System Components

| Component | Vendor | Role |
|---|---|---|
| MinXray CMDR.T.120.60.S | MinXray, Inc. | Portable digital radiography system (generator + DR detector + laptop) |
| MinXray DX-R | MinXray, Inc. | Image acquisition, patient registration, QA software (Windows, on-system laptop) |
| Qure.ai App (DCMIO / Gateway) | Qure.ai | DICOM Input/Output forwarder; routes studies to qXR; publishes results back |
| qXR | Qure.ai | AI chest X-ray interpretation engine; detects 30+ abnormalities including TB |
| qTrack | Qure.ai | Care coordination platform; patient channel, TB clinical forms, worklist, dashboards |
| PIH PACS | Partners in Health | Institutional PACS for image archival, routing, and radiologist review |

### 1.2 Naming Conventions Used in This Document

- **DX-R** — MinXray's image acquisition software installed on the CMDR.T.120.60.S laptop
- **Qure.ai App** — The unified desktop/mobile/web application that surfaces both the qXR AI worklist and the qTrack patient care coordination channel
- **DCMIO / Gateway** — Qure.ai's Windows service that acts as DICOM SCP/SCU forwarder, installed alongside the Qure.ai App; the terms are used interchangeably in Qure's documentation
- **qXR** — The AI inference module for chest X-ray; can run cloud-side or on-premises
- **qTrack** — The care coordination layer within the Qure.ai App (patient channel, clinical forms, GeneXpert, TB vouchers); this is the marketing name for what the documentation calls the Qure.ai App's patient management features

---

## 2. Architecture

### 2.1 Software Layering on the MinXray Laptop

The MinXray CMDR.T.120.60.S ships with three co-resident software systems on
a single Windows laptop:

```
┌─────────────────────────────────────────────┐
│           MinXray CMDR Laptop (Windows)     │
│                                             │
│  ┌─────────────────┐  ┌──────────────────┐  │
│  │  MinXray DX-R   │  │  Qure.ai App     │  │
│  │  (acquisition,  │  │  (qTrack patient │  │
│  │   QA, DICOM)    │  │   channel, AI    │  │
│  └────────┬────────┘  │   worklist)      │  │
│           │ DICOM     └────────┬─────────┘  │
│           │ C-STORE            │ REST API    │
│           ▼                    ▼             │
│  ┌─────────────────────────────────────┐    │
│  │      DCMIO / Gateway (Windows svc) │    │
│  │  - DICOM SCP (receives from DX-R)  │    │
│  │  - Filter config                   │    │
│  │  - Anonymize fields                │    │
│  │  - Metadata swap / append          │    │
│  │  - Publisher: DICOM / API / HL7    │    │
│  └─────────────────┬───────────────────┘    │
│                    │                        │
│         ┌──────────┴──────────┐             │
│         ▼                     ▼             │
│  ┌─────────────┐   ┌────────────────────┐  │
│  │  qXR        │   │   PIH PACS         │  │
│  │  (local or  │   │   (DICOM C-STORE   │  │
│  │   cloud)    │   │    publisher)      │  │
│  └─────────────┘   └────────────────────┘  │
└─────────────────────────────────────────────┘
```

**Important:** DX-R and the Qure.ai App / DCMIO are not directly integrated
at the application level. Their relationship is purely DICOM: DX-R acts as
a DICOM SCU and pushes completed studies to the DCMIO acting as a DICOM SCP.
The DCMIO config requires both apps to be installed on the same Windows system.

### 2.2 DICOM Study Structure

A chest X-ray study processed through qXR produces multiple SOP instances
within a single Study Instance UID:

| Instance | SOP Class | Content |
|---|---|---|
| Primary | Digital Radiography (DX) `1.2.840.10008.5.1.4.1.1.1.1` | Original DR image from detector |
| Secondary Capture (SC) | Secondary Capture `1.2.840.10008.5.1.4.1.1.7` | qXR AI overlay / annotated image |
| Structured Report (SR) | SR TID1500 (optional) | Machine-readable AI findings |
| Encapsulated PDF (optional) | Encapsulated PDF `1.2.840.10008.5.1.4.1.1.104.1` | Human-readable qXR report |

The DCMIO `Keys To Send` publisher config controls which of SC / SR / PDF
are forwarded to downstream destinations (PIH PACS, modality).

### 2.3 qXR Deployment Modes

qXR inference can run in two modes. The MinXray bundle uses **on-premises**:

**Cloud mode (standard Qure.ai App deployment)**
- DICOM study sent by DCMIO to Qure.ai cloud (AWS) via HTTPS
- Inference runs on Qure cloud
- Results returned to DCMIO and surfaced in Qure.ai App
- Patient data, AI results, clinical forms persist in Qure cloud (AES-256-GCM at rest)
- Requires internet connectivity

**On-premises mode (MinXray bundle; offline-capable)**
- Full Qure platform API stack runs locally in Docker containers on the laptop
- Containers: nginx, qure-api (Gunicorn), Postgres, worker threads
- Model checkpoints for qXR (`cxr_checkpoints`) are pre-loaded locally
- Patient data, AI results persist in local Postgres instance
- Explicitly supports air-gapped/offline deployment; Docker images can be
  transferred via removable media if the system has no internet
- Gateway retry logic queues failed upload/process/result tasks and retries
  up to 5 times per hour when connectivity is restored

**Lab implication:** When hooking up a Qure.ai App laptop to IMLADRIS, determine
whether the license is cloud-mode or on-premises-mode. The integration test
topology and data persistence behaviour differs significantly between the two.

---

## 3. Workflows

### Workflow 1 — qTrack-First Worklist-Driven Field Screening (Primary)

This is Qure.ai's intended primary deployment model for public health TB
screening programs. It is patient-first: care coordination precedes imaging.

```
[CHW / Nurse]                [CMDR.T.120.60.S Laptop]           [PIH PACS / Cloud]
     │                              │                                    │
     │  Register patient            │                                    │
     │  in qTrack (mobile/web):     │                                    │
     │  - Demographics              │                                    │
     │  - TB risk factors           │                                    │
     │  - Symptoms form             │                                    │
     │  - GeneXpert order           │                                    │
     ▼                              │                                    │
  [qTrack patient                   │                                    │
   record created                   │                                    │
   in Qure cloud]                   │                                    │
     │                              │                                    │
     │  Patient arrives at          │                                    │
     │  CMDR.T.120.60.S ─────────▶ │                                    │
     │                         DX-R pulls MWL entry                     │
     │                         (DICOM Modality Worklist)                │
     │                         Patient auto-associated                   │
     │                              │                                    │
     │                         Radiographer images patient               │
     │                         DX-R QA (accept/reject)                  │
     │                              │                                    │
     │                         DX-R → DCMIO (DICOM C-STORE)             │
     │                         DCMIO → qXR (local or cloud)             │
     │                         qXR result → Qure.ai App                 │
     │                              │                                    │
     │  qXR result populates ◀──── │                                    │
     │  qTrack patient channel      │                                    │
     │  Care coordination triggered │                                    │
     │  (referral, alert, voucher)  │                                    │
     │                              │                                    │
     │                         DCMIO publisher → PIH PACS (optional)    │
     │                              │  ─────────────────────────────▶   │
```

**Key capability:** If DCMIO Modality Worklist (MWL) integration is configured,
DX-R can pull the pre-registered patient from qTrack so the radiographer does
not re-enter demographics at the scanner. This is the integration point that
avoids duplicate data entry and links the DICOM study to the qTrack patient record.

**Note:** MWL support requires DCMIO to expose a Worklist SCP that DX-R queries.
This capability is implied by the architecture but not explicitly documented in
Qure's public docs. Confirm with Qure.ai whether DCMIO provides MWL SCP or
whether the worklist-to-acquisition linkage uses a different mechanism
(e.g., manual patient ID entry matching).

---

### Workflow 2 — Offline Local Capture with On-Device AI Screening (Fallback)

Used when there is no network connectivity. All processing is local.

```
[CMDR.T.120.60.S Laptop]

  1. Radiographer registers patient in DX-R (manual entry)
  2. Chest X-ray acquired; image received from CsI DR detector panel
  3. DX-R QA: windowing, review, accept/reject, annotate
  4. DX-R pushes completed study → DCMIO (DICOM C-STORE, localhost)
  5. DCMIO applies filter config (e.g., BodyPartExamined == 'CHEST')
  6. DCMIO applies upload config:
       - Anonymize configured PHI fields before processing
       - Set batch size (default 32)
  7. DCMIO → local qXR (Docker on-prem stack, no internet required)
  8. qXR processes in < 60 seconds
  9. Results returned: SC image + SR + PDF
 10. DCMIO publisher (DICOM): sends SC/SR back to DX-R worklist
     (and/or queues for PIH PACS when connectivity restored)
 11. Results visible in Qure.ai App on same laptop
 12. qTrack patient channel updated locally (Postgres)

 Queued for sync when connected:
  - Studies re-uploaded to Qure cloud for audit/program dashboard
  - qTrack patient record synced to cloud tenant
```

**DICOM study output:**
- Study Instance UID: single, shared across all instances
- Series 1: Original DR image (primary)
- Series 2: SC image with qXR AI overlay
- Series 3 (optional): SR TID1500 structured report
- Series 4 (optional): Encapsulated PDF

**PHI handling:** DCMIO anonymization field list is configurable. In the offline
mode, the local Postgres retains full PHI. In cloud-upload mode, fields listed
in the `Anonymize Fields` upload config are stripped before the study leaves
the site. The `Fields To Deanonymize` publisher config re-attaches PHI to
the outbound DICOM when publishing back to the modality or PIH PACS.

**Relevant to IMLADRIS:** This is the workflow most testable without a live
Qure.ai cloud tenant. A local on-prem Docker stack can be used to simulate
the full offline flow end-to-end.

---

### Workflow 3 — Connected Upload with Cloud-Side AI and PIH PACS Archival

Used when site has reliable internet. Two sub-variants depending on where
Gateway (DCMIO) is deployed:

#### Variant A: Gateway on the Acquisition Laptop

```
[CMDR.T.120.60.S]  →  DX-R  →  DCMIO (laptop)  →  Qure.ai cloud (qXR)
                                      │                      │
                                      │      Results ◀───────┘
                                      │
                                      └─→  PIH PACS (DICOM C-STORE)
                                               Study: DR + SC + SR
```

DCMIO intercepts the study, uploads to Qure cloud for inference, receives SC/SR
results, then publishes the complete study (original + AI results) to PIH PACS.
The Qure.ai App on the same laptop displays the worklist and qTrack patient channel.

#### Variant B: Gateway at the PIH PACS / Site Server Level (Preferred for Multi-Modality)

```
[Any DICOM modality]  →  DICOM C-STORE  →  PIH PACS
                                                │
                                   Routing rule: forward to DCMIO
                                                │
                                                ▼
                                         DCMIO (site server)
                                                │
                                                ▼
                                         Qure.ai cloud (qXR)
                                                │
                                         Results ◀──┘
                                                │
                                                ▼
                                         PIH PACS: SC + SR
                                         appended to original study
```

This decouples qXR processing from any individual acquisition device. Any
DICOM-conformant modality at the site (not just the MinXray) benefits from
AI interpretation without per-device Gateway configuration.

**PIH PACS routing rule:** Configure a DICOM routing rule to auto-forward
incoming chest X-ray studies (filter on Modality = CR/DR/DX, BodyPartExamined
= CHEST) to the site DCMIO AE Title. Results are pushed back by DCMIO publisher
config and appended to the original study in PIH PACS.

---

## 4. DCMIO / Gateway Configuration Reference

The Gateway configuration consists of four blocks, all administered through
the DCMIO local web UI at `localhost:7000/config/`.

### 4.1 API Config (Cloud Credentials)

Provisioned by Qure.ai. Required fields:

| Field | Description |
|---|---|
| Base URL | Qure.ai cloud API endpoint (region-specific) |
| Username | Cloud identity name |
| Source | Cloud identity source name |
| Sitename | Unique name for this deployment location |
| Token | Authentication/license key |
| Number of threads | Default: 5 |
| Enable compute | For series-based processing (qER/qCT): enable and set `process_delay`. For single-instance (qXR): leave disabled. |

**process_delay:** Edit via `localhost:7000/config/`, locate `"stability"` section,
change `"process_delay"` value (default 20 seconds). POST to save.

### 4.2 Filter Config

Controls which incoming studies are forwarded to qXR for processing.

```
Enable Query: ☑
Query: {metadata__BodyPartE} == 'CHEST'
```

Query syntax references DICOM metadata fields by name (case-sensitive).
Multiple conditions can be combined.

### 4.3 Upload Config

| Setting | Notes |
|---|---|
| Batch size | Default 32; number of images uploaded per batch |
| Enable compression | Select and set `+eb` for default compression |
| Anonymize Fields | Per-field list stripped before cloud upload |

Example fields to anonymize:
`PatientID`, `PatientName`, `InstitutionName`, `InstitutionAddress`,
`ReferringPhysicianName`, `OperatorsName`, `PatientBirthDate`,
`StationName`, `AdditionalPatientHistory`, `PatientComments`,
`PlateID`, `AdmissionID`

**IMLADRIS / PHI note:** For the PIH Lesotho deployment, align the anonymize
field list with the DICOM PS3.15 de-identification profile and the Lesotho
Data Protection Act 2012 requirements. The Gateway anonymization operates
upstream of cloud transmission; PHI in the local Postgres is not anonymized.

### 4.4 Publishers Config

The DCMIO can send results to up to four destination types. Configure each
with Enable checkbox + destination details:

**DICOM Publisher (back to modality or PIH PACS):**

| Field | Value |
|---|---|
| Remote AET | AE Title of PIH PACS or modality |
| Remote Address | IP address of destination |
| Remote Port | DICOM port of destination |
| Compression | Optional |
| Keys To Send | `SC` and/or `SR` and/or `pdf` |
| Fields To Deanonymize | Re-attach PHI stripped at upload (list same fields) |

**Publisher filtering** (since Gateway v1.0.17): Publishers can be filtered
on AI results, DICOM metadata, and DICOM private tags. Example: only forward
to PIH PACS if qXR result is ABNORMAL.

**DICOM metadata transformations** (since Gateway v1.0.16):
The Gateway can swap metadata fields and append values from one metadata field
to another before publishing. This enables tag morphing at the routing layer
without upstream changes.

**Standalone DICOM sorter mode:** As of recent Gateway versions, DCMIO can
act as a high-performance standalone DICOM sorter based on DICOM tags, metadata,
or private tags — routing to different PACS destinations based on Modality,
AE Title, AE IP Address + Port, or AI result. This is useful for multi-site
deployments routing to site-specific PIH PACS nodes.

**API Publisher:** For forwarding results to external REST endpoints (e.g.,
OpenMRS, DHIS2, or a custom PIH integration layer).

**HL7 Publisher:** For sending results to RIS or EHR via HL7 v2 (host + port).

---

## 5. Modality-Side Configuration (DX-R to DCMIO)

On the MinXray DX-R laptop, configure DCMIO as a DICOM archive node:

1. In DX-R DICOM settings, add DCMIO as an archive destination:
   - **Alias / Name:** DCMIO (or descriptive label)
   - **AE Title:** As configured in DCMIO (customizable since v1.0.14)
   - **IP Address:** 127.0.0.1 (same machine)
   - **Port:** DCMIO DICOM listen port (check via `netstat -na`)
2. Enable **Always send images to this archive** for auto-push on study completion
3. Verify connection using DX-R's DICOM Echo / Ping function

**Troubleshooting checklist:**
- Ping `127.0.0.1` from Command Prompt
- `netstat -na` — confirm DCMIO port is listening
- `telnet 127.0.0.1 <port>` — confirm port is accessible
- Check Windows Defender Firewall / antivirus if connection fails
- Use DVTK Storage SCU Emulator to send test DICOM files directly to DCMIO
- DCMIO Status page at `localhost:7000` shows received studies and task queue

---

## 6. Data Persistence and Cloud Sovereignty

### 6.1 Standard Cloud Deployment

All patient data, AI results, imaging studies, qTrack clinical forms, and
care coordination records persist in Qure.ai's cloud infrastructure (AWS).

- Encryption at rest: AES-256-GCM
- Active-active HA across AWS availability zones
- Backups with restoration tests twice yearly
- Audit logs retained 1 year (AWS CloudWatch / Graylog)
- ISO 27001 certified (periodic external audit)
- Auth: Keycloak OIDC (`accounts.qure.ai`)

### 6.2 On-Premises Deployment (MinXray Bundle Mode)

Local Docker stack retains all data in an on-device Postgres instance:

- `CLEAN_UP_AFTER_PROCESSING=True` — image files purged from local filesystem
  after `CLEAN_UP_DELAY=3600` seconds (1 hour) by default
- Postgres data volume persists patient records, study metadata, AI results
- Auth still references `https://accounts.qure.ai/auth` (Keycloak) — requires
  connectivity for initial authentication; token caching behaviour for
  fully offline operation should be confirmed with Qure.ai
- Retry logic: failed upload/process/result tasks retried 5×/hour when
  connectivity restored (max retry configurable via `max_retry_task`)

### 6.3 Open Questions for PIH Lesotho Deployment

The following require direct clarification from Qure.ai before production:

1. **Sync scope:** When on-prem instance reconnects, what data is synced to
   Qure cloud? Full patient demographics + clinical forms + imaging, or only
   AI results / aggregate metrics?
2. **MWL source:** Does DCMIO expose a DICOM Worklist SCP for DX-R to query,
   or is patient-to-study linkage achieved by other means?
3. **Offline auth:** Can the Qure.ai App and qTrack patient channel function
   fully without reaching `accounts.qure.ai`? Token refresh interval?
4. **Data residency:** Can Qure.ai provision a tenant on an AWS region outside
   South Africa / EU for Lesotho Data Protection Act compliance?
5. **TR90B compatibility:** The MinXray AI bundle is specified for the TR90BH.
   Confirm with MinXray that a TR90B + compatible CsI DR panel + DX-R is
   supported for the qXR integration (the generator is not in the data path;
   the question is DX-R software version and detector panel compatibility).

---

## 7. qTrack Patient Channel — Clinical Data Elements

qTrack's patient channel captures the following structured data, all of which
is accessible to authorized users across mobile, desktop, and web interfaces:

**Demographics and registration:**
- Patient ID, name, date of birth, gender
- Socioeconomic data (programme-dependent)
- Workspace / source site assignment

**TB-specific clinical forms:**
- Risk groups (age, gender, HIV status, prior TB, contact history, etc.)
- Symptoms (cough, haemoptysis, night sweats, weight loss, etc.)
- TB vouchers
- Confirmatory lab tests: GeneXpert / CBNAAT results
- WHO Treatment Decision Algorithm A (TDA) for paediatric TB (added 2025)

**Imaging:**
- Chest X-ray DICOM viewer (AI overlay from qXR)
- qXR AI findings (30+ abnormalities, TB probability, contours)
- Follow-up scan comparison / disease progression quantification
- Secondary capture image with annotation

**Care coordination:**
- Automated study sharing to user groups
- Emergency activation alert
- Patient merge (duplicate resolution)
- Referral / next steps / comments
- Notifications (configurable per finding type)

**Program management (admin dashboard):**
- Case counts by site, status, finding
- Screening program health metrics

---

## 8. IMLADRIS Lab Integration Node — Qure.ai App Laptop

### 8.1 Purpose

Adding a Qure.ai App licensed laptop to the IMLADRIS lab allows end-to-end
testing of all three workflows against the actual Qure.ai software stack,
complementing simulated DICOM node testing.

### 8.2 Minimum Requirements (from Qure on-prem deployment specs)

| Resource | Minimum |
|---|---|
| OS | Windows 10/11 (64-bit) — DCMIO is Windows-only |
| CPU | Intel Core i5-8265U (4-core, 1.6–3.9 GHz) or equivalent |
| RAM | 8 GB |
| Storage | 256 GB SSD (qXR model checkpoints are substantial; verify with Qure) |
| Docker | Docker Desktop for Windows (for on-prem stack) |
| Network | DICOM port access to PIH PACS; HTTPS to Qure cloud (if cloud mode) |

**Note:** The on-prem deployment Docker Compose stack includes nginx, API server,
Postgres, and multiple worker containers plus model checkpoint volumes. A
machine with 16 GB RAM and 512 GB SSD is recommended for comfortable lab use
alongside DX-R and DCMIO.

### 8.3 Lab Network Configuration

```
IMLADRIS Lab Network

  ┌─────────────────────────┐
  │  Qure.ai App Laptop     │
  │  - DX-R (optional)      │
  │  - DCMIO / Gateway      │
  │  - Qure.ai App          │
  │  - Docker (qXR on-prem) │
  │                         │
  │  AE Title: QURE_DCMIO   │
  │  DICOM Port: TBD        │
  └────────────┬────────────┘
               │ DICOM C-STORE / C-FIND
               │
  ┌────────────▼────────────┐
  │  PIH PACS (AdvaPACS)    │
  │  (IMLADRIS instance)    │
  │                         │
  │  AE Title: PIH_PACS     │
  │  DICOM Port: 11112      │
  └────────────┬────────────┘
               │ DICOM routing rule
               │
  ┌────────────▼────────────┐
  │  MinXray CMDR simulator │
  │  (or real CMDR unit)    │
  │  DX-R → DCMIO push      │
  └─────────────────────────┘
```

### 8.4 Integration Test Scenarios

The following scenarios should be validated in the lab:

| # | Test | Expected result |
|---|---|---|
| T1 | DX-R DICOM Echo to DCMIO (localhost) | DICOM Echo success |
| T2 | DX-R study push → DCMIO → local qXR | SC + SR returned; visible in Qure.ai App |
| T3 | DCMIO publisher → PIH PACS | Study with SC + SR visible in PIH PACS |
| T4 | Filter config (BodyPartExamined ≠ CHEST) | Study not forwarded to qXR |
| T5 | Anonymize upload; deanonymize on publish | PHI stripped outbound; PHI restored in PACS |
| T6 | DICOM metadata swap | Tag values transformed per config before publish |
| T7 | qTrack patient registration → DX-R MWL pull | Patient auto-populated in DX-R |
| T8 | qTrack TB form completion → patient channel | Forms visible in Qure.ai App |
| T9 | Offline mode: disconnect network | qXR completes locally; results queue for sync |
| T10 | Reconnect: retry sync | Queued studies submitted; PIH PACS receives results |

### 8.5 Simulator Considerations

Until a live Qure.ai App license is available, the following simulation
approaches apply:

- **DCMIO simulation:** The Gateway's DICOM SCP behaviour can be partially
  simulated using dcm4che or Orthanc with a scripted response. However,
  the qXR inference and Qure.ai App patient channel cannot be meaningfully
  simulated without the real software.

- **qXR result injection:** For PACS integration testing, a test SC DICOM
  file with a synthetic qXR overlay can be pushed directly to PIH PACS
  to validate routing and display without a live qXR inference.

- **qTrack patient channel:** The `qtrack.qure.ai` and `qtrack-app.qure.ai`
  web endpoints are live (Qure-hosted). A Qure.ai trial or sandbox account
  may provide access for integration testing without a full production license.

---

## 9. Key Public Documentation Sources

| Source | URL |
|---|---|
| Qure.ai documentation root | `https://documentation.qure.ai/` |
| Full doc index (LLM-readable) | `https://documentation.qure.ai/llms.txt` |
| App User Manual | `https://documentation.qure.ai/users-manual/qure.ai-app-users-manual` |
| Gateway / DCMIO User Manual | `https://documentation.qure.ai/users-manual/gateway-user-manual` |
| DCMIO Configuration | `https://documentation.qure.ai/users-manual/gateway-user-manual/configuration` |
| Modality configuration | `https://documentation.qure.ai/users-manual/gateway-user-manual/configuration/setting-up-the-medical-system-modality-configuration/configuring-medical-system-modality` |
| Gateway release notes | `https://documentation.qure.ai/release-notes/gateway` |
| App release notes | `https://documentation.qure.ai/release-notes/qure.ai-app` |
| Platform API overview | `https://documentation.qure.ai/api/platform-api/overview` |
| On-prem deployment files | `https://documentation.qure.ai/api/platform-api/on-premises-deployment-specifications/deployment-files` |
| Security and privacy FAQ | `https://documentation.qure.ai/users-manual/qure.ai-app-users-manual/faqs/security-and-privacy` |
| TB clinical forms (symptoms) | `https://documentation.qure.ai/users-manual/qure.ai-app-users-manual/qure.ai-app-features/windows-mac-os-app-ui/patient-channel/to-add-clinical-forms/tuberculosis-diagnosis-forms/symptoms` |
| MinXray Impact TB landing page | `https://www.minxray.com/impact-tb-landing-page` |
| MinXray CMDR-ST Quick Setup (ManualsLib) | `https://www.manualslib.com/manual/2904754/Minxray-Cmdr-St-Series.html` |
| FIND.dx portable DR spec comparison | `https://www.finddx.org/wp-content/uploads/2023/12/20210407_rep_lsc_digital_chest_xray_tb_dx_ax_2_FV_EN.pdf` |
| MinXray TR90BH FDA 510(k) | `https://www.accessdata.fda.gov/cdrh_docs/pdf18/K182207.pdf` |
| MinXray Impact FDA 510(k) | `https://www.accessdata.fda.gov/cdrh_docs/pdf21/K210479.pdf` |
| qTrack product page | `https://www.qure.ai/product/qtrack` |

---

## 10. Contacts for Integration Questions

| Question | Contact |
|---|---|
| Qure.ai Gateway / DCMIO config | support@qure.ai or assigned client partner |
| MinXray technical support | drimaging@minxray.com · 1-800-221-2245 |
| MinXray dealer resources / service manuals | https://www.minxray.com/dealer-resources (dealer login required) |
| Qure.ai sales / deployment | https://www.qure.ai/product/qtrack (contact form) |

---

*Document synthesized from publicly available vendor documentation, FDA 510(k)
submissions, and product pages. Subject to revision as vendor documentation
evolves. Last updated: July 2026.*
