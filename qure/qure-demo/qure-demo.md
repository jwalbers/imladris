





### Technical details

```bash
PS C:\Dev\git> cd C:\Dev\git\imladris\minxray-sim
PS C:\Dev\git\imladris\minxray-sim> $env:LIBRARY_HOST = "../../imladris-data/raw/tb-cxr/set-1"
PS C:\Dev\git\imladris\minxray-sim> docker compose run --rm minxray-sim worklist
2026-09-30 21:12:41,429 WARNING Invalid value for VR UI: '1.2.840.12345.3.152.0.3661202164303379.0.3955276292305643.0.0177'. Please see <https://dicom.nema.org/medical/dicom/current/output/html/part05.html#table_6.2-1> for allowed values for each VR.
/usr/local/lib/python3.12/site-packages/pydicom/valuerep.py:440: UserWarning: Invalid value for VR UI: '1.2.840.12345.3.152.0.3661202164303379.0.3955276292305643.0.0177'. Please see <https://dicom.nema.org/medical/dicom/current/output/html/part05.html#table_6.2-1> for allowed values for each VR.
  warn_and_log(msg)
  #  Date      Accession     Patient ID        Name                          Sex  DOB       Mod  Station
  0  20261001  CXR3234       4ME0UG            Lekhanya^Rethabile                 19910930  DX   MIX
  1  20261001  CXR190.7      VL4F8A            Ramohapi^Rethabile                 19980930  DX   MIX
  2  20261001  CXR5614       AKNGME            Sebatane^Tumelo                    19730930  DX   MIX
  3  20261001  CXR8176       GN21TF            Khoza^Nthabiseng                   19710930  DX   MIX
  4  20260824  CXR2747       E2ETEST98934      Vulture^Ivory                      19960930  DX   MIX
  5  20260824  CXR6822       E2ETEST43527      Marten^Coral                       19960930  DX   MIX
PS C:\Dev\git\imladris\minxray-sim> docker compose run --rm minxray-sim capture --patient-id GN21TF --image /library/Tuberculosis/Tuberculosis-1.png
2026-09-30 21:12:42,805 WARNING Invalid value for VR UI: '1.2.840.12345.3.152.0.3661202164303379.0.3955276292305643.0.0177'. Please see <https://dicom.nema.org/medical/dicom/current/output/html/part05.html#table_6.2-1> for allowed values for each VR.
/usr/local/lib/python3.12/site-packages/pydicom/valuerep.py:440: UserWarning: Invalid value for VR UI: '1.2.840.12345.3.152.0.3661202164303379.0.3955276292305643.0.0177'. Please see <https://dicom.nema.org/medical/dicom/current/output/html/part05.html#table_6.2-1> for allowed values for each VR.
  warn_and_log(msg)
2026-09-30 21:12:42,818 INFO Capturing Khoza^Nthabiseng (GN21TF, acc CXR8176) from /library/Tuberculosis/Tuberculosis-1.png
2026-09-30 21:12:43,447 INFO MPPS N-CREATE IN PROGRESS -> 0x0000
2026-09-30 21:12:46,535 INFO Saved /output/CXR8176_1.2.826.0.1.3680043.8.498.16245399674198062368555032357649295444.dcm
2026-09-30 21:12:47,851 INFO C-STORE 1.2.826.0.1.3680043.8.498.16245399674198062368555032357649295444 -> 0x0000
2026-09-30 21:12:48,389 INFO MPPS N-SET COMPLETED -> 0x0000
PS C:\Dev\git\imladris\minxray-sim>
```
