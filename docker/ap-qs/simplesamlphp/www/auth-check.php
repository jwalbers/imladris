<?php
/**
 * SSO check for other lab sites (nginx auth_request), e.g. Guacamole at
 * qure.imladrislab.org.
 *
 * 200 + "X-Auth-User: <email>" when the browser has a valid SAML session,
 * 401 otherwise. Works across subdomains because the SSP session cookie is set
 * for .imladrislab.org / .imladrislab.net (config.php).
 *
 * Also reachable as https://imladrislab.org/auth-check.php; it only ever tells a
 * browser its own sign-in state.
 */
declare(strict_types=1);

require '/var/simplesamlphp/vendor/autoload.php';

header('Cache-Control: no-store');

$as = new \SimpleSAML\Auth\Simple('default-sp');
if (!$as->isAuthenticated()) {
    http_response_code(401);
    exit;
}

$attrs = $as->getAttributes();
$email = $attrs['emailaddress'][0] ?? '';
if ($email === '') {
    $email = $as->getAuthData('saml:sp:NameID')?->getValue() ?? '';
}
if ($email === '') {
    http_response_code(401);   // no usable identity: treat as not signed in
    exit;
}

header('X-Auth-User: ' . strtolower($email));
http_response_code(200);
