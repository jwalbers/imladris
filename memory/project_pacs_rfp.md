---
name: PACS RFP and Virtual Integration Lab future use
description: PIH dev lead plans to use Imladris VIL to evaluate and integrate the new PACS being procured via RFP
type: project
---

PIH dev lead mentioned (for the first time) that he may use the Imladris Virtual Integration Lab for integrating the new PACS coming out of the active RFP process. The lab might serve as the integration test bench before production deployment at Botsabelo. This was a positive signal but not a firm commitment.

**Why:** Validates the lab's purpose — drop in the new PACS in place of orthanc-pacs and run the full end-to-end workflow.

**One vendor uses Orthanc as its base** — if that vendor wins, the swap may be near-trivial (AET/URL config change). For non-Orthanc vendors the integration surface is C-STORE in, DICOMweb out, MLLP ORU^R01.

**How to apply:** When the RFP winner is known, the next task is:
1. Update `PACS_URL`/`PACS_USER`/`PACS_PASSWORD` in docker-compose
2. Update `DicomModalities` in `orthanc/modality.json` with new AET/host/port
3. Verify DICOMweb root path for OHIF (`/dicom-web/` vs `/wado/` etc.)
4. Check auth model (Basic vs OAuth) and TLS requirements
5. Confirm SOP class acceptance (CR, US multiframe) via conformance statement
