# OpenMRS TOTP: "Invalid credentials" with fast-fill authenticators (1Password, Bitwarden)

**Target:** OpenMRS Authentication Module (JIRA project: AUT)  
**Type:** Bug / Robustness  
**Priority:** Minor  
**Status:** Draft — parked for future investigation

---

## Summary

Users of browser-integrated TOTP authenticators (1Password, Bitwarden, etc.) occasionally
receive "Invalid credentials" on the first login attempt when the TOTP code is submitted
near the end of its 30-second validity window. Retrying once or twice succeeds because a
new, fresh code is submitted. Users using hardware tokens or manual entry (Google
Authenticator, Authy) are much less likely to trigger this — they introduce natural delay
between copying the code and submitting the form.

## What happens

1. Browser extension auto-fills username, password, and TOTP code in ~0-100ms.
2. The filled TOTP code was valid at fill time but is at second 29 of its 30-second window.
3. By the time the form POST reaches the server and the authentication module validates the
   code, the window has rolled over.
4. The code is now in the previous window, which the module rejects → "Invalid credentials".
5. User retries. Extension fills a fresh code from the new window. Login succeeds.

This is a TOTP clock-skew problem. RFC 6238 §5.2 recommends implementations allow
a tolerance of at most one time-step in each direction (±30 seconds = ±1 window) to
account for transmission delay and minor clock drift. If OpenMRS's TOTP implementation
only accepts the exact current window, fast-fill clients will hit this intermittently.

## Concrete scenario that triggered this report

- User: Botsabelo Hospital demo deployment, clinical users with 1Password browser extension
- Frequency: occasional — maybe 1 in 10 logins for a user who lets 1Password auto-submit
- Impact: confusing but not blocking — second attempt always succeeds
- Lab observation: confirmed that retrying immediately with the same session succeeds,
  consistent with a new TOTP code being generated (not a session/cookie issue)

## Fix to investigate

Check whether `openmrs-module-authentication` exposes a global property for TOTP
clock skew tolerance:

- Admin → Global Properties, search for `authentication.totp` or `totp.allowed`
- If a `totp.clockSkew` or `totp.allowedWindowCount` property exists, set it to `1`
  (allow ±1 adjacent window in addition to the current)
- If no GP exists, the fix requires a code change in the TOTP validation logic

Standard fix in RFC 6238 implementations:

```java
// Accept current window ±1 adjacent window
for (int i = -1; i <= 1; i++) {
    long timeStep = (Instant.now().getEpochSecond() / 30) + i;
    if (computedTotp(secret, timeStep).equals(submittedCode)) return true;
}
```

This ±30-second tolerance is negligible from a security perspective (TOTP is already
limited to 30-second windows) and is consistent with Google Authenticator, Duo, and
most other TOTP validators.

## Upstream suggestion

If the module does not already implement window tolerance, add it and expose a GP:

```
authentication.totp.allowedSkewWindows = 1   (default: 1, min: 0, max: 2)
```

Document that browser-integrated password managers trigger this more often than manual
entry, as rationale for defaulting to 1 rather than 0.

## Environment

- `authentication` module: 2.3.0  
- OpenMRS core: 2.8.7  
- Clients affected: 1Password browser extension (and likely Bitwarden, Dashlane — any
  extension that auto-submits immediately after fill)
- Clients not affected: Google Authenticator / Authy (manual copy-paste introduces
  sufficient delay to stay well within the current window)

---

## Notes

- Low priority for the Imladris lab — users work around it by retrying.
- Higher priority for production Botsabelo: clinical users with 1Password will encounter
  this regularly, and "Invalid credentials" on the first TOTP attempt erodes confidence
  in the auth system.
- File as GitHub issue on https://github.com/openmrs/openmrs-module-authentication
  after verifying no existing issue covers this (search: "totp window", "clock skew",
  "1password", "autofill").
