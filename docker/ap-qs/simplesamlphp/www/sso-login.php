<?php
/**
 * Sign in through Entra, then return to another lab site.
 *
 *   https://imladrislab.org/sso-login.php?return=https://qure.imladrislab.org/
 *
 * Used by nginx in front of lab sites (Guacamole) when auth-check.php says
 * "not signed in". The return URL must be https on an imladrislab.org/.net
 * host, so this can't be used as an open redirect.
 */
declare(strict_types=1);

if (($_SERVER['HTTP_X_FORWARDED_PROTO'] ?? '') === 'https') {
    $_SERVER['SERVER_PORT'] = '443';
}

require '/var/simplesamlphp/vendor/autoload.php';

$return = (string)($_GET['return'] ?? '');
$parts  = parse_url($return);
$host   = strtolower($parts['host'] ?? '');
$ok = ($parts['scheme'] ?? '') === 'https'
    && preg_match('/^([a-z0-9-]+\.)?imladrislab\.(org|net)$/', $host) === 1;
if (!$ok) {
    $return = '/';
}

$as = new \SimpleSAML\Auth\Simple('default-sp');
$as->requireAuth(['ReturnTo' => $return]);

header('Location: ' . $return, true, 302);
