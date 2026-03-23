# notes.md


## Initial prompt

"I need to design a virtual integration lab to prepare for deploying a
clinical site that uses a cloud based PACS.  I need a demo server that
emulates an DICOM modality, perhaps as a container that exposes the
DICOM protocol and has a database of public domain DICOM images that
we edit with demographics for a fictional MDR tuberculosis patient
population.  I need a radiology technologist workstation VM (Windows
11) that has an open-source DICOM viewer and that will act as a client
for this as-yet unspecified cloude-based PACS.  I need a radiologist
workstation VM (Windows 11) that would act like a radiologist work
station for evaluating images in studies and creating reports.  I need
a clinician workstation VM (Windows 11) that would access the images
and radiologist reports to assist in determining treatment.  All
workstations would connect to an OpenMRS server instance for imaging
scheduling and patient records."
