# MWL Order Created Timestamp — Open Question for Site Team

## What the prototype shows

The "Order Created" column on the modality worklist console currently displays
the time the sidecar first received a webhook notification for the order from
AdvaPACS. This is approximately the time the order was created, but is not an
authoritative clinical timestamp.

For active orders the column may show the scheduled procedure step date from
the DICOM worklist file instead (written by the MWL poller). For completed or
cancelled orders it falls back to the webhook receipt time.

## Why this is imprecise

AdvaPACS does not populate `occurrenceDateTime` or `authoredOn` on the FHIR
ServiceRequest, which are the standard fields we would use for an authoritative
order date. Without those, there is no single reliable source of "when was this
order placed" available to the modality console.

## Questions for the site team

1. **What time do staff need to see on the worklist?**
   - Time the clinician placed the order in OpenMRS?
   - Time AdvaPACS accepted and scheduled the order?
   - Scheduled/requested exam date (which may be a future date)?
   - Something else?

2. **How do staff interpret the time shown?**
   - Is it "when was this ordered" (for prioritisation)?
   - Is it "when should this be done" (a scheduled slot)?
   - Is it used to detect stale orders that have been waiting too long?

3. **What happens if the time is wrong or missing?**
   - Would staff notice or care during normal workflow?
   - Could a wrong time cause a patient safety issue (e.g. wrong-day exam)?

## Prototype note

This is a prototype — the goal of showing any timestamp is to provoke this
conversation, not to get the timestamp right before feedback is gathered.
The column header and display format should be treated as placeholders until
the site team confirms what they actually need.
