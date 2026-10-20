// OHIF Viewer — Imladris configuration
// Currently: AdvaPACS cloud via nginx CORS proxy (port 8087 → usa1.api.dicomweb.advapacs.com/rs)
// HAProxy frontend: advapacs-p.imladrislab.{org,net} → lab host :8087
// The domain follows the page's own host, so the same file serves either domain.
//
// To switch back to Orthanc PACS, replace the dataSources block with:
//
//   {
//     namespace: '@ohif/extension-default.dataSourcesModule.dicomweb',
//     sourceName: 'dicomweb',
//     configuration: {
//       friendlyName: 'Imladris Cloud PACS',
//       name: 'IML_PACS_01',
//       wadoUriRoot:    'https://orthanc-p.imladrislab.org/wado',
//       qidoRoot:       'https://orthanc-p.imladrislab.org/dicom-web',
//       wadoRoot:       'https://orthanc-p.imladrislab.org/dicom-web',
//       qidoSupportsIncludeField: true,
//       supportsReject: false,
//       imageRendering: 'wadors',
//       thumbnailRendering: 'wadors',
//       enableStudyLazyLoad: true,
//       supportsFuzzyMatching: false,
//       supportsWildcard: true,
//     },
//   },
//
// After editing, regenerate the compressed copy: gzip -k -f app-config.js

const LAB_DOMAIN =
  (window.location.hostname.match(/imladrislab\.(org|net)$/) || ['imladrislab.org'])[0];

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
        friendlyName: 'AdvaPACS Cloud',
        name: 'ADVAPACS',
        wadoUriRoot:    'https://advapacs-p.' + LAB_DOMAIN,
        qidoRoot:       'https://advapacs-p.' + LAB_DOMAIN,
        wadoRoot:       'https://advapacs-p.' + LAB_DOMAIN,
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
