# REST API service accounts and 2FA: documentation gap + behavior clarification

**Target:** OpenMRS Authentication Module (JIRA project: AUT)  
**Type:** Improvement / Informational  
**Priority:** Minor  
**Status:** Draft — pending OpenMRS JIRA access (file at issues.openmrs.org or as GitHub issue/PR on openmrs/openmrs-module-authentication)

---

## Summary

When the `authentication` module is deployed with `TwoFactorAuthenticationScheme`
as the active scheme, REST API clients using HTTP Basic Auth (Authorization header)
will fail silently if the service account user has a secondary authentication factor
configured (`authentication.secondaryType` user property). This is currently not
documented and the failure mode is difficult to diagnose.

## What happens

`TwoFactorAuthenticationScheme.getCredentials()` runs the primary factor (username/password)
check successfully, then looks for a secondary factor for the user. If no secondary
credentials can be extracted from the request (there's no way to pass a TOTP code
or secret question answer in a REST Authorization header), `getCredentials()` returns
null. The `AuthenticationFilter` then treats the request as having no credentials and
redirects (or sets a `Location` header) rather than returning a 401 with auth failure.

The result: a REST API client with a valid username/password gets a 302 redirect (or
a 200 with a `Location` header for `/ws/rest/*/session`) with no indication that the
secondary factor is the problem. The `AUTHENTICATION_FAILED` events in the log show
`schemeId=basic` (not 2fa), further obscuring the root cause.

## Concrete scenario that triggered this report

A service account (`imladris-service`) was inadvertently configured with TOTP
as a secondary factor while setting up a new deployment. The order-polling sidecar
began receiving redirects on every REST call. The `loginAttempts` counter in
`user_property` accumulated from automated retries until the account was locked out
(`lockoutTimestamp` set), at which point even removing the TOTP still didn't restore
access until the lockout was cleared and OpenMRS restarted to flush Hibernate cache.

Total diagnostic time: several hours, because:
- The log event showed `schemeId=basic, AUTHENTICATION_FAILED` (not `schemeId=2fa`)
- The `Location` header pointed to the login page, not a 2FA-specific page
- Account lockout from retries compounded the confusion

## Suggested improvements

**Documentation:**
1. Add a section to the README explicitly addressing REST API service accounts:
   - Service accounts used only for REST API access must NOT have any secondary
     authentication factor set (`authentication.secondaryType` user property absent or empty)
   - Recommend a dedicated service account with no secondary factor for programmatic access
   - Note that `authentication.whiteList` may be useful to include REST paths
     (`/ws/rest/**,/ws/fhir2/**`) to ensure unauthenticated requests to REST endpoints
     get a 401 rather than a login page redirect

2. Add a note to the TwoFactorAuthenticationScheme documentation that secondary factors
   are incompatible with REST API basic auth, linking to the service account guidance.

**Possibly worth considering:**
- When a request carries an `Authorization: Basic` header (explicit credential attempt),
  should the filter return 401 rather than redirecting — even for 2FA-configured users?
  Currently the 302/Location behavior applies whether or not credentials were attempted.
- The REST session endpoint (`/ws/rest/*/session`) already gets the `Location` header
  instead of a redirect, but other endpoints do not.
- A higher (or separate) lockout threshold for non-browser clients (those sending
  an Authorization header) might reduce the blast radius of misconfiguration.

## Environment

- `authentication` module: 2.3.0
- `authenticationui` module: 1.3.0
- OpenMRS core: 2.8.7
- Configuration: `authentication.scheme = 2fa` (TwoFactorAuthenticationScheme wrapping basic + totp/secret/email)

---

## Notes on filing

- JIRA project key: **AUT** at issues.openmrs.org (requires OpenMRS ID linked to Atlassian account — auth flow unclear as of 2026-06-29, ask on talk.openmrs.org)
- Alternative: file as GitHub Discussion or README PR on https://github.com/openmrs/openmrs-module-authentication
- Consider cross-posting on talk.openmrs.org in #dev after filing, citing PIH Lesotho MDR-TB screening deployment as the real-world context
