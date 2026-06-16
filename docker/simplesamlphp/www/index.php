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

require '/var/www/simplesamlphp/vendor/autoload.php';

$as = new \SimpleSAML\Auth\Simple('default-sp');
$as->requireAuth();

// Authenticated — hand off to the static landing page.
// landing.html is mounted from docker/landing/index.html.
header('Content-Type: text/html; charset=utf-8');
header('Cache-Control: no-store, no-cache, must-revalidate');
readfile('/var/www/html/landing.html');
