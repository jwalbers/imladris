# `emr.atFacilityVisitType` not seeded in lesotho-botsabelo-demo — visit creation silently fails

**Target module:** `openmrs-module-emrapi` / `pih-config` (lesotho-botsabelo-demo)  
**Related:** `openmrs-module-coreapps` (QuickVisitFragmentController)  
**Type:** Bug / Missing configuration  
**Priority:** High (blocks all visit creation for non-admin users)  
**Status:** Draft — consider filing at GitHub PIH/pih-config or PIH/openmrs-module-emrapi

---

## Summary

In the `lesotho-botsabelo-demo` PIH configuration, the `emr.atFacilityVisitType` global
property is not seeded. When any user attempts to start a visit via the Quick Visit button,
the UI appears to hang (spinner, no feedback) while Tomcat logs an unhandled exception.
No error is shown to the user; the request silently fails.

## Error (Tomcat log)

```
java.lang.IllegalStateException: Configuration required: emr.atFacilityVisitType
    at org.openmrs.module.emrapi.EmrApiProperties.getEmrApiMetadataByCode(EmrApiProperties.java:444)
    at org.openmrs.module.emrapi.EmrApiProperties.getAtFacilityVisitType(EmrApiProperties.java:186)
    at org.openmrs.module.emrapi.adt.AdtServiceImpl.buildVisit(AdtServiceImpl.java:435)
    at org.openmrs.module.emrapi.adt.AdtServiceImpl.ensureVisit(AdtServiceImpl.java:306)
    at org.openmrs.module.coreapps.fragment.controller.visit.QuickVisitFragmentController.create(QuickVisitFragmentController.java:67)
```

The exception propagates through `FragmentFactory.invokeFragmentAction` and is swallowed
by the uiframework fragment error handler, so the browser receives a generic fragment error
response that the Quick Visit UI does not surface to the user.

## Root cause

`EmrApiProperties.getAtFacilityVisitType()` calls `getEmrApiMetadataByCode("emr.atFacilityVisitType")`,
which reads the global property of that name and looks up the corresponding visit type.
If the property is absent (or null), it throws `IllegalStateException: Configuration required`.

The `lesotho-botsabelo-demo` seed does not include this property. The core `lesotho` config
appears to set it (the production Lesotho distro works), but the demo overlay does not
re-apply or inherit it, leaving the property unset after a fresh stack bring-up with only
the demo seed data.

## Available visit types in this distro

| UUID | Name |
|------|------|
| `f01c54cb-2225-471a-9cd5-d348552c337c` | Clinic or Hospital Visit |
| `90973824-1ae9-4e22-b2bb-9cbd56fb3238` | Home Visit |

## Workaround / fix applied

```sql
INSERT INTO global_property (property, property_value, description, uuid)
  VALUES ('emr.atFacilityVisitType', 'f01c54cb-2225-471a-9cd5-d348552c337c',
          'Visit type used for at-facility visits', UUID())
  ON DUPLICATE KEY UPDATE property_value = 'f01c54cb-2225-471a-9cd5-d348552c337c';
```

OpenMRS must be restarted (or the global property cache flushed) after the direct DB update,
since OpenMRS caches global properties and does not detect out-of-band DB changes.

## Proper fix

Add `emr.atFacilityVisitType` to the configuration seeded by `lesotho-botsabelo-demo`
(or whatever PIH config layer is responsible for the demo environment) so a fresh stack
bring-up includes it. The value should reference the UUID of the "Clinic or Hospital Visit"
visit type, which is already present in the demo seed.

Alternatively, `EmrApiProperties.getAtFacilityVisitType()` could fall back gracefully
(log a warning, return null, or let callers handle absence) rather than throwing an
`IllegalStateException` with no user-facing context. A caught exception with a meaningful
UI message ("Visit type not configured — contact administrator") would be far preferable
to a silent hung spinner.

## Environment

- Distribution: PIH Lesotho (`partnersinhealth/lesotho-emr`, pih.config=lesotho,lesotho-botsabelo-demo)
- `emrapi` version: 3.5.0-SNAPSHOT
- `coreapps` version: in distro
- OpenMRS core: 2.8.7
- Context: imladris radiology stack, first visit creation attempt by a newly created clinical user

## Notes on filing

- The missing property likely belongs in `PIH/pih-config` under the `lesotho` or
  `lesotho-botsabelo-demo` configuration directory
- The silent failure UX is a secondary issue for `openmrs-module-coreapps` or `openmrs-module-emrapi`
- Cross-reference with `pihapps-new-user-login-redirect-loop.md` (same session, same pattern:
  missing metadata/config causes silent failure with no user-visible diagnostic)
