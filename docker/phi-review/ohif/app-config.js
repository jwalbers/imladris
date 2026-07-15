// OHIF Viewer — imladris-phi PHI Review configuration
//
// Points to the local phi-orthanc instance via pacs-proxy on localhost:8057.
// No connection to AdvaPACS, cloud PACS, or any remote system.
//
// After editing: regenerate the compressed copy with:
//   gzip -k -f app-config.js
// or in PowerShell:
//   (Get-Content app-config.js -Raw -Encoding UTF8) | Set-Content app-config.js.gz  # use compress-archive instead:
//   Compress-Archive -Path app-config.js -DestinationPath app-config.js.gz -Force

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
        friendlyName: 'PHI Review PACS (local only)',
        name: 'PHI_REVIEW',
        wadoUriRoot:    'http://localhost:8057/wado',
        qidoRoot:       'http://localhost:8057/dicom-web',
        wadoRoot:       'http://localhost:8057/dicom-web',
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

  experimentalStudyBrowserSort: true,
  customizationService: {
    'studyBrowser.sortFunctions': [
      {
        label: 'Instance Number',
        sortFunction: (a, b) =>
          (parseInt(a.InstanceNumber, 10) || 0) -
          (parseInt(b.InstanceNumber, 10) || 0),
      },
    ],
  },
};

// ── PHI environment banner ────────────────────────────────────────────────────
// Injected into the OHIF viewer so the warning persists across all screens.
;(function phi_banner() {
  function insert() {
    if (!document.body) { setTimeout(insert, 50); return; }
    if (document.getElementById('phi-env-banner')) return;
    var d = document.createElement('div');
    d.id = 'phi-env-banner';
    d.style.cssText = [
      'position: fixed',
      'top: 0',
      'left: 0',
      'right: 0',
      'z-index: 99999',
      'background: #7B0000',
      'color: #FFDDDD',
      'font: bold 12px/32px monospace',
      'text-align: center',
      'letter-spacing: 0.08em',
      'border-bottom: 2px solid #FF4444',
      'pointer-events: none',
    ].join('; ');
    d.textContent = '⚠  PHI ENVIRONMENT — identifiable patient data — LOCAL ONLY — do not forward studies to any remote or cloud system  ⚠';
    document.body.insertBefore(d, document.body.firstChild);

    // Push OHIF content down so the banner does not overlap the toolbar
    var root = document.getElementById('root');
    if (root) root.style.paddingTop = '32px';
  }
  insert();
})();
