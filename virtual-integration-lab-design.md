# Virtual Integration Lab Architecture
## Clinical Site with Cloud-Based PACS — MDR-TB Patient Population

### Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Virtual Lab Network (192.168.100.0/24)       │
│                                                                     │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────────┐  │
│  │  DICOM       │    │  OpenMRS     │    │   Cloud PACS         │  │
│  │  Modality    │───▶│  Server      │    │  (Orthanc / DCM4CHEE │  │
│  │  Simulator   │    │  + Radiology │    │   or cloud-hosted)   │  │
│  │  Container   │    │  Module      │    │                      │  │
│  │  .10         │    │  .20         │    │   .30 / external     │  │
│  └──────┬───────┘    └──────┬───────┘    └──────────┬───────────┘  │
│         │                  │                        │              │
│         └──────────────────┼────────────────────────┘              │
│                            │                                       │
│  ┌─────────────┐  ┌────────┴────────┐  ┌──────────────────────┐   │
│  │  Rad Tech   │  │  Radiologist    │  │  Clinician           │   │
│  │  WS VM      │  │  WS VM          │  │  WS VM               │   │
│  │  Win11 .40  │  │  Win11 .50      │  │  Win11 .60           │   │
│  └─────────────┘  └─────────────────┘  └──────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Component Specifications

### 1. DICOM Modality Simulator (Docker Container)

**Base image:** `orthancteam/orthanc` or custom Python image with `pydicom` + `pynetdicom`

**Capabilities to emulate:**
- Modality Worklist SCU (queries OpenMRS for scheduled exams)
- C-STORE SCU (pushes completed studies to cloud PACS)
- C-FIND SCP (responds to worklist queries)
- DICOM TLS optional for realistic security testing

**Source DICOM data (public domain / open license):**

| Dataset | Source | Relevance |
|---|---|---|
| TCIA NLST | cancerimagingarchive.net | Chest CT, low-dose |
| TCIA Tuberculosis-Chest-Radiographs | cancerimagingarchive.net | Direct TB relevance |
| NIH CXR14 | openaccess.nih.gov | 112k chest X-rays |
| RSNA Pneumonia Challenge | kaggle.com/rsna | Chest X-ray pathology |
| Montgomery County TB dataset | LHNCBC/NLM | 138 TB CXRs, annotated |

**Patient anonymization + re-identification pipeline:**

```bash
# Pipeline: source DICOM → strip PHI → inject fictional MDR-TB demographics
#
# Tools: dcm2niix (optional), pydicom scripts, dicomanon (MATLAB), or
#        Orthanc anonymization plugin + Lua/Python script
```

**Fictional patient population design:**
- 25-50 patients, mixed demographics, consistent with MDR-TB epidemiology
- Multiple imaging timepoints per patient (baseline, 2mo, 6mo) to simulate treatment monitoring
- Modality mix: CXR (PA + lateral), chest CT, optional sputum AFB smear scans
- DICOM tags to populate: PatientName, PatientID, PatientBirthDate, PatientSex, AccessionNumber, StudyDate, ReferringPhysicianName, InstitutionName (all fictional)

**Container compose snippet:**
```yaml
dicom-modality:
  image: orthancteam/orthanc:latest
  ports:
    - "4242:4242"   # DICOM port
    - "8042:8042"   # Orthanc REST API / web UI
  volumes:
    - ./dicom-data:/var/lib/orthanc/db
    - ./orthanc.json:/etc/orthanc/orthanc.json
  environment:
    ORTHANC__WORKLISTS__DATABASE: /var/lib/orthanc/worklists
```

---

### 2. Cloud PACS

**Options ranked by cost/complexity:**

| Option | Hosting | Cost | DICOM Standard | Notes |
|---|---|---|---|---|
| **Orthanc + plugins** | Self-hosted cloud VM (GCP/AWS/Azure) | ~$20-50/mo | Full DIMSE + DICOMweb | Best for lab control |
| **DCM4CHEE 5** | Self-hosted | Free | Full | More enterprise-realistic |
| **Google Cloud Healthcare API** | GCP managed | Pay-per-use | DICOMweb only | No DIMSE; needs adapter |
| **AWS HealthImaging** | AWS managed | Pay-per-use | DICOMweb | Similar limitation |
| **Orthanc on Fly.io / Render** | Managed PaaS | Free tier | Full | Easy for lab |

**Recommendation for lab:** Orthanc on a small cloud VM with the following plugins:
- `orthanc-dicomweb` — DICOMweb (WADO-RS, STOW-RS, QIDO-RS) for browser-based viewers
- `orthanc-authorization` — role-based access per workstation type
- `orthanc-postgresql` — persistent storage
- `stone-webviewer` — built-in zero-footprint viewer

---

### 3. Radiology Technologist Workstation (Windows 11 VM)

**Role:** Receives scheduled exams from OpenMRS worklist, QCs incoming images, sends corrected studies to PACS

**Software stack:**

| Software | Purpose | License |
|---|---|---|
| **Weasis** | DICOM viewer / QC | Open source (EPL) |
| **MicroDicom** | Lightweight DICOM viewer | Freeware |
| **Horos** (if Mac alt needed) | Advanced viewing | Open source |
| **OHIF Viewer** | Web-based, connects to DICOMweb PACS | Open source |
| OpenMRS patient portal | Worklist / scheduling | Web browser |

**Key workflows to configure:**
- Modality Worklist pull from OpenMRS Radiology Module
- C-STORE send to cloud PACS after acquisition
- Study verification / patient demographic QC

**VM specs:** 4 vCPU, 8GB RAM, 60GB disk, Windows 11 Pro

---

### 4. Radiologist Workstation (Windows 11 VM)

**Role:** Reads studies from PACS, generates structured radiology reports, signs and sends to OpenMRS

**Software stack:**

| Software | Purpose | License |
|---|---|---|
| **OHIF Viewer v3** | Diagnostic viewer with DICOMweb | Open source (MIT) |
| **Weasis** | Local DICOM viewer with tools | Open source |
| **3D Slicer** | Advanced TB lesion volumetrics | Open source (BSD) |
| **RadReport / MIRP** | Structured reporting templates | Open source |
| **OpenMRS** (browser) | Report submission | Web |

**OHIF configuration** points to cloud PACS DICOMweb endpoint. Use OHIF's built-in measurement tools for TB-specific findings (cavity size, consolidation extent, pleural effusion).

**Structured report templates to include:**
- Chest X-ray TB assessment (WHO scoring)
- CT chest for MDR-TB monitoring
- Treatment response comparison

**VM specs:** 8 vCPU, 16GB RAM, 100GB disk (GPU passthrough if available for 3D rendering), Windows 11 Pro

---

### 5. Clinician Workstation (Windows 11 VM)

**Role:** Reviews imaging + reports to guide MDR-TB treatment decisions; does not perform diagnostic reading

**Software stack:**

| Software | Purpose |
|---|---|
| OHIF Viewer (web, read-only role) | Image review |
| OpenMRS patient portal | Clinical records, treatment history, lab results |
| Browser-based report viewer | Radiology report access via OpenMRS |

**VM specs:** 2 vCPU, 4GB RAM, 40GB disk, Windows 11 Pro

---

### 6. OpenMRS Server

**Recommended distribution:** **Bahmni** (OpenMRS-based) — purpose-built for resource-limited settings, includes radiology workflow, lab module, and imaging integration out of the box.

Alternatively: **OpenMRS Reference Application** + **Radiology Module (OpenMRS-contrib)**

**Container compose:**
```yaml
openmrs:
  image: bahmni/openmrs:latest   # or openmrs/openmrs-reference-application
  ports:
    - "8080:8080"
  depends_on:
    - openmrs-db
  environment:
    DB_HOST: openmrs-db
    ...

openmrs-db:
  image: mysql:5.7
  volumes:
    - openmrs-db-data:/var/lib/mysql
```

**Key OpenMRS modules to install:**

| Module | Function |
|---|---|
| Radiology Module | DICOM MWL, study ordering, report storage |
| Bahmni-PACS Integration | Connects OpenMRS orders → PACS worklist |
| Reporting Module | TB outcome dashboards |
| Bahmni Apps (EMR) | Clinical encounter forms |

**HL7 / FHIR integration:**
- OpenMRS → Modality: HL7 ORM^O01 (order message) → converted to DICOM MWL entry
- PACS → OpenMRS: HL7 ORU^R01 (results) or FHIR DiagnosticReport
- Orthanc → OpenMRS: via `orthanc-hl7` plugin or custom webhook

---

## Integration Workflow (End-to-End)

```
1. Clinician orders chest imaging in OpenMRS
        │
        ▼
2. OpenMRS Radiology Module creates MWL entry
        │
        ▼
3. Rad Tech WS queries MWL → selects patient → "acquires" on modality simulator
        │
        ▼
4. Modality simulator C-STOREs DICOM study to cloud PACS
        │
        ▼
5. Cloud PACS sends HL7 ORM / webhook to OpenMRS marking study received
        │
        ▼
6. Radiologist WS fetches study via DICOMweb (WADO-RS) from cloud PACS
        │
        ▼
7. Radiologist reads, measures, creates structured report in OHIF / RadReport
        │
        ▼
8. Report stored in OpenMRS via HL7 ORU or FHIR DiagnosticReport
        │
        ▼
9. Clinician WS views images (read-only PACS access) + report in OpenMRS
        │
        ▼
10. Clinical decision: drug regimen adjustment, referral, etc.
```

---

## Hypervisor / Infrastructure Recommendations

**For a single-machine lab:**
- **VMware Workstation Pro** or **VirtualBox** for Windows 11 VMs
- **Docker Desktop** or **Podman** for DICOM modality + OpenMRS containers
- Host machine: 32GB+ RAM, 8+ cores, 500GB SSD recommended

**For a multi-machine / team lab:**
- **Proxmox VE** as hypervisor (free, supports LXC + KVM)
- All VMs and containers on a single Proxmox node or small cluster
- Internal VLAN for lab network isolation

**Networking:**
- Internal host-only network (e.g., 192.168.100.0/24) for all components
- NAT for outbound internet (Windows Update, software downloads)
- Optional: pfSense VM as gateway to simulate realistic network segmentation (clinical LAN vs. cloud PACS DMZ)

---

## MDR-TB Patient Data Design

**Suggested cohort structure:**
```
25 fictional patients
├── 5 newly diagnosed, pre-treatment (baseline CXR + CT)
├── 10 on treatment 2-month follow-up (comparative CXRs)
├── 5 treatment failure / disease progression
├── 3 culture conversion, improving radiographs
└── 2 pediatric cases (age-appropriate imaging)

Each patient record includes:
  - Fictional name, DOB, MRN, national ID
  - OpenMRS: HIV status, sputum culture results, drug regimen
  - 2-4 imaging studies at different timepoints
  - Completed radiology reports (for training reference)
```

---

## Suggested Build Order

1. Stand up OpenMRS/Bahmni container, verify web UI
2. Deploy DICOM modality simulator container, load TB DICOM dataset, run anonymization scripts
3. Deploy cloud PACS (Orthanc), configure AE titles, test C-STORE from modality
4. Configure OpenMRS → PACS MWL integration
5. Build Rad Tech Windows 11 VM, install Weasis, configure PACS connection
6. Build Radiologist Windows 11 VM, configure OHIF against cloud PACS DICOMweb endpoint
7. Build Clinician Windows 11 VM, configure read-only PACS access + OpenMRS access
8. Run end-to-end workflow test with one synthetic patient
9. Load full fictional patient cohort

---

## Key Open-Source Projects to Reference

| Project | URL | Role |
|---|---|---|
| Orthanc | orthanc-server.com | PACS + modality simulator |
| DCM4CHEE | dcm4che.org | Enterprise PACS alternative |
| OHIF Viewer | ohif.org | Diagnostic + clinical viewer |
| Weasis | weasis.org | Rad tech / radiologist viewer |
| 3D Slicer | slicer.org | Advanced volumetric analysis |
| Bahmni | bahmni.org | OpenMRS distro for resource-limited settings |
| pydicom | pydicom.github.io | DICOM scripting (anonymization pipeline) |
| pynetdicom | pydicom.github.io/pynetdicom | DICOM network services in Python |
| TCIA | cancerimagingarchive.net | Public domain DICOM datasets |
