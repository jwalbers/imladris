# Timezones in IMLADRIS

The lab joins systems in several timezones: the Wisconsin lab (America/Chicago), the
Oregon lab (America/Los_Angeles), the Qure.ai laptop and MinXray simulator (Africa/Maseru,
the Lesotho field setup; UTC+2, no DST), PIH's OpenMRS development servers, and AdvaPACS
in the cloud. Mismatched clocks show up as wrong study times and broken turnaround numbers,
e.g. [AdvaPACS shifting qTrack studies by +4 h](../issues/advapacs-study-time-shift-no-dicom-timezone.md).

## The rule

1. **Store and compare in UTC** (or local time with an explicit offset).
2. **Every timestamp a system sends carries its offset**: FHIR `…-05:00` / `Z`; DICOM
   **Timezone Offset From UTC (0008,0201)** next to StudyDate/StudyTime; HL7 `YYYYMMDDHHMMSS-0500`.
3. **Show people their local time.** Lists sort on the underlying UTC, so studies from
   Lesotho, Imladris and PIH interleave correctly.
4. **Use IANA names** (`America/Chicago`, `Africa/Maseru`), never abbreviations
   (`IST` is India, Ireland or Israel; `CST` is US Central or China).

## Per system

| System | Server clock | What it writes | People see |
|---|---|---|---|
| OpenMRS (lab, `lesotho-emr`) | **UTC** (container and MySQL). Keep it: stored DATETIMEs have no offset, so changing the server zone would shift every existing record | UTC; FHIR orders to AdvaPACS with `Z` | Browser-local, via global property `timezone.conversions=true` |
| Lab sidecar (modality simulator, `IML_*_02`) | `LAB_TZ` (America/Chicago) | DICOM in lab-local time **with 0008,0201** (−0500 CDT / −0600 CST); worklist times converted from the order's offset to lab-local | Modality Console: lab-local |
| qure-sim (lab AI stand-in) | `LAB_TZ` | copies the study's date, time and 0008,0201 into its SC | (via AdvaPACS) |
| Report Console | `LAB_TZ` | stores UTC | lab-local, UTC on hover; sorted by UTC |
| Lab AdvaPACS gateway | `LAB_TZ` | passes DICOM through unchanged | |
| Qure laptop, MinXray sim, qTrack | Africa/Maseru | **UTC** in StudyDate/StudyTime, whatever the laptop's zone (confirmed CXR5319, 2026-10-22: 20:45:29 written, arrived 20:47 UTC). The PACS adapter adds 0008,0201 = `+0000` | qTrack UI: Maseru |
| PIH OpenMRS integration (Mark) | his server | should add 0008,0201 (with the top-level Accession/Patient ID fix) | |
| AdvaPACS | cloud, UTC | | lists: the viewing computer's timezone; AdvaView overlay: DICOM time as written |

Container TZ comes from `LAB_TZ` in `docker/ap-qs/.env` (`America/Chicago` in Wisconsin,
default `America/Los_Angeles` for Oregon). Python's `datetime.now().astimezone()` then gives
the DST-correct offset.

## AdvaPACS settings (portal)

- **Remote AE timezone** = the zone of the clock the sender **writes**, not where the machine
  sits. It's the fallback for senders that omit 0008,0201:
  `IML_*_02`, `IML_TOOLS_02` → America/Chicago; `IML_*_01`, `IML_TOOLS_01` →
  America/Los_Angeles; `QURE01_*` → **UTC** (qTrack writes UTC; the zone the laptop sits in
  doesn't matter); PIH's AE → its server's zone.
- **Display timezone:** AdvaPACS lists use the viewing computer's timezone (no per-user setting).
  AdvaView's image overlay shows the DICOM time as written, without conversion (for qTrack: UTC).
- **Inbound HL7 service "Default Timezone"** → the sending site's zone (gw-02: America/Chicago).

## Lesotho deployment notes

- OpenMRS server in UTC, `timezone.conversions=true`, browsers in Africa/Maseru.
- `sms.timezone` is `IST` (Bahmni default, unused while SMS alerts are off). Set it to
  `Africa/Maseru` before enabling SMS appointment reminders.
- Modality consoles (MinXView) and the Qure laptop: Africa/Maseru, DICOM with 0008,0201.

## Checking a study

DICOMweb metadata through the lab's AdvaPACS proxy (lab VM):

```bash
curl -s localhost:8087/studies/<StudyUID>/series/<SeriesUID>/metadata \
  | jq '.[0] | {date: ."00080020".Value[0], time: ."00080030".Value[0], tz: ."00080201".Value[0]}'
```

Compare with `ImagingStudy.started` in AdvaPACS FHIR (stored as UTC).
