import os
import zipfile
from dotenv import load_dotenv
from kaggle.api.kaggle_api_extended import KaggleApi
from google.cloud import storage


# 1. Load the environment variables from the .env file
load_dotenv()

# 2. Access the variables using os.getenv
PROJECT_ID = os.getenv("GCP_PROJECT_ID")
BUCKET_NAME = os.getenv("GCP_BUCKET_NAME")
KEY_PATH = os.getenv("GCP_KEY_PATH")
LOCAL_TMP_DIR = os.getenv("LOCAL_TMP_DIR")

# 2. Authenticate Kagglen using kaggle.json in KAGGLE_CONFIG_DIR
# Uses the KAGGLE_CONFIG_DIR either set in outer env or set by load_dotenv()
api = KaggleApi()
api.authenticate()

# 3. Download Kaggle TB dataset.
dataset = "tawsifurrahman/tuberculosis-tb-chest-xray-dataset"
print(f"--- Downloading {dataset} to {LOCAL_TMP_DIR} ---")
if not os.path.exists(LOCAL_TMP_DIR):
    os.makedirs(LOCAL_TMP_DIR)
api.dataset_download_files(dataset, path=LOCAL_TMP_DIR, unzip=True)

# 4. Initialize GCS Client
# (This uses your default gcloud credentials)
# Passing the variables directly into the client
storage_client = storage.Client.from_service_account_json(
    KEY_PATH, 
    project=PROJECT_ID
    )
bucket = storage_client.bucket(BUCKET_NAME)

def upload_folder(source_dir):
    for root, dirs, files in os.walk(source_dir):
        for file in files:
            local_path = os.path.join(root, file)
            # Create a clean path for the bucket
            remote_path = os.path.relpath(local_path, source_dir)
            blob = bucket.blob(f"botsabelo_raw/{remote_path}")
            blob.upload_from_filename(local_path)
            print(f"Uploaded: {blob.name}")

print(f"--- Uploading to gs://{BUCKET_NAME}/botsabelo_raw/ ---")
upload_folder(LOCAL_TMP_DIR)
print("\n--- Transfer to {PROJECT_ID} {BUCKET_NAME} Complete! ---")

