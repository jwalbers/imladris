// ============================================================================
// FHIR ServiceRequest State Machine — SysML v2 Textual Notation
//
// Models the lifecycle of a FHIR R5 ServiceRequest (radiology order) from
// creation through terminal states, and documents how the Imladris sidecar
// interacts with each state.
//
// FHIR reference:
//   https://hl7.org/fhir/R5/servicerequest.html
//   https://hl7.org/fhir/R5/valueset-request-status.html
//
// The FHIR standard defines the status value set (required binding) but does
// NOT formally mandate specific transition paths. Transitions below reflect
// documented intent and common implementation practice.
//
// Imports HealthcareInterfaces for FhirServiceRequest item def.
//
// Standard:  SysML v2 (ISO/IEC 19514:2024)
// Tooling:   SysML v2 API Server · Jupyter SysML v2 kernel · Cameo SysML Plugin
// See also:  docs/sysml/healthcare-interfaces.sysml
//            docs/advapacs-config/fhir-integration-setup.md
// ============================================================================

package FhirServiceRequestStateMachine {

    private import ScalarValues::*;
    private import HealthcareInterfaces::FHIRItems::*;


    // =========================================================================
    // Status value set  (maps 1:1 to FHIR ServiceRequest.status — required binding)
    // =========================================================================

    enum def ServiceRequestStatus {
        enum draft;           // Created; not yet ready for action. Default on OpenMRS order creation.
        enum active;          // In force; not yet completed. Modality worklist entry is present.
        enum onHold;          // Temporarily suspended. Worklist entry should be suppressed.
        enum revoked;         // Cancelled before completion. Terminal.
        enum completed;       // Study fully performed; images in PACS. Terminal.
        enum enteredInError;  // Order void — should never have existed. Terminal. No imaging done.
        enum unknown;         // Authoring system cannot determine current status.
    }


    // =========================================================================
    // Trigger occurrence definitions
    // =========================================================================

    occurrence def OrderCreated;      // Clinician submits radiology order in OpenMRS.
    occurrence def OrderActivated;    // Order accepted and scheduled; ready for modality.
    occurrence def OrderSuspended;    // Order temporarily placed on hold.
    occurrence def OrderResumed;      // Hold lifted; order returns to active scheduling.
    occurrence def OrderCancelled;    // Clinician or system explicitly cancels the order.
    occurrence def StudyPerformed;    // Modality sends C-STORE to PACS; images confirmed received.
    occurrence def DataCorrected;     // Administrative correction — no imaging occurred.


    // =========================================================================
    // Full lifecycle state machine
    // =========================================================================

    state def ServiceRequestLifecycle {
        // Lifecycle of a FHIR ServiceRequest from order creation to terminal state.
        //
        // Imladris integration context:
        //   order_poller    — creates ServiceRequest in AdvaPACS (status: draft)
        //   fhir_mwl_poller — polls AdvaPACS for draft/active orders; writes .wl files;
        //                     deletes .wl files when status leaves draft/active
        //   acquisition_loop — sends C-STORE to AdvaPACS when .wl file is present
        //
        // Known gap: AdvaPACS does not automatically transition status to 'completed'
        // after imaging. fhir_mwl_poller cleanup therefore never fires, and .wl files
        // accumulate. acquired_accessions.txt persistence is the current workaround.

        entry; then draft;

        // ── States ───────────────────────────────────────────────────────────

        state draft {
            // Order created. fhir_mwl_poller writes a .wl worklist file.
            // Modality console displays the order; acquisition_loop may auto-send.
            // NOTE: AdvaPACS leaves ServiceRequest in this state after imaging (known gap).
        }

        state active {
            // Order accepted and scheduled. Worklist entry present.
            // In many implementations draft and active are treated identically
            // by modality worklist consumers (both produce a .wl file).
        }

        state onHold {
            // Order temporarily suspended. Worklist entry should be hidden or removed.
            // Resumption returns the order to active, not draft.
        }

        state revoked {
            // Order cancelled. Terminal.
            // FHIR distinguishes revoked (real-world action may have begun) from
            // entered-in-error (no real-world action taken).
            // fhir_mwl_poller should delete the .wl file when this state is detected.
        }

        state completed {
            // Study performed; images in PACS. Terminal. Expected end state.
            // fhir_mwl_poller cleanup targets this state — see known gap above.
        }

        state enteredInError {
            // Order void. Terminal. Used when order was a data entry mistake.
            // Distinguished from revoked: implies no imaging was ever intended.
        }

        // ── Transitions ──────────────────────────────────────────────────────
        // Permitted by FHIR intent; not enforced by the standard as a formal FSM.

        transition 'draft-to-active'
            first draft
            accept OrderActivated
            then active;

        transition 'active-to-on-hold'
            first active
            accept OrderSuspended
            then onHold;

        transition 'on-hold-to-active'
            first onHold
            accept OrderResumed
            then active;

        transition 'active-to-completed'
            first active
            accept StudyPerformed
            then completed;

        transition 'draft-to-completed'    // imaging performed without explicit activation
            first draft
            accept StudyPerformed
            then completed;

        transition 'draft-to-revoked'
            first draft
            accept OrderCancelled
            then revoked;

        transition 'active-to-revoked'
            first active
            accept OrderCancelled
            then revoked;

        transition 'on-hold-to-revoked'
            first onHold
            accept OrderCancelled
            then revoked;

        transition 'draft-to-error'
            first draft
            accept DataCorrected
            then enteredInError;

        transition 'active-to-error'
            first active
            accept DataCorrected
            then enteredInError;
    }


    // =========================================================================
    // Simplified lifecycle — tutorial / team presentation use
    // =========================================================================

    state def ServiceRequestLifecycleSimplified {
        // Happy-path and cancel only. Omits on-hold and entered-in-error for clarity.
        //
        // Happy path:   draft → active → completed
        // Cancel path:  draft → revoked  |  active → revoked
        //
        // This is the subset relevant to the Imladris/AdvaPACS demo workflow.

        entry; then draft;

        state draft;
        state active;
        state revoked;
        state completed;

        transition 'activate'      first draft  accept OrderActivated then active;
        transition 'complete'      first active accept StudyPerformed  then completed;
        transition 'cancel-draft'  first draft  accept OrderCancelled  then revoked;
        transition 'cancel-active' first active accept OrderCancelled  then revoked;
    }
}
