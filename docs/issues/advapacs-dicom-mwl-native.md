# AdvaPACS Gateway — Native DICOM MWL C-FIND Confirmed

## Finding (tested 2026-07-13)

The AdvaPACS gateway (port 11112, AE `ADVAPACS_GW_01`) implements a DICOM
Modality Worklist SCP and responds correctly to C-FIND queries using SOP Class
`1.2.840.10008.5.1.4.31` (Modality Worklist Information - FIND).

Test result: association established, one pending result returned for a scheduled
US procedure (Letseka^Kabelo, station IML_US_01), followed by a clean success
status. The worklist data matches what was created via the FHIR ServiceRequest API.

## Architectural implication

**Real modalities do not need the sidecar worklist at all.**

Production CR/DR/US rooms (GE, Siemens, Philips) query Modality Worklist via
DICOM C-FIND — they do not speak FHIR. With native MWL confirmed on the
AdvaPACS gateway, any physical modality can be configured to query the gateway
directly for its worklist with no additional middleware.

Configuration on the modality side:
- Host: AdvaPACS gateway IP (BESSIE: 192.168.1.10 in lab)
- Port: 11112
- Called AE: `ADVAPACS_GW_01`
- Calling AE: modality's own AET (e.g. `IML_CR_01`)

## Why the sidecar worklist still has value

The sidecar's `fhir_mwl_poller` + `.wl` synthesis and the modality console UI
serve a different purpose from the raw DICOM MWL:

1. **Status tracking** — the console shows order state (Pending Review, Approved,
   Completed) overlaid on the worklist. Native DICOM MWL only returns scheduled
   items; it has no concept of completed or cancelled.

2. **Rad tech workflow gate** — the Image Patient button is gated on order status.
   A native DICOM C-FIND query has no equivalent gate.

3. **Training and demo** — the console is the primary teaching tool for staff
   who are new to the order-to-image workflow.

In production, the two paths coexist:
- Physical modalities → DICOM C-FIND → AdvaPACS gateway (zero sidecar involvement)
- Modality console → `.wl` files + webhook status → sidecar (operator oversight UI)

## Demo talking point

*"When a real X-ray machine arrives on site, you point its worklist query at the
AdvaPACS gateway — same address it already uses for image storage. No extra
servers, no extra configuration. The worklist is already there."*

## Official documentation

Confirmed in the [AdvaPACS DICOM Conformance Statement](https://conformance.advapacs.com/overview/dimse-services):

| SOP Class | SOP UID | SCU | SCP |
|-----------|---------|-----|-----|
| Modality Worklist Information Model - FIND | 1.2.840.10008.5.1.4.31 | N | **Y** |

Transfer syntaxes: Implicit VR Little Endian, Explicit VR Little Endian.

This is official — MWL C-FIND is a documented, supported capability, not an
undocumented side effect.

Note: The conformance statement covers the AdvaPACS Gateway (both SCU and SCP
roles for some services). The Cloud Gateway only supports SCP role. For our
on-premise gateway at BESSIE this is irrelevant — we are always using the
on-premise gateway as SCP.

## Open questions for AdvaPACS support

- Can MWL results be filtered by Scheduled Station AE Title in C-FIND queries
  (so a CR room only sees CR orders, not US)?
- Is MWL populated from ServiceRequest `draft` only, or also `active`?
  Our test returned an `active` order — need to confirm this is intentional.
- Are completed (`completed`) orders automatically suppressed from MWL results?
