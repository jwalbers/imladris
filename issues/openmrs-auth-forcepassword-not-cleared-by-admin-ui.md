# Admin UI "Require password change" checkbox does not clear forcePassword flag — new users always intercepted on login

**Target module:** `openmrs-module-authentication` / `openmrs-module-legacyui`  
**Related:** `openmrs-module-coreapps` (Manage Accounts), `openmrs-module-authenticationui`  
**Type:** Bug / Property name mismatch  
**Priority:** High (every new user's first login fails or is intercepted; symptom is indistinguishable from wrong password)  
**Status:** Draft — file at GitHub openmrs/openmrs-module-authentication or openmrs/openmrs-module-legacyui

---

## Summary

When a new user is created via the OpenMRS admin UI, the `openmrs-module-authentication`
module sets a `forcePassword=true` user property on the account. On login, this causes every
authentication attempt to be intercepted and redirected to a "Your current password has
expired. Please choose a new password to continue." page — regardless of whether the password
is correct and regardless of the "Require password change" checkbox state in the UI.

The admin UI's "Require that this user change their password on next login" checkbox does
**not** write to the `forcePassword` user property. It writes to a different property
(likely `changePassword`), which the `authentication` module does not read. The result is
that `forcePassword` remains `true` permanently, and no amount of unchecking the checkbox
and saving through either the legacy Manage Users or the Manage Accounts UI will clear it.

The only working remediation is a direct SQL UPDATE on the `user_property` table.

## Symptom

New user accounts cannot log in. The login page accepts the credentials and redirects,
but the user lands on "Your current password has expired. Please choose a new password to
continue." on every attempt, including after an admin has:

1. Gone to Legacy Administration → Manage Users → [user] → Change Password, set a new
   password, and unchecked "Require that this user change their password on next login"
2. Gone to System Administration → Manage Accounts → [user] → Change Password and gone
   through the same process

Both paths appear to succeed (no error shown), but `forcePassword` remains `true` in the
database after saving.

From the admin's perspective this is indistinguishable from a wrong-password failure —
there is no indication in the login flow that the issue is a stuck `forcePassword` flag
rather than incorrect credentials. Time is wasted resetting passwords and testing character
sets before the real cause is found.

## Root cause

The `openmrs-module-authentication` 2.3.0 uses the user property key `forcePassword` to
signal that a password change is required on next login. The legacy admin UI and/or
coreapps Manage Accounts uses a different key (likely `changePassword`) for the
"require password change" checkbox. The two sides are not in sync:

- **Authentication module sets:** `forcePassword = true` (on account creation)
- **Admin UI reads/writes:** `changePassword` (a different property)
- **Authentication module checks on login:** `forcePassword` (ignores `changePassword`)

Unchecking the admin checkbox sets `changePassword = false` or removes it, but leaves
`forcePassword = true` untouched. The authentication module sees `forcePassword = true`
and intercepts every login.

## Confirmed affected users

In a fresh `lesotho-botsabelo-demo` bring-up, all newly created users have `forcePassword=true`:

```sql
SELECT u.username, up.property, up.property_value
FROM users u
JOIN user_property up ON u.user_id = up.user_id
WHERE up.property = 'forcePassword'
ORDER BY u.username;
```

Admin account shows `forcePassword=false` (set explicitly during initialization). All
manually created clinical users show `forcePassword=true`.

## Workaround

After creating users and setting their passwords, run:

```sql
UPDATE user_property
SET property_value = 'false'
WHERE property = 'forcePassword'
  AND user_id IN (
    SELECT user_id FROM users
    WHERE username IN ('username1', 'username2', ...)
  );
```

Or clear for all non-admin users at once:

```sql
UPDATE user_property
SET property_value = 'false'
WHERE property = 'forcePassword'
  AND user_id NOT IN (
    SELECT user_id FROM users WHERE system_id = 'admin'
  );
```

No OpenMRS restart is required — the flag is read on each login attempt.

## Exact code locations

**`openmrs-module-legacyui`** — `omod/src/main/webapp/admin/users/userForm.jsp`

```jsp
<input type="checkbox" name="forcePassword" value="true"
       <c:if test="${changePassword == true}">checked</c:if> />
```

The JSP renders correctly (checkbox named `forcePassword`), and the display binding
`${changePassword}` is correct because the controller populates that model attribute.

**`openmrs-module-legacyui`** — `omod/src/main/java/org/openmrs/web/controller/user/UserFormController.java`

```java
// Line 55 — read side: put current value into model as "changePassword" for JSP
model.addAttribute("changePassword",
    new UserProperties(user.getUserProperties()).isSupposedToChangePassword());

// Line 124 — write side: bind checkbox POST param
@RequestParam(required = false, value = "forcePassword") Boolean forcePassword,

// Line 215 — write side: persist checkbox value
new UserProperties(user.getUserProperties()).setSupposedToChangePassword(forcePassword);
```

The legacyui controller does call `setSupposedToChangePassword()` when the form is saved.
The bug is one level deeper: **`UserProperties.setSupposedToChangePassword()`** (in
`openmrs-core`) writes the value to the property key `changePassword`, but
`openmrs-module-authentication` 2.3.0 reads and writes the property key `forcePassword`.
These are two separate DB rows with different `property` column values.

**Net effect of unchecking the checkbox:**
1. `setSupposedToChangePassword(false)` → writes `changePassword=false` to `user_property`
2. `forcePassword` row (written by the auth module at account creation) is never touched
3. Next login: auth module reads `forcePassword=true` → intercepts with "password expired"

## Proper fix

Either:

1. **`openmrs-core` `UserProperties`:** Change `setSupposedToChangePassword()` to write
   `forcePassword` instead of (or in addition to) `changePassword`, so legacyui's save
   clears the key the authentication module actually reads.

2. **`openmrs-module-authentication`:** On login check, honor both `forcePassword` and
   `changePassword` property keys (treat either `true` as requiring a password change,
   and treat either `false` as clearing the requirement).

3. **`openmrs-module-legacyui` `UserFormController.java` line 215:** After calling
   `setSupposedToChangePassword()`, also directly clear `forcePassword` from the user's
   properties map when `forcePassword == false`.

4. **Documentation:** Until the code is fixed, add a note to the Manage Users / Manage
   Accounts documentation that the "Require password change" checkbox does not function
   correctly when `openmrs-module-authentication` is installed, and provide the SQL
   workaround.

## Environment

- Distribution: PIH Lesotho (`partnersinhealth/lesotho-emr`, `pih.config=lesotho,lesotho-botsabelo-demo`)
- `openmrs-module-authentication`: 2.3.0
- `openmrs-module-legacyui`: 2.1.0
- OpenMRS core: 2.8.7
- Context: imladris training lab; fresh user creation

## Cross-references

- [pihapps-new-user-login-redirect-loop.md](pihapps-new-user-login-redirect-loop.md) — separate login redirect issue affecting users without roles; same session
- [lesotho-emr-compose-pih-config-quoted-default.md](lesotho-emr-compose-pih-config-quoted-default.md) — other fresh bring-up issue from the same session
