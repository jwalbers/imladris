# AdvaPACS FHIR R5 Integration — Admin Notes

## Gateway: advapacs-gw-01 (current as of July 2026)

The original gateway (`imladris-bophelong`) was replaced with a clean-slate gateway
(`advapacs-gw-01`) after its API key stopped authenticating.  Key facts:

| Item | Value |
|------|-------|
| Container image | `advahealthsolutions/advapacs-gateway:1.19.1` |
| Local AE | `ADVAPACS_GW_01` on port 11112 |
| Accepted Calling AEs | `IML_CR_01`, `IML_US_01`, `IML_CT_01` |
| IP Whitelist | `68.116.51.0/8`, `192.168.3.0/24`, `192.168.1.0/24`, `172.19.0.0/24`, `172.16.0.0/12` |
| DICOMweb Proxy | **Disabled** (old gateway had it enabled, but it had an NPE bug; direct STOW-RS to the AdvaPACS cloud DICOMweb API works independently) |
| Credentials | `docker/ap-qs/.env` → `ADVAPACS_GW_KEY_ID`, `ADVAPACS_GW_SECRET` |

### Gateway credential lifecycle

Gateway API keys are generated **once at gateway creation time** and are never shown again.
The portal's "Regenerate keys" button issues a new key, but per AdvaPACS docs this requires
reinstalling (restarting) the gateway container with the new credentials.

If a key needs to be replaced:
1. Disable the old gateway in the AdvaPACS portal (required before deletion).
2. Create a new gateway object — copy the one-time key ID and secret immediately.
3. Update `ADVAPACS_GW_KEY_ID` / `ADVAPACS_GW_SECRET` in `.env`.
4. `docker compose up -d --force-recreate advapacs-gateway` — the container picks up its
   Local AE title and accepted-AE config from the cloud on startup; no env var needed for AET.

### Two separate credential pairs

| Purpose | Env vars | Auth endpoint |
|---------|----------|---------------|
| FHIR R5 API + DICOMweb | `ADVAPACS_KEY_ID`, `ADVAPACS_SECRET` | `usa1.api.integration.advapacs.com/fhir/R5` |
| Gateway container | `ADVAPACS_GW_KEY_ID`, `ADVAPACS_GW_SECRET` | `usa1.api.gateway.advapacs.com/auth/token` |

Using FHIR credentials for the gateway (or vice-versa) causes 401 on startup.  The gateway
will still accept local C-STOREs (returning 0x0000) but will silently discard them rather
than forwarding to the cloud.

---

## Multiple Assigning Authorities (enabled 2026-07-10, irreversible)

### Background

When AdvaPACS "Multiple Assigning Authorities" is disabled (the default), patient identifiers
do not require a `system` field.  Once enabled:

- Every FHIR identifier (Patient, ServiceRequest) **must** carry a `system` URI.
- Each `system` URI must match a `NamingSystem` registered in AdvaPACS.
- **This setting cannot be reversed.**

We enabled it because AdvaPACS began rejecting Patient POSTs with 422 "Unknown system" when
`"system": "http://openmrs.org/identifier"` was present, and with 422 "Identifier system
required" when the field was omitted.  Enabling Multiple Assigning Authorities lets us
register `http://openmrs.org/identifier` as a valid system.

### Portal configuration

**Path:** Admin → Settings → Assigning Authorities

Fields entered at enable time:

| Field | Value | Notes |
|-------|-------|-------|
| Namespace ID | `PIH_A` | HL7 v2 assigning authority short name; becomes DICOM tag 0010,0021 "Issuer of Patient ID".  Chosen as a PIH global assigning authority prototype. |
| Universal Entity Type ID | `URI` | |
| Universal Entity ID | (blank) | |
| Backfill existing patients/studies | Checked | Retroactively stamps existing records with PIH_A as issuer. |

AdvaPACS automatically created **two** NamingSystem resources from the one entry:

| NamingSystem type | Identifier type | FHIR System URI (set manually) |
|-------------------|-----------------|-------------------------------|
| PN (Patient Number) | Patient identifiers | `http://openmrs.org/identifier` |
| ACSN (Accession Number) | Accession identifiers | `http://imladrislab.org/accession-number` |

The FHIR System URI for each was set via the edit dialog in the NamingSystems list after
enabling.  These URIs are what appear as the `system` field in FHIR resources.

### Why PIH_A?

`PIH_A` is being used as a prototype for a PIH-wide global patient identifier assigning
authority.  Underscores are valid in HL7 v2 IS (coded string) data types and in DICOM LO
values, so `PIH_A` is safe.  The suffix leaves room for future regional or role variants.

### Adding more assigning authorities later

After enabling, additional NamingSystems can be added through Admin → Settings →
Assigning Authorities.  Each new entry requires a Namespace ID; FHIR System URI is set
separately in the edit dialog.

---

## FHIR R5 Identifier Patterns

These patterns apply to all code that creates resources in AdvaPACS.

### Patient

```json
{
  "resourceType": "Patient",
  "identifier": [
    { "system": "http://openmrs.org/identifier", "value": "EKHF7G" }
  ],
  "name": [{ "family": "Mokoena", "given": ["Tau"] }],
  "gender": "male",
  "birthDate": "1990-03-15"
}
```

Search: `GET /fhir/R5/Patient?identifier=EKHF7G` — no system qualifier needed for search.

### ServiceRequest identifiers

```json
"identifier": [
  {
    "system": "http://imladrislab.org/accession-number",
    "type": {
      "coding": [{ "system": "http://terminology.hl7.org/CodeSystem/v2-0203", "code": "ACSN" }]
    },
    "value": "TC-0710194256"
  },
  {
    "system": "urn:dicom:uid",
    "value": "urn:oid:1.2.826.0.1.3680043.8.498...."
  }
]
```

Both identifiers are required.  The `urn:dicom:uid` entry does not require an assigning
authority match.

### Modality in ServiceRequest.orderDetail

AdvaPACS uses a **proprietary** coding system for the orderDetail parameter — not the DICOM
DCM system.  Using the DICOM DCM system URI causes the literal text `"modality"` to appear
in the worklist Modality column instead of the modality code.

```json
"orderDetail": [{
  "parameter": [{
    "code": {
      "coding": [{
        "system": "http://advapacs.com/fhir/servicerequest-orderdetail-parameter-code",
        "code": "modality"
      }]
    },
    "valueString": "CR"
  }]
}]
```

`valueString` is the DICOM modality code: `CR`, `US`, `CT`, `MR`, `RF`, etc.

---

## Order Poller State Management

`sidecar/order_poller.py` polls OpenMRS for new radiology orders and posts them to AdvaPACS
as FHIR ServiceRequests.  State is persisted to `/data/order_poller_state.json` on the
`sidecar-data` Docker volume:

```json
{ "last_polled": "2026-07-10T20:00:19+00:00", "fail_counts": {} }
```

**`last_polled`** — Updated to `max(dateActivated) + 1 second` after each poll, regardless
of whether individual orders succeeded.  Orders with `dateActivated < last_polled` are never
re-fetched from OpenMRS.

**`fail_counts`** — Orders that fail 3 consecutive times are silently skipped on future polls
(logged at DEBUG level only).  Keyed by raw accession number or order UUID.

### Resetting stuck orders

If the poller stops picking up orders (fail_counts at 3, or last_polled advanced past the
order's dateActivated):

```powershell
# 1. Stop the sidecar — must be stopped before editing the file
cd docker\ap-qs
docker compose stop modality-sidecar

# 2. Write a clean state file to the volume (PowerShell — avoids quoting issues)
$json = '{"last_polled":"2026-07-10T18:00:00+00:00","fail_counts":{}}'
$tmp  = "$env:TEMP\order_poller_state.json"
[System.IO.File]::WriteAllText($tmp, $json)
docker cp $tmp imladris-sidecar:/data/order_poller_state.json

# 3. Verify
docker run --rm --volumes-from imladris-sidecar busybox cat /data/order_poller_state.json

# 4. Rebuild and start (or just start if no code changes)
docker compose up -d --build modality-sidecar
```

> **Do not** edit the state file while the sidecar is running — the poller writes the file
> after every poll cycle and will immediately overwrite manual changes.

### OpenMRS dateActivated format

OpenMRS returns `dateActivated` as `"2026-07-10T05:35:02.000+0000"` (fractional seconds,
timezone offset without colon).  FHIR R5 requires `"2026-07-10T05:35:02+00:00"`.
`order_poller._post_service_request()` normalises the string before posting:

```python
_raw = re.sub(r'\.\d+', '', occurrence)                              # strip .NNN
occurrence_dt = re.sub(r'([+-])(\d{2})(\d{2})$', r'\1\2:\3', _raw) # +0000 → +00:00
```
