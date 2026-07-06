# lesotho-emr compose.yaml: OMRS_EXTRA_PIH_CONFIG default includes literal quote characters, causing pihcore crash loop on fresh deployment

**Target:** `PIH/lesotho-emr` — `docker/compose.yaml`  
**Related:** `openmrs-module-pihcore` (`Config` class), `partnersinhealth/openmrs-docker` entrypoint  
**Type:** Bug / Deployment configuration  
**Priority:** High (blocks fresh deployment entirely; silent crash loop on every start)  
**Status:** Draft — file at https://github.com/PIH/lesotho-emr

---

## Summary

`docker/compose.yaml` sets the default value for `OMRS_EXTRA_PIH_CONFIG` with surrounding
double-quote characters:

```yaml
OMRS_EXTRA_PIH_CONFIG: ${PIH_CONFIG:-"lesotho,lesotho-botsabelo-demo"}
```

When `PIH_CONFIG` is not defined in the shell or a `.env` file (which is the default on a
fresh clone — only `default.env` is provided, not `.env`), Docker Compose uses the literal
default string `"lesotho,lesotho-botsabelo-demo"` including the quote characters. The
entrypoint script then writes this to `openmrs-runtime.properties` as:

```
pih.config="lesotho,lesotho-botsabelo-demo"
```

`pihcore`'s `Config` class fails to parse this value (it gets `"lesotho` as the first profile
name instead of `lesotho`), throwing `RuntimeException: Error parsing json configuration`.

Because `OMRS_EXTRA_PIH_CONFIG` is re-written from the env var on **every container start**,
manually editing `openmrs-runtime.properties` inside the container has no effect — the fix is
overwritten on the next restart.

## Cascade from pihcore failure

pihcore's startup failure triggers a destructive cleanup cascade that makes the situation
progressively worse:

1. pihcore fails to instantiate its `Config` bean → `ModuleException: Unable to start OpenMRS`
2. OpenMRS calls `ModuleFactory.stopModule()` on pihcore and all modules that depend on it
   (printer, htmlformentry, htmlformentryui, pihapps, radiologyapp, registrationapp,
   registrationcore, dispensing, legacyui, paperrecord, spa, uilibrary, reportingrest,
   reportingui, appointmentschedulingui — ~16 modules total)
3. `stopModule()` removes each module's extracted jars from `.openmrs-lib-cache/`
4. Spring context initialization fails; OpenMRS retries every ~70 seconds
5. On the next retry, printer and its siblings are missing from the cache, so
   `printerService` is never registered as a Spring bean
6. `conversionService` tries to `@Autowired(required=true)` `printerService` (via
   `StringToPrinterConverter`) → `NoSuchBeanDefinitionException`
7. Context fails again → step 3 repeats → self-reinforcing crash loop

After the first pihcore failure, the observable error in subsequent retries shifts away
from `Error parsing json configuration` to `NoSuchBeanDefinitionException: PrinterService`
(from `conversionService`), obscuring the original root cause.

## Why diagnosis is difficult

- The root error (`Error parsing json configuration`) only appears in the **first** startup
  attempt's log. Subsequent retries show only the `PrinterService`/`conversionService` cascade.
- The manual runtime.properties fix is silently overwritten on each container restart.
- The Docker image already sets `OMRS_EXTRA_pih_config=lesotho,lesotho-botsabelo-demo`
  (lowercase, no quotes) as a Dockerfile `ENV` default, but the entrypoint script only
  processes uppercase `OMRS_EXTRA_*` variables. The image's correct lowercase default is
  silently ignored while the compose.yaml's broken uppercase override wins.

## Workaround (immediate)

On any machine where a `.env` file has not been created from `default.env`:

```bash
cd docker/
cp default.env .env
```

This makes `PIH_CONFIG=lesotho,lesotho-botsabelo-demo` available to Docker Compose for
interpolation, so `${PIH_CONFIG:-"lesotho,lesotho-botsabelo-demo"}` resolves to the env var
value (without quotes) rather than the quoted literal default.

Then recreate the openmrs container to pick up the corrected env var:

```bash
docker compose up -d --force-recreate openmrs
```

## Proper fix

Remove the quotes from the YAML default value in `docker/compose.yaml`:

```yaml
# Before (broken):
OMRS_EXTRA_PIH_CONFIG: ${PIH_CONFIG:-"lesotho,lesotho-botsabelo-demo"}

# After (correct):
OMRS_EXTRA_PIH_CONFIG: ${PIH_CONFIG:-lesotho,lesotho-botsabelo-demo}
```

The quotes are not needed in YAML here — the value is already an unambiguous scalar. They
are interpreted as part of the string value, not as YAML string delimiters.

Consider also documenting in `README.md` that `.env` must be created from `default.env`
before first `docker compose up`, since without it the deploy silently uses the broken default.

## Environment

- Distribution: `PIH/lesotho-emr` (Docker), `pih.config=lesotho,lesotho-botsabelo-demo`
- `pihcore`: 2.2.0-SNAPSHOT
- OpenMRS core: 2.8.7
- MySQL: 5.6.51
- Reproduced on: Windows 11 / Docker Desktop (WSL2 backend), fresh clone without `.env`

## Cross-references

- `imladris/issues/emrapi-metadata-term-mappings-null-in-demo-config.md` — subsequent issue
  encountered after resolving this crash loop
- `imladris/issues/pihapps-new-user-login-redirect-loop.md` — same session, fresh bring-up
