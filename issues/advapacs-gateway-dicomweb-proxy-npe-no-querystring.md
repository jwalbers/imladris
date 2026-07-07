# AdvaPACS Gateway: NullPointerException in DICOMweb proxy when request has no query string

**Target:** AdvaPACS Gateway — `advahealthsolutions/advapacs-gateway:latest`  
**Component:** `DicomWebController` (package `com.advahealthsolutions.advapacs.gateway.modules.dicomweb`)  
**Type:** Bug  
**Priority:** High — blocks DICOMweb STOW-RS integration  
**Status:** Active — workaround in place (C-STORE on port 11112)

---

## Summary

Every HTTP request to the gateway's DICOMweb proxy endpoint that carries no query string
results in an HTTP 500 Internal Server Error. The root cause is a missing null check before
calling `.isBlank()` on the return value of `HttpServletRequest.getQueryString()`, which
returns `null` per the Jakarta Servlet specification when the request URL contains no `?`.

STOW-RS POST requests from Orthanc carry no query parameters, so 100% of STOW-RS calls
via the DICOMweb proxy fail. QIDO-RS GET requests from Orthanc likewise carry no query
string and fail identically.

## Steps to reproduce

1. Run `advahealthsolutions/advapacs-gateway:latest` with valid credentials.
2. Send any HTTP request to the DICOMweb proxy (port 8085) with no query string:
   ```
   POST http://<gateway-host>:8085/rs/studies   (STOW-RS, no query params)
   GET  http://<gateway-host>:8085/rs/studies   (QIDO-RS, no query params)
   ```
3. Observe HTTP 500 response.

## Stack trace (from gateway container log)

```
java.lang.NullPointerException: Cannot invoke "String.isBlank()" because the return value
of "jakarta.servlet.http.HttpServletRequest.getQueryString()" is null
    at com.advahealthsolutions.advapacs.gateway.modules.dicomweb.DicomWebController.proxy(DicomWebController.java:73)
    at java.base/jdk.internal.reflect.DirectMethodHandleAccessor.invoke(Unknown Source)
    at java.base/java.lang.reflect.Method.invoke(Unknown Source)
    at org.springframework.web.method.support.InvocableHandlerMethod.doInvoke(...)
    ...
```

## Root cause

`DicomWebController.java:73` calls `request.getQueryString().isBlank()` unconditionally.
Per the Jakarta Servlet 6.x specification (§3.4), `getQueryString()` returns `null` — not
an empty string — when the request URL contains no query component. The fix is a null check:

```java
// Broken
if (request.getQueryString().isBlank()) { ... }

// Fixed
String qs = request.getQueryString();
if (qs == null || qs.isBlank()) { ... }
```

## Impact

- All STOW-RS uploads via the DICOMweb proxy (port 8085) fail with HTTP 500.
- QIDO-RS and WADO-RS requests with no query parameters fail identically.
- Only requests that happen to include at least one query parameter succeed.
- Standard DICOMweb clients (Orthanc, dcm4chee, etc.) do not add query parameters
  to STOW-RS POST requests, making the proxy unusable for store-and-forward workflows.

## Workaround

Use DICOM C-STORE to the gateway's DICOM SCP on port 11112 instead of DICOMweb STOW-RS.
The gateway queues and forwards studies to AdvaPACS cloud via this path without issue.

## Environment

- Gateway image: `advahealthsolutions/advapacs-gateway:latest` (July 2026)
- Caller: Orthanc DICOMweb plugin (orthancteam/orthanc:latest)
- Host OS: Windows 11 / Docker Desktop (WSL2 backend)
- Gateway runtime: Spring Boot / Apache Tomcat (Java 21)
