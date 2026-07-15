# Study Reporting State Machine — Design Rationale

*Companion to `study-reporting-statemachine.sysml`*

---

## Governing standards

Three specifications directly constrain which states exist and what they mean:

**FHIR R5 `DiagnosticReport.status`** is the primary driver. Any reporting
worklist we build will publish FHIR DiagnosticReport resources, and downstream
clinical systems (OpenMRS, the ordering provider's EHR) expect specific status
codes. The FHIR value set forces certain distinctions that might otherwise
collapse into a single "in progress" bucket: `preliminary`, `partial`, `final`,
`amended`, and `cancelled` are all distinct codes with defined semantics.

**DICOM PS3.3 SR Completion/Verification flags** constrain the transition into
and out of the verified state. A Structured Report object carries
`CompletionFlag` (PARTIAL / COMPLETE) and `VerificationFlag` (UNVERIFIED /
VERIFIED). The moment a radiologist digitally signs, the SR must be reissued
with VERIFIED — which is what triggers the `verified` → `archived` path.
Amendment requires creating a *new SR version* linked to the original by
`PredecessorDocuments` sequence, not overwriting the signed record.

**IHE Scheduled Workflow (SWF)** integration profile governs the pre-reading
states. The `orderPlaced → readyToImage → readyToRead` chain maps directly to
the IHE SWF transaction set (order placement, modality worklist scheduling,
image availability notification). This matters for DICOM MWL integration with
AdvaPACS.

---

## Why `amended` is a separate state (not a loop back to `verified`)

A correction after sign-off is legally and technically distinct from an
original report:

- FHIR mandates `status = amended` on the *new* resource; the original resource
  must remain accessible with `status = final`. These are different resource
  instances, linked by `basedOn` or explicit reference.
- DICOM requires a new SR SOP Instance with its own UID, carrying the original
  in `PredecessorDocuments`. Overwriting the signed SR is not conformant.
- Audit trail: regulators and medicolegal review expect to see both versions.

The `amended` state holds the work-in-progress correction. Once re-signed it
transitions back to `verified` (FHIR `final` on the new version), closing the
loop cleanly while preserving both versions in the record.

---

## Why `preliminary` is a state, not just a transition

FHIR `DiagnosticReport.status = preliminary` is a first-class status code for
urgent verbal findings communicated before dictation is complete. Radiologists
treating STAT cases routinely phone the ordering provider before finishing the
full report. Modeling this as a transition effect (rather than a state) would
lose the ability to query "which studies have a preliminary out but no final"
— a common worklist filter for attending review and for tracking compliance with
turnaround-time targets.

---

## Why `rejected` and `cancelled` are separate

`rejected` is **not** terminal — it models "study cannot be read, may reimage."
`cancelled` is terminal — "no further action intended." FHIR maps both to
`cancelled`, but from a worklist standpoint the technologist needs to see
rejected studies (to schedule a repeat acquisition) while administrators need
to see cancelled ones (for billing/closure). Collapsing them would require
filtering on a separate reason code rather than the state itself.

---

## FHIR status mapping summary

| State machine state | FHIR `DiagnosticReport.status` |
|---|---|
| orderPlaced / readyToImage / readyToRead / reading | *(no report resource yet)* |
| preliminary | `preliminary` |
| reported / transcribing | `partial` |
| verified | `final` |
| amended (in progress) | `amended` |
| rejected / cancelled | `cancelled` |
| archived | *(operational; no FHIR equivalent)* |
