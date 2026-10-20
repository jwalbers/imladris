# Qure.ai / MinXray handoff (as of 2026-10-19)

Ground truth: `docs/qure/MinXray_Qure_Integration_Reference.docx` (Appendix A = open questions).
Sources: `qXR-UM-03_4.2.pdf` (IFU v4.2, 1 Sept 2024, most authoritative) and `qTrack_Onprem manual V2.pdf`. Both are Qure-confidential.
We now have a Qure technical contact; open questions go to them.

## Architecture (working model)
- **MinXView** (MinXray acquisition software, DICOM 3.0) -> **Qure Gateway == DCMIO** (confirmed: qTrack manual FAQ) -> qXR AI (Qure cloud, or local on the qTrack laptop) -> results back as DICOM.
- Gateway/DCMIO does de-identification before upload and re-identification on return (Upload "Anonymize Fields" and Publishers "Fields To Deanonymize"; matches the IFU's "client-side re-identification module").
- **qTrack** (TB program management) syncs patient/clinical data to its own cloud workspace, probably via a proprietary REST path in the app, NOT through Gateway. This is inferred, not confirmed.
- qTrack laptop runs AI offline (confirmed, manual FAQ), so it needs a real GPU. Which GPU ships in it is unknown.
- qTrack appears to be a TB-focused configuration of the Qure.ai App platform (inferred from identical TB forms); version relationship unconfirmed.

## Confirmed facts
- Input: CR (1.2.840.10008.5.1.4.1.1.1) or DX (.1.1.1 For Presentation / .1.1.1.1 For Processing).
- IFU-documented output: Secondary Capture and/or GSPS (.11.1) plus PDF. Encapsulated PDF = .104.1.
- Hardware per IFU Table 7-1: recommended GTX 1080 Ti 12GB / min GTX 1070 Ti 8GB, i7 8th gen, 16/8GB RAM, Docker 20.10.14. The Tesla T4 is only the AWS cloud reference (g4dn.2xlarge), not the on-prem spec.
- HL7: Gateway has an outbound HL7 publisher (host/port). qER emits an .hl7 result file. **No FHIR anywhere.**
- No public DICOM Conformance Statement exists.

## Do not trust
- Public "Deployment Files" page (docker-compose.yml, image 3.1.5): "last updated 3 years ago". Its shared Docker Hub credential (a named Qure engineer's PAT, repo:read) authenticates but every `qureai/*` pull is denied. Don't build from it. The IFU describes a simpler download-URL installer for on-prem Gateway; ask Qure for that.
- Never write the token into any repo or doc.

## Top open items (full list: Appendix A)
1. DICOM port: 5252 (Gateway docs) vs 4242 (IFU). AE Title QUREAI. Config UI localhost:7000/config/. Confirm for the laptop build.
2. Is SR (structured report) a supported qXR output? The IFU omits it; the Platform API/qER specs list it. If yes, which SOP class: Chest CAD SR (.88.65) or Comprehensive SR (.88.33)?
3. Which Secondary Capture variant is sent (.7 / .7.2 / .7.3)? Why is GSPS missing from the DICOM publisher "Keys To Send" (SC/SR/pdf)?
4. Does MinXView emit DX For Presentation or For Processing, and which does qXR prefer?
5. GPU in the Qure-configured MinXray laptop; recommended GPU for a dedicated lab server; is the laptop tier the same on-prem product as the heavier docker-compose stack?
6. Request current on-prem Gateway package and credentials, plus a formal DICOM Conformance Statement.
