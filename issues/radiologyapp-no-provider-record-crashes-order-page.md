# OrderRadiologyPageController crashes with NoSuchElementException when user has no provider record

**Target module:** `openmrs-module-radiologyapp` (OrderRadiologyPageController)  
**Related:** `pih-config` / admin UX (provider record not created during user setup)  
**Type:** Bug — missing guard + privilege check gap  
**Priority:** High (crashes page; affects all new clinical users)  
**Status:** Draft — file at GitHub PIH/openmrs-module-radiologyapp

---

## Summary

When a user who is not registered as a Provider attempts to open the radiology order page,
the server throws `java.util.NoSuchElementException` and renders a UIFramework error page.
The "Order X-ray" button is shown to the user with no prior privilege/provider check, so
the crash only surfaces after the user fills out the form and clicks the button. There is
no user-visible message explaining what went wrong or how to fix it.

## Stack trace

```
java.util.NoSuchElementException
    at java.base/java.util.ArrayList$Itr.next(ArrayList.java:970)
    at org.openmrs.module.radiologyapp.page.controller.OrderRadiologyPageController.controller(OrderRadiologyPageController.java:76)
```

## Root cause

[OrderRadiologyPageController.java:74-76](https://github.com/PIH/openmrs-module-radiologyapp/blob/master/omod/src/main/java/org/openmrs/module/radiologyapp/page/controller/OrderRadiologyPageController.java#L74):

```java
// TODO better handle the case where this is multiple providers for a single user
Collection<Provider> providers = Context.getProviderService().getProvidersByPerson(Context.getAuthenticatedUser().getPerson());
model.addAttribute("currentProvider", providers.iterator().next());
```

The TODO on line 74 already acknowledges the multi-provider edge case but the code does
not handle the zero-provider case at all. When `getProvidersByPerson()` returns an empty
collection (because the user has no row in the `provider` table), `.iterator().next()`
throws `NoSuchElementException`.

## Who is affected

Any user who:
1. Has been created via the OpenMRS admin UI, AND
2. Was not manually linked to a `provider` record in the `provider` table

The admin user-creation flow does not create a provider record. For PIH deployments that
use the radiologyapp, every ordering clinician must have a provider record, but there is
no UI prompt or warning to alert the admin to create one.

## Privilege check gap

The "Order X-ray" button on the patient dashboard is rendered without checking whether
the logged-in user is a registered provider. The privilege check (such as it is) happens
server-side only after the user has navigated to the order form. This means:

1. User sees the button → clicks it → the order page renders (this now works)
2. User fills out the form → clicks Submit → crash

There is no graceful "you are not configured as a provider" message at any point in the flow.

## Fix applied (workaround)

Create a `provider` row for each clinical user directly in the DB:

```sql
INSERT INTO provider (person_id, identifier, creator, date_created, retired, uuid)
VALUES
  (<person_id>, 'PROV-<username>', 1, NOW(), 0, UUID());
```

Then restart OpenMRS to flush the Hibernate provider cache.

In our deployment:
- tmokoena (person_id=3) → `PROV-TMOKOENA`
- msello (person_id=55) → `PROV-MSELLO`
- pntsekhe (person_id=56) → `PROV-PNTSEKHE`

## Suggested fixes

### Short-term (radiologyapp)

1. **Guard the `.next()` call** with an emptiness check and return a meaningful error
   or model attribute when the user has no provider record:

   ```java
   if (providers.isEmpty()) {
       model.addAttribute("currentProvider", null);
       // or: throw a user-visible exception with a message
   } else {
       model.addAttribute("currentProvider", providers.iterator().next());
   }
   ```

2. **Address the TODO** — if there are multiple provider records, pick the preferred one
   or surface a selection UI rather than arbitrarily taking the first.

### Medium-term (radiology UI)

3. **Hide or disable the "Order X-ray" button** when the logged-in user has no provider
   record, with tooltip text: "Your account is not configured as a provider — contact
   your administrator."

### Long-term (admin UX / pih-config)

4. **Create a provider record automatically** when a user is created with a clinical role
   (e.g., `Application Role: physician`, `Application Role: labTech`), or at minimum
   show a warning in the admin UI when saving a user who will need provider access.

## Environment

- Distribution: PIH Lesotho (`partnersinhealth/lesotho-emr`, pih.config=lesotho,lesotho-botsabelo-demo)
- `radiologyapp` version: in distro
- OpenMRS core: 2.8.7
- Context: imladris radiology stack; first radiology order attempt by a new clinical user

## Cross-references

- [pihapps-new-user-login-redirect-loop.md](pihapps-new-user-login-redirect-loop.md) — login loop when user has no roles
- [emrapi-metadata-term-mappings-null-in-demo-config.md](emrapi-metadata-term-mappings-null-in-demo-config.md) — NULL metadata mappings blocking visit/order creation
- [emrapi-atFacilityVisitType-missing-in-demo-config.md](emrapi-atFacilityVisitType-missing-in-demo-config.md) — earlier related failure

**Pattern:** All four failures affect new clinical users in a fresh demo stack. None surface
a user-visible diagnostic message. Together they represent a systemic gap in new-user
onboarding for PIH distributions using the radiologyapp workflow.
