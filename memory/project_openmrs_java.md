---
name: OpenMRS Java version requirement
description: OpenMRS SDK on this machine must be run with Java 11, not the system default Java 21
type: project
---

OpenMRS (openmrs-distro-zl, server: imladris01) must be started with Java 11.

**Why:** macOS system default Java is 21 (temurin-21). Infinispan 13 (bundled with openmrs-core 2.8.x) calls `Subject.getSubject()` which throws `UnsupportedOperationException` on Java 18+ (security manager removed). This causes `sessionFactory` → `CacheImplementor` failure and prevents Spring context from starting.

**How to apply:** Always start the server with:
```bash
JAVA_HOME=/Library/Java/JavaVirtualMachines/temurin-11.jdk/Contents/Home \
  mvn openmrs-sdk:run -DserverId=imladris01
```
Java 11 is installed at `/Library/Java/JavaVirtualMachines/temurin-11.jdk`. Java 8 (Corretto, Zulu) is also available but Java 11 is the recommended target for openmrs-core 2.8.x.
