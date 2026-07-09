// ============================================================================
// Healthcare Interface Definitions — SysML v2 Textual Notation
//
// Reusable port, item, and connection definitions for DICOM, HL7 v2, and FHIR R4.
// Import this package to type ports in system models.
//
// NOTE: The SysML v2 spec allows `port def X conjugates Y;` at the header level,
// but Cameo's parser expects `;` or `{` after the name and rejects the keyword
// there. All conjugate pairs are therefore expressed as explicit reversed-direction
// bodies, which is semantically equivalent.
//
// Standard:  SysML v2 (ISO/IEC 19514:2024)
// Tooling:   SysML v2 API Server · Jupyter SysML v2 kernel · Cameo SysML Plugin
// ============================================================================

package HealthcareInterfaces {

    // =========================================================================
    // DICOM — Digital Imaging and Communications in Medicine (NEMA PS3)
    // =========================================================================

    package DicomItems {

        item def DicomDataset;

        item def DicomSOPInstance :> DicomDataset {
            attribute sopClassUID       : String;
            attribute sopInstanceUID    : String;
            attribute transferSyntaxUID : String;
            attribute modality          : String;   // CR, DX, CT, MR, US, …
        }

        item def DicomStudy {
            attribute studyInstanceUID : String;
            attribute patientID        : String;
            attribute studyDate        : String;
            attribute studyDescription : String;
            item instances[1..*] : DicomSOPInstance;
        }

        item def DicomQueryDataset :> DicomDataset;   // C-FIND / C-MOVE identifier dataset

        item def DicomMWLEntry :> DicomDataset {
            attribute accessionNumber          : String;
            attribute patientID                : String;
            attribute scheduledAETitle         : String;
            attribute scheduledProcedureStep   : String;
            attribute modality                 : String;
            attribute scheduledDateTime        : String;
        }
    }

    // ─── Traditional DICOM Service Ports ──────────────────────────────────────

    package DicomPorts {
        private import DicomItems::*;

        // C-STORE: SOP Instance transfer (PS3.4 — Storage Service Class)
        port def DicomCStoreSCP {
            in item sopInstances[0..*] : DicomSOPInstance;
        }
        port def DicomCStoreSCU {
            out item sopInstances[0..*] : DicomSOPInstance;
        }

        // C-ECHO: Connectivity verification (PS3.4 — Verification SOP Class)
        port def DicomCEchoSCP;
        port def DicomCEchoSCU;

        // C-FIND: Query (PS3.4 — Query/Retrieve Service Class)
        port def DicomCFindSCP {
            in  item query         : DicomQueryDataset;
            out item matches[0..*] : DicomDataset;
        }
        port def DicomCFindSCU {
            out item query         : DicomQueryDataset;
            in  item matches[0..*] : DicomDataset;
        }

        // C-MOVE: Retrieve initiation (PS3.4 — Query/Retrieve Service Class)
        port def DicomCMoveSCP {
            in item moveRequest : DicomQueryDataset;
        }
        port def DicomCMoveSCU {
            out item moveRequest : DicomQueryDataset;
        }

        // Modality Worklist (MWL) — specialization of C-FIND (PS3.4 — SOP 1.2.840.10008.5.1.4.31)
        port def DicomMWLSCP :> DicomCFindSCP {
            out item worklistEntries[0..*] : DicomMWLEntry;
        }
        port def DicomMWLSCU :> DicomCFindSCU {
            in item worklistEntries[0..*] : DicomMWLEntry;
        }

        // Modality Performed Procedure Step (MPPS) — PS3.4 § N
        port def MppsSCP {
            in item ppStep : DicomDataset;   // N-CREATE / N-SET
        }
        port def MppsSCU {
            out item ppStep : DicomDataset;
        }
    }

    // ─── DICOMweb Ports (PS3.18) ──────────────────────────────────────────────

    package DicomWebPorts {
        private import DicomItems::*;

        // STOW-RS: Store (POST instances/studies)
        port def StowRsServer {
            in item instances[0..*] : DicomSOPInstance;
        }
        port def StowRsClient {
            out item instances[0..*] : DicomSOPInstance;
        }

        // WADO-RS: Retrieve (GET instances/frames/metadata)
        port def WadoRsServer {
            out item instances[0..*] : DicomSOPInstance;
        }
        port def WadoRsClient {
            in item instances[0..*] : DicomSOPInstance;
        }

        // QIDO-RS: Query (GET studies/series/instances search)
        port def QidoRsServer {
            out item results[0..*] : DicomDataset;
        }
        port def QidoRsClient {
            in item results[0..*] : DicomDataset;
        }

        // Composite DICOMweb endpoint (STOW + WADO + QIDO bundled)
        port def DicomWebServer {
            port stow : StowRsServer;
            port wado : WadoRsServer;
            port qido : QidoRsServer;
        }
        port def DicomWebClient {
            port stow : StowRsClient;
            port wado : WadoRsClient;
            port qido : QidoRsClient;
        }
    }

    // ─── DICOM Connection Definitions ─────────────────────────────────────────

    package DicomConnections {
        private import DicomPorts::*;
        private import DicomWebPorts::*;

        connection def DicomCStoreLink {
            end scu : DicomCStoreSCU;
            end scp : DicomCStoreSCP;
        }

        connection def DicomCEchoLink {
            end scu : DicomCEchoSCU;
            end scp : DicomCEchoSCP;
        }

        connection def DicomCFindLink {
            end scu : DicomCFindSCU;
            end scp : DicomCFindSCP;
        }

        connection def DicomMWLLink {
            end scu : DicomMWLSCU;
            end scp : DicomMWLSCP;
        }

        connection def DicomCMoveLink {
            end scu : DicomCMoveSCU;
            end scp : DicomCMoveSCP;
        }

        connection def StowRsLink {
            end client : StowRsClient;
            end server : StowRsServer;
        }

        connection def DicomWebLink {
            end client : DicomWebClient;
            end server : DicomWebServer;
        }
    }


    // =========================================================================
    // HL7 v2 — Health Level Seven Version 2.x (MLLP transport)
    // =========================================================================

    package HL7v2Items {

        item def HL7v2Message {
            attribute messageType    : String;   // e.g. "ADT", "ORM", "ORU", "MDM"
            attribute triggerEvent   : String;   // e.g. "A01", "O01", "R01", "T02"
            attribute version        : String;   // e.g. "2.5", "2.6", "2.8"
            attribute sendingApp     : String;
            attribute receivingApp   : String;
            attribute messageControl : String;   // unique message ID
        }

        item def AdtMessage :> HL7v2Message;
        // A01 Admit · A02 Transfer · A03 Discharge · A04 Register · A08 Update · A40 Merge

        item def OrmMessage :> HL7v2Message;
        // O01 Order — radiology / lab orders with order detail (OBR) segments

        item def OruMessage :> HL7v2Message;
        // R01 Unsolicited Observation Result — diagnostic report delivery

        item def MdmMessage :> HL7v2Message;
        // T01 Original Document Notification · T02 Original Document + Content

        item def SiuMessage :> HL7v2Message;
        // S12 Notification of New Appointment · S14 Notification of Appointment Modification

        item def AckMessage :> HL7v2Message;
        // Application acknowledgement (AA / AE / AR)
    }

    // ─── HL7 v2 Port Definitions ──────────────────────────────────────────────

    package HL7v2Ports {
        private import HL7v2Items::*;

        // Generic MLLP message ports (transport-level)
        port def HL7v2MLLPServer {
            in  item messages[0..*] : HL7v2Message;
            out item acks[0..*]     : AckMessage;
        }
        port def HL7v2MLLPClient {
            out item messages[0..*] : HL7v2Message;
            in  item acks[0..*]     : AckMessage;
        }

        // Typed application-level ports
        port def AdtSender {
            out item adtMessages[0..*] : AdtMessage;
        }
        port def AdtReceiver {
            in item adtMessages[0..*] : AdtMessage;
        }

        port def OrmSender {
            out item orders[0..*] : OrmMessage;
        }
        port def OrmReceiver {
            in item orders[0..*] : OrmMessage;
        }

        port def OruSender {
            out item reports[0..*] : OruMessage;
        }
        port def OruReceiver {
            in item reports[0..*] : OruMessage;
        }

        port def MdmSender {
            out item documents[0..*] : MdmMessage;
        }
        port def MdmReceiver {
            in item documents[0..*] : MdmMessage;
        }

        port def SiuSender {
            out item scheduleNotices[0..*] : SiuMessage;
        }
        port def SiuReceiver {
            in item scheduleNotices[0..*] : SiuMessage;
        }
    }

    // ─── HL7 v2 Connection Definitions ────────────────────────────────────────

    package HL7v2Connections {
        private import HL7v2Ports::*;

        connection def HL7v2MLLPLink {
            end client : HL7v2MLLPClient;
            end server : HL7v2MLLPServer;
        }

        connection def HL7v2AdtLink {
            end sender   : AdtSender;
            end receiver : AdtReceiver;
        }

        connection def HL7v2OrmLink {
            end sender   : OrmSender;
            end receiver : OrmReceiver;
        }

        connection def HL7v2OruLink {
            end sender   : OruSender;
            end receiver : OruReceiver;
        }

        connection def HL7v2MdmLink {
            end sender   : MdmSender;
            end receiver : MdmReceiver;
        }
    }


    // =========================================================================
    // FHIR R4 — Fast Healthcare Interoperability Resources (HL7 FHIR R4)
    // =========================================================================

    package FHIRItems {

        item def FhirResource {
            attribute resourceType : String;
            attribute id           : String;
        }

        item def FhirPatient :> FhirResource {
            attribute identifier : String;
            attribute name       : String;
            attribute birthDate  : String;
            attribute gender     : String;
        }

        item def FhirServiceRequest :> FhirResource {
            // Imaging order (replaces DiagnosticOrder in earlier FHIR versions)
            attribute status   : String;   // draft | active | completed | revoked
            attribute intent   : String;   // order | plan | proposal
            attribute category : String;   // 363679005 (imaging)
            attribute code     : String;   // procedure / modality code
        }

        item def FhirDiagnosticReport :> FhirResource {
            // Radiology report (final or preliminary)
            attribute status        : String;  // registered | preliminary | final | amended
            attribute category      : String;  // LP29684-5 (Radiology)
            attribute code          : String;
            attribute conclusion    : String;
            attribute presentedForm : String;  // PDF / narrative
        }

        item def FhirImagingStudy :> FhirResource {
            attribute studyInstanceUID  : String;
            attribute modality          : String;
            attribute numberOfSeries    : Integer;
            attribute numberOfInstances : Integer;
            attribute endpoint          : String;  // ref to FhirEndpoint
        }

        item def FhirEndpoint :> FhirResource {
            // DICOMweb / WADO endpoint descriptor
            attribute connectionType : String;   // dicom-wado-rs | dicom-qido-rs | …
            attribute address        : String;
        }

        item def FhirBundle :> FhirResource {
            attribute bundleType : String;   // transaction | searchset | document
            item entries[0..*]  : FhirResource;
        }

        item def FhirOperationOutcome :> FhirResource {
            attribute severity : String;
            attribute code     : String;
            attribute details  : String;
        }
    }

    // ─── FHIR Port Definitions ─────────────────────────────────────────────────

    package FHIRPorts {
        private import FHIRItems::*;

        // Generic FHIR REST server (CRUD + search, any resource type)
        port def FhirRestServer {
            in  item create[0..*] : FhirResource;
            out item read[0..*]   : FhirResource;
            in  item update[0..*] : FhirResource;
            out item search[0..*] : FhirBundle;
        }
        port def FhirRestClient {
            out item create[0..*] : FhirResource;
            in  item read[0..*]   : FhirResource;
            out item update[0..*] : FhirResource;
            in  item search[0..*] : FhirBundle;
        }

        // Typed resource-specific endpoints
        port def FhirPatientServer {
            out item patients[0..*] : FhirPatient;
        }
        port def FhirPatientClient {
            in item patients[0..*] : FhirPatient;
        }

        port def FhirOrderServer {
            out item orders[0..*]    : FhirServiceRequest;
            in  item newOrders[0..*] : FhirServiceRequest;
        }
        port def FhirOrderClient {
            in  item orders[0..*]    : FhirServiceRequest;
            out item newOrders[0..*] : FhirServiceRequest;
        }

        port def FhirReportServer {
            in  item inboundReports[0..*]  : FhirDiagnosticReport;
            out item outboundReports[0..*] : FhirDiagnosticReport;
        }
        port def FhirReportClient {
            out item inboundReports[0..*]  : FhirDiagnosticReport;
            in  item outboundReports[0..*] : FhirDiagnosticReport;
        }

        port def FhirImagingServer {
            out item studies[0..*] : FhirImagingStudy;
        }
        port def FhirImagingClient {
            in item studies[0..*] : FhirImagingStudy;
        }
    }

    // ─── FHIR Connection Definitions ──────────────────────────────────────────

    package FHIRConnections {
        private import FHIRPorts::*;

        connection def FhirRestLink {
            end client : FhirRestClient;
            end server : FhirRestServer;
        }

        connection def FhirOrderLink {
            end client : FhirOrderClient;
            end server : FhirOrderServer;
        }

        connection def FhirReportLink {
            end client : FhirReportClient;
            end server : FhirReportServer;
        }
    }

}  // end package HealthcareInterfaces
