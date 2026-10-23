# OpenHIM in the IMLADRIS lab

OpenHIM (core, console, MongoDB) and PIH's `openhim-advapacs-mediator`, deployed from the
`openmrs-contrib-distro-tools` compose fragments that Kol-CI uses, with lab settings in `.env`.
Plan and status: [../../docs/openhim-migration-plan.md](../../docs/openhim-migration-plan.md).

- Distro-tools clone: `~/git/PIH/openmrs-contrib-distro-tools`, tracking `main` (note the commit
  deployed below when updating).
- `./up.sh` starts or updates; `./up.sh ps`, `./up.sh logs -f openhim-core`, `./up.sh down`.
- Console: https://openhim.imladrislab.org (PIH sign-in, then OpenHIM login), user `root@openhim.org`, password `OPENHIM_PASSWORD`.
- The mediator runs in `push` mode, so it sends no orders: the lab's orders still go over HL7 from
  the sidecar until AdvaPACS fixes FHIR order completion.

| Host port | Container | Purpose |
|---|---|---|
| 127.0.0.1:9000 | openhim-console | admin console (localhost only) |
| 9001 | openhim-sso-gate | PIH sign-in in front of the console; HAProxy `openhim.imladrislab.org` → here |
| 8081 | openhim-core :8080 | admin API (the console calls it from the browser) |
| 127.0.0.1:5011 | openhim-core :5001 | router: channels (moved off 5001, the modality console; localhost only, since the outbound channel is public) |
