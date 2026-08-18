// ============================================================================
// Imladris Virtual Integration Lab — SysML v2 System Model
//
// A complete model of the Imladris radiology integration lab hosted on BESSIE
// (192.168.1.10) and exposed via imladrislab.org (pfSense / HAProxy frontend).
//
// Imports: HealthcareInterfaces (healthcare-interfaces.sysml)
//
// Standard:  SysML v2 (ISO/IEC 19514:2024)
// See also:  docs/advapacs-config/advapacs-config.md
//
// Revision history:
//   2026-07  Initial model — core order/acquisition/routing/viewing workflows
//   2026-08  Add ToolCabinet (DICOM upload), AdvaPACSProxy (auth injector),
//            OHIFRemote (port 3001), ExternalDicomViewer (OsiriX/Horus)
// ============================================================================

package ImladrisLab {

    private import ScalarValues::*;   // String, Integer
    private import HealthcareInterfaces::DicomItems::*;
    private import HealthcareInterfaces::DicomPorts::*;
    private import HealthcareInterfaces::DicomWebPorts::*;
    private import HealthcareInterfaces::DicomConnections::*;
    private import HealthcareInterfaces::HL7v2Items::*;
    private import HealthcareInterfaces::HL7v2Ports::*;
    private import HealthcareInterfaces::HL7v2Connections::*;
    private import HealthcareInterfaces::FHIRItems::*;
    private import HealthcareInterfaces::FHIRPorts::*;
    private import HealthcareInterfaces::FHIRConnections::*;


    // =========================================================================
    // Lab Items
    // =========================================================================

    item def WorklistFile {
        // .wl file dropped into Orthanc worklist directory
        attribute accessionNumber   : String;
        attribute patientID         : String;
        attribute aeTitle           : String;   // IML_CR_01 or IML_US_01
        attribute modality          : String;
        attribute scheduledDateTime : String;
    }

    item def RadiologyReport {
        attribute accessionNumber  : String;
        attribute studyInstanceUID : String;
        attribute reportText       : String;
        attribute status           : String;   // preliminary | final
    }


    // =========================================================================
    // Part Definitions — individual lab components
    // =========================================================================

    // ─── OpenMRS EMR (lesotho-emr stack, port 8080) ───────────────────────────

    part def OpenMRS {
        // FHIR R4 REST API (port 8080/openmrs/ws/fhir2/R4)
        port fhirApi : FhirRestServer;

        // HL7 v2 MLLP — ADT (patient events) and ORM (radiology orders)
        port adtOut  : AdtSender;
        port ormOut  : OrmSender;

        // Report receipt — ORU inbound from reporting systems
        port oruIn   : OruReceiver;
    }

    // ─── Worklist Bridge (Python service, port 5000) ──────────────────────────
    // Polls OpenMRS FHIR ServiceRequest resources and converts accepted orders
    // to Orthanc worklist .wl files. Replaces HL7 ORM → MWL pipeline.

    part def WorklistBridge {
        // Polls FHIR orders from OpenMRS
        port fhirOrdersIn : FhirOrderClient;

        // Writes worklist files to shared volume (not a typed port — filesystem I/O)
        // Files land in /orthanc/worklists/ which Orthanc modality hot-folder monitors

        // Optionally polls HL7 ORM for fallback / dual-feed
        port ormIn : OrmReceiver;
    }

    // ─── Orthanc Modality (IML_CR_01 / IML_US_01, container port 4242) ───────
    // Simulates the X-ray / ultrasound acquisition station.
    // Serves MWL to the modality console; receives acquired studies via C-STORE.

    part def OrthancModality {
        attribute aeTitle   : String  = "IML_CR_01";
        attribute host      : String  = "192.168.1.10";
        attribute dicomPort : Integer = 4242;

        // Serves Modality Worklist to technologist consoles
        port mwlScp         : DicomMWLSCP;

        // Receives C-STORE from the technologist console
        port cstoreScp      : DicomCStoreSCP;

        // C-ECHO responder (DICOM verification)
        port cechoScp       : DicomCEchoSCP;

        // Forwards acquired studies to Orthanc PACS via C-STORE
        port cstoreScu      : DicomCStoreSCU;

        // DICOMweb server (Orthanc built-in; /wado, /dicom-web)
        port dicomWebServer : DicomWebServer;
    }

    // ─── Technologist Modality Console (browser app, port 3001) ──────────────
    // Simulated RIS/modality console. Tech logs in, retrieves worklist, selects
    // patient, acquires study, and pushes DICOM to Orthanc Modality.

    part def ModalityConsole {
        // Fetches worklist from Orthanc Modality
        port mwlScu   : DicomMWLSCU;

        // Sends acquired DICOM studies
        port cstoreScu : DicomCStoreSCU;

        // Optional MPPS notification after procedure completes
        port mppsScu   : MppsSCU;
    }

    // ─── Orthanc PACS (IML_PACS_01, container port 4243 → host) ─────────────
    // Central local archive. Receives studies from modality, serves OHIF,
    // forwards to AdvaPACS gateway, and can route to QureAI simulator.

    part def OrthancPACS {
        attribute aeTitle   : String  = "IML_PACS_01";
        attribute host      : String  = "192.168.1.10";
        attribute dicomPort : Integer = 4243;

        // Receives studies from orthanc-modality or direct C-STORE from console
        port cstoreScp       : DicomCStoreSCP;

        // C-ECHO responder
        port cechoScp        : DicomCEchoSCP;

        // C-FIND / C-MOVE Query/Retrieve (standard PACS retrieval)
        port cfindScp        : DicomCFindSCP;
        port cmoveScp        : DicomCMoveSCP;

        // DICOMweb server (Orthanc built-in, proxied via PacsProxy on port 8044)
        port dicomWebServer  : DicomWebServer;

        // STOW-RS client — pushes to AdvaPACS gateway DICOMweb proxy (port 8085)
        port stowRsToGateway : StowRsClient;

        // C-STORE to AdvaPACS gateway DICOM port (11112) — alternative push path
        port cstoreToGateway : DicomCStoreSCU;

        // C-STORE to QureAI Simulator (port 5252)
        port cstoreToQure    : DicomCStoreSCU;
    }

    // ─── PACS Proxy — nginx CORS proxy (port 8044) ───────────────────────────
    // Strips CORS restriction from Orthanc PACS DICOMweb endpoint so that OHIF
    // (served from a different origin) can call it directly in the browser.

    part def PacsProxy {
        // Forwards DICOMweb requests to Orthanc PACS
        port dicomWebClient : DicomWebClient;

        // Exposes proxied DICOMweb to OHIF (and any CORS-restricted browser client)
        port dicomWebServer : DicomWebServer;
    }

    // ─── OHIF Viewer (port 3000, ohif.imladrislab.org) ───────────────────────
    // Zero-footprint DICOM viewer. Queries and retrieves studies from Orthanc PACS
    // via the PacsProxy DICOMweb endpoint.

    part def OHIFViewer {
        port dicomWebClient : DicomWebClient;
    }

    // ─── AdvaPACS Gateway (ADVAPACS_GW_01, port 11112) ───────────────────────
    // AdvaPACS on-premises gateway container. Presents a DICOM C-STORE SCP on
    // the local network and a DICOMweb proxy (port 8085). Forwards to cloud.
    // Runs with network_mode: host on BESSIE.

    part def AdvaPACSGateway {
        attribute aeTitle           : String  = "ADVAPACS_GW_01";
        attribute host              : String  = "192.168.1.10";
        attribute dicomPort         : Integer = 11112;
        attribute dicomWebProxyPort : Integer = 8085;

        // Receives C-STORE from local Orthanc instances
        port cstoreScp      : DicomCStoreSCP;

        // C-ECHO responder
        port cechoScp       : DicomCEchoSCP;

        // DICOMweb STOW-RS proxy endpoint (local, port 8085)
        port stowRsServer   : StowRsServer;

        // Forwards to AdvaPACS cloud via STOW-RS (outbound)
        port stowRsToCloud  : StowRsClient;

        // DICOMweb proxy (full) toward cloud
        port dicomWebToCloud : DicomWebClient;
    }

    // ─── AdvaPACS Cloud (pih.advapacs.com) ───────────────────────────────────
    // AdvaHealth cloud PACS. Receives studies from gateway, serves AdvaView
    // web viewer, provides FHIR endpoint, and integrates RADPAIR AI reporting.

    part def AdvaPACSCloud {
        attribute endpoint : String = "https://pih.advapacs.com";

        // Receives forwarded studies from gateway via STOW-RS
        port stowRsServer   : StowRsServer;

        // Full DICOMweb endpoint (WADO-RS / QIDO-RS for AdvaView and API clients)
        port dicomWebServer : DicomWebServer;

        // FHIR R4 REST API (ImagingStudy, ServiceRequest, DiagnosticReport)
        port fhirApi        : FhirRestServer;

        // RADPAIR AI reporting engine port (embedded; receives study refs)
        port reportOut      : FhirReportServer;
    }

    // ─── QureAI Simulator (QUREAI, port 5252) ─────────────────────────────────
    // Simulates Qure.ai C-STORE SCP. Receives CXR studies from Orthanc PACS,
    // processes them, and returns AI-annotated DICOMweb results (or SR objects).

    part def QureSimulator {
        attribute aeTitle   : String  = "QUREAI";
        attribute host      : String  = "192.168.1.10";
        attribute dicomPort : Integer = 5252;

        // Receives chest X-ray studies from Orthanc PACS
        port cstoreScp      : DicomCStoreSCP;

        // C-ECHO responder
        port cechoScp       : DicomCEchoSCP;

        // Returns annotated results (C-STORE SCU to PACS / structured report)
        port cstoreScu      : DicomCStoreSCU;

        // DICOMweb result endpoint (if enabled)
        port dicomWebServer : DicomWebServer;
    }

    // ─── Tool Cabinet (FastAPI, port 8080) ───────────────────────────────────
    // Web-based lab utility. Provides a /dicom/upload endpoint that accepts .dcm
    // files or .zip archives containing .dcm files (nested dirs OK) and C-STOREs
    // them to the AdvaPACS gateway. Results streamed as NDJSON to the browser.
    // Calling AE: IML_TOOLS — must be in gateway Accepted Calling AE Titles list.
    // Only proposes the transfer syntax(es) actually present in each file;
    // does not offer uncompressed alternatives it cannot deliver.

    part def ToolCabinet {
        attribute aeTitle : String = "IML_TOOLS";

        // HTTP server — multipart/form-data upload, NDJSON progress stream
        port httpServer : FhirRestServer;   // placeholder: HTTP upload API (not FHIR)

        // DICOM C-STORE SCU — pushes uploaded instances to AdvaPACS gateway
        port cstoreScu  : DicomCStoreSCU;
    }

    // ─── AdvaPACS DICOMweb Proxy (nginx, advapacs-p.imladrislab.org) ─────────
    // nginx reverse proxy that injects AdvaPACS Basic Auth (Access Key ID +
    // Secret) into every outbound request to the AdvaPACS cloud DICOMweb
    // endpoint.  External viewers (OsiriX, Horus, Weasis) connect to this proxy
    // without managing credentials directly; access is gated by HAProxy IP
    // whitelist.  Also serves as the OHIF-remote backend config origin.

    part def AdvaPACSProxy {
        // DICOMweb endpoint exposed to viewers — no credentials required from client
        port dicomWebServer : DicomWebServer;

        // Outbound to AdvaPACS cloud — Authorization header injected by nginx
        port dicomWebClient : DicomWebClient;
    }

    // ─── External DICOM Viewer (OsiriX / Horus / Weasis) ─────────────────────
    // Third-party desktop or web viewer connecting to the lab via the
    // AdvaPACS DICOMweb proxy at advapacs-p.imladrislab.org.

    part def ExternalDicomViewer {
        attribute viewerName : String;   // OsiriX | Horus | Weasis | custom
        port dicomWebClient  : DicomWebClient;
    }

    // ─── pfSense / HAProxy Frontend ───────────────────────────────────────────
    // Physical network gateway (not on BESSIE). Terminates TLS for *.imladrislab.org,
    // enforces IP whitelist, and routes to backend services on BESSIE.

    part def PfSenseFrontend {
        attribute wanIp    : String = "68.116.51.146";
        attribute lanIp    : String = "192.168.1.1";
        attribute fqdnBase : String = "imladrislab.org";

        // TLS termination + reverse proxy — web apps
        port httpsProxy : FhirRestServer;  // placeholder; no typed port for HTTP proxy

        // SAML IdP via SimpleSAMLphp — protects imladrislab.org (landing + SP)
        // Subdomains rely on IP whitelist only (no SimpleSAMLphp on subdomains)
    }


    // =========================================================================
    // ImladrisLabSystem — top-level assembly with all connections
    // =========================================================================

    part def ImladrisLabSystem {

        // ── Part instances ─────────────────────────────────────────────────────

        part emr         : OpenMRS;
        part wlBridge    : WorklistBridge;
        part modality    : OrthancModality;
        part console     : ModalityConsole;
        part pacs        : OrthancPACS;
        part pacsProxy   : PacsProxy;
        part ohif        : OHIFViewer;        // local OHIF (Orthanc, port 3000)
        part ohifRemote  : OHIFViewer;        // remote OHIF (AdvaPACS, port 3001)
        part advagw      : AdvaPACSGateway;
        part advacloud   : AdvaPACSCloud;
        part quresim     : QureSimulator;
        part toolCabinet : ToolCabinet;
        part advaProxy   : AdvaPACSProxy;
        part extViewer   : ExternalDicomViewer;

        // ── Workflow 1: Order → Worklist ───────────────────────────────────────

        // WorklistBridge polls FHIR ServiceRequest from OpenMRS
        connection : FhirOrderLink connect wlBridge.fhirOrdersIn to emr.fhirApi;

        // Technologist console pulls MWL from Orthanc Modality
        connection : DicomMWLLink connect console.mwlScu to modality.mwlScp;

        // ── Workflow 2: Acquisition → Local PACS ──────────────────────────────

        // Console sends acquired study to Orthanc Modality (step 1 of two-hop)
        connection : DicomCStoreLink connect console.cstoreScu to modality.cstoreScp;

        // Orthanc Modality auto-routes received study to Orthanc PACS
        connection : DicomCStoreLink connect modality.cstoreScu to pacs.cstoreScp;

        // ── Workflow 3: OHIF Viewer ────────────────────────────────────────────

        // PacsProxy provides CORS-safe DICOMweb to OHIF
        connection : DicomWebLink connect pacsProxy.dicomWebClient to pacs.dicomWebServer;
        connection : DicomWebLink connect ohif.dicomWebClient to pacsProxy.dicomWebServer;

        // ── Workflow 4: Forward to AdvaPACS Cloud (STOW-RS path) ──────────────

        // Orthanc PACS pushes via STOW-RS to gateway DICOMweb proxy (port 8085)
        connection : StowRsLink connect pacs.stowRsToGateway to advagw.stowRsServer;

        // Gateway forwards to AdvaPACS cloud via STOW-RS
        connection : StowRsLink connect advagw.stowRsToCloud to advacloud.stowRsServer;

        // ── Workflow 5: Forward to AdvaPACS Cloud (C-STORE path — alternate) ──

        // Orthanc PACS pushes via traditional C-STORE to gateway DICOM port 11112
        connection : DicomCStoreLink connect pacs.cstoreToGateway to advagw.cstoreScp;

        // ── Workflow 6: AdvaPACS Cloud DICOMweb ───────────────────────────────

        // Gateway proxies DICOMweb from cloud (WADO-RS / QIDO-RS for AdvaView)
        connection : DicomWebLink connect advagw.dicomWebToCloud to advacloud.dicomWebServer;

        // ── Workflow 7: QureAI Routing ─────────────────────────────────────────

        // Orthanc PACS routes CXR studies to QureAI simulator (C-STORE)
        connection : DicomCStoreLink connect pacs.cstoreToQure to quresim.cstoreScp;

        // QureAI returns annotated SR / secondary capture back to PACS
        connection : DicomCStoreLink connect quresim.cstoreScu to pacs.cstoreScp;

        // ── Workflow 8: HL7 v2 Order Feed (supplemental / fallback) ───────────

        // OpenMRS sends HL7 ORM to WorklistBridge MLLP listener
        connection : HL7v2OrmLink connect emr.ormOut to wlBridge.ormIn;

        // ── Workflow 9: Tool Cabinet DICOM Upload ──────────────────────────────
        // Radiologist/engineer uploads .dcm or .zip via browser → Tool Cabinet
        // FastAPI → C-STORE (IML_TOOLS) to AdvaPACS gateway → cloud.
        // Calling AE IML_TOOLS must be in gateway Accepted Calling AE Titles.
        // Only the file's actual transfer syntax is proposed in A-ASSOCIATE-RQ.
        connection : DicomCStoreLink connect toolCabinet.cstoreScu to advagw.cstoreScp;

        // ── Workflow 10: Remote OHIF Viewer (AdvaPACS path) ───────────────────
        // Remote browser → ohif.imladrislab.org → ohif-remote (port 3001,
        // ap-qs config) → advapacs-p.imladrislab.org (AdvaPACSProxy injects auth)
        // → AdvaPACS cloud DICOMweb.
        // Separate from local ohif (port 3000) which hits Orthanc via PacsProxy.
        connection : DicomWebLink connect ohifRemote.dicomWebClient to advaProxy.dicomWebServer;
        connection : DicomWebLink connect advaProxy.dicomWebClient to advacloud.dicomWebServer;

        // ── Workflow 11: External Viewer (OsiriX / Horus / Weasis) ────────────
        // External desktop viewer connects to advapacs-p.imladrislab.org;
        // proxy injects AdvaPACS API key pair as Basic Auth toward cloud.
        // HAProxy IP whitelist gates access — no per-viewer credential management.
        connection : DicomWebLink connect extViewer.dicomWebClient to advaProxy.dicomWebServer;
    }


    // =========================================================================
    // Deployment Context (non-functional view)
    // =========================================================================

    // Physical host mapping (informative — not enforced by SysML runtime)
    //
    //  BESSIE (192.168.1.10) — Windows 11 Pro, Docker Desktop
    //  ┌─────────────────────────────────────────────────────────────────┐
    //  │  lesotho-emr (docker compose)                                   │
    //  │    openmrs           8080:8080                                  │
    //  │    mysql-openmrs                                                │
    //  │    worklist-bridge   5000:5000                                  │
    //  │                                                                 │
    //  │  ap-qs (docker compose) — AdvaPACS production config           │
    //  │    orthanc-modality  4242:4242 (DICOM) · 8042:8042 (HTTP)      │
    //  │    orthanc-pacs      4243:4242 (DICOM) · 8043:8042 (HTTP)      │
    //  │    pacs-proxy        8044:80  (nginx CORS proxy → Orthanc)     │
    //  │    ohif              3000:80  (Orthanc config — local only)     │
    //  │    modality-console  3001:80  (tech console)                   │
    //  │    landing           8090:80                                    │
    //  │    simplesamlphp     443 (TLS via HAProxy)                      │
    //  │    advapacs-gateway  11112:11112 · 8085:8085 (host networking)  │
    //  │    advapacs-proxy    8086:80  (nginx auth injector →            │
    //  │                     advapacs-p.imladrislab.org)                 │
    //  │    tool-cabinet      8087:8080  (FastAPI upload / IML_TOOLS)   │
    //  │    qure-sim          5252:5252                                  │
    //  │                                                                 │
    //  │  op-qs-local (docker compose) — optional Orthanc overlay       │
    //  │    ohif-remote       3001:80  (AdvaPACS config, port 3001;     │
    //  │                      HAProxy ohif.imladrislab.org → :3001)     │
    //  └─────────────────────────────────────────────────────────────────┘
    //
    //  pfSense (192.168.1.1 / 68.116.51.146)
    //    HAProxy — TLS termination for *.imladrislab.org
    //      ohif.imladrislab.org      → BESSIE:3001 (ohif-remote, AdvaPACS config)
    //      advapacs-p.imladrislab.org → BESSIE:8086 (advapacs-proxy)
    //    IP whitelist — only whitelisted WAN CIDRs (advapacs-p frontend)
    //    SimpleSAMLphp Entra SAML — protects imladrislab.org (landing)
    //    Split DNS Host Override — imladrislab.org → 192.168.1.10 (hairpin fix)
    //
    //  AdvaPACS Cloud (pih.advapacs.com / advapacs-p.imladrislab.org)
    //    AdvaView (FlexView) — zero-footprint DICOM viewer
    //    RADPAIR — AI radiology report drafting side panel
    //    DICOMweb STOW-RS / WADO-RS / QIDO-RS
    //    FHIR R4 REST API
    //    Auth: Access Key ID + Secret (Basic Auth header; injected by advapacs-proxy)
    //
    //  External Viewers (via advapacs-p.imladrislab.org)
    //    OsiriX / Horus (macOS) — DICOMweb client → AdvaPACS proxy → cloud
    //    Weasis (desktop) — same path
    //
    //  Qure.ai (cloud AI inference) — not yet integrated; QureSim used instead
    //
    //  Wisconsin site (future / in progress)
    //    Static WAN IP: 98.100.201.218  BESSIE: 192.168.3.3
    //    HAProxy to be added to existing pfSense (not replaced)

}  // end package ImladrisLab
