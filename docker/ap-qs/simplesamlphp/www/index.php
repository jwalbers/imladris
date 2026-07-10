<?php
/**
 * IMLADRIS Lab Portal — auth-gated landing page.
 *
 * Requires a valid SimpleSAMLphp SAML session (PIH Entra ID).
 * If the user is not authenticated, requireAuth() redirects them to
 * the Entra login page; after successful login Entra POSTs the assertion
 * to the ACS URL and SimpleSAMLphp redirects back here.
 *
 * On the way back in, we simply serve landing.html — the page's own JS
 * calls /user-info.php to populate the auth bar with the user's name.
 */
declare(strict_types=1);

// SSP strips port from HTTP_HOST then re-appends SERVER_PORT when it's non-standard.
// Apache reports SERVER_PORT=80 (its internal listen port) even though the external
// port is 443, so SSP builds https://imladrislab.org:80/ without this fix.
if (($_SERVER['HTTP_X_FORWARDED_PROTO'] ?? '') === 'https') {
    $_SERVER['SERVER_PORT'] = '443';
}

require '/var/simplesamlphp/vendor/autoload.php';

$as = new \SimpleSAML\Auth\Simple('default-sp');
$as->requireAuth();

// Authenticated — hand off to the static landing page.
// Mounted from docker/landing/ as a directory to avoid VirtioFS inode-swap issues.
header('Content-Type: text/html; charset=utf-8');
header('Cache-Control: no-store, no-cache, must-revalidate');
readfile('/var/www/html/landing.html');
