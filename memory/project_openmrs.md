---
name: OpenMRS / PIH EMR decision
description: OpenMRS distribution chosen for IMLADRIS is PIH EMR, not Bahmni; details being finalized with PIH software lead
type: project
---

The OpenMRS instance for IMLADRIS will use the **PIH EMR** distribution, not Bahmni as originally designed.

**Why:** PIH EMR is purpose-built for Partners in Health clinical sites including Lesotho. Better fit for Botsabelo than generic Bahmni. Specifics being finalized with the PIH software lead (as of 2026-04-08).

**How to apply:** Do not design around Bahmni-specific modules (Bahmni-PACS Integration, Bahmni Apps). Wait for PIH EMR specifics before designing the MWL integration and sidecar configuration. The modality sidecar MWL C-FIND SCU design is EMR-agnostic and should be fine regardless.
