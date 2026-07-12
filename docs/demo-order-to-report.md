# Imladris — Order-to-Report Demo Script

Full clinical radiology workflow: OpenMRS order → AdvaPACS review → modality acquisition →
Qure.ai AI analysis → AdvaPACS reporting.

**Audience:** Clinical and technical stakeholders at Botsabelo Hospital.
**Duration:** ~15 minutes for the scripted run; allow 15 min for Q&A.

---

## Personas

| Role | Person | System login |
|------|--------|-------------|
| Ordering clinician | Dr. Thato Mokoena | OpenMRS — `tmokoena` |
| Radiologist / order approver | Dr. Yonathan (AdvaPACS) | AdvaPACS — `admin` |
| Radiographer (rad tech) | Mr. Mohapi | Modality console — no login |
| Reporting radiologist | Dr. Yonathan | AdvaPACS viewer |

---

## Pre-flight checklist

Before starting, confirm all services are running:

```
docker compose --profile full up -d   # from imladris/docker/ap-qs/
```

| Service | URL | Expected state |
|---------|-----|----------------|
| OpenMRS | https://imladrislab.org/openmrs | Login page |
| AdvaPACS | https://pih.advapacs.com | Orders list visible |
| Modality console | https://console.imladrislab.org | Worklist visible |
| AdvaPACS FHIR webhook | https://console.imladrislab.org/events | Events page accessible |

Confirm the patient **Thabo Tau** exists in both OpenMRS and AdvaPACS
(seeded via `seed_patients.py`). Confirm Thabo Tau's DOB and sex are populated
in AdvaPACS — the DICOM validation check will reject the study otherwise.

---

## Step 1 — Clinician places order (Dr. Mokoena, OpenMRS)

**Actor:** Dr. Mokoena at the OpenMRS workstation.

1. Log in to OpenMRS as `tmokoena`.
2. Find patient **Thabo Tau**.
3. Start a visit → **Order Radiology Study**.
4. Select order type **Chest X-Ray (CR)**, set urgency **Routine**.
5. Submit.

**What happens (automated, ~10 sec):**
- `order_poller` detects the new order and creates a **ServiceRequest** in AdvaPACS
  with `status=draft`.
- AdvaPACS fires an **ORDER_CREATED** webhook to the sidecar.
- Sidecar updates `_order_states` with `status=draft`.
- `fhir_mwl_poller` writes a `.wl` worklist file for the order.

**What to show the audience:**
- Refresh the Modality console → Thabo Tau appears with badge **Pending Review** (blue).
- Image Patient button is **greyed out** — the order has not been approved yet.
- Click **Events** in the nav bar → show the ORDER_CREATED webhook payload.

> **Talking point:** The order is in the system but intentionally blocked from imaging.
> A clinician has to review and approve it first. Nothing goes to the X-ray room without
> that sign-off.

---

## Step 2 — Radiologist reviews and approves (Dr. Yonathan, AdvaPACS)

**Actor:** Dr. Yonathan at the AdvaPACS workstation.

1. Open AdvaPACS Orders list.
2. Find the new order for Thabo Tau (status shown as **Draft** in AdvaPACS UI).
3. Open the order, review procedure and patient demographics.
4. Change status to **In Progress** (AdvaPACS term for FHIR `active`).
5. Save.

**What happens (automated, ~2 sec):**
- AdvaPACS fires an **ORDER_UPDATED** webhook (`status=active`).
- Sidecar receives webhook → fetches full ServiceRequest from AdvaPACS FHIR R5 →
  updates `_order_states` with `status=active`.

**What to show the audience:**
- Refresh the Modality console → badge changes to **Approved** (green).
- Image Patient button is now **active** (green, clickable).
- Events page shows the ORDER_UPDATED event.

> **Terminology note:** AdvaPACS calls this state "In Progress"; our console calls it
> "Approved." Both refer to FHIR `active` — the order has been clinically cleared for
> imaging. We can align the label if the site team prefers "In Progress."

> **Talking point:** No one had to call the X-ray room. The badge changed the moment
> Dr. Yonathan clicked Save in AdvaPACS. Mr. Mohapi sees it immediately on the console.

---

## Step 3 — Radiographer images the patient (Mr. Mohapi, Modality console)

**Actor:** Mr. Mohapi at the modality console workstation.

1. Open the Modality console → confirm Thabo Tau shows **Approved**.
2. Verify patient name, ID, and procedure match the request form (manual ID check).
3. Click **Image Patient**.

> **Rad tech QA note:**
> In a real workflow the radiographer confirms patient identity at the machine and
> checks image quality before releasing to the radiologist. Currently the Image Patient
> button press is the implied go-ahead. The site team should advise whether an explicit
> "Accept image quality" confirmation step is needed in the production flow.
> Note: AdvaPACS does not auto-close the order on study receipt (see Step 4), so
> there is a natural human QA gate before completion is recorded.

**What happens (automated):**
- Sidecar pulls the source DICOM from the Bophelong patient library for Thabo Tau.
- Demographics and accession number are patched onto the DICOM dataset.
- Study (1 series, typically 1–2 instances for CXR) is C-STOREd to the AdvaPACS gateway.
- Because modality is CR: study is **also** sent to Qure.ai simulator (`QUREAI` AE).
- Qure.ai simulator attaches a **Secondary Capture** (annotated overlay image) and
  sends it back to the sidecar's SCP relay.
- SCP relay immediately forwards the SC to the AdvaPACS gateway.
- AdvaPACS now holds: original CR + Qure.ai SC annotation in one study.

**What to show the audience:**
- Console button cycles: "Acquiring…" → "✓ Acquired".
- Open AdvaPACS study list → Thabo Tau's study appears with primary CR and Qure.ai SC.
- Modality console badge remains **Approved** — order is not yet closed (by design).

> **Talking point:** The AI analysis runs in parallel with no radiographer action.
> Dr. Yonathan will see the Qure.ai overlay automatically when opening the study.

---

## Step 4 — Radiologist accepts study; order marked completed

**Confirmed behaviour (tested 2026-07-12):**
AdvaPACS does **not** automatically transition the ServiceRequest to `completed` when
a study is received. The order stays **In Progress / Approved** until a human action
in AdvaPACS closes it. This is clinically correct — it provides a natural QA gate
between imaging and reporting.

**Actor:** Dr. Yonathan in AdvaPACS, after verifying the images are acceptable.

1. Open the order in AdvaPACS.
2. Confirm images are present and of diagnostic quality.
3. Change order status to **Complete**.
4. Save.

**What happens (automated, ~2 sec):**
- AdvaPACS fires **ORDER_UPDATED** webhook (`status=completed`).
- Sidecar receives webhook → fetches ServiceRequest → confirms `status=completed`.
- Sidecar sends **ORU^R01** to OpenMRS HL7 endpoint.
- OpenMRS marks the radiology order as fulfilled.

**What to show the audience:**
- Modality console badge changes to **Completed** (grey); Image Patient disabled.
- Order disappears from **Active Orders** view; visible under **All Orders**.
- Events page shows the ORDER_UPDATED event with `status=completed`.

> **ORU → OpenMRS status:** The sidecar successfully sends the ORU^R01.
> OpenMRS HL7 processing is confirmed working at the sidecar end;
> end-to-end delivery to the patient chart is pending HL7 module verification.

---

## Step 5 — Radiologist reads and reports (Dr. Yonathan, AdvaPACS)

**Actor:** Dr. Yonathan returns to AdvaPACS.

1. Open the completed study for Thabo Tau.
2. Qure.ai Secondary Capture is visible alongside the primary CR image.
3. Dictate or type the radiology report using AdvaPACS's built-in reporting tool.
4. Sign and release the report.

> **Next integration:** When the report is signed, AdvaPACS fires a **REPORT_CREATED**
> webhook. The sidecar can receive this and forward a second ORU^R01 to OpenMRS
> with the report text in the OBX segment, so the written report appears on the
> clinical chart. This is the next item on the integration roadmap.

---

## Confirmed state machine (tested 2026-07-12)

| AdvaPACS action | Webhook fired | Console badge | OpenMRS |
|-----------------|---------------|---------------|---------|
| `order_poller` creates order | ORDER_CREATED | **Pending Review** (blue) | Order placed |
| Dr. Yonathan → In Progress | ORDER_UPDATED | **Approved** (green) | — |
| Mr. Mohapi → Image Patient | *(none)* | still **Approved** | — |
| Dr. Yonathan → Complete | ORDER_UPDATED | **Completed** (grey) | ORU^R01 sent |

---

## Key talking points summary

| What the audience sees | What it means |
|------------------------|---------------|
| Order appears as **Pending Review**, button greyed | Order is gated — imaging cannot start without approval |
| Badge flips to **Approved** without page reload | Real-time webhook — approval in AdvaPACS reaches the X-ray room in ~2 seconds |
| Image Patient button activates | The approval directly enables the next step; no phone call needed |
| Badge stays **Approved** after imaging | Order is open — a radiologist still needs to accept the images |
| Qure.ai SC appears in study | AI analysis is automatic — radiologist sees it without any extra steps |
| Badge flips to **Completed**, button greys out | Feedback loop closed — the console reflects what actually happened |
| ORU on OpenMRS chart | The ordering clinician knows the study is done without checking AdvaPACS |

---

## Open questions for site team

1. **Label alignment:** Should the console show "In Progress" (matching AdvaPACS) or
   "Approved" (emphasising the authorisation act) for `status=active`?
2. **Rad tech QA step:** Is an explicit image quality acceptance step required at the
   console, or is the natural gate (radiologist closes the order in AdvaPACS) sufficient?
3. **Report delivery:** Should the signed report text appear on the OpenMRS clinical
   chart via a second ORU^R01, or is it sufficient for the radiologist to report in
   AdvaPACS only?
4. **Urgency / STAT orders:** Should STAT orders appear differently on the modality
   console (e.g., red highlight, sorted to top)?
5. **DOB / sex in DICOM:** AdvaPACS enforces that DICOM PatientSex and DOB match the
   patient record. Ensure all patients in AdvaPACS have these fields populated before
   go-live; a seeding gap caused a validation rejection during testing.
