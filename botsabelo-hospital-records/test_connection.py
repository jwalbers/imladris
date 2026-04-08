import os
from dotenv import load_dotenv
from google.cloud import storage

# 1. Load the environment variables from the .env file
load_dotenv()

# 2. Access the variables using os.getenv
PROJECT_ID = os.getenv("GCP_PROJECT_ID")
BUCKET_NAME = os.getenv("GCP_BUCKET_NAME")
KEY_PATH = os.getenv("GCP_KEY_PATH")

# 3. Use them in your Service Account authentication
def connect_to_gcs():
    print(f"Connecting to project: {PROJECT_ID}...")
    
    # Passing the variables directly into the client
    client = storage.Client.from_service_account_json(
        KEY_PATH, 
        project=PROJECT_ID
    )
    
    bucket = client.bucket(BUCKET_NAME)
    return bucket

# 4. Test the connection
bucket = connect_to_gcs()
print(f"Verified access to bucket: {bucket.name}")
