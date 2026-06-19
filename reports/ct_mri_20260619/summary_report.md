# IMLADRIS Lab — DICOM Dataset Summary

**Generated:** 2026-06-19 09:54:36  
**Source:** `/Users/jalbers/git/PIH/imladris-basotho/CT&MRI STUDIES FROM BOPHELONG VIRTUALHOSPITAL`  
**GCS target:** `gs://botsabelo-hospital-records/botsabelo_processed/ct_mri`  

---

## Overview

| Metric | Count |
|---|---|
| Files scanned | 9,405 |
| Files read successfully | 9,405 |
| Read errors / skipped | 0 |
| Unique patients | 7 |
| Unique studies | 7 |
| Unique series | 42 |
| Study date range | 2026-06-17 → 2026-06-17 |

---

## Modalities

| Modality | Instances |
|---|---|
| CT | 9,405 |

---

## Body Parts Examined

| Body Part | Instances |
|---|---|
| CHEST | 5,239 |
| BRAIN | 3,280 |
| ABDOMEN | 879 |

---

## Patient Demographics

| Sex | Patients |
|---|---|
| Female | 3 |
| Male | 3 |
| Other | 1 |

---

## Studies

| Patient ID | Patient Name | Date | Description | Modalities | Series | Instances |
|---|---|---|---|---|---|---|
| 0000001 | Anonymous Patient | 2026-06-17 | BRAIN | CT | 5 | 1202 |
| 0000008 | Anonymous Patient | 2026-06-17 | CT CHEST  PRE AND POST CONTRAST | CT | 5 | 2646 |
| 12345678 | Anonymous Patient | 2026-06-17 |  | CT | 3 | 459 |
| 0000005 | Anonymous Patient | 2026-06-17 | Chest Pre Contrast | CT | 8 | 2138 |
| 0000011 | Anonymous Patient | 2026-06-17 | CT BRAIN UNCONTRASTED | CT | 11 | 2080 |
| 0000007 | Anonymous Patient | 2026-06-17 | Abdomen Pre & Post Contrast | CT | 7 | 850 |
| 0000014 | Anonymous Patient | 2026-06-17 |  | CT | 3 | 30 |

---

## Data Quality

| Field | Missing instances | % |
|---|---|---|
| PatientID | 0 | 0.0% |
| StudyDate | 0 | 0.0% |
| Modality | 0 | 0.0% |
| InstitutionName | 9,405 | 100.0% |

---

## GCS Upload

Files to upload: **9,405** instances  
Target prefix: `gs://botsabelo-hospital-records/botsabelo_processed/ct_mri`  

```bash
# Upload (run from imladris-basotho directory):
gcloud storage rsync -r \
  "/Users/jalbers/git/PIH/imladris-basotho/CT&MRI STUDIES FROM BOPHELONG VIRTUALHOSPITAL" \
  "gs://botsabelo-hospital-records/botsabelo_processed/ct_mri"
```