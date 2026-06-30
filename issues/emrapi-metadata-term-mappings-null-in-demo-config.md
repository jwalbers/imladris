# emrapi metadata term mappings seeded with NULL UUIDs — silent failures on visit/encounter creation

**Target module:** `openmrs-module-emrapi` / `pih-config` (lesotho-botsabelo-demo)  
**Related:** `openmrs-module-metadatamapping`  
**Type:** Bug / Missing configuration  
**Priority:** High (blocks visit creation; other NULLs likely to surface as encounters are used)  
**Status:** Draft — consider filing at GitHub PIH/pih-config

---

## Summary

In a fresh `lesotho-botsabelo-demo` stack, 13 of 17 emrapi metadata term mappings have
`metadata_uuid = NULL` in the `metadatamapping_metadata_term_mapping` table. The mapping
*rows* are created (by the emrapi module's startup migration) but the UUIDs pointing to the
actual OpenMRS metadata objects are never populated. The result is silent, user-invisible
failures when clinical workflows hit any of these unmapped codes.

The first failure encountered was visit creation: `QuickVisitFragmentController` calls
`AdtServiceImpl.ensureVisit()` → `EmrApiProperties.getAtFacilityVisitType()` →
`MetadataMappingService.getMetadataItem(VisitType.class, "org.openmrs.module.emrapi",
"emr.atFacilityVisitType")` → returns null (UUID is NULL) → throws
`IllegalStateException: Configuration required: emr.atFacilityVisitType`.

## Current mapping state (lesotho-botsabelo-demo, fresh bring-up)

| Code | Class | UUID | Status |
|------|-------|------|--------|
| emr.atFacilityVisitType | VisitType | f01c54cb-... | **fixed (see workaround)** |
| emr.primaryIdentifierType | PatientIdentifierType | 17e79b97-... | ✓ populated |
| emr.extraPatientIdentifierTypes | MetadataSet | e4aab2eb-... | ✓ populated |
| emr.unknownProvider | Provider | f9badd80-... | ✓ populated |
| emr.admissionEncounterType | EncounterType | NULL | ⚠ unmapped |
| emr.admissionForm | Form | NULL | ⚠ unmapped |
| emr.checkInClerkEncounterRole | EncounterRole | NULL | ⚠ unmapped |
| emr.checkInEncounterType | EncounterType | NULL | ⚠ unmapped |
| emr.clinicianEncounterRole | EncounterRole | NULL | ⚠ unmapped |
| emr.consultEncounterType | EncounterType | NULL | ⚠ unmapped |
| emr.exitFromInpatientEncounterType | EncounterType | NULL | ⚠ unmapped |
| emr.exitFromInpatientForm | Form | NULL | ⚠ unmapped |
| emr.orderingProviderEncounterRole | EncounterRole | NULL | ⚠ unmapped |
| emr.transferWithinHospitalEncounterType | EncounterType | NULL | ⚠ unmapped |
| emr.transferWithinHospitalForm | Form | NULL | ⚠ unmapped |
| emr.unknownLocation | Location | NULL | ⚠ unmapped |
| emr.visitNoteEncounterType | EncounterType | NULL | ⚠ unmapped |

## Why the error message is misleading

The exception is `IllegalStateException: Configuration required: emr.atFacilityVisitType`.
This sounds like a missing global property — but:

1. There IS a `global_property` row named `emr.atFacilityVisitType` (we added one, and one
   may be seeded by the distro). Setting it has **no effect** because emrapi does not read it.
2. `EmrApiProperties.getAtFacilityVisitType()` calls `getEmrApiMetadataByCode(VisitType.class,
   "emr.atFacilityVisitType")`, which calls `MetadataMappingService.getMetadataItem()` — a
   concept-mapping service lookup, not a global property read.
3. The exception message embeds the mapping *code*, not the missing GP name — it just happens
   to look identical.

**This means the standard advice "set the global property" will not fix it.** Only updating
`metadatamapping_metadata_term_mapping.metadata_uuid` works.

## How this was diagnosed

Standard log search showed `IllegalStateException: Configuration required: emr.atFacilityVisitType`.
Setting the global property and restarting had no effect. To understand why, we:

1. Located `emrapi-api-3.5.0-SNAPSHOT.jar` in the container
2. Ran `javap -c EmrApiProperties.class` to inspect bytecode
3. Found that `getAtFacilityVisitType()` calls `getEmrApiMetadataByCode(VisitType.class, "emr.atFacilityVisitType")`
4. The 3-arg overload at line 442 calls `metadataMappingService.getMetadataItem(type, sourceName, code)` — confirmed via constant pool references in bytecode
5. Queried `metadatamapping_metadata_term_mapping` → found the row present but `metadata_uuid = NULL`

Total time lost to the misleading "Configuration required" message: ~1 hour.

## Workaround applied

```sql
UPDATE metadatamapping_metadata_term_mapping
SET metadata_uuid = 'f01c54cb-2225-471a-9cd5-d348552c337c',
    date_changed  = NOW()
WHERE metadata_source_id = (SELECT metadata_source_id FROM metadatamapping_metadata_source
                            WHERE name = 'org.openmrs.module.emrapi')
  AND code = 'emr.atFacilityVisitType';
```

Followed by an OpenMRS restart to flush the MetadataMappingService cache.

## Proper fix

The `lesotho-botsabelo-demo` (or `lesotho`) pih-config should include a Liquibase changeset
or initializer configuration that populates all emrapi metadata term mappings with the correct
UUIDs for this distribution's EncounterTypes, EncounterRoles, VisitTypes, Locations, etc.

Each NULL entry above represents a clinical workflow that will fail silently when first
exercised. The remaining unmapped codes should be identified and populated before going
further in testing:
- `emr.unknownLocation` — needed for patient registration fallback
- `emr.orderingProviderEncounterRole` — needed when placing orders
- `emr.consultEncounterType` / `emr.visitNoteEncounterType` — needed for note entry
- `emr.checkInEncounterType` / `emr.checkInClerkEncounterRole` — needed for check-in workflow
- Inpatient/transfer/admission codes (may not apply to this outpatient-only demo)

## Suggested emrapi improvement

When `getMetadataItem()` returns null for a mapping that exists but has `metadata_uuid = NULL`,
the error message should distinguish between:
- "Mapping code does not exist" (row absent)
- "Mapping code exists but UUID is not set" (row present, UUID null)

The second case strongly suggests a seeding/migration gap and should say so explicitly,
rather than the generic "Configuration required" which implies the GP is simply not set.

## Environment

- Distribution: PIH Lesotho (`partnersinhealth/lesotho-emr`, pih.config=lesotho,lesotho-botsabelo-demo)
- `emrapi`: 3.5.0-SNAPSHOT
- `metadatamapping`: version in distro
- OpenMRS core: 2.8.7
- Context: imladris radiology stack; first visit creation attempt in fresh demo bring-up

## Cross-references

- [emrapi-atFacilityVisitType-missing-in-demo-config.md](emrapi-atFacilityVisitType-missing-in-demo-config.md) — earlier (incorrect) diagnosis of the same failure
- [pihapps-new-user-login-redirect-loop.md](pihapps-new-user-login-redirect-loop.md) — same session, same pattern: missing metadata causes silent failure
