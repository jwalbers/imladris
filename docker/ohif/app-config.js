// OHIF Viewer — Imladris configuration
// Points at the Cloud PACS (orthanc-pacs) DICOMweb endpoint.
// The browser fetches from localhost:8044, so this must be the host-accessible URL.

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
        name: 'CLOUD_PACS',
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
