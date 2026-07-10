<?php
/**
 * User info endpoint — returns JSON with the authenticated user's name/email.
 *
 * Called by landing.html's auth bar JS on every page load.
 *
 * Returns 200 { name, email } when a valid SAML session exists,
 *         401 {}              when not authenticated.
 *
 * The auth bar JS shows the bar only on 200 — gracefully silent when
 * running without auth (local dev via port 8090).
 */
declare(strict_types=1);

require '/var/simplesamlphp/vendor/autoload.php';

header('Content-Type: application/json');
header('Cache-Control: no-store');

$as = new \SimpleSAML\Auth\Simple('default-sp');

if (!$as->isAuthenticated()) {
    http_response_code(401);
    echo '{}';
    exit;
}

$attrs = $as->getAttributes();

$given   = $attrs['givenname'][0]    ?? '';
$surname = $attrs['surname'][0]      ?? '';
$name    = trim("$given $surname") ?: ($attrs['name'][0] ?? '');
$email   = $attrs['emailaddress'][0] ?? '';

echo json_encode(['name' => $name, 'email' => $email]);
