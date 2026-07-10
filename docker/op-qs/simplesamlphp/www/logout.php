<?php
declare(strict_types=1);

require_once('/var/simplesamlphp/src/_autoload.php');

$as = new \SimpleSAML\Auth\Simple('default-sp');
$as->logout('https://imladrislab.org/');
