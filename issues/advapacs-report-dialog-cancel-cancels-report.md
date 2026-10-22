# AdvaPACS Reporting Worklist: "Cancel" in the report dialog cancels the report, not the dialog

**Target:** AdvaPACS Reporting Worklist (region `usa1`, tenant `pih.advapacs.com`)  
**Component:** Report editor dialog; worklist boards and transition buttons  
**Type:** Usability / data-safety issue  
**Priority:** Medium. A radiologist backing out of the editor silently removes the study from every normal board  
**Status:** Open. Found 2026-10-20 during the Qure/qTrack demo; workaround below

---

## Summary

In the report editor, the **Cancel** button does not just close the dialog. It sets the
**report** to *Cancelled* (FHIR `DiagnosticReport.status = cancelled`). The study then drops
off the usual boards (Ready to Report, etc.). Getting it back needs an admin: there is no
default board that shows cancelled reports, and no default transition out of *Cancelled*.

## Steps to reproduce

1. Send a study to AdvaPACS (any route; here a qTrack/qXR result pushed through the Qure
   laptop's gateway, accession `CXR8455`, which AdvaPACS put on the worklist as *Ready to Report*).
2. Open it from the Reporting Worklist and start a report.
3. Intending only to leave the editor, click **Cancel**.

**Expected:** the dialog closes; the study stays *Ready to Report* (or keeps its draft).  
**Actual:** the report becomes *Cancelled* and the study disappears from the worklist boards.

## Evidence

The lab's report console (AdvaPACS FHIR, webhook-triggered) recorded the sequence for
`CXR8455` (UTC):

| Time | Event |
|---|---|
| 22:02:39 | webhook `REPORT_CREATED` |
| 22:02:40 | `DiagnosticReport` first read back as **cancelled** |
| 22:04:55 | cancelled → `unknown` (Draft), after the recovery below |
| 22:09:55 | `unknown` → `partial` (Draft) |
| 22:10:10 | `partial` → `preliminary` |

## Workaround (admin)

1. Worklist admin: create a board that filters on the *Cancelled* status.
2. Add a transition button on it from *Cancelled* to *Ready to Report*.
3. Find the study on that board and use the button; the report can then be completed.

Keep the board; it is the only way to see cancelled reports.

## Suggested fix (for AdvaPACS)

- Label the button by what it does ("Cancel report"), and ask for confirmation, or
- add a separate **Close** that leaves the report and study state unchanged, and
- ship a default way to restore a cancelled report.

## Notes for demos and training

Close the report editor with the window's **X**, not **Cancel**, unless the report really
should be cancelled.
