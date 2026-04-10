imladris IMaging Lab for Digital Radiography Information Systems
================================================================

# Overview

Primary notes for this project live on the PIH EMR Confluence site: ](IMaging LAb for Digital Radiology Information Systems (IMLADRIS) Ideas)(https://pihemr.atlassian.net/wiki/x/CAA9_Q)]

See that page for latest overview and discussion of the project.

# Setup

## Python config

```
mkdir .imladris_venv
python -m venv .imladris_venv
source .imladris_venv/bin/activate
python -m pip install <packages below>
```

| Package | Version | Purpose |
|---|---|---|
| `ffmpeg-python` | 0.2.0 | MP4 frame extraction |
| `google-cloud-storage` | 3.10.1 | GCS upload/download |
| `kaggle` | 2.0.0 | Kaggle dataset access |
| `numpy` | 2.4.4 | Pixel array handling |
| `pandas` | 3.0.2 | Census CSV handling |
| `pillow` | 12.2.0 | Image processing |
| `pydicom` | 3.0.2 | DICOM read/write (dep of pynetdicom) |
| `pynetdicom` | 3.0.4 | needed by sidecar |
| `python-dotenv` | 1.2.2 | `.env` config loading |

## Emacs config

(setenv "TERM" "dumb")
(setenv "NO_COLOR" "1")

## Startup

```
docker compose restart
docker compose down && docker compose up -d
docker ps
```
Confirm the following have started.
imladris-mysql
imladris-ohif
imladris-pacs-proxy
imladris-pacs
imladris-modality

# Resources

Eventually, may create sites for our domains: https://imladrislabs.org

We own imladrislabs.[org,net,info,com]

# Sourcing the Xray Component

## Use the Kaggle TB_Chest_Radiography_Database dataset

Create a free Kaggle account and get an API token from the site.

Maintain the Kaggle API token in the keys subdirectory, but do not commit it to github.  The keys/ dir is in the .gitignore list.

We have cloned the dataset in gcloud and use those images to randomly select Normal vs. Tuberculosis images for our fictional patients.


## Sourcing the Ultrasound (FASH) Component

We need fultrasound images. For an MDR-TB population in Lesotho, specifically FASH (Focused Assessment with Sonography for HIV-associated TB) findings.

Since these aren't in the X-ray sets, need to find representative public domain clips/stills for:
- Pericardial Effusion: Look for "POCUS Parasternal Long Axis Effusion."
- Pleural Effusion: Look for "POCUS Lung Sliding Fluid Line."
- Abdominal Lymphadenopathy: Look for "POCUS Para-aortic Lymph Nodes."

### POCUS Atlas: the Primary Source

This is the "gold standard" for open-access ultrasound clips. It is peer-reviewed and explicitly intended for educational use.

The POCUS Atlas is the best public domain source for these specific clips. You can download a few "Fluid" or "Abscess" clips and upload them to your GCS bucket under a /ultrasound folder.

#### POCUS Image Library
Unlike the chest X-ray datasets, there isn't a single "Kaggle-style" bulk DICOM download for FASH. Instead, you need to pull from clinical "atlases" that provide the specific pathological findings (fluid and nodes).

Link: [(The POCUS Atlas - Image Library)(https://casebrowser.tbportals.niaid.nih.gov/)]

How to search: Don't just search for "FASH." Search for the specific findings that make up a positive FASH exam:

- Pericardial Effusion: (Fluid around the heart—highly suggestive of TB in Lesotho).
- Pleural Effusion: (Fluid in the lung base).
- Ascites: (Free fluid in the abdomen).
- Splenic Microabscesses: (Look for "Splenic Lesions").
- Lymphadenopathy: (Look for "Abdominal Lymph Nodes").

### The "Pictorial Review" (Reference Data)
For your synthetic medical records, you’ll need to know what the reports look like. This 2012 foundational paper contains a "pictorial review" of FASH findings in high-prevalence settings like South Africa and Lesotho.

Link: FASH: A short protocol and a pictorial review (ResearchGate) https://www.researchgate.net/publication/233744858_Focused_assessment_with_sonography_for_HIV-associated_tuberculosis_FASH_A_short_protocol_and_a_pictorial_review 

Utility: Use the images in the "Results" section to understand the "Starry Sky" appearance of a TB-infected spleen.

## Sourcing the Metadata: NIH TB Portals (Ultrasound)

While the "Case Explorer" is now the "Case Browser," the NIH TB Portals does contain ultrasound findings for some of its MDR-TB cases.

Link: TB Portals Case Browser https://casebrowser.tbportals.niaid.nih.gov/

Tip: Once you log in, filter cases by "Extrapulmonary TB" and look for records that have "Ultrasound" listed under the "Imaging" tab.

# Claude config

### Save memory to repo (before committing)
rsync -av ~/.claude/projects/-Users-jalbers-git-Fastpilot-imladris/memory/ memory/

### Restore memory from repo (after clone/pull)
rsync -av memory/ ~/.claude/projects/-Users-jalbers-git-Fastpilot-imladris/memory/
