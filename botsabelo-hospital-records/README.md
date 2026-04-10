# README.md

Data in this directory is maintained in Google Cloud, with the following layout.

./botsabelo_processed - DICOM files with fictional patient data applied.

./botsabelo_processed/ultrasound_cine
./botsabelo_processed/ultrasound
./botsabelo_processed/xray

./botsabelo_raw - .PNG, .GIF, and .MP4 imagery acquired from public domain databases

./botsabelo_raw/TB_Chest_Radiography_Database
./botsabelo_raw/TB_Chest_Radiography_Database/Tuberculosis
./botsabelo_raw/TB_Chest_Radiography_Database/Normal
./botsabelo_raw/ultrasound


The .env file in the parent dir has the connection info.

PROJECT_HOME - local filesystem path to the parent of this directory.
GCP_PROJECT_ID
GCP_KEY_PATH
GCP_BUCKET_NAME

We don't save the working account credentials given by GCP_KEY_PATH in the git repo, so use your own as needed.

# Testing the connection.

```
cd $PROJECT_HOME
python test_connection.py
```
## Syncing with local files

Scripts generally update / upload files directly to the GCP_BUCKET_NAME.  Grab files as needed. Can be selective, e.g. no need to synch "_raw".

gcloud storage rsync -r gs://botsabelo-hospital-records/botsabelo_processed/ botsabelo-hospital-records/botsabelo_processed/

## Push local file changes back to gcloud, with deletions.

gcloud storage rsync -r botsabelo-hospital-records/botsabelo_processed/ gs://botsabelo-hospital-records/botsabelo_processed/

To delete any gcloud objects no longer in local files:

gcloud storage rsync botsabelo-hospital-records/botsabelo_processed/ gs://botsabelo-hospital-records/botsabelo_processed/ --delete-unmatched-destination-objects



# GS Cloud info

## Storage

https://console.cloud.google.com/storage/overview;tab=overview?authuser=1&project=imladris-492521

and, specifically, our bucket

https://console.cloud.google.com/storage/browser/botsabelo-hospital-records;tab=objects?forceOnBucketsSortingFiltering=true&authuser=1&project=imladris-492521&prefix=&forceOnObjectsSortingFiltering=false


## BigQuery console for imladris
https://console.cloud.google.com/bigquery?referrer=search&authuser=1&project=imladris-492521&ws=!1m5!1m4!16m3!1m1!1simladris-492521!3e19


## imladris dashboard
https://console.cloud.google.com/home/dashboard?authuser=1&project=imladris-492521
