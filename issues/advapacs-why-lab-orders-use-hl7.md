**Why the IMLADRIS lab now sends orders to AdvaPACS over HL7 instead of FHIR**

**Expected reading workflow.** PIH is still settling the report workflow with stakeholders, but a reasonable starting point is:

1. The technologist images the patient and **completes the order** (after QA).
2. The study enters the Reporting Worklist as **Ready to Read** and appears on the **Unread** board.
3. **Draft** is where a radiologist *parks* a report they've started, not where new studies arrive.

**What AdvaPACS does today** (tested in the lab, same tenant):

| How the order was created | Worklist entry when the order is completed |
|---|---|
| **HL7 ORM^O01** via the gateway's Inbound HL7 Service | **Ready to Report**, on the **Unread** board (from the service's "AdvaPACS Worklist Status" setting) |
| **FHIR ServiceRequest** via the API | **Draft**, on the Drafts board, as if a radiologist had already started the report |
| No prior order (study arrives first, e.g. qTrack) | **Ready to Read** (incoming-study rule) |

In every case nothing reaches the worklist until the order is **completed**. Completing a FHIR order after the study arrives, or before it, still gives Draft, so the FHIR path puts studies in the radiologist's "in progress" bucket from the start.

**So the lab now uses HL7 for orders.** New orders are sent as ORM^O01 NW; the modality console's *Complete Order* sends XO/CM; cancellations in OpenMRS send CA/CA. Verified end to end (OpenMRS order → AdvaPACS → modality worklist → image → complete → **Unread / Ready to Report**, about 90 s).

**Notes**
- HL7-created orders reject later FHIR updates (422 "Identifier system required"), so an HL7-ordering system must also complete and cancel over HL7.
- HL7 orders still arrive as *draft* and need to be set *In Process* before they reach the modality worklist.
- The lab can switch back to FHIR with one setting (`ORDER_TRANSPORT=fhir`).

**Open question for AdvaHealth:** what is the FHIR equivalent of the HL7 service's "AdvaPACS Worklist Status", so that completed FHIR-created orders enter the worklist as **Ready to Read**? FHIR is the path PIH's production OpenMRS integration is being built on.
