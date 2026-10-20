# AdvaPACS shows study times shifted by +4 h for studies without a DICOM timezone (qTrack pushes)

**Target:** AdvaPACS (region `usa1`), studies pushed from the Qure.ai laptop (qTrack/qXR via PACS adapter and gateway)  
**Component:** DICOM ingest (StudyDate/StudyTime → `ImagingStudy.started`, ad-hoc order `occurrenceDateTime`)  
**Type:** Configuration / interoperability  
**Priority:** Medium. Wrong study times in the worklist, and wrong turnaround times in any report built on them  
**Status:** Open. Found 2026-10-20

---

## Summary

DICOM dates and times carry no timezone unless **Timezone Offset From UTC (0008,0201)** is
present. The qTrack studies don't send it. AdvaPACS then reads the bare time as **UTC−4**
(US Eastern daylight time, apparently its default) and stores it as UTC, 4 hours late.

## Evidence: accession `CXR8455` (patient 4JHTF9)

| Source | Value |
|---|---|
| DICOM StudyDate / StudyTime (DX, OT overlay, SR, encapsulated PDF; Series/Content times identical) | `20261020` / `214853.000` |
| DICOM Timezone Offset From UTC (0008,0201) | **absent** on all four series |
| AdvaPACS received the study (`ImagingStudy.meta.lastUpdated`) | 2026-10-20T21:53:23Z (first webhook 21:51Z) |
| AdvaPACS `ImagingStudy.started` and ad-hoc order `occurrenceDateTime` | **2026-10-21T01:48:53Z** |

The acquisition time (21:48:53) is three minutes before arrival **in UTC**, so the time
written into the DICOM looks like UTC. The laptop's clock is believed to be set to GMT+2
(Lesotho/Rwanda), so qTrack or the simulator may write UTC regardless, which is still to be confirmed
on the laptop. AdvaPACS added 4 hours: 21:48:53 read as UTC−4 = 01:48:53Z the next day.

Query used (lab VM, AdvaPACS DICOMweb proxy):
`/studies/<StudyInstanceUID>/series/<SeriesInstanceUID>/metadata` → tags 0008,0020 / 0008,0030 / 0008,0201.

## Options

1. **Send the timezone.** The Qure PACS adapter already normalizes every object; add
   `TimezoneOffsetFromUTC` (0008,0201) matching the times it writes (`+0000` if they are
   UTC, `+0200` if laptop-local). This is the standards-based fix and works with any PACS.
2. **Set AdvaPACS's default timezone** for this source (Local AE / site / account setting,
   if one exists; the inbound HL7 service has its own "Default Timezone",
   America/Los_Angeles in our config). Ask AdvaPACS which setting governs DICOM ingest.
3. **Field reality:** in Lesotho the modality, laptop and AdvaPACS reading site will all
   differ. Option 1 is the only one that stays right everywhere.

## To confirm

- Laptop clock/timezone, and whether qTrack/MinXray write local time or UTC into StudyTime.
- Which AdvaPACS setting supplies the UTC−4 assumption.
