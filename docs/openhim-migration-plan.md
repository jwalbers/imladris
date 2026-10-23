# IMLADRIS lab: OpenHIM migration plan

Goal: bring the IMLADRIS lab's OpenMRS integration to par with the Kol-CI setup
([Mark's write-up](../openhim-migration/Kol-CI%20Test%20Server-%20OpenMRS,%20OpenHIM%20&%20AdvaPACS.md)):
OpenMRS ↔ AdvaPACS traffic routed and logged through OpenHIM.

Status: Phase 1 deployed on the lab VM, 2026-10-22 (HAProxy names and the SSO gate still to do).

## Phase 1 status (2026-10-22)

- Deployed from `imladris/docker/openhim/up.sh`: distro-tools fragments at `f1ea9a8`, mediator image
  `partnersinhealth/openhim-advapacs-mediator@sha256:549c6182c86b976c4b401ed480da0b948b1bb4ab5e7bc3c295a12afac1f8bb83`.
- Core, console and MongoDB are healthy. The mediator registered (`urn:mediator:openmrs-advapacs-fhir`),
  created client `openmrs` and both channels, and is idle (`ORDER_INGESTION_MODE=push`); orders stay HL7.
- Ports: console 9000 and admin API 8081 on the LAN; router on **127.0.0.1:5011** only (the outbound
  channel is public).
- Lab autostart starts and stops the stack and health-checks console, API and router.
- To do: HAProxy `openhim.imladrislab.org` → :9000 and `openhim-api.imladrislab.org` → :8081
  (HTTPS, `X-Forwarded-Proto`), then switch the console API settings in `.env` to those names and
  put the console behind the PIH sign-in; MongoDB backup.

## Decision: HL7 orders for now

AdvaPACS puts studies on the reading worklist (Unread, **Ready to Report**) when their order was
created over **HL7** and then completed. Orders created through the **FHIR** API enter the worklist
as **Draft** when completed ([details](../issues/advapacs-fhir-orders-enter-worklist-as-draft.md),
[why the lab uses HL7](../issues/advapacs-why-lab-orders-use-hl7.md)). Kol-CI's mediator creates
orders through FHIR.

FHIR vs HL7 is under discussion between the lab, PIH (Mark's team) and AdvaHealth. Until
AdvaHealth makes completed FHIR orders enter as Ready to Report, the lab **keeps HL7 orders** and
puts OpenHIM in the middle of the paths it already uses.

## Today vs target

| Path | Lab today | Lab target (this plan) | Kol-CI |
|---|---|---|---|
| Orders to AdvaPACS | sidecar → HL7 ORM → gateway :2576 | sidecar → **OpenHIM TCP (MLLP) channel** → gateway :2576 | mediator → OpenHIM → AdvaPACS FHIR |
| Order intake from OpenMRS | sidecar polls OpenMRS REST | sidecar polls through an **OpenHIM HTTP channel** | mediator polls OpenMRS FHIR (fhir2) |
| Results to OpenMRS | sidecar → ORU^R01 → OpenMRS REST HL7 endpoint | through an **OpenHIM HTTP channel** | not built yet |
| FHIR mediator | — | deployed, order polling **off** | live |
| Images | modality console / MinXray → gateway | unchanged | modality-simulator → gateway |

## Phases

1. **Deploy OpenHIM** (core, console, MongoDB) on the lab VM from the `openmrs-contrib-distro-tools`
   compose fragments, as on Kol-CI; console and admin API at `openhim.imladrislab.org` behind the
   lab's PIH sign-in (the admin API must be HTTPS with `X-Forwarded-Proto`). Deploy the
   `openhim-advapacs-mediator` with order polling off. About 1–1.5 GB RAM; ports 9000 / 8081 / 5001.
2. **Route the sidecar through OpenHIM**, one path at a time, each verified in the OpenHIM console:
   results (ORU, HTTP) first, then OpenMRS intake (HTTP), then HL7 orders (TCP/MLLP).
3. **Switch orders to the FHIR mediator** once AdvaHealth fixes FHIR completion. Before that:
   - patient identifier system: the mediator uses PIH's `…/lesotho/emr-id`; lab patients exist in
     AdvaPACS under `http://openmrs.org/identifier` → align or migrate, or AdvaPACS gets duplicates;
   - accession numbers: the mediator uses the OpenMRS order number (lab `0000000075`, Kol-CI
     `0000010215`); agree per-site prefixes or ranges in the shared tenant;
   - the mediator's prototype limits (in-memory poll cursor, modality fixed to CR, no results path).
4. **Operations:** OpenHIM in the lab autostart health checks; MongoDB backup (not done on Kol-CI
   yet); OpenHIM console users; docs.

## Facts checked in the lab (2026-10-22)

- OpenMRS `fhir2` module answers (`/ws/fhir2/R4/metadata`, ServiceRequest search).
- All 51 lab patients have an **EMR ID** identifier.
- Radiology order numbers are `0000000075`-style; OpenMRS accession numbers are empty (the sidecar
  derives accessions from the order UUID today).

## Open questions for Mark

- Repo access / tags to track for the mediator and distro-tools fragments.
- Patient identifier system and accession-number ranges for a second OpenMRS instance in the
  shared AdvaPACS tenant.
- Whether the mediator will get an HL7 outbound option (ORM to the gateway via OpenHIM) as an
  interim, so both sites follow the same path.
