<?php
/**
 * SimpleSAMLphp configuration — IMLADRIS SP
 *
 * Edit .env to set:
 *   SAML_SP_SECRETSALT   openssl rand -base64 32
 *   SAML_ADMIN_PASSWORD  (any strong password for the /simplesaml/admin UI)
 */

$config = [

    // ── Core ──────────────────────────────────────────────────────────────
    'baseurlpath'        => 'https://imladrislab.org/simplesaml/',

    // Required in SSP 2.x — Symfony compiled container cache.
    // /tmp is always writable; cache is rebuilt on container restart (fine for lab).
    'cachedir'           => '/tmp/simplesamlphp/cache',
    'loggingdir'         => '/tmp/simplesamlphp/log',
    'datadir'            => '/tmp/simplesamlphp/data',
    'secretsalt'         => getenv('SAML_SP_SECRETSALT') ?: 'CHANGE_ME_run_openssl_rand_base64_32',
    'auth.adminpassword' => getenv('SAML_ADMIN_PASSWORD') ?: 'CHANGE_ME',

    'admin.protectindexpage' => true,
    'admin.protectmetadata'  => false,  // SP metadata must be publicly readable

    // ── Contact ───────────────────────────────────────────────────────────
    'technicalcontact_name'  => 'Jim Albers',
    'technicalcontact_email' => 'albers.jim@gmail.com',

    // ── Locale / timezone ─────────────────────────────────────────────────
    'language.default' => 'en',
    'timezone'         => 'America/Los_Angeles',

    // ── Logging ───────────────────────────────────────────────────────────
    'logging.level'   => \SimpleSAML\Logger::NOTICE,
    'logging.handler' => 'errorlog',

    // ── Session / cookies ─────────────────────────────────────────────────
    //
    // SameSite=None is REQUIRED for SAML to work.
    // Entra POSTs the assertion cross-site (from login.microsoftonline.com
    // to our ACS URL on imladrislab.org).  The browser must send our session
    // cookie with that POST — which it won't do unless SameSite=None; Secure.
    //
    'session.cookie.secure'   => true,
    'session.cookie.samesite' => 'None',
    'session.cookie.httponly' => true,
    'store.type'              => 'phpsession',

    // ── Metadata ──────────────────────────────────────────────────────────
    'metadata.sources' => [
        ['type' => 'flatfile'],  // reads /var/simplesamlphp/metadata/
    ],

    // ── SP-only — no built-in IdP needed ──────────────────────────────────
    'enable.saml20-idp' => false,

];
