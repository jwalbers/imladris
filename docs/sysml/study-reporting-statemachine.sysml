// ============================================================================
// Study Reporting Workflow — SysML v2 State Machine
//
// Models the lifecycle of a radiology/cardiology study from image acquisition
// through final report archival, including consulting, transcription, and
// amendment paths.
//
// Design basis:
//   - IHE Scheduled Workflow (SWF) integration profile
//   - FHIR DiagnosticReport.status value set (R5)
//   - DICOM SR CompletionFlag / VerificationFlag
//   - AdvaPACS configurable worklist states
//
// FHIR DiagnosticReport.status mapping (where applicable):
//   readyToRead / reading    → partial (preliminary results not yet available)
//   preliminary              → preliminary
//   reported / transcribing  → partial (report exists, not yet verified)
//   verified                 → final
//   amended                  → amended
//   rejected / cancelled     → cancelled
//   archived                 → (no direct FHIR equivalent; operational state)
//
// DICOM SR flags (on the report object itself):
//   reported:   CompletionFlag = COMPLETE, VerificationFlag = UNVERIFIED
//   verified:   CompletionFlag = COMPLETE, VerificationFlag = VERIFIED
//   amended:    CompletionFlag = COMPLETE, VerificationFlag = VERIFIED (new version)
//
// AdvaPACS worklist configuration note:
//   Each state below corresponds to a configurable worklist column in AdvaPACS.
//   Transitions are the workflow action buttons visible to each user role.
//   Recommend hiding PRELIMINARY from non-urgent queues to avoid confusion.
//
// Standard:  SysML v2 (ISO/IEC 19514:2024)
// Tooling:   Cameo SysML Plugin (MagicDraw 2024+)
// See also:  docs/sysml/fhir-servicerequest-statemachine.sysml
//            docs/sysml/healthcare-interfaces.sysml
// ============================================================================

package StudyReportingStateMachine {

    private import ScalarValues::*;


    // =========================================================================
    // Trigger occurrence definitions
    // =========================================================================
    //
    // These correspond to explicit user or system actions that cause a state
    // transition. In AdvaPACS they map to worklist action buttons.

    occurrence def StudyScheduled;
        // Technologist or scheduler assigns a worklist slot for the study.

    occurrence def ImagesAcquired;
        // Modality sends C-STORE; images confirmed received in PACS.
        // In AdvaPACS: triggered by DICOM C-STORE completion event.

    occurrence def RadiologistAccepted;
        // Radiologist self-assigns the study from the READY_TO_READ queue.

    occurrence def ReturnedToQueue;
        // Radiologist returns the study to the unassigned queue without reporting.
        // Common when a more appropriate reader should handle the case.

    occurrence def ConsultRequested;
        // Reading radiologist requests a specialist or peer consult.

    occurrence def ConsultCompleted;
        // Consultant finishes review and returns the case to the reading radiologist.

    occurrence def PreliminaryReleased;
        // Radiologist releases a preliminary / verbal report for urgent cases
        // before completing the full dictated report. Study remains in READING
        // internally — radiologist continues reading after releasing prelim.

    occurrence def ReadingResumed;
        // Reading radiologist continues reading after a preliminary release.

    occurrence def ReportDictated;
        // Radiologist completes dictation. Moves to REPORTED (unverified).
        // In voice-recognition sites this is the only path to REPORTED.
        // In transcription sites this triggers the NeedsTranscription split.

    occurrence def TranscriptionRequired;
        // Site workflow routes the dictated report to a human transcriptionist
        // rather than voice recognition. Triggered by a system rule or manually.

    occurrence def TranscriptionCompleted;
        // Transcriptionist finalises the typed report and submits for verification.

    occurrence def ReportVerified;
        // Attending radiologist (or the reporting radiologist at sites that allow
        // self-verification) digitally signs the report.
        // Sets DICOM SR VerificationFlag = VERIFIED.

    occurrence def AmendmentRequested;
        // Radiologist or clinician identifies an error or omission in a VERIFIED
        // report and initiates an amendment or addendum.

    occurrence def AmendmentVerified;
        // Amended report re-signed by a radiologist. Returns to VERIFIED state.

    occurrence def DeficiencyFlagged;
        // A verifier or QA reviewer returns a REPORTED study to the reading
        // radiologist because the report is incomplete, unclear, or incorrect.
        // Renamed from 'queueForRead' in the original draft.

    occurrence def StudyRejected;
        // Reading radiologist determines the study cannot be interpreted:
        // non-diagnostic image quality, wrong patient, equipment malfunction.

    occurrence def CancellationConfirmed;
        // Radiologist or administrator confirms the study is permanently rejected
        // with no intent to reimage. Terminal path.

    occurrence def ReimageRequested;
        // Technologist or radiologist initiates a repeat acquisition.
        // Returns the study to READY_TO_IMAGE for a new attempt.

    occurrence def ArchiveRequested;
        // Study and report are committed to long-term storage.
        // Triggered automatically after verification (site-configurable delay)
        // or manually from READY_TO_READ for transferred/no-report-needed studies.


    // =========================================================================
    // Activity definitions  (entry / exit / do state actions)
    // =========================================================================

    action def AssignAccessionNumber;
        // Generate and bind accession number to the study in RIS/PACS.

    action def AddToSchedulerWorklist;
        // Place study on the scheduling worklist for technologist assignment.

    action def NotifyTechnologist;
        // Alert technologist that the study is ready for acquisition.

    action def AddToRadiologistWorklist;
        // Place study in the unread queue visible to all eligible radiologists.

    action def LockStudyInPACS;
        // Mark study as in-progress in PACS to prevent concurrent assignment.

    action def UnlockStudyInPACS;
        // Release the PACS lock when reading is interrupted or completed.

    action def NotifyConsultant;
        // Route consult request to the identified specialist's worklist.

    action def DistributePreliminaryReport;
        // Transmit preliminary findings to the ordering provider via preferred
        // channel (HL7 ORU, FHIR DiagnosticReport, or direct message).

    action def NotifyOrderingProviderPrelim;
        // Alert ordering provider that a preliminary report is available.

    action def ReleaseUnverifiedReport;
        // Make dictated / transcribed report readable by clinical staff
        // with a clear UNVERIFIED watermark. FHIR status: partial.

    action def NotifyVerifier;
        // Alert the designated verifying radiologist that sign-off is pending.

    action def NotifyTranscriptionist;
        // Route audio or draft text to the transcription queue.

    action def SignAndDistributeFinalReport;
        // Apply radiologist digital signature; set DICOM SR VerificationFlag = VERIFIED;
        // distribute final report via HL7 ORU / FHIR DiagnosticReport (status: final).

    action def NotifyOrderingProviderFinal;
        // Alert ordering provider that the final verified report is available.

    action def CreateAmendmentRecord;
        // Create a new SR version or addendum linked to the original verified report.
        // FHIR DiagnosticReport.status → amended.

    action def DocumentRejectionReason;
        // Record rejection code and free-text reason; notify technologist and
        // ordering provider.

    action def RecordCancellation;
        // Close the study record with CANCELLED status; notify ordering provider.

    action def ArchiveStudyAndReport;
        // Move images and report to long-term storage tier; confirm PACS receipt.


    // =========================================================================
    // Full study reporting lifecycle
    // =========================================================================

    state def StudyReportingLifecycle {
        // Full lifecycle from order receipt through archival.
        //
        // Role mapping (AdvaPACS worklist):
        //   Scheduler / RIS    — sees: ORDER_PLACED
        //   Technologist       — sees: READY_TO_IMAGE, REJECTED (for reimage)
        //   Radiologist        — sees: READY_TO_READ, READING, CONSULTING,
        //                              PRELIMINARY, REPORTED, TRANSCRIBING
        //   Verifying Attending — sees: REPORTED, TRANSCRIBING
        //   QA / Admin         — sees: all states
        //   System / PACS      — drives: ARCHIVED

        entry; then orderPlaced;


        // ── ORDER_PLACED ──────────────────────────────────────────────────────
        state orderPlaced {
            // Study order received from RIS/OpenMRS. Accession number assigned.
            // Scheduler assigns a modality time slot.
            entry action assignAcc     : AssignAccessionNumber;
            entry action addSched      : AddToSchedulerWorklist;
        }

        transition 'orderPlaced-to-readyToImage'
            first orderPlaced
            accept StudyScheduled
            then readyToImage;


        // ── READY_TO_IMAGE ───────────────────────────────────────────────────
        state readyToImage {
            // Technologist worklist entry present. Awaiting acquisition.
            entry action notifyTech : NotifyTechnologist;
        }

        transition 'readyToImage-to-readyToRead'
            first readyToImage
            accept ImagesAcquired
            then readyToRead;


        // ── READY_TO_READ ────────────────────────────────────────────────────
        state readyToRead {
            // Images in PACS. Study visible in unread radiologist queue.
            // No radiologist assigned yet.
            entry action addWorklist : AddToRadiologistWorklist;
        }

        transition 'readyToRead-to-reading'
            first readyToRead
            accept RadiologistAccepted
            then reading;

        transition 'readyToRead-to-archived'
            // Studies transferred in with no local reporting need, or
            // no-report-required studies (e.g. pre-procedure scout).
            first readyToRead
            accept ArchiveRequested
            then archived;


        // ── READING ──────────────────────────────────────────────────────────
        state reading {
            // Radiologist actively reading. Study locked in PACS.
            // May consult, release a preliminary, or directly dictate.
            entry action lockStudy  : LockStudyInPACS;
            exit action unlockStudy : UnlockStudyInPACS;
        }

        transition 'reading-to-readyToRead'
            // Radiologist returns study to unread queue (no report generated).
            first reading
            accept ReturnedToQueue
            then readyToRead;

        transition 'reading-to-consulting'
            first reading
            accept ConsultRequested
            then consulting;

        transition 'reading-to-preliminary'
            // Urgent / STAT: radiologist releases findings before completing
            // the full dictated report. Reading continues after release.
            first reading
            accept PreliminaryReleased
            then preliminary;

        transition 'reading-to-reported'
            first reading
            accept ReportDictated
            then reported;

        transition 'reading-to-rejected'
            first reading
            accept StudyRejected
            then rejected;


        // ── CONSULTING ───────────────────────────────────────────────────────
        state consulting {
            // Specialist or peer review in progress. Primary radiologist waits.
            // AdvaPACS: study visible in consultant's worklist only.
            entry action notifyConsult : NotifyConsultant;
        }

        transition 'consulting-to-reading'
            // Consultant returns case with findings to primary radiologist.
            first consulting
            accept ConsultCompleted
            then reading;


        // ── PRELIMINARY ──────────────────────────────────────────────────────
        state preliminary {
            // Preliminary findings distributed to ordering provider.
            // Study remains formally in READING — radiologist must return to
            // complete dictation. FHIR DiagnosticReport.status = preliminary.
            entry action distPrelim  : DistributePreliminaryReport;
            entry action notifyPrelim : NotifyOrderingProviderPrelim;
        }

        transition 'preliminary-to-reading'
            // Radiologist resumes reading to complete the full dictated report.
            first preliminary
            accept ReadingResumed
            then reading;


        // ── REPORTED ─────────────────────────────────────────────────────────
        state reported {
            // Report dictated (and transcribed, if applicable).
            // Unverified — visible to clinical staff with UNVERIFIED watermark.
            // Awaiting attending sign-off. FHIR DiagnosticReport.status = partial.
            entry action releaseUnverified : ReleaseUnverifiedReport;
            entry action notifyVerifier    : NotifyVerifier;
        }

        transition 'reported-to-transcribing'
            // Site uses human transcription rather than voice recognition.
            first reported
            accept TranscriptionRequired
            then transcribing;

        transition 'reported-to-verified'
            // Direct verification path (voice recognition or self-verifying site).
            first reported
            accept ReportVerified
            then verified;

        transition 'reported-to-reading'
            // Verifier returns report to radiologist due to deficiency:
            // incomplete findings, incorrect laterality, clinical discrepancy.
            first reported
            accept DeficiencyFlagged
            then reading;


        // ── TRANSCRIBING ─────────────────────────────────────────────────────
        state transcribing {
            // Transcriptionist converting dictated audio to typed report text.
            // No radiologist action required until transcription is complete.
            entry action notifyTranscript : NotifyTranscriptionist;
        }

        transition 'transcribing-to-reported'
            // Typed report returned to REPORTED for radiologist verification.
            first transcribing
            accept TranscriptionCompleted
            then reported;


        // ── VERIFIED ─────────────────────────────────────────────────────────
        state verified {
            // Report digitally signed by attending radiologist.
            // DICOM SR VerificationFlag = VERIFIED.
            // FHIR DiagnosticReport.status = final.
            entry action signAndDist   : SignAndDistributeFinalReport;
            entry action notifyFinal   : NotifyOrderingProviderFinal;
        }

        transition 'verified-to-amended'
            // Error or omission discovered after sign-off.
            first verified
            accept AmendmentRequested
            then amended;

        transition 'verified-to-archived'
            // Auto-triggered after configurable hold period, or manual archive.
            first verified
            accept ArchiveRequested
            then archived;


        // ── AMENDED ──────────────────────────────────────────────────────────
        state amended {
            // Correction or addendum in progress. New SR version linked to
            // original. Ordering provider notified of pending amendment.
            // FHIR DiagnosticReport.status = amended (on the new version).
            entry action createAmend : CreateAmendmentRecord;
        }

        transition 'amended-to-verified'
            // Radiologist signs the corrected / addended report.
            first amended
            accept AmendmentVerified
            then verified;


        // ── REJECTED ─────────────────────────────────────────────────────────
        state rejected {
            // Study cannot be interpreted. Two resolution paths:
            //   1. Cancel — no reimage intended (terminal)
            //   2. Reimage — new acquisition requested (loops back)
            entry action docRejection : DocumentRejectionReason;
        }

        transition 'rejected-to-cancelled'
            first rejected
            accept CancellationConfirmed
            then cancelled;

        transition 'rejected-to-readyToImage'
            // Technologist schedules repeat acquisition.
            first rejected
            accept ReimageRequested
            then readyToImage;


        // ── CANCELLED ────────────────────────────────────────────────────────
        state cancelled {
            // Terminal. Study permanently closed with no report.
            // FHIR DiagnosticReport.status = cancelled.
            entry action recordCancel : RecordCancellation;
        }


        // ── ARCHIVED ─────────────────────────────────────────────────────────
        state archived {
            // Terminal. Images and report committed to long-term storage.
            // Reachable from VERIFIED (normal path) or READY_TO_READ
            // (no-report-needed path).
            entry action archiveAll : ArchiveStudyAndReport;
        }
    }


    // =========================================================================
    // Simplified lifecycle — happy path only (tutorial / demo use)
    // =========================================================================

    state def StudyReportingLifecycleSimplified {
        // Happy path with voice recognition (no transcription):
        //   orderPlaced → readyToImage → readyToRead → reading → reported → verified → archived
        //
        // Omits: consulting, preliminary, transcribing, amended, rejected, cancelled.

        entry; then orderPlaced;

        state orderPlaced;
        state readyToImage;
        state readyToRead;
        state reading;
        state reported;
        state verified;
        state archived;

        transition 'schedule'    first orderPlaced   accept StudyScheduled       then readyToImage;
        transition 'acquire'     first readyToImage  accept ImagesAcquired       then readyToRead;
        transition 'assign'      first readyToRead   accept RadiologistAccepted  then reading;
        transition 'dictate'     first reading       accept ReportDictated       then reported;
        transition 'verify'      first reported      accept ReportVerified        then verified;
        transition 'archive'     first verified      accept ArchiveRequested      then archived;
    }
}
