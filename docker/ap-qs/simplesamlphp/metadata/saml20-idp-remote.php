<?php
/**
 * PIH Microsoft Entra ID — remote IdP metadata for IMLADRIS SP.
 *
 * Source: App Federation Metadata URL from PIH IT (retrieved 2026-06-16):
 *   https://login.microsoftonline.com/5254789f-6860-4375-85bc-302509fad508/
 *   federationmetadata/2007-06/federationmetadata.xml?appid=6f1a7974-8579-4f06-bf44-efce1aec9d39
 *
 * Cert rotation: Entra auto-rolls signing certs roughly every 3 years.
 * When PIH IT notifies of cert rotation, update 'certData' below and
 * restart the simplesamlphp container.
 * Cert valid until: 2029-06-16
 */

$metadata['https://sts.windows.net/5254789f-6860-4375-85bc-302509fad508/'] = [
    'entityid' => 'https://sts.windows.net/5254789f-6860-4375-85bc-302509fad508/',
    'name'     => ['en' => 'PIH Microsoft Entra ID'],

    'SingleSignOnService' => [[
        'Binding'  => 'urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST',
        'Location' => 'https://login.microsoftonline.com/5254789f-6860-4375-85bc-302509fad508/saml2',
    ]],

    'SingleLogoutService' => [[
        'Binding'  => 'urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect',
        'Location' => 'https://login.microsoftonline.com/5254789f-6860-4375-85bc-302509fad508/saml2',
    ]],

    // Entra signing certificate (from federation metadata).
    // SimpleSAMLphp uses this to validate the signature on incoming assertions.
    'certData' => 'MIIC8DCCAdigAwIBAgIQGwjzk8rmp7NHRu3rFjzqWDANBgkqhkiG9w0BAQsFADA0MTIwMAYDVQQDEylNaWNyb3NvZnQgQXp1cmUgRmVkZXJhdGVkIFNTTyBDZXJ0aWZpY2F0ZTAeFw0yNjA2MTYyMDU5MDFaFw0yOTA2MTYyMDU5MDFaMDQxMjAwBgNVBAMTKU1pY3Jvc29mdCBBenVyZSBGZWRlcmF0ZWQgU1NPIENlcnRpZmljYXRlMIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA5YgMVGJ0lwm1//I1HVKfrgV5W1IzKSRgBhiC+V/nMbbHelKXhmfUsplYnZzDJX8+a2VAMmmiTpQdA/vJSSOqy78n54ntinXBKhBJsjTUcFvRRqXou0RVLQR5H5yL8qDnnEG2qDGd8g4WMY+T2VmUwD0ZYnn8u6B9xOyfhLrKAJnmIrs5dL+Gf0slnsXY381y7+GV1dkS7YU3s2UTmSPZLwidGiDAqopYo7zAZr00UBHkeeQiFkelxNYD9Uu1WDXtzEydjpI7Z3CqhwwEAZ1ezlIi32ZFQV/oaplsZecjT0FSlJKHxv7BZErjfK61lxKgiptd5vxQQ9LVE2tJeYClYQIDAQABMA0GCSqGSIb3DQEBCwUAA4IBAQDkj/6RXMniJeTiXdUnym/QIbixAhT3NLCNs1g9Qk4gf4TdUmH1e1Qq8ebIid5lZ09zLsBPQcbQoVdM6R/BTLgR/hfeN96omhED5DFh/1mYMUA8uMI48ToCCPzNYkJsbwb0dsZs+YZtWe/ol2CbqnxpCu9LjiSUHulHo28VtiOtWR/FP81Vh8G7Xl10QAgF2pcJXF52dJf0zF9SxlWPT0OOL+o/txuruJFTnuxyQX/RPa4RX2NQfiGjxIbhcB6S0dlXWvKOCGMi5248tkriv0TGI30j2+xp3snfF9lKv0yrj/8TRtAmOzHbRMGpoT7ifmStvVRNJOLRi6fsaA+HhQP/',
];
