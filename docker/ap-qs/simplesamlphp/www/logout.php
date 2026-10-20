<?php
declare(strict_types=1);

require_once('/var/simplesamlphp/src/_autoload.php');

$as = new \SimpleSAML\Auth\Simple('default-sp');
$labHost = strtolower(explode(':', $_SERVER['HTTP_HOST'] ?? '')[0]);
if (!in_array($labHost, ['imladrislab.org', 'imladrislab.net'], true)) {
    $labHost = 'imladrislab.org';
}
$as->logout('https://' . $labHost . '/');
