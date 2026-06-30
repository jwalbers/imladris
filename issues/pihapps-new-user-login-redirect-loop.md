# New users without roles get ERR_TOO_MANY_REDIRECTS on first login

**Target module:** `openmrs-module-pihapps` (LoginLocationFilter + loginLocation page)  
**Related:** `openmrs-module-authenticationui` (post-login redirect flow)  
**Type:** Bug / UX improvement  
**Priority:** Medium  
**Status:** Draft — consider filing at GitHub openmrs/openmrs-module-pihapps or talk.openmrs.org

---

## Summary

When a new user is created in the admin UI without any roles assigned, their first login
results in `ERR_TOO_MANY_REDIRECTS` (Chrome) or "page isn't redirecting properly" (Firefox)
with no diagnostic information shown to the user or admin. The root cause is a privilege
check inside `loginLocation.page` that fires before the user has been given appropriate roles,
creating an unbreakable redirect loop between the location-selection page and an error handler.

## What happens — the redirect chain

1. User submits username + password → authentication succeeds → redirected to `loginLocation.page`
2. `loginLocation.page` controller calls `getProvidersByPerson()` internally, which requires
   the **"Get Providers"** privilege
3. The user has no roles → no privileges → `AuthorizationAdvice` throws
   `"Privileges required: Get Providers"`
4. The uiframework/error handler redirects the response (e.g. to an error page)
5. `RequireLoginLocationFilter` intercepts the error-page request — the user still has no
   login location — and redirects back to `loginLocation.page`
6. Go to step 2. Browser gives up after ~20 iterations: **ERR_TOO_MANY_REDIRECTS**

The loop is invisible to the user (they see only a browser error) and invisible to the admin
(no log entry clearly connects the blank-roles account to the redirect symptom).

## Who is affected

Any user account created:
- without assigning a role that includes the **"Get Providers"** privilege (in our distro,
  that means `Privilege Level: Full` or `Privilege Level: High` must be present), or
- without assigning any role at all (the OpenMRS admin UI allows this; it gives no warning)

Superusers (`System Developer` role) are immune because OpenMRS bypasses privilege checks
for superusers. This is why admin accounts work while freshly-created clinical users do not.

## Workaround (now)

Assign at minimum `Privilege Level: Full` to any clinical user. In SQL:
```sql
INSERT INTO user_role (user_id, role) VALUES (<user_id>, 'Privilege Level: Full');
```
Then restart OpenMRS (or log the user out and back in) to flush the Hibernate role cache.

## Suggested fixes

### Short-term (module level — pihapps)

1. **Guard the privilege call in `loginLocation.page`.**  
   Wrap the `getProvidersByPerson()` call in a proxy-privilege block or a null-safe check
   so that the page can still render (or at least fail gracefully to a readable error) when
   the user lacks "Get Providers". The location picker does not actually need provider lookup
   for its core function.

2. **Whitelist error/exception pages in `RequireLoginLocationFilter`.**  
   If the filter detects it is already redirecting from an error or exception page back to
   `loginLocation.page`, break the loop and surface a meaningful message like
   "Your account is missing required roles — contact your administrator."

### Medium-term (admin UX)

3. **Warn when saving a new user with no roles.**  
   The admin user-creation form should show a visible warning (or block save) if no role is
   selected, since a roleless user cannot log in to a PIH distribution.

4. **Ship a minimum viable default role for new users.**  
   Consider a `Default User` role (or include `Privilege Level: Full` in any application
   role hierarchy) so that basic page rendering never requires manual privilege-chasing.

### Long-term (authentication module)

5. **Surface post-login errors as user-visible messages, not redirect loops.**  
   If `loginLocation.page` (or any post-login landing page) throws an unhandled exception,
   the authentication module's `redirectAfterLogin` flow should catch this and show a
   diagnostic error to the logged-in user rather than entering a redirect cycle.

## Environment where this was diagnosed

- Distribution: PIH Lesotho (`partnersinhealth/lesotho-emr`, pih.config=lesotho,lesotho-botsabelo-demo)
- Modules: `pihapps` (version in distro), `authentication` 2.3.0, `authenticationui` 1.3.0
- OpenMRS core: 2.8.7
- Authentication scheme: `TwoFactorAuthenticationScheme` (2FA config)
- Context: imladris radiology stack (MDR-TB chest X-ray screening at Bophelong/Botsabelo)

## How this was diagnosed

1. Observed `ERR_TOO_MANY_REDIRECTS` for all non-admin users
2. Used REST API (`/ws/rest/v1/session`) to confirm the session WAS authenticated
3. Traced `GET /openmrs/` → 302 → `loginLocation.page` with the live JSESSIONID
4. Retrieved `loginLocation.page` directly — response body was the JSON exception stack trace:
   `"Privileges required: Get Providers"` from `AuthorizationAdvice.throwUnauthorized`
5. Identified `RequireLoginLocationFilter` as the loop-closing redirect (line 78 in stack trace)
6. Fix: added `Privilege Level: Full` to affected user accounts

---

## Notes on filing

- Likely belongs in **openmrs-module-pihapps** (GitHub: `PIH/openmrs-module-pihapps`) since
  both the filter and the page are in that module
- Secondary issue for the admin UX warning could be filed against
  **openmrs-module-authenticationui** or OpenMRS core
- Reference this issue alongside `openmrs-auth-module-rest-api-2fa.md` (also in imladris/issues)
  as a pattern: authentication module interactions with PIH modules produce silent, hard-to-diagnose
  failures for non-expert administrators
