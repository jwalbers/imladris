<?php
/**
 * SimpleSAMLphp authentication sources — IMLADRIS SP
 *
 * 'default-sp' is the SAML 2.0 Service Provider config for PIH Entra ID.
 *
 * SP Entity ID and ACS URL given to PIH IT:
 *   Entity ID : https://imladrislab.org/simplesaml/module.php/saml/sp/metadata.php/default-sp
 *   ACS URL   : https://imladrislab.org/simplesaml/module.php/saml/sp/saml2-acs.php/default-sp
 *
 * NOTE: PIH IT registered the SP Entity ID as 'https://imladrislab.org' (simplified).
 * entityID below is set to match — Entra's assertion Audience element must equal entityID
 * exactly or SimpleSAMLphp will reject the assertion with an audience mismatch error.
 *
 * ── Optional SP signing keypair ───────────────────────────────────────────
 * Not required for the lab but best practice.  To add it:
 *
 *   cd docker/simplesamlphp/cert
 *   openssl req -newkey rsa:3072 -new -x509 -days 3650 -nodes \
 *     -out saml.crt -keyout saml.pem \
 *     -subj "/CN=imladrislab.org"
 *
 * Then send saml.crt to PIH IT so they can upload it to the Entra app
 * registration under "SAML Certificates → Verification certificates".
 * Uncomment 'privatekey' and 'certificate' below.
 */

$config = [
    'default-sp' => [
        'saml:SP',

        // Must match what PIH IT configured in the Entra enterprise app.
        // They registered it as the simplified form (not the full metadata URL we gave them).
        'entityID' => 'https://imladrislab.org',

        // PIH Entra IdP (from federation metadata).
        'idp' => 'https://sts.windows.net/5254789f-6860-4375-85bc-302509fad508/',

        // PIH IT configured NameID as emailAddress format.
        'NameIDPolicy' => [
            'Format'      => 'urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress',
            'AllowCreate' => true,
        ],

        // Optional SP signing cert.  Uncomment after generating keypair (see above).
        // 'privatekey'  => 'saml.pem',
        // 'certificate' => 'saml.crt',

        // Attributes sent by PIH IT's Entra enterprise app.
        'attributes' => [
            'givenname',    // user.givenname
            'surname',      // user.surname
            'emailaddress', // user.mail
            'name',         // user.userprincipalname
        ],
        'attributes.required' => ['emailaddress'],
    ],
];
