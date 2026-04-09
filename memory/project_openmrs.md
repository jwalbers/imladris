---
name: OpenMRS / PIH EMR decision
description: OpenMRS distribution chosen for IMLADRIS is PIH EMR, not Bahmni; details being finalized with PIH software lead
type: project
---

The OpenMRS instance for IMLADRIS will use the **PIH EMR** distribution, not Bahmni as originally designed.

**Why:** PIH EMR is purpose-built for Partners in Health clinical sites including Lesotho. Better fit for Botsabelo than generic Bahmni.

**Distro:** `https://github.com/PIH/openmrs-distro-zl` (Zanmi Lasante / Haiti distro — PIH's most complete, foundation for Lesotho configs). Will be cloned adjacent to the imladris repo and added to the VSCode workspace.

**Plan:** Get PIH EMR up and running locally, then dockerize the distro with Claude's help. Requires IntelliJ for Java/Maven build work.

**How to apply:** Do not design around Bahmni-specific modules. The modality sidecar MWL C-FIND SCU design is EMR-agnostic and should be fine regardless. Once PIH EMR is running, wire the sidecar to its MWL endpoint.
