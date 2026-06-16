# Entra SAML 2.0 Authentication — IMLADRIS Lab

Replaces the HAProxy htpasswd stopgap with server-side SAML via
**SimpleSAMLphp** acting as the Service Provider against the
**PIH Microsoft Entra ID** tenant.

---

## Architecture

```
Browser
  │
  ▼
pfSense HAProxy (imladrislab.org:443 HTTPS)
  │
  ▼ Imladris_Landing backend (port 8091)
SimpleSAMLphp SP container (imladris-saml-sp)
  │
  ├─ /simplesaml/*  → SimpleSAMLphp SAML engine
  │                   (ACS, metadata, login, logout)
  │
  └─ /              → index.php (PHP portal)
       │ requireAuth() — if not authed, redirects to /simplesaml/login → Entra
       └─ if authed   — readfile(landing.html), auth bar JS calls /user-info.php
```

Sub-services (OpenMRS, Orthanc, OHIF, Console) are **not** gated by SAML —
they retain their own application-level auth.  Add them to the SAML gate
later if needed by repeating the Imladris_Landing backend pattern for each.

---

## Registration details

| Field | Value |
|---|---|
| **SP Entity ID** | `https://imladrislab.org` *(PIH IT registered this simplified form)* |
| **SP Entity ID (original)** | `https://imladrislab.org/simplesaml/module.php/saml/sp/metadata.php/default-sp` *(what we gave them; they simplified it)* |
| **ACS URL** | `https://imladrislab.org/simplesaml/module.php/saml/sp/saml2-acs.php/default-sp` |
| **NameID format** | `emailAddress` (`user.mail`) |
| **IdP Entity ID** | `https://sts.windows.net/5254789f-6860-4375-85bc-302509fad508/` |
| **IdP SSO URL** | `https://login.microsoftonline.com/5254789f-6860-4375-85bc-302509fad508/saml2` |
| **App ID** | `6f1a7974-8579-4f06-bf44-efce1aec9d39` |
| **Tenant ID** | `5254789f-6860-4375-85bc-302509fad508` |
| **Metadata URL** | `https://login.microsoftonline.com/5254789f-6860-4375-85bc-302509fad508/federationmetadata/2007-06/federationmetadata.xml?appid=6f1a7974-8579-4f06-bf44-efce1aec9d39` |
| **Entra signing cert valid until** | 2029-06-16 |

---

## Files

| File | Purpose |
|---|---|
| `docker/simplesamlphp/config/config.php` | Core SimpleSAMLphp config (baseurlpath, cookie settings) |
| `docker/simplesamlphp/config/authsources.php` | SP definition (entityID, IdP, NameID, attributes) |
| `docker/simplesamlphp/metadata/saml20-idp-remote.php` | IdP metadata (SSO URL, Entra signing cert) |
| `docker/simplesamlphp/www/index.php` | Auth-gated portal — calls `requireAuth()`, serves landing.html |
| `docker/simplesamlphp/www/user-info.php` | JSON endpoint for auth bar (name/email from session) |
| `docker/simplesamlphp/cert/` | SP signing keypair (optional — see below) |

---

## First-time setup

### 1. Generate a secretsalt and admin password

```bash
openssl rand -base64 32   # → paste as SAML_SP_SECRETSALT in .env
```

Add to `docker/.env`:
```
SAML_SP_SECRETSALT=<output from openssl above>
SAML_ADMIN_PASSWORD=<choose a strong password>
```

### 2. Start the container

```bash
cd docker
docker compose up -d simplesamlphp
```

### 3. Verify SimpleSAMLphp is running

```
http://localhost:8091/simplesaml/
```

You should see the SimpleSAMLphp admin page (password-protected).

### 4. Test the auth flow end-to-end

```
https://imladrislab.org/
```

Should redirect to `login.microsoftonline.com` → authenticate with your
`@pih.org` account → land back on the Imladris portal with your name in
the auth bar.

### 5. Update pfSense HAProxy

Two changes in the pfSense HAProxy GUI:

**Backend `Imladris_Landing`** — change server address:
- Old: `192.168.1.11:8090`
- New: `192.168.1.11:8091`

Add a header to the backend:
- `http-request set-header X-Forwarded-Proto https`
  (Required: SimpleSAMLphp uses this to build redirect URLs correctly,
   and for the `SameSite=None; Secure` cookie the SAML POST needs.)

**Frontend Advanced Pass Thru** — remove these three lines entirely:
```
acl is_imladris_openmrs_auth hdr(host) -m str -i openmrs.imladrislab.org
acl is_imladris_domain hdr(host) -m reg -i ^(imladrislab\.org|.*\.imladrislab\.org)$
http-request auth realm ImladrisLab if is_imladris_domain !{ http_auth(imladris_users) } !is_imladris_openmrs_auth
```

**Global Advanced Pass Thru** — remove the userlist block:
```
userlist imladris_users
    user imladris password $apr1$...
```

---

## Optional: SP signing certificate

Not required for the lab — Entra doesn't enforce signed AuthnRequests
by default.  Add it for production hardening:

```bash
cd docker/simplesamlphp/cert
openssl req -newkey rsa:3072 -new -x509 -days 3650 -nodes \
  -out saml.crt -keyout saml.pem \
  -subj "/CN=imladrislab.org"
```

Then:
1. Send `saml.crt` to PIH IT — they upload it to the Entra enterprise app
   under **SAML Certificates → Verification certificates**.
2. Uncomment `'privatekey'` and `'certificate'` in
   `docker/simplesamlphp/config/authsources.php`.
3. Restart the container: `docker compose restart simplesamlphp`

---

## Entra signing cert rotation

Entra auto-rolls its signing cert approximately every 3 years.
PIH IT will notify when this happens.  To update:

1. Fetch new cert from the federation metadata URL (see table above).
2. Extract the `X509Certificate` value from `IDPSSODescriptor`.
3. Replace `certData` in
   `docker/simplesamlphp/metadata/saml20-idp-remote.php`.
4. `docker compose restart simplesamlphp`

---

## Troubleshooting

**"Unapproved requester" or "AADSTS" error from Entra**
→ The SP Entity ID in `authsources.php` doesn't match what PIH IT
  registered in the enterprise app.  Verify exact string match.
  PIH IT used `https://imladrislab.org` (not the full metadata URL).

**SimpleSAMLphp "Audience mismatch" / assertion rejected**
→ The `entityID` in `authsources.php` must exactly match what Entra has
  as the "Identifier (Entity ID)" in its enterprise app registration.
  Currently set to `https://imladrislab.org` to match what PIH IT entered.

**Redirect loop (never gets past login)**
→ Check `SameSite=None` is set — SimpleSAMLphp can't receive the
  SAML POST from Entra without it.  Verify `session.cookie.secure = true`
  and that HAProxy is sending `X-Forwarded-Proto: https`.

**"SimpleSAMLphp error: Could not find metadata for..."**
→ `saml20-idp-remote.php` key must exactly match the `idp` value in
  `authsources.php` (both `https://sts.windows.net/{tenant-id}/`).

**Auth bar doesn't show user name**
→ Check browser console for `/user-info.php` 401 or network error.
  A 401 means the SimpleSAMLphp session cookie isn't being sent (SameSite
  or HTTPS issue).

**Testing locally without auth**
→ Use `http://localhost:8090` (nginx-landing, no auth).  The auth bar JS
  calls `/user-info.php` and silently hides the bar on error.
