## Findings: why our ordered studies don't reach the Unread board

**Summary.** A Reporting Worklist entry appears only once the **order is completed**, and its starting status depends on who created the order:

| Order status | Who created the order | Reporting Worklist |
|---|---|---|
| **completed** | Our integration, via the FHIR API (`POST ServiceRequest`) | **Draft**: 7 of 7 orders, July to Oct 2026 |
| **completed** | AdvaPACS itself, for a study that arrived without an order (qTrack / qXR) | **Ready to Read / Ready to Report** (the incoming-study rule applies) |
| **active** (In Process) | Our integration, via the FHIR API | **No entry on any board**: 3 of 3 orders |

We confirmed the last row with an "All Reports" board that selects every worklist status: active orders do not appear on it at all.

So the "incoming studies → Ready to Read, Unread board" rule works for studies that arrive **without** an order. Studies that match an order created through the FHIR API reach the worklist only after the order is completed, and then as **Draft**.

### Evidence (accession numbers)

| Accession | Order source | Order status | Study linked to order | Worklist status |
|---|---|---|---|---|
| `1ed0d34dc4b84fee` | FHIR | completed | yes | Draft |
| `aa8020c4859346dc` | FHIR | completed | yes | Draft |
| `5b8b39a121184f41`, `518275c8c38f460b`, `73727a88310a4321`, `2026072723422183`, `66d299d0b9c944…` | FHIR | completed | yes | Draft |
| `WSTaf2b2505ae88` | FHIR (created with `status: active`) | active (In Process) | yes | **none** (until completed) |
| `5dbc56cb613a43a0`, `71bc917d52f74879` | FHIR | active | no | none |
| `CXR8455`, `CXR602.0` | AdvaPACS (study without a prior order) | completed | yes | Ready to Read / Ready to Report |

What we ruled out:
- **Order status at the time the images arrive.** Completing the order *before* sending the study (`1ed0d34dc4b84fee`) still gave **Draft**.
- **Completing an order *after* its study has arrived** (`aa8020c4859346dc`, completed in the AdvaPACS UI) also gives **Draft**, not Unread.
- **Creating the FHIR order as `active` instead of `draft`** (`WSTaf2b2505ae88`) makes no difference; there is no worklist entry until completion.
- **DICOM identifiers.** Study Instance UID, Accession Number (Issuer `PIH_A`), Patient ID (Issuer `PIH_A`) and patient name are consistent with the order in every case. The Request Attributes Sequence on matched studies is written by AdvaPACS when it links the study to the order, so it isn't the cause.

### What we've changed on our side

Our modality console now has a **Complete Order** step, used by the radiology technologist after imaging and QA. It sets the ServiceRequest to `completed` through the FHIR API, which puts the study on the Reporting Worklist, currently as **Draft**. An authorised user can also complete the order in AdvaPACS.

### Follow-up question (to raise separately as a support question)

> For orders created through the FHIR API (`ServiceRequest`), completion creates the Reporting Worklist entry as **Draft**. Our "incoming study → Ready to Read" rule applies only to orders AdvaPACS creates for unordered studies. How should completed FHIR orders enter the worklist as **Ready to Read** (Unread board)? Is there a rule condition, a setting on the API client, or an order field? The HL7 inbound service has an "AdvaPACS Worklist Status" setting; is there a FHIR equivalent?

Meanwhile, a Draft → Ready to Read transition button on the Drafts board moves these studies to Unread by hand.

### Update 2026-10-22: HL7-created orders reach the Unread board

Same test with the order created by **HL7 ORM^O01** through the gateway's Inbound HL7 Service
(gw-02, "AdvaPACS Worklist Status" = Ready to Report), accession `HL7d5d5d4adb84f`:

- Order created as **draft** (ORC-5 `SC` doesn't make it active); study linked on arrival; on **no
  board** until completed.
- Completed with ORM^O01 `XO` / `CM` (AdvaPACS Procedure Update): the study appeared on the
  **Unread** board as **Ready to Report**.

So the initial worklist status comes from the order's source: HL7 service setting → Ready to
Report; FHIR API → Draft; no prior order → incoming-study rule. **The FHIR question stands:** how do
FHIR-created orders get the equivalent of the HL7 service's Worklist Status?

Also found:
- **Orders created via HL7 can't be updated via FHIR:** PATCH/PUT returns 422 "Identifier system
  required". AdvaPACS stores the HL7 placer/filler (and two plain accession) identifiers without a
  `system`, then rejects FHIR writes to its own record. An HL7-ordering system must do all updates
  (complete, cancel) over HL7.
