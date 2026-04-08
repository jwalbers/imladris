---
name: DICOM Modality Simulator Architecture Decision
description: Decided architecture for the DICOM modality simulator in the vesotho virtual integration lab
type: project
---

The DICOM modality simulator uses **Orthanc + Python sidecar (pynetdicom)**.

- **Orthanc** handles: TB DICOM image storage, C-STORE SCU (pushes studies to Cloud PACS via REST API `/modalities/{ae}/store`), anonymization plugin for fictional patient re-tagging
- **Python sidecar** handles: MWL C-FIND SCU (Orthanc cannot query worklists natively), polls OpenMRS MWL every 5 minutes, matches worklist entries to pre-loaded TB dataset by PatientID, triggers Orthanc REST API to push matched study to Cloud PACS

**Why:** Orthanc is the right image store and SCU for transmission, but cannot act as a MWL SCU (C-FIND client). pynetdicom fills that gap with minimal added complexity. DVTk and dcm4che tools were considered but rejected — DVTk is Windows-only/GUI, dcm4che tools require more wiring. pynetdicom in a sidecar keeps everything containerized.

**How to apply:** When designing or building the modality simulator container, always treat it as a two-service compose group: `orthanc-modality` + `modality-sidecar`. Do not try to make Orthanc query the MWL natively.
