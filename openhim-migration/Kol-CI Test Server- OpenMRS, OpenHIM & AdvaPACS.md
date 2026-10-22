# Kol\-CI Test Server: OpenMRS, OpenHIM & AdvaPACS

# Overview

**Kol-CI** is a test instance of the Lesotho EMR. It runs on the PIH app cluster server (`somprinfappclstr-01`) alongside **OpenHIM**, an interoperability layer, and the **OpenHIM-AdvaPACS mediator**. Together they send radiology orders placed in OpenMRS to the **AdvaPACS** integration (test) environment.

The same server also runs an **AdvaPACS gateway**, which receives images (DICOM) from imaging devices and uploads them to AdvaPACS. It is separate from OpenHIM and the mediator. DEPLOYED (UHM-9562)

To test the whole flow without real equipment, the server also runs a **modality simulator**: a fake CR/US/CT imaging device. It reads the gateway's worklist (the orders AdvaPACS has scheduled), and when you click **Acquire** it sends made-up images for that order to the gateway, as a real X-ray or ultrasound machine would. DEPLOYED (UHM-9564)

# Components and URLs

| Component | What it is | URL |
| --- | --- | --- |
| OpenMRS (Lesotho EMR) | Where clinicians register patients and place radiology orders. Uses the `lesotho,lesotho-kol-ci` configuration. | <https://kol-ci.pih-emr.org/openmrs> |
| OpenHIM console | Web UI for OpenHIM. Shows every message (a "transaction") passing between the mediator and AdvaPACS. | <https://kol-ci.pih-emr.org/openhim> |
| OpenHIM core | The OpenHIM engine that routes and logs messages. Internal, with no direct login. | — |
| OpenHIM-AdvaPACS mediator | A small PIH service that finds new radiology orders in OpenMRS and converts them for AdvaPACS. Internal; visible in the OpenHIM console under **Mediators**. | — |
| AdvaPACS gateway DEPLOYED | AdvaPACS's on-premises gateway. Receives DICOM images (and optionally HL7) from imaging devices and uploads them to AdvaPACS over outbound HTTPS. It has no web UI of its own: it is configured and monitored in AdvaPACS under **Configuration \> Gateways** (see Setting up AdvaPACS). | — |
| Modality simulator DEPLOYED | A fake imaging device for testing. Its web console lists the gateway's worklist, with an **Acquire** button for each order, and shows recent acquisitions. The images it sends are generated and marked "simulated"; they are not real X-rays. | Tailscale only: <http://100.90.25.20:8095> (see **Logging in**) |
| AdvaPACS | The PACS that receives the orders. Kol-CI points at the AdvaPACS **integration (test)** environment. | <https://pih.advapacs.com/> |

# Logging in

**OpenMRS**

- Go to <https://kol-ci.pih-emr.org/openmrs>
- If you don't have an account on Kol-CI, ask the HIS team for one.

**OpenHIM console**

- Go to <https://kol-ci.pih-emr.org/openhim>
- The OpenHIM admin credentials are in **Bitwarden**

**Modality simulator**

- Its console has **no login**, so it isn't on the public proxy. It is published only on `somprinfappclstr-01`'s **Tailscale** address, `100.90.25.20`.
- Connect to the PIH tailnet, then go to <http://100.90.25.20:8095>. If you aren't on the tailnet, ask the HIS team for access.

**AdvaPACS**

- Go to <https://pih.advapacs.com/>
- If you don't have an AdvaPACS account, ask the HIS team for one.

# Workflow: ordering a study end to end

1. **Pick a test patient in OpenMRS.** The patient must have a **Lesotho EMR ID**. AdvaPACS matches patients on this ID, so the mediator rejects orders for patients without one.
2. **Place a radiology order.** Open the patient's visit and order a radiology study from the Radiology section.
3. **Wait about 15 seconds.** The mediator checks OpenMRS for new radiology orders every 15 seconds.
4. **The mediator sends the order through OpenHIM:**
    1. It sends the order to OpenHIM on the **"OpenMRS to Mediator Order Push"** channel. This is the inbound step and is recorded as a transaction.
    2. It creates the patient in AdvaPACS, or updates them if AdvaPACS already has them.
    3. It sends the order to AdvaPACS through the **"Mediator to AdvaPACS Order Push"** channel.
5. **Check the OpenHIM console.** Go to **Transactions** and look for recent entries on the two channels above:
    - **Successful** means the message got through. Open a transaction to see exactly what was sent and what came back.
    - **Failed** or **Completed with errors**: open the transaction. The AdvaPACS response body usually says why.
6. **Check AdvaPACS.** Log in at <https://pih.advapacs.com/> . The patient and order should now appear there.
7. **Set the order to In Process in AdvaPACS.** In AdvaPACS (see **Logging in**), find the order by its patient or its accession number (the OpenMRS order number). Edit it and change its status from **Scheduled** to **In Process**. AdvaPACS only puts In Process orders on the gateway's worklist, so until you do this the order won't appear in the modality simulator.
8. **Acquire images with the modality simulator.** Open its console (see **Logging in**). The order appears in its worklist with the patient and its accession number (the OpenMRS order number). Click **Acquire**. The **Recent acquisitions** table should say "stored N image(s)".
9. **Check the images in AdvaPACS.** The study should appear under the same patient and accession number, and **not** in the Validation Queue. The gateway uploads it, so allow a minute or so.

**What the mediator changes on the way to AdvaPACS**

- The patient is identified by their Lesotho EMR ID.
- The OpenMRS order number is used as the AdvaPACS **accession number**.
- The modality is currently **hardcoded to "CR"** for every order, whatever study was ordered. So every order shows in the simulator as a CR (X-ray) order.

# Setting up AdvaPACS

The gateway and the modality simulator only work once AdvaPACS knows about them. This is done in the AdvaPACS web UI (<https://pih.advapacs.com/>), under **Configuration**, in this order: the gateway, then a Local AE on it, then a Remote AE for each device that connects to it. For Kol-CI this is already done; these are the settings to check, or to repeat for another server.

## 1. The gateway

**Configuration \> Gateways \> +**

- Create the gateway. AdvaPACS shows its **region** (Kol-CI: `usa1`), **access key ID** and **access key secret**.
- Copy the secret straight away: it is shown only once, and regenerating it replaces the old one. The region goes in puppet (`region` on `openmrs_docker::service::advapacs_gateway`); the key ID and secret go in encrypted hiera (`kol_ci_advapacs_gateway_access_key_id` and `kol_ci_advapacs_gateway_access_key_secret`).
- Once puppet has deployed it, the gateway shows as **Online** within a few minutes. Settings below only reach it once it is Online.
- Leave its **Data Directory** at the default, `/opt/AdvaHealthSolutions/AdvaPACSGateway`.

[Gateway Setup Screenshot](gateway-setup.webp)

## 2. A Local AE on the gateway

**Configuration \> Local AEs \> +**

A Local AE is a DICOM server that the gateway runs: imaging devices (and the simulator) connect to it to read the worklist and send images.

| Field | Kol-CI value | Notes |
| --- | --- | --- |
| Gateway | the Kol-CI gateway | The one from step 1. |
| AE Title | `PIH_KOL-CI_GW` | Must match the simulator's `gateway_ae` in puppet exactly. |
| Description | anything |  |
| Port | `11112` | Must match the simulator's `gateway_port` (default `11112`). The gateway uses the server's network, so it opens this port directly on `somprinfappclstr-01`. |

[Local AE Setup Screenshot](local-ae-setup.webp)

## 3. A Remote AE for the modality simulator

**Configuration \> Remote AEs \> +**

A Remote AE tells the gateway which devices may connect to its Local AE. The gateway refuses a device whose AE title it doesn't recognise.

| Field | Kol-CI value | Notes |
| --- | --- | --- |
| Type | **AdvaPACS Gateway** | Not "AdvaPACS Cloud": the simulator connects to the gateway, not straight to the cloud. |
| Name | e.g. "Kol-CI modality simulator" |  |
| AE Title | `KOL-CI_SIM` | Must match the simulator's `calling_ae` in puppet exactly, case included. |
| Host | anything | Required, but not used here (see **Allow IP mismatch**). |
| Port | anything | Required, but not used: the simulator never listens for connections, so the gateway never connects back to it. |
| **Allow IP mismatch** | **On** | **Required.** The simulator runs in a Docker container, so it connects from the container's internal address, which isn't the Host above and can change whenever the container is recreated. With this off, the gateway rejects it. |
| Worklist / Allow Query | On | Lets the simulator read the worklist. |
| Enabled | On |  |

[Remote AE Setup Screenshot](remote-ae-setup.webp)

# Troubleshooting

| Symptom | Likely cause / what to do |
| --- | --- |
| No transaction appears in OpenHIM | Check that the patient has a Lesotho EMR ID. Wait at least 15 seconds and refresh. |
| An order placed earlier never went through | In this protoype, orders placed while the mediator was restarting or down are **never** picked up later. (This will be improved prior to production) |
| Transaction failed on "Mediator to AdvaPACS Order Push" | Open the transaction and read the AdvaPACS response. |
| Can't log in to the OpenHIM console | Make sure you're using the `https://kol-ci.pih-emr.org/openhim` address and the credentials from Bitwarden. |
| The modality simulator's console doesn't load | Check that you're connected to Tailscale and using `http://100.90.25.20:8095` (http, not https). |
| Simulator: "couldn't be reached, or closed the connection" | The gateway isn't listening on its DICOM port yet. In AdvaPACS, check that the gateway is **Online** and has the Local AE `PIH_KOL-CI_GW` on port `11112` (Setting up AdvaPACS, steps 1–2). |
| Simulator: "rejected the association" | The gateway doesn't accept the simulator. In AdvaPACS, check the `KOL-CI_SIM` Remote AE (step 3): **Allow IP mismatch** is on, it is enabled, its type is AdvaPACS Gateway, and the AE title is spelled exactly, case included. Also check that the Local AE is `PIH_KOL-CI_GW`. |
| Simulator: "accepted the association but not the worklist query" | The `KOL-CI_SIM` Remote AE isn't allowed to query the worklist. Turn on its worklist and query permissions. |
| The simulator's worklist is empty, or an order is missing from it | Check that the order reached AdvaPACS (steps 5–6 of the workflow), and that its status there is **In Process**, not Scheduled (step 7): AdvaPACS leaves Scheduled orders off the gateway's worklist. An order without an accession number is listed but can't be acquired, because AdvaPACS would put its images in the Validation Queue. |

If the problem persists, contact the HIS team.

# Current limitations: prototype, not production-ready

> **Warning**
The AdvaPACS mediator is a **simplified prototype**. It would need significant hardening before production use.
>
> **We are deliberately not hardening it now.** We may move from today's **pull** model, where the mediator polls OpenMRS for new orders, to a **push** model, where OpenMRS sends each order to OpenHIM as it's placed. That change would replace much of the current design.
>
> **Results back to OpenMRS has not yet been implemented.**

Known simplifications in the current (pull) design:

**Polling**

- The mediator checks OpenMRS every 15 seconds.
- It remembers what it has already processed only in memory. Orders placed while it is down or restarting are missed.
- It doesn't filter orders by status.

**Hardcoded workarounds**

- The modality is always "CR".
- Some order details aren't sent (encounter, ordering provider, location).

**Error handling**

- OpenHIM retries only on network or connection failures, not when AdvaPACS returns an error.
- There is no alerting on failed orders.

**Modality simulator**

- Its images are generated: a grey shape with the patient, accession number and procedure written on it, marked "simulated". They test the flow, not image reading. An AI read would reject them.
- It supports CR, US and CT only. It doesn't send progress messages (MPPS) back to the gateway.
- Its console has no login. Anyone on the tailnet who can reach the server on port 8095 can use it, including sending studies to AdvaPACS.

**Operations**

- The Kol-CI software images track the latest builds and update automatically. The exception is the AdvaPACS gateway, which is pinned to an AdvaPACS release and upgraded deliberately.
- OpenHIM's transaction history isn't backed up.

# For the technical team

**Deployment**

- Puppet manages the instance: the `openmrs_docker` module, node `somprinfappclstr-01`, in the `kol-ci` section of `manifests/site.pp` in PIH puppet. Secrets live in encrypted hiera.

**Docker components**

- The compose files come from [openmrs-contrib-distro-tools](https://github.com/PIH/openmrs-contrib-distro-tools):
    - `docker/services/openhim.yaml`: OpenHIM core, console and MongoDB.
    - `docker/services/openhim-advapacs-mediator.yaml`
    - `docker/services/advapacs-gateway.yaml`: the AdvaPACS gateway.
    - `docker/services/modality-simulator.yaml`: the modality simulator.
- OpenHIM docs are in distro-tools' `docs/services.md`.

**AdvaPACS gateway**

- Image `advahealthsolutions/advapacs-gateway`, pinned to `1.21.1`. Declared in puppet as `openmrs_docker::service::advapacs_gateway { 'kol-ci': }`.
- It is registered in AdvaPACS under **Configuration \> Gateways**. Region `usa1`. Its access key ID and secret are in encrypted hiera. The secret is shown only once in AdvaPACS, and regenerating it replaces the old one.
- It uses the host's network, so its listening ports (Local AEs and HL7 inbound services) are set in AdvaPACS and pushed to the gateway, not set in puppet. A device sending DICOM must be able to reach `somprinfappclstr-01` on the port configured there.
- Received studies, the upload queue and its database are in the `advapacs-gateway-data` Docker volume. Leave the gateway's Data Directory in AdvaPACS at the default (`/opt/AdvaHealthSolutions/AdvaPACSGateway`), or the data lands outside the volume.

**Modality simulator**

- Source: [PIH/modality-simulator](https://github.com/PIH/modality-simulator). Its README covers settings, the image library and an end-to-end checklist. Image `partnersinhealth/modality-simulator:latest`.
- Declared in puppet as `openmrs_docker::service::modality_simulator { 'kol-ci': }`, with `gateway_ae => 'PIH_KOL-CI_GW'`, `calling_ae => 'KOL-CI_SIM'` and `host_port => '100.90.25.20:8095'`. It has no secrets.
- It connects to the gateway at `host.docker.internal:11112`. The gateway uses the host's network, so that address reaches it from the simulator's container.
- Its console is published only on `100.90.25.20:8095`, `somprinfappclstr-01`'s Tailscale IP, because it has no login. Tailscale must be up on the server when Docker starts the container (it normally is after a reboot), or Docker can't bind the port. If the server's Tailscale IP ever changes, update `host_port` in site.pp.
- It needs the Local AE `PIH_KOL-CI_GW` and the Remote AE `KOL-CI_SIM` (with **Allow IP mismatch** on) described in Setting up AdvaPACS.
- It keeps a log of every acquisition in the `modality-simulator-data` volume. Auto-acquire, which sends images for every new order without clicking, is off.
- To send real images instead of generated ones, put **de-identified** DICOM files in `/home/kol-ci/modality-simulator-images` on the server.

**Mediator**

- Source: [PIH/openhim-advapacs-mediator](https://github.com/PIH/openhim-advapacs-mediator). Its README covers the design and known limitations in detail.
- Each push to `main` builds `partnersinhealth/openhim-advapacs-mediator:latest` and deploys it to Kol-CI.

**Related tickets:** UHM-9455 (deploy OpenHIM prototype), TASKS-596 (OpenHIM console addresses; mediator registration), UHM-9562 (AdvaPACS gateway), UHM-9564 (modality simulator).
