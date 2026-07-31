
Issue https://advahealthsolutions.atlassian.net/servicedesk/customer/portal/2/ADPS-1557

Possible to create presentation contexts for these two Ultrasound contexts?

Attachments: ECHO-0002 US000002.dcm and ECHO-0002 US000007.dcm

Description: We’re in the process of working with Ben & Ian. to see if AdvaView can meet our minimal requirements for Lesotho in the Fall.  We’re trying a number of experiments just to understand what exists today so we can discuss hard requirements per longer timeline.

Are these presentation context errors something in how we have configured AdvaView up front, or do these represent limitations in the current release?

# No presentation context for 'Ultrasound Multi-frame Image Storage'

## DICOM Uploader log
```
2026-07-31 16:56:51  INFO      127.0.0.1:40532 - "POST /dicom/upload HTTP/1.1" 200 OK
DICOM upload: C-STORE exception  US000002.dcm  error=No presentation context for 'Ultrasound Multi-frame Image Storage' has been accepted by the peer with 'JPEG Baseline (Process 1)' transfer syntax for the SCU role
```

## AdvaPACS Gateway log
```
2026-07-31T10:00:59.997-07:00 DEBUG 1 --- [   scheduling-1] c.a.a.g.services.DiskMonitorService      : Disk status is OK
2026-07-31T10:01:54.453-07:00  INFO 1 --- [pool-5-thread-1] org.dcm4che3.net.Connection              : Accept connection Socket[addr=/127.0.0.1,port=34493,localport=11112]
2026-07-31T10:01:54.453-07:00 DEBUG 1 --- [pool-5-thread-1] org.dcm4che3.net.Association             : /127.0.0.1:11112<-/127.0.0.1:34493(5): enter state: Sta2 - Transport connection open
2026-07-31T10:01:54.453-07:00 DEBUG 1 --- [pool-5-thread-1] org.dcm4che3.net.Timeout                 : /127.0.0.1:11112<-/127.0.0.1:34493(5): start A-ASSOCIATE-RQ timeout of 15000ms
2026-07-31T10:01:54.453-07:00 DEBUG 1 --- [pool-5-thread-1] org.dcm4che3.net.Connection              : Wait for connection on /0.0.0.0:11112
2026-07-31T10:01:54.454-07:00  INFO 1 --- [pool-5-thread-6] org.dcm4che3.net.Association             : ADVAPACS_GW_01<-IML_US_01(5) >> A-ASSOCIATE-RQ
2026-07-31T10:01:54.454-07:00 DEBUG 1 --- [pool-5-thread-6] org.dcm4che3.net.Association             : A-ASSOCIATE-RQ[
  calledAET: ADVAPACS_GW_01
  callingAET: IML_US_01
  applicationContext: 1.2.840.10008.3.1.1.1 - DICOM Application Context Name
  implClassUID: 1.2.826.0.1.3680043.9.3811.3.0.4
  implVersionName: PYNETDICOM_304
  maxPDULength: 16382
  maxOpsInvoked/maxOpsPerformed: 1/1
  PresentationContext[id: 1
    as: 1.2.840.10008.5.1.4.1.1.3.1 - Ultrasound Multi-frame Image Storage
    ts: 1.2.840.10008.1.2 - Implicit VR Little Endian
    ts: 1.2.840.10008.1.2.1 - Explicit VR Little Endian
    ts: 1.2.840.10008.1.2.1.99 - Deflated Explicit VR Little Endian
    ts: 1.2.840.10008.1.2.2 - Explicit VR Big Endian (Retired)
  ]
]
2026-07-31T10:01:54.454-07:00 DEBUG 1 --- [pool-5-thread-6] org.dcm4che3.net.Timeout                 : ADVAPACS_GW_01<-IML_US_01(5): stop A-ASSOCIATE-RQ timeout
2026-07-31T10:01:54.454-07:00 DEBUG 1 --- [pool-5-thread-6] org.dcm4che3.net.Association             : ADVAPACS_GW_01<-IML_US_01(5): enter state: Sta3 - Awaiting local A-ASSOCIATE response primitive
2026-07-31T10:01:54.454-07:00 DEBUG 1 --- [pool-5-thread-6] c.a.a.gateway.dicom.AssociationHandler   : Got association from IML_US_01 from IP: 127.0.0.1
2026-07-31T10:01:54.454-07:00  INFO 1 --- [pool-5-thread-6] org.dcm4che3.net.Association             : ADVAPACS_GW_01<-IML_US_01(5) << A-ASSOCIATE-AC
2026-07-31T10:01:54.454-07:00 DEBUG 1 --- [pool-5-thread-6] org.dcm4che3.net.Association             : A-ASSOCIATE-AC[
  calledAET: ADVAPACS_GW_01
  callingAET: IML_US_01
  applicationContext: 1.2.840.10008.3.1.1.1 - DICOM Application Context Name
  implClassUID: 1.3.6.1.4.1.54068.2.2.1.19.1
  implVersionName: APGW 1.19.1
  maxPDULength: 16378
  maxOpsInvoked/maxOpsPerformed: 1/1
  PresentationContext[id: 1
    result: 0 - acceptance
    ts: 1.2.840.10008.1.2 - Implicit VR Little Endian
  ]
]
2026-07-31T10:01:54.454-07:00 DEBUG 1 --- [pool-5-thread-6] org.dcm4che3.net.Association             : ADVAPACS_GW_01<-IML_US_01(5): enter state: Sta6 - Association established and ready for data transfer
2026-07-31T10:01:54.454-07:00 DEBUG 1 --- [pool-5-thread-6] org.dcm4che3.net.Timeout                 : ADVAPACS_GW_01<-IML_US_01(5): start idle timeout of 20000ms
2026-07-31T10:01:54.458-07:00  INFO 1 --- [pool-5-thread-6] org.dcm4che3.net.Association             : ADVAPACS_GW_01<-IML_US_01(5) >> A-RELEASE-RQ
2026-07-31T10:01:54.458-07:00 DEBUG 1 --- [pool-5-thread-6] org.dcm4che3.net.Timeout                 : ADVAPACS_GW_01<-IML_US_01(5): stop idle timeout
2026-07-31T10:01:54.458-07:00 DEBUG 1 --- [pool-5-thread-6] org.dcm4che3.net.Association             : ADVAPACS_GW_01<-IML_US_01(5): enter state: Sta8 - Awaiting local A-RELEASE response primitive
2026-07-31T10:01:54.458-07:00  INFO 1 --- [pool-5-thread-6] org.dcm4che3.net.Association             : ADVAPACS_GW_01<-IML_US_01(5) << A-RELEASE-RP
2026-07-31T10:01:54.458-07:00 DEBUG 1 --- [pool-5-thread-6] org.dcm4che3.net.Timeout                 : ADVAPACS_GW_01<-IML_US_01(5): start A-ABORT timeout of 1000ms
2026-07-31T10:01:54.458-07:00 DEBUG 1 --- [pool-5-thread-6] org.dcm4che3.net.Timeout                 : ADVAPACS_GW_01<-IML_US_01(5): stop A-ABORT timeout
2026-07-31T10:01:54.458-07:00 DEBUG 1 --- [pool-5-thread-6] org.dcm4che3.net.Association             : ADVAPACS_GW_01<-IML_US_01(5): enter state: Sta13 - Awaiting Transport Connection Close Indication
2026-07-31T10:01:54.458-07:00 DEBUG 1 --- [pool-5-thread-6] org.dcm4che3.net.Association             : ADVAPACS_GW_01<-IML_US_01(5): closing Socket[addr=/127.0.0.1,port=34493,localport=11112] in 50 ms
2026-07-31T10:01:54.458-07:00 DEBUG 1 --- [pool-5-thread-6] c.a.advapacs.gateway.dicom.StoreSCP      : Cleaned up incoming association for Association: ADVAPACS_GW_01<-IML_US_01(5)
2026-07-31T10:01:54.508-07:00  INFO 1 --- [pool-4-thread-1] org.dcm4che3.net.Association             : ADVAPACS_GW_01<-IML_US_01(5): close Socket[addr=/127.0.0.1,port=34493,localport=11112]
2026-07-31T10:01:54.508-07:00 DEBUG 1 --- [pool-4-thread-1] org.dcm4che3.net.Association             : ADVAPACS_GW_01<-IML_US_01(5): enter state: Sta1 - Idle
2026-07-31T10:01:54.936-07:00 DEBUG 1 --- [      Thread-50] c.a.a.gateway.metrics.MetricsService     : Pushing metrics...
2026-07-31T10:01:55.004-07:00 DEBUG 1 --- [      Thread-50] c.a.a.gateway.metrics.MetricsService     : Successfully pushed metrics!
2026-07-31T10:01:55.307-07:00 DEBUG 1 --- [      Thread-50] c.a.a.g.m.collectors.LatencyMetric       : Performing latency test...
2026-07-31T10:01:55.307-07:00 DEBUG 1 --- [      Thread-50] c.a.a.g.m.collectors.LatencyMetric       : Warming up connection
2026-07-31T10:01:55.346-07:00 DEBUG 1 --- [      Thread-50] c.a.a.g.m.collectors.LatencyMetric       : Warmed up connection. Performing measurement...
2026-07-31T10:01:55.391-07:00 DEBUG 1 --- [      Thread-50] c.a.a.g.m.collectors.LatencyMetric       : Measured latency as 45ms
2026-07-31T10:01:59.997-07:00 DEBUG 1 --- [   scheduling-1] c.a.a.g.services.DiskMonitorService      : Disk status is OK
```

# No presentation context for 'Ultrasound Image Storage'

## DICOM Uploader log
```
2026-07-31 17:05:08  INFO      127.0.0.1:46522 - "POST /dicom/upload HTTP/1.1" 200 OK
DICOM upload: C-STORE exception  US000007.dcm  error=No presentation context for 'Ultrasound Image Storage' has been accepted by the peer with 'JPEG Lossless, Non-Hierarchical, First-Order Prediction (Process 14 [Selection Value 1])' transfer syntax for the SCU role
```

## AdvaPACS Gateway log
```
2026-07-31T10:04:59.998-07:00 DEBUG 1 --- [   scheduling-1] c.a.a.g.services.DiskMonitorService      : Disk status is OK
2026-07-31T10:05:08.663-07:00  INFO 1 --- [pool-5-thread-1] org.dcm4che3.net.Connection              : Accept connection Socket[addr=/127.0.0.1,port=33181,localport=11112]
2026-07-31T10:05:08.663-07:00 DEBUG 1 --- [pool-5-thread-1] org.dcm4che3.net.Association             : /127.0.0.1:11112<-/127.0.0.1:33181(6): enter state: Sta2 - Transport connection open
2026-07-31T10:05:08.663-07:00 DEBUG 1 --- [pool-5-thread-1] org.dcm4che3.net.Timeout                 : /127.0.0.1:11112<-/127.0.0.1:33181(6): start A-ASSOCIATE-RQ timeout of 15000ms
2026-07-31T10:05:08.664-07:00 DEBUG 1 --- [pool-5-thread-1] org.dcm4che3.net.Connection              : Wait for connection on /0.0.0.0:11112
2026-07-31T10:05:08.664-07:00  INFO 1 --- [pool-5-thread-7] org.dcm4che3.net.Association             : ADVAPACS_GW_01<-IML_US_01(6) >> A-ASSOCIATE-RQ
2026-07-31T10:05:08.664-07:00 DEBUG 1 --- [pool-5-thread-7] org.dcm4che3.net.Association             : A-ASSOCIATE-RQ[
  calledAET: ADVAPACS_GW_01
  callingAET: IML_US_01
  applicationContext: 1.2.840.10008.3.1.1.1 - DICOM Application Context Name
  implClassUID: 1.2.826.0.1.3680043.9.3811.3.0.4
  implVersionName: PYNETDICOM_304
  maxPDULength: 16382
  maxOpsInvoked/maxOpsPerformed: 1/1
  PresentationContext[id: 1
    as: 1.2.840.10008.5.1.4.1.1.6.1 - Ultrasound Image Storage
    ts: 1.2.840.10008.1.2 - Implicit VR Little Endian
    ts: 1.2.840.10008.1.2.1 - Explicit VR Little Endian
    ts: 1.2.840.10008.1.2.1.99 - Deflated Explicit VR Little Endian
    ts: 1.2.840.10008.1.2.2 - Explicit VR Big Endian (Retired)
  ]
]
2026-07-31T10:05:08.664-07:00 DEBUG 1 --- [pool-5-thread-7] org.dcm4che3.net.Timeout                 : ADVAPACS_GW_01<-IML_US_01(6): stop A-ASSOCIATE-RQ timeout
2026-07-31T10:05:08.664-07:00 DEBUG 1 --- [pool-5-thread-7] org.dcm4che3.net.Association             : ADVAPACS_GW_01<-IML_US_01(6): enter state: Sta3 - Awaiting local A-ASSOCIATE response primitive
2026-07-31T10:05:08.665-07:00 DEBUG 1 --- [pool-5-thread-7] c.a.a.gateway.dicom.AssociationHandler   : Got association from IML_US_01 from IP: 127.0.0.1
2026-07-31T10:05:08.665-07:00  INFO 1 --- [pool-5-thread-7] org.dcm4che3.net.Association             : ADVAPACS_GW_01<-IML_US_01(6) << A-ASSOCIATE-AC
2026-07-31T10:05:08.665-07:00 DEBUG 1 --- [pool-5-thread-7] org.dcm4che3.net.Association             : A-ASSOCIATE-AC[
  calledAET: ADVAPACS_GW_01
  callingAET: IML_US_01
  applicationContext: 1.2.840.10008.3.1.1.1 - DICOM Application Context Name
  implClassUID: 1.3.6.1.4.1.54068.2.2.1.19.1
  implVersionName: APGW 1.19.1
  maxPDULength: 16378
  maxOpsInvoked/maxOpsPerformed: 1/1
  PresentationContext[id: 1
    result: 0 - acceptance
    ts: 1.2.840.10008.1.2 - Implicit VR Little Endian
  ]
]
2026-07-31T10:05:08.665-07:00 DEBUG 1 --- [pool-5-thread-7] org.dcm4che3.net.Association             : ADVAPACS_GW_01<-IML_US_01(6): enter state: Sta6 - Association established and ready for data transfer
2026-07-31T10:05:08.665-07:00 DEBUG 1 --- [pool-5-thread-7] org.dcm4che3.net.Timeout                 : ADVAPACS_GW_01<-IML_US_01(6): start idle timeout of 20000ms
2026-07-31T10:05:08.669-07:00  INFO 1 --- [pool-5-thread-7] org.dcm4che3.net.Association             : ADVAPACS_GW_01<-IML_US_01(6) >> A-RELEASE-RQ
2026-07-31T10:05:08.669-07:00 DEBUG 1 --- [pool-5-thread-7] org.dcm4che3.net.Timeout                 : ADVAPACS_GW_01<-IML_US_01(6): stop idle timeout
2026-07-31T10:05:08.669-07:00 DEBUG 1 --- [pool-5-thread-7] org.dcm4che3.net.Association             : ADVAPACS_GW_01<-IML_US_01(6): enter state: Sta8 - Awaiting local A-RELEASE response primitive
2026-07-31T10:05:08.669-07:00  INFO 1 --- [pool-5-thread-7] org.dcm4che3.net.Association             : ADVAPACS_GW_01<-IML_US_01(6) << A-RELEASE-RP
2026-07-31T10:05:08.669-07:00 DEBUG 1 --- [pool-5-thread-7] org.dcm4che3.net.Timeout                 : ADVAPACS_GW_01<-IML_US_01(6): start A-ABORT timeout of 1000ms
2026-07-31T10:05:08.669-07:00 DEBUG 1 --- [pool-5-thread-7] org.dcm4che3.net.Timeout                 : ADVAPACS_GW_01<-IML_US_01(6): stop A-ABORT timeout
2026-07-31T10:05:08.669-07:00 DEBUG 1 --- [pool-5-thread-7] org.dcm4che3.net.Association             : ADVAPACS_GW_01<-IML_US_01(6): enter state: Sta13 - Awaiting Transport Connection Close Indication
2026-07-31T10:05:08.669-07:00 DEBUG 1 --- [pool-5-thread-7] org.dcm4che3.net.Association             : ADVAPACS_GW_01<-IML_US_01(6): closing Socket[addr=/127.0.0.1,port=33181,localport=11112] in 50 ms
2026-07-31T10:05:08.669-07:00 DEBUG 1 --- [pool-5-thread-7] c.a.advapacs.gateway.dicom.StoreSCP      : Cleaned up incoming association for Association: ADVAPACS_GW_01<-IML_US_01(6)
2026-07-31T10:05:08.719-07:00  INFO 1 --- [pool-4-thread-1] org.dcm4che3.net.Association             : ADVAPACS_GW_01<-IML_US_01(6): close Socket[addr=/127.0.0.1,port=33181,localport=11112]
2026-07-31T10:05:08.719-07:00 DEBUG 1 --- [pool-4-thread-1] org.dcm4che3.net.Association             : ADVAPACS_GW_01<-IML_US_01(6): enter state: Sta1 - Idle
```
