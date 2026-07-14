// OHIF Viewer — Imladris configuration
// Currently: Orthanc PACS via nginx DICOMweb proxy (orthanc-p.imladrislab.org)
//
// To switch to AdvaPACS cloud, replace the dataSources block with:
//
//   {
//     namespace: '@ohif/extension-default.dataSourcesModule.dicomweb',
//     sourceName: 'dicomweb',
//     configuration: {
//       friendlyName: 'AdvaPACS Cloud',
//       name: 'ADVAPACS',
//       wadoUriRoot:    'https://advapacs-p.imladrislab.org',
//       qidoRoot:       'https://advapacs-p.imladrislab.org',
//       wadoRoot:       'https://advapacs-p.imladrislab.org',
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
        friendlyName: 'Imladris Orthanc PACS',
        name: 'IML_PACS_01',
        wadoUriRoot:    'https://orthanc-p.imladrislab.org/wado',
        qidoRoot:       'https://orthanc-p.imladrislab.org/dicom-web',
        wadoRoot:       'https://orthanc-p.imladrislab.org/dicom-web',
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
