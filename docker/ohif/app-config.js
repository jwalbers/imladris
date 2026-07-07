// OHIF Viewer — Imladris configuration
// Points at the Cloud PACS (orthanc-pacs) DICOMweb endpoint via pacs-proxy.
// Uses the external hostname so the browser can reach it from WAN or LAN.

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
        friendlyName: 'Imladris Cloud PACS',
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
