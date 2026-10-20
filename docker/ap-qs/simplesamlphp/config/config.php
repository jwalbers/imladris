<?php
/**
 * SimpleSAMLphp configuration — IMLADRIS SP
 *
 * Edit .env to set:
 *   SAML_SP_SECRETSALT   openssl rand -base64 32
 *   SAML_ADMIN_PASSWORD  (any strong password for the /simplesaml/admin UI)
 */

// Serve whichever lab domain the request came in on (HAProxy keeps the Host
// header); anything else falls back to .org.  Both domains' ACS URLs must be
// registered as Reply URLs on the Entra enterprise app.
$labHosts = ['imladrislab.org', 'imladrislab.net'];
$labHost  = strtolower(explode(':', $_SERVER['HTTP_HOST'] ?? '')[0]);
if (!in_array($labHost, $labHosts, true)) {
    $labHost = 'imladrislab.org';
}

$config = [

    // ── Core ──────────────────────────────────────────────────────────────
    'baseurlpath'        => 'https://' . $labHost . '/simplesaml/',
    // Redirect targets after sign-in: the lab domains and their subdomains
    // (qure.imladrislab.org for Guacamole, ...). Patterns are anchored by SSP.
    'trusted.url.regex'   => true,
    'trusted.url.domains' => ['([a-z0-9-]+\\.)?imladrislab\\.(org|net)'],

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
    // Valid on every lab subdomain, so other lab sites (Guacamole via nginx
    // auth_request -> /auth-check.php) can see the same sign-in.
    'session.cookie.domain'   => '.' . $labHost,
    // Renamed when the domain changed (2026-10-19): older host-only cookies
    // under the default names are ignored instead of shadowing the shared ones.
    'session.phpsession.cookiename' => 'IMLADRIS_SSP_SESSION',
    'session.authtoken.cookiename'  => 'IMLADRIS_SSP_AUTHTOKEN',
    'store.type'              => 'phpsession',

    // ── Metadata ──────────────────────────────────────────────────────────
    'metadata.sources' => [
        ['type' => 'flatfile'],  // reads /var/simplesamlphp/metadata/
    ],

    // ── SP-only — no built-in IdP needed ──────────────────────────────────
    'enable.saml20-idp' => false,

];
