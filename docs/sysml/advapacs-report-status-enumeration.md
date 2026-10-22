# AdvaPACS report status enumeration

Reference for the report-workflow state machine
([study-reporting-statemachine.sysml](study-reporting-statemachine.sysml),
[design notes](study-reporting-design-notes.md)). Captured 2026-10-22 from the AdvaPACS
Reporting Worklist admin UI, where these values appear in board status filters and
transition-button definitions. AdvaPACS board statuses (Unread, Drafts, Prelims, Verified, …)
are built on them.

## As listed in AdvaPACS (verbatim, in order)

1. No Result
2. In Lab - Results Pending
3. Partial Results
4. Results Entered - Not Verified
5. Preliminary
6. Modified
7. Final
8. Amended
9. Corrected
10. Appended
11. Cancelled
12. Entered In Error
13. Unknown

The list looks like a union of two standard code sets (below).

## Two layers: worklist state vs report status

AdvaPACS transition definitions use two different state variables (as seen in the admin UI, 2026-10-22):

| Layer | Values | Where |
|---|---|---|
| **Worklist state** | Ready to Report, Draft, Preliminary, Verified, Archived, Cancelled (the lab's defined states) | transition *from* / *to*; board filters |
| **Report status** | the 13 values above (HL7 v2 table 0123 ∪ FHIR DiagnosticReport.status), single-select | the transition's "Report Status" property; per the AdvaPACS docs, "the status of the generated report after clicking the button" |

Working interpretation: firing a transition moves the study between worklist states **and** stamps the
report with one result status, which is what downstream systems receive (FHIR
`DiagnosticReport.status`, HL7 ORU OBR-25). E.g. Preliminary → Verified with report status Final.

**To confirm empirically:** fire each transition on a test study and read the resulting
`DiagnosticReport.status` in the report console's timeline. Record the results here as a
transition → report-status table; it is also the evidence for a product-improvement proposal
(the UI mixes a closed workflow list with an open standards code list without saying which system
consumes the second).

## Mapping to the standards

| AdvaPACS label | HL7 v2 result status (table 0123, OBR-25) | FHIR `DiagnosticReport.status` | Board (board state), observed | Notes |
|---|---|---|---|---|
| No Result | `O`: order received, specimen not yet received | `registered` | (not seen) | order exists, nothing reported yet |
| In Lab - Results Pending | `I`: in lab, results pending | `registered` | (not seen) | |
| Partial Results | `S`: partial | `partial` | Drafts (Draft): report saved | |
| Results Entered - Not Verified | `R`: results stored, not yet verified | `partial` (closest) | (not seen) | AdvaPACS-side "draft" report? to confirm |
| Preliminary | `P` | `preliminary` | Prelims (Preliminary) | |
| Modified | | `modified` (R5) | (not seen) | |
| Final | `F` | `final` | Verified (Verified); also Completed (Verified) | AdvaPACS shows "Verified" when a verifier (performer function `VRF`) is present |
| Amended | | `amended` | (not seen) | |
| Corrected | `C` | `corrected` | (not seen) | |
| Appended | | `appended` | (not seen) | |
| Cancelled | `X`: cannot obtain / cancelled | `cancelled` | Cancelled (Cancelled) | set by the report editor's **Cancel** button ([issue](../../issues/advapacs-report-dialog-cancel-cancels-report.md)) |
| Entered In Error | | `entered-in-error` | (not seen) | |
| Unknown | | `unknown` | Ready to Report after a reset from Cancelled; Drafts just after a report is opened | |

### By board

| Board | Board state (worklist state) | FHIR `DiagnosticReport.status` seen | Notes |
|---|---|---|---|
| Unread | **Ready to Report** | **none**: no DiagnosticReport exists yet | AdvaPACS creates the report when a radiologist opens the study; `unknown` seen once, after a reset from Cancelled |
| Drafts | **Draft** | `unknown` (just opened) → `partial` (saved) | FHIR-created orders land here on completion with **no** DiagnosticReport: a worklist state, not a report |
| Prelims | Preliminary | `preliminary` | |
| Verified | Verified | `final`, verifier = performer function `VRF` | |
| Completed | Verified | `final` | same state as Verified, different column layout |
| Cancelled (custom) | Cancelled | `cancelled` | report editor's Cancel button |
| (none yet) | Archived | | not observed |

So for FHIR consumers, **Ready to Report** has no report status at all, and **Draft** is `partial`
(or nothing, for FHIR-created orders). The transition test will tell which Report Status each
transition actually stamps.

The HL7 and FHIR columns are our inference from the labels; AdvaHealth hasn't published the
mapping. Confirm before the state machine depends on it.

By standard:

- **In both** (HL7 / FHIR): Partial Results (`S` / `partial`), Preliminary (`P` / `preliminary`),
  Final (`F` / `final`), Corrected (`C` / `corrected`), Cancelled (`X` / `cancelled`).
- **HL7 only:** No Result (`O`), In Lab - Results Pending (`I`), Results Entered - Not Verified
  (`R`). FHIR `DiagnosticReport.status` has no equivalent (and no `draft`), so AdvaPACS must
  translate these on the FHIR side, probably to `registered`, `partial` or `unknown`. To confirm.
- **FHIR only:** Modified, Amended, Appended, Entered In Error, Unknown.

FHIR R5 `DiagnosticReport.status` allows exactly 11 codes: registered, partial, preliminary,
modified, final, amended, corrected, appended, cancelled, entered-in-error, unknown. Design report
states around these, since that is what FHIR consumers (OpenMRS) receive.

## Observed so far (lab, FHIR `DiagnosticReport.status` via the report console)

| Situation | FHIR status seen | Worklist board / label |
|---|---|---|
| Completed order, study on the worklist, no report started | (no DiagnosticReport yet) | **Ready to Report** (Unread) for HL7- and ad-hoc orders; **Draft** for FHIR-created orders ([why](../../issues/advapacs-fhir-orders-enter-worklist-as-draft.md)) |
| Report started, saved | `unknown`, then `partial` | Drafts |
| Report released as preliminary | `preliminary` | Prelims |
| Report signed | `final`, performer with function `VRF` | Verified |
| Report editor **Cancel** | `cancelled` | (only on a custom Cancelled board) |

## Terminology to keep straight

- **Ready to Report** is the AdvaPACS worklist status for studies awaiting a radiologist. The
  SysML model's state is named `readyToRead`; align the name when the model is next revised.
- **"Draft"** means three different things: FHIR `ServiceRequest.status = draft` (an order
  not yet approved), the AdvaPACS worklist **Draft** board/status (a report in progress, or a
  completed FHIR-created order), and the report console's "Draft" badge (DiagnosticReport
  `registered` / `partial` / `unknown`).
