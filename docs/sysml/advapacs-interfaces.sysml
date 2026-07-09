// ============================================================================
// AdvaPACS Interface Library — SysML v2 Textual Notation
//
// Models the complete public interface surface of the AdvaPACS cloud PACS
// platform (AdvaHealth), based on docs.advapacs.com (accessed July 2026).
//
// Covers four interface families:
//   1. HL7 v2  — IHE Radiology profile transactions (RAD-1, RAD-4, RAD-13,
//                inbound reports) via MLLP or HTTPS REST
//   2. FHIR    — R4 and R5 REST API + outbound webhooks
//   3. DICOM   — Gateway C-STORE SCP and DICOMweb proxy (PS3.18)
//   4. Viewer  — DICOMweb or DICOM Q/R connections to diagnostic viewers
//
// Imports HealthcareInterfaces for reusable base port/item types.
//
// Standard:  SysML v2 (ISO/IEC 19514:2024)
// See also:  docs/advapacs-config/advapacs-config.md
// ============================================================================

package AdvaPACSInterfaces {

    private import ScalarValues::*;
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
    // AdvaPACS-Specific Items
    // =========================================================================

    package AdvaPACSItems {
        private import ScalarValues::*;
        private import HealthcareInterfaces::HL7v2Items::*;
        private import HealthcareInterfaces::FHIRItems::*;

        // ── HL7 Items ─────────────────────────────────────────────────────────

        // IHE RAD-1: Patient Registration
        // Trigger events: ADT^A01/A04/A05 (create), A08 (update), A11/A38 (delete)
        // HL7 versions: 2.3.1, 2.5.1
        // Required segments: MSH, EVN, PID, PV1
        item def AdvaPACS_RAD1_ADT :> AdtMessage {
            attribute triggerEvent : String;
            // A01/A04/A05 → create patient
            // A08          → update patient demographics
            // A11/A38      → delete patient (only if no associated resources)
        }

        // IHE RAD-4: Procedure Scheduled
        // Trigger event: ORM^O01
        // Required segments: MSH, PID, PV1, ORC, OBR, ZDS
        // ZDS-1: Study Instance UID (DICOM-compliant)
        item def AdvaPACS_RAD4_ORM :> OrmMessage {
            attribute studyInstanceUID  : String;   // ZDS-1 — creates order
            attribute accessionNumber   : String;   // OBR-18 (max 16 chars)
            attribute requestedProcID   : String;   // OBR-19
            attribute scheduledStepID   : String;   // OBR-20
            attribute dicomModality     : String;   // OBR-24
        }

        // IHE RAD-13: Procedure Updated
        // Trigger event: ORM^O01 (re-used after RAD-4 has been sent)
        // Order Control codes: CA (cancel), DC (discontinue), XO (change)
        item def AdvaPACS_RAD13_ORM :> OrmMessage {
            attribute studyInstanceUID  : String;   // ZDS-1 — locates existing order
            attribute orderControl      : String;   // CA | DC | XO
            attribute accessionNumber   : String;   // OBR-18
        }

        // Inbound Report (HL7 type not confirmed in public docs;
        // likely MDM^T02 with document content, or ORU^R01)
        item def AdvaPACS_InboundReport :> HL7v2Message {
            attribute accessionNumber  : String;
            attribute reportStatus     : String;   // preliminary | final
            attribute reportContent    : String;   // narrative or PDF reference
        }

        // ── API / Auth Items ──────────────────────────────────────────────────

        item def AdvaPACSApiKey {
            attribute keyId     : String;   // used in Authorization header ID=
            attribute keySecret : String;   // used in Authorization header Secret=
            attribute permissions : String; // comma-delimited: FHIR, HL7, etc.
        }

        // ── Routing Rule Items ────────────────────────────────────────────────

        item def AdvaPACSRoutingRule {
            // Routing occurs at study, series, or instance granularity.
            // Priority 1 (lowest) – 100 (highest).
            attribute ruleName    : String;
            attribute priority    : Integer;
            attribute level       : String;   // study | series | instance
            attribute sourceAET   : String;   // originating Remote AE
            attribute localAET    : String;   // ingress Local AE on gateway
            attribute bindAET     : String;   // Local AE routing to destination
            attribute destAET     : String;   // target Remote AE
        }

        // ── HL7 Service Configuration Items ──────────────────────────────────

        item def AdvaPACSHL7ServiceConfig {
            attribute serviceName    : String;
            attribute gatewayName    : String;
            attribute mllpPort       : Integer;
            attribute processingMode : String;   // live | migration
            attribute ipWhitelist    : String;   // comma-delimited CIDR list
            attribute maxRetentionDays : Integer; // max 180
        }
    }


    // =========================================================================
    // HL7 v2 Ports — AdvaPACS-Specific Inbound / Outbound
    // =========================================================================

    package AdvaPACSHL7Ports {
        private import AdvaPACSItems::*;

        // ── Inbound HL7 from RIS/HIS → AdvaPACS ──────────────────────────────

        // Patient Registration (RAD-1) — receives ADT messages
        port def AdvaPACS_PatientRegServer {
            in item registration[0..*] : AdvaPACS_RAD1_ADT;
        }
        port def AdvaPACS_PatientRegClient {
            out item registration[0..*] : AdvaPACS_RAD1_ADT;
        }

        // Procedure Scheduled (RAD-4) — receives new ORM orders
        port def AdvaPACS_ProcScheduledServer {
            in item scheduledOrders[0..*] : AdvaPACS_RAD4_ORM;
        }
        port def AdvaPACS_ProcScheduledClient {
            out item scheduledOrders[0..*] : AdvaPACS_RAD4_ORM;
        }

        // Procedure Updated (RAD-13) — receives ORM order changes / cancels
        port def AdvaPACS_ProcUpdatedServer {
            in item updatedOrders[0..*] : AdvaPACS_RAD13_ORM;
        }
        port def AdvaPACS_ProcUpdatedClient {
            out item updatedOrders[0..*] : AdvaPACS_RAD13_ORM;
        }

        // Inbound Reports — receives completed diagnostic reports
        port def AdvaPACS_ReportInboundServer {
            in item reports[0..*] : AdvaPACS_InboundReport;
        }
        port def AdvaPACS_ReportInboundClient {
            out item reports[0..*] : AdvaPACS_InboundReport;
        }
    }

    // ─── HL7 Connectivity Options ─────────────────────────────────────────────

    package AdvaPACSHL7Connectivity {

        // Option A: MLLP to AdvaPACS Gateway
        // Gateway runs an HL7 MLLP listener on a configured port (IP-whitelisted).
        // Processing: live (sync ACK) or migration (async queue, immediate ACK).
        // Transformations: remove, constant, regex, field-copy, JavaScript (Rhino).
        port def AdvaPACSGatewayMLLP {
            // Composite: receives all RAD-1/4/13 + report message types
            in item hl7Messages[0..*] : HealthcareInterfaces::HL7v2Items::HL7v2Message;
            out item acks[0..*]       : HealthcareInterfaces::HL7v2Items::AckMessage;
        }
        port def AdvaPACSGatewayMLLPClient {
            out item hl7Messages[0..*] : HealthcareInterfaces::HL7v2Items::HL7v2Message;
            in  item acks[0..*]        : HealthcareInterfaces::HL7v2Items::AckMessage;
        }

        // Option B: MLLP direct to AdvaPACS Cloud Gateway (mTLS secured)
        // Same message set as gateway MLLP but no on-premises gateway required.
        port def AdvaPACSCloudMLLP {
            in item hl7Messages[0..*] : HealthcareInterfaces::HL7v2Items::HL7v2Message;
            out item acks[0..*]       : HealthcareInterfaces::HL7v2Items::AckMessage;
        }
        port def AdvaPACSCloudMLLPClient {
            out item hl7Messages[0..*] : HealthcareInterfaces::HL7v2Items::HL7v2Message;
            in  item acks[0..*]        : HealthcareInterfaces::HL7v2Items::AckMessage;
        }

        // Option C: HL7 over HTTPS REST API
        // Endpoint: POST https://<Region>.api.integration.advapacs.com/hl7/services/<Service ID>
        // Content-Type: application/hl7-v2+er7 | application/hl7-v2+xml
        // Auth: API Key (requires "Send HL7 over HTTPS" permission)
        // Response: HTTP 200 → HL7 ACK body; non-HL7 errors → JSON + HTTP status
        port def AdvaPACSHL7HttpsServer {
            in item hl7Messages[0..*] : HealthcareInterfaces::HL7v2Items::HL7v2Message;
            out item acks[0..*]       : HealthcareInterfaces::HL7v2Items::AckMessage;
        }
        port def AdvaPACSHL7HttpsClient {
            out item hl7Messages[0..*] : HealthcareInterfaces::HL7v2Items::HL7v2Message;
            in  item acks[0..*]        : HealthcareInterfaces::HL7v2Items::AckMessage;
        }
    }


    // =========================================================================
    // FHIR R4 / R5 Ports
    // =========================================================================

    package AdvaPACSFhirPorts {
        private import ScalarValues::*;
        private import HealthcareInterfaces::FHIRItems::*;

        // ── FHIR R4 API ───────────────────────────────────────────────────────
        // Base: https://<region>.api.integration.advapacs.com/fhir
        // Auth: Authorization: ID=<Access Key ID>,Secret=<Access Key Secret>

        port def AdvaPACS_FhirR4Server {
            // Confirmed supported resources (inferred from FHIR R5 listing + integration guides)
            out item patients[0..*]        : FhirPatient;
            out item serviceRequests[0..*] : FhirServiceRequest;
            out item imagingStudies[0..*]  : FhirImagingStudy;
            out item reports[0..*]         : FhirDiagnosticReport;
            out item bundles[0..*]         : FhirBundle;
        }
        port def AdvaPACS_FhirR4Client {
            in item patients[0..*]        : FhirPatient;
            in item serviceRequests[0..*] : FhirServiceRequest;
            in item imagingStudies[0..*]  : FhirImagingStudy;
            in item reports[0..*]         : FhirDiagnosticReport;
            in item bundles[0..*]         : FhirBundle;
        }

        // ── FHIR R5 API ───────────────────────────────────────────────────────
        // Base: https://<region>.api.integration.advapacs.com/fhir/R5
        // Resources confirmed in docs: CapabilityStatement, NamingSystem, Device,
        // DiagnosticReport, Location, Organization, Patient, Practitioner, ServiceRequest
        // Operations: Search, Read (Create/Update inferred for writable resources)

        port def AdvaPACS_FhirR5Server {
            out item patients[0..*]         : FhirPatient;
            out item serviceRequests[0..*]  : FhirServiceRequest;
            out item reports[0..*]          : FhirDiagnosticReport;
            out item resources[0..*]        : FhirResource;  // Device, Location, Org, Practitioner
            out item capabilities[0..*]     : FhirResource;  // CapabilityStatement
        }
        port def AdvaPACS_FhirR5Client {
            in item patients[0..*]        : FhirPatient;
            in item serviceRequests[0..*] : FhirServiceRequest;
            in item reports[0..*]         : FhirDiagnosticReport;
            in item resources[0..*]       : FhirResource;
            in item capabilities[0..*]    : FhirResource;
        }

        // ── FHIR Webhook (outbound notification from AdvaPACS → external) ────
        // AdvaPACS POSTs to a configured webhook URL when events occur.
        // Payload: FHIR resource (DiagnosticReport, ImagingStudy, etc.)
        // Auth header: user-configured secret value
        port def AdvaPACSWebhookSender {
            out item notification[0..*] : FhirResource;
        }
        port def AdvaPACSWebhookReceiver {
            in item notification[0..*] : FhirResource;
        }
    }


    // =========================================================================
    // DICOM / DICOMweb Ports — Gateway and Cloud
    // =========================================================================

    package AdvaPACSDicomPorts {
        private import HealthcareInterfaces::DicomItems::*;
        private import HealthcareInterfaces::DicomPorts::*;
        private import HealthcareInterfaces::DicomWebPorts::*;

        // ── Gateway DICOM (on-premises container, network_mode: host) ─────────
        // Presents a DICOM C-STORE SCP (Local AE) to local-network modalities.
        // Port is user-configured; typical deployment uses 11112.
        // Accepted calling AEs are registered as Remote AEs in the cloud UI.
        // The gateway then forwards studies to AdvaPACS cloud.

        port def AdvaPACSGatewayDicomSCP {
            // Accepts C-STORE from registered Remote AEs (modalities, Orthanc instances)
            in item sopInstances[0..*] : DicomSOPInstance;
        }
        port def AdvaPACSGatewayDicomSCU {
            out item sopInstances[0..*] : DicomSOPInstance;
        }

        // C-ECHO — gateway responds to DICOM verification from local systems
        port def AdvaPACSGatewayCEchoSCP;
        port def AdvaPACSGatewayCEchoSCU;

        // ── Gateway DICOMweb Proxy (STOW-RS inbound, port 8085) ───────────────
        // Local systems can STOW-RS directly to the gateway instead of C-STORE.
        // The gateway proxies the data forward to AdvaPACS cloud.

        port def AdvaPACSGatewayStowRsServer {
            in item instances[0..*] : DicomSOPInstance;
        }
        port def AdvaPACSGatewayStowRsClient {
            out item instances[0..*] : DicomSOPInstance;
        }

        // ── Cloud DICOMweb (STOW-RS / WADO-RS / QIDO-RS) ─────────────────────
        // Endpoint served from the AdvaPACS cloud PACS.
        // Used by: AdvaView/FlexView viewer, RADPAIR, external diagnostic viewers.
        // Authentication via API key or SSO session token.

        port def AdvaPACSCloudDicomWebServer {
            port stow : StowRsServer;
            port wado : WadoRsServer;
            port qido : QidoRsServer;
        }
        port def AdvaPACSCloudDicomWebClient {
            port stow : StowRsClient;
            port wado : WadoRsClient;
            port qido : QidoRsClient;
        }

        // ── Modality Worklist (centrally managed from AdvaPACS cloud UI) ──────
        // AdvaPACS manages worklist query configuration centrally.
        // Filters are applied in the cloud and pushed to gateway for DICOM C-FIND.
        port def AdvaPACSMWLSCP {
            in  item query[0..*]            : DicomQueryDataset;
            out item worklistEntries[0..*]  : DicomMWLEntry;
        }
        port def AdvaPACSMWLSCU {
            out item query[0..*]           : DicomQueryDataset;
            in  item worklistEntries[0..*] : DicomMWLEntry;
        }
    }


    // =========================================================================
    // Viewer Integration Port
    // =========================================================================

    package AdvaPACSViewerPorts {
        private import HealthcareInterfaces::DicomWebPorts::*;
        private import HealthcareInterfaces::DicomPorts::*;

        // AdvaPACS natively integrates: Weasis (desktop/free),
        // eUnity (web/Mach7, paid), MedDream (web/Softneta, paid).
        // Any vendor-neutral viewer supporting DICOMweb or DICOM Q/R can be added.

        port def AdvaPACSViewerDicomWebClient {
            // Viewer fetches studies via WADO-RS / QIDO-RS from the cloud
            port wado : WadoRsClient;
            port qido : QidoRsClient;
        }

        port def AdvaPACSViewerQRClient {
            // Alternative: viewer uses classic DICOM C-FIND + C-MOVE
            port cfind : DicomCFindSCU;
            port cmove : DicomCMoveSCU;
        }
    }


    // =========================================================================
    // SSO Port
    // =========================================================================

    package AdvaPACSSSOPorts {
        private import ScalarValues::*;

        item def SamlAssertion {
            attribute issuer       : String;
            attribute samlSubject  : String;   // 'subject' is a reserved SysML v2 keyword
            attribute nameId       : String;
            attribute sessionId    : String;
        }

        // AdvaPACS acts as SAML SP; external IdP (e.g. Entra ID) is the IdP.
        port def AdvaPACSSamlSP {
            in  item assertion[0..*] : SamlAssertion;
        }
        port def ExternalSamlIdP {
            out item assertion[0..*] : SamlAssertion;
        }
    }


    // =========================================================================
    // AdvaPACS System Part Definitions
    // =========================================================================

    // ─── AdvaPACS On-Premises Gateway ─────────────────────────────────────────
    // Container deployed on the facility server. Bridges local-network DICOM
    // and HL7 to the AdvaPACS cloud. Managed remotely via the cloud UI.

    part def AdvaPACSGateway {
        private import AdvaPACSItems::*;
        private import AdvaPACSHL7Connectivity::*;
        private import AdvaPACSDicomPorts::*;

        attribute gatewayName : String;
        attribute hostIp      : String;

        // HL7 MLLP listener (configurable port, IP-whitelisted)
        port hl7Mllp        : AdvaPACSGatewayMLLP;

        // DICOM Local AE (C-STORE SCP — main study ingress)
        port dicomSCP       : AdvaPACSGatewayDicomSCP;

        // DICOM C-ECHO SCP (DICOM verification)
        port dicomEchoSCP   : AdvaPACSGatewayCEchoSCP;

        // DICOMweb STOW-RS proxy (port 8085 by default)
        port stowRsProxy    : AdvaPACSGatewayStowRsServer;

        // Modality Worklist SCP (centrally managed from cloud)
        port mwlSCP         : AdvaPACSMWLSCP;

        // Outbound to cloud
        port cloudUpload    : AdvaPACSGatewayDicomSCU;
    }

    // ─── AdvaPACS Cloud PACS ──────────────────────────────────────────────────
    // Cloud-hosted SaaS. Receives images from gateways, serves viewers,
    // exposes HL7 / FHIR / DICOMweb APIs.

    part def AdvaPACSCloud {
        private import AdvaPACSHL7Ports::*;
        private import AdvaPACSHL7Connectivity::*;
        private import AdvaPACSFhirPorts::*;
        private import AdvaPACSDicomPorts::*;
        private import AdvaPACSSSOPorts::*;

        attribute tenantId  : String;
        attribute regionUrl : String;   // e.g. hkg.api.integration.advapacs.com

        // ── HL7 Interfaces ────────────────────────────────────────────────────

        // IHE RAD-1: Patient Registration
        port hl7PatientReg   : AdvaPACS_PatientRegServer;

        // IHE RAD-4: Procedure Scheduled
        port hl7ProcScheduled : AdvaPACS_ProcScheduledServer;

        // IHE RAD-13: Procedure Updated
        port hl7ProcUpdated  : AdvaPACS_ProcUpdatedServer;

        // Inbound reports from reporting systems
        port hl7ReportInbound : AdvaPACS_ReportInboundServer;

        // Cloud Gateway MLLP endpoint (mTLS)
        port cloudMllp       : AdvaPACSCloudMLLP;

        // HL7 over HTTPS REST API
        port hl7HttpsApi     : AdvaPACSHL7HttpsServer;

        // ── FHIR Interfaces ───────────────────────────────────────────────────

        // FHIR R4 REST API
        port fhirR4          : AdvaPACS_FhirR4Server;

        // FHIR R5 REST API
        port fhirR5          : AdvaPACS_FhirR5Server;

        // Outbound webhook notifications
        port webhookOut      : AdvaPACSWebhookSender;

        // ── DICOM / DICOMweb ──────────────────────────────────────────────────

        // Cloud DICOMweb (STOW-RS / WADO-RS / QIDO-RS)
        port dicomWeb        : AdvaPACSCloudDicomWebServer;

        // ── SSO ───────────────────────────────────────────────────────────────

        // SAML SP — accepts assertions from external IdP (Entra ID)
        port samlSP          : AdvaPACSSamlSP;
    }

    // ─── Diagnostic Viewer ────────────────────────────────────────────────────
    // Represents any viewer connected to AdvaPACS (AdvaView/FlexView, eUnity,
    // MedDream, Weasis, or any DICOMweb/Q/R-capable viewer).

    part def AdvaPACSViewer {
        private import AdvaPACSViewerPorts::*;

        attribute viewerName : String;   // AdvaView | eUnity | MedDream | Weasis | custom

        // DICOMweb path (preferred — zero-footprint web viewers)
        port dicomWebClient : AdvaPACSViewerDicomWebClient;

        // Classic DICOM Q/R path (desktop viewers, legacy)
        port qrClient       : AdvaPACSViewerQRClient;
    }

}  // end package AdvaPACSInterfaces
