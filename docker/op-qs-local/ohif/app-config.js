// OHIF Viewer — Imladris local configuration
// Uses direct localhost:8044 (pacs-proxy) — no HAProxy, no external NIC hairpin.
// Use this config when running on BESSIE directly to avoid Realtek NIC lockups
// under heavy DICOM frame load.
//
// Start with:
//   docker compose -f docker/op-qs/docker-compose.yml \
//                  -f docker/op-qs-local/docker-compose.yml up -d
//
// After editing, regenerate the compressed copy: gzip -k -f app-config.js

window.config = {
  routerBasename: '/',
  showStudyList: true,
  extensions: [],
  modes: [],

  dataSources: [
    {
      namespace: '@ohif/extension-default.dataSourcesModule.dicomweb',
      sourceName: 'dicomweb',
      configuration: {
        friendlyName: 'Imladris Orthanc PACS (local)',
        name: 'IML_PACS_01',
        wadoUriRoot:    'http://localhost:8044/wado',
        qidoRoot:       'http://localhost:8044/dicom-web',
        wadoRoot:       'http://localhost:8044/dicom-web',
        qidoSupportsIncludeField: true,
        supportsReject: false,
        imageRendering: 'wadors',
        thumbnailRendering: 'wadors',
        enableStudyLazyLoad: true,
        supportsFuzzyMatching: false,
        supportsWildcard: true,
      },
    },
  ],

  defaultDataSourceName: 'dicomweb',
};
