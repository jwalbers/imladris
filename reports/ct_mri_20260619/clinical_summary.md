# Bophelong Virtual Hospital — CT Dataset Clinical Summary
**Prepared:** 2026-06-19  
**Dataset:** CT & MRI Studies from Bophelong Virtual Hospital  
**GCS:** `gs://botsabelo-hospital-records/botsabelo_processed/ct/`  
**Files:** 9,405 DICOM instances · 7 studies · 42 series  

---

## Executive Summary

This batch is a **pool of high-quality clinical CT studies** acquired on a Philips
Incisive CT (120 kVp, 1 mm thin-slice throughout). The set contains three body
regions — **brain, chest, and abdomen** — with full multi-phase contrast protocols
in most studies. It is suitable as a generic imaging pool for fictional patient
history construction; however, real patient demographics were stripped before
receipt and the 7 study containers do **not** represent 7 real patients.

> **For lab use:** treat these as 7 unnamed *imaging templates* representing
> clinically realistic CT presentations. Assign them to fictional census patients
> as needed for workflow testing.

---

## Scanner & Technical Parameters

| Parameter | Value |
|---|---|
| Manufacturer | Philips |
| Model | Incisive CT |
| Software | CHESS5_0 |
| Tube voltage | 120 kVp (all studies) |
| Tube current | 200–285 mA (AEC — varies by body habitus) |
| Primary slice thickness | 1 mm (thin-slice throughout) |
| Secondary reconstructions | 2–3 mm (standard); 4.65 mm (reformats) |
| Matrix | 512×512 (primary); 988×953 (MPR reformats) |
| Pixel spacing | 0.46 mm (brain); varies by FOV |

---

## Studies

### Study A — Brain, Pre + Post Contrast  
*(7 series · 1,202 instances)*

| Series | Description | Slices | Thickness |
|---|---|---|---|
| 101 | Localizer | 2 | — |
| 202 | Pre-contrast axial | 343 | 1 mm |
| 203 | Bone window | 171 | 2 mm |
| 302 | Arterial phase | 343 | 1 mm |
| 402 | Venous phase | 343 | 1 mm |

**CTDIvol:** 48 mGy  
**Protocol:** Brain Pre & Post Contrast  
**Clinical context:** Three-phase brain CT (pre/arterial/venous) with bone
reconstruction. Standard protocol for intracranial mass characterization,
vascular lesions, or metastatic disease workup. The bone series enables
assessment of calvarium and skull base.  
**Imaging findings potential:** Intracranial masses, AVM/vascular malformation,
leptomeningeal enhancement, bony metastases, skull fractures.

---

### Study B — Brain, Pre + Post Contrast  
*(11 series · 2,080 instances)*

| Series | Description | Slices | Thickness |
|---|---|---|---|
| 201 | Pre-contrast axial | 182 | 2 mm |
| 202 | Pre-contrast (thin recon) | 363 | 1 mm |
| 203 | Bone window | 182 | 2 mm |
| 301 | Arterial phase | 182 | 2 mm |
| 302 | Arterial (thin recon) | 363 | 1 mm |
| 401 | Delayed phase | 182 | 2 mm |
| 402 | Delayed (thin recon) | 363 | 1 mm |
| 36078–36081 | Coronal + sagittal reformats | 263 | 3 mm |

**CTDIvol:** 56 mGy  
**Protocol:** Brain Pre & Post Contrast  
**Clinical context:** Most complete brain study in the set — pre/arterial/delayed
phases plus full MPR reformats. The delayed phase (vs. venous in Study A)
suggests lesion characterisation requiring prolonged enhancement assessment.

> ⚠️ **Metadata inconsistency:** Study description is `CT BRAIN UNCONTRASTED`
> but series clearly include Arterial and Delayed contrast phases. The study
> description field should be treated as unreliable for this study.

**Imaging findings potential:** Same as Study A plus blood-brain barrier
breakdown assessment (delayed enhancement); excellent for simulating tumour,
abscess, or cerebral metastasis scenarios.

---

### Study C — Chest, Pre-Contrast Only  
*(5 series · 2,138 instances)*

| Series | Description | Slices | Thickness |
|---|---|---|---|
| 101 | Localizer | 2 | — |
| 202 | Pre-contrast axial | 886 | 1 mm |
| 501 | Arterial phase | 439 | 2 mm |
| 502 | Arterial (thin recon) | 880 | 1 mm |
| 503 | Lung window | 439 | 2 mm |

**CTDIvol:** 11 mGy (low-dose technique — typical for chest)  
**Protocol:** Chest Pre Contrast  
**Clinical context:** Despite the protocol name, this study includes an arterial
phase — suggesting a pulmonary embolism (PE) / CT pulmonary angiogram (CTPA)
protocol, or a combined chest oncology protocol. The dedicated lung window
series enables parenchymal assessment at 2 mm.  
**Imaging findings potential:**
- **TB presentations:** Consolidation, cavitation, tree-in-bud nodularity,
  miliary pattern, pleural effusion, mediastinal lymphadenopathy
- **PE:** Filling defects in pulmonary arteries (arterial series)
- **Malignancy:** Pulmonary nodules, masses, hilar/mediastinal nodes

---

### Study D — Chest, Pre + Post Contrast  
*(8 series · 2,646 instances)*

| Series | Description | Slices | Thickness |
|---|---|---|---|
| 101 | Localizer | 1 | — |
| 201 | Pre-contrast axial | 419 | 2 mm |
| 202 | Pre-contrast MPR | 512 | 0.7 mm |
| 203 | Lung window | 419 | 2 mm |
| 203 | Lung window MPR | 512 | 0.7 mm |
| 10001 | Dose record | 1 | — |
| 30841 | Coronal reformat | 116 | 2 mm |
| 30842 | Sagittal reformat | 158 | 2 mm |

**CTDIvol:** 12 mGy  
**Protocol:** Chest Pre & Post Contrast  
**Clinical context:** Sub-millimetre MPR reconstructions (0.7 mm) indicate a
high-resolution chest protocol, likely for detailed parenchymal or airway
assessment. Full triplanar reformats (axial/coronal/sagittal) make this the
most radiologically complete chest study in the set.

> ⚠️ **Series number conflict:** Two series are both numbered `203` (Lung 2mm
> axial and Lung 2mm MPR). This is a DICOM non-conformance that may cause
> display issues in some viewers.

**Imaging findings potential:** HRCT-quality parenchymal detail — ideal for
simulating interstitial lung disease, bronchiectasis (common in MDR-TB),
or subpleural nodule scenarios.

---

### Study E — Chest, Reformats Only  
*(3 series · 459 instances)*

| Series | Description | Slices | Thickness |
|---|---|---|---|
| 31107 | Sagittal | 63 | 4.65 mm |
| 31108 | Coronal | 52 | 3.65 mm |
| 31109 | Axial reformat | 344 | 1 mm |

**CTDIvol:** Not recorded (NaN)  
**Study description:** Not recorded  
**Patient ID:** 12345678 (non-standard format — possible test/QA entry)  
**Clinical context:** This study contains only reformatted series with no
primary axial acquisition or dose record, and the patient ID uses a non-standard
format. Most likely a secondary capture from a workstation-generated reformatted
series, or a study transferred from another system without its source series.

> ⚠️ **Low confidence study:** Missing dose record, study description, and
> standard patient ID. Treat as supplementary chest anatomy reference only.

---

### Study F — Abdomen, 4-Phase Contrast  
*(7 series · 850 instances)*

| Series | Description | Slices | Thickness |
|---|---|---|---|
| 101 | Localizer | 1 | — |
| 201 | Pre-contrast | 187 | 3 mm |
| 501 | Arterial phase | 193 | 3 mm |
| 601 | Venous phase | 185 | 3 mm |
| 701 | Delayed phase | 192 | 3 mm |
| 30214 | Coronal reformat | 45 | 2.6 mm |
| 30215 | Sagittal reformat | 47 | 2.7 mm |

**CTDIvol:** 17 mGy  
**Protocol:** Abdomen Pre & Post Contrast  
**Clinical context:** Classic 4-phase abdominal protocol (pre/arterial/portal
venous/delayed) — the gold standard for hepatic mass characterization. The
complete phase set enables differential diagnosis between HCC, metastases,
haemangioma, and other liver lesions. Series numbering (501/601/701) with gaps
suggests dedicated phase triggers.  
**Imaging findings potential:**
- Hepatic masses (HCC, cholangiocarcinoma, metastases, abscess)
- Renal lesions (cysts vs. masses, arterial vs. venous enhancement pattern)
- Pancreatic pathology
- Abdominal lymphadenopathy (TB, lymphoma)
- Peritoneal disease

---

### Study G — Abdomen, Thin Reconstructions  
*(3 series · 30 instances)*

| Series | Description | Slices | Thickness |
|---|---|---|---|
| 202 | Axial recon 1mm | 9 | 1 mm |
| 502 | Arterial recon 1mm | 13 | 1 mm |
| 602 | Venous recon 1mm | 8 | 1 mm |

**CTDIvol:** 14 mGy  
**Clinical context:** Very small study — thin 1 mm reconstructions only, no
primary 2–3 mm series, likely a targeted thin-slice reformat of a focal area
(e.g., specific organ or lesion follow-up). Only 30 images; limited standalone
utility. Best used as a supplementary reference.

---

## Clinical Categories Summary

| Category | Studies | Key Protocols |
|---|---|---|
| **Intracranial mass / vascular workup** | A, B | Brain pre + arterial + venous/delayed |
| **Pulmonary TB / MDR-TB pattern** | C, D, E | Chest pre ± arterial, lung window, HRCT |
| **Pulmonary embolism / CTPA** | C | Chest arterial phase |
| **Hepatic mass characterization** | F | 4-phase abdomen |
| **Abdominal oncology / lymphadenopathy** | F, G | Multi-phase abdomen |

### Signs & Symptoms This Pool Can Simulate

**Neurological**
- Headache, focal neurology → brain mass / AVM / metastasis (Studies A, B)
- Altered consciousness → intracranial bleed follow-up (bone + soft tissue series)

**Respiratory**
- Chronic cough, haemoptysis, night sweats → TB / MDR-TB (Studies C, D)
- Acute dyspnoea, pleuritic chest pain → PE (Study C arterial)
- Progressive dyspnoea → interstitial lung disease / bronchiectasis (Study D HRCT)

**Abdominal**
- Right upper quadrant pain, weight loss → hepatic mass (Study F)
- Abdominal distension, constitutional symptoms → peritoneal TB / lymphoma (Study F)

---

## Data Quality Notes

| Issue | Affected Study | Impact |
|---|---|---|
| Study description `UNCONTRASTED` but contrast series present | Study B | Low — series descriptions are accurate |
| Duplicate series number `203` | Study D | Medium — may confuse PACS/viewer ordering |
| Missing study description | Studies E, G | Low — body part and series descriptions intact |
| Missing dose record (CTDIvol NaN) | Study E | Low — reformats only, no primary acquisition |
| Non-standard Patient ID (`12345678`) | Study E | Low — treat as separate from numbered patients |
| No InstitutionName in any study | All | Low — expected for de-identified export |

---

## GCS Locations

| Body Part | GCS Prefix |
|---|---|
| Brain | `gs://botsabelo-hospital-records/botsabelo_processed/ct/brain/` |
| Chest | `gs://botsabelo-hospital-records/botsabelo_processed/ct/chest/` |
| Abdomen | `gs://botsabelo-hospital-records/botsabelo_processed/ct/abdomen/` |

Database-ready CSVs (instances, series, studies, patients):  
`gs://botsabelo-hospital-records/` — sync from `reports/ct_mri_20260619/`

---

## Recommended Next Steps

1. **View sample studies** in OHIF via the lab's Orthanc PACS (push one study via C-STORE to confirm viewer rendering)
2. **Assign to fictional patients** — draw from this pool when building patient histories; Studies A/B suit neurological presentations, C/D/E suit pulmonary, F/G suit abdominal
3. **Resolve Study B metadata inconsistency** — correct study description from `CT BRAIN UNCONTRASTED` to `CT BRAIN PRE AND POST CONTRAST` before assigning to a patient record
4. **Upload CSVs to BigQuery** for structured querying once patient assignment is done
