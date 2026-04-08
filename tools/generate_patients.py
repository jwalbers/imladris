import os
from dotenv import load_dotenv
import pandas as pd
import random

# 1. Load the environment variables from the .env file
load_dotenv()

# 2. Set configuration
GCP_PROJECT_ID = os.getenv("GCP_PROJECT_ID")
GCP_BUCKET_NAME = os.getenv("GCP_BUCKET_NAME")
GCP_KEY_PATH = os.getenv("GCP_KEY_PATH")

PROJECT_HOME = os.getenv("PROJECT_HOME")
LOCAL_TMP_DIR = os.getenv("LOCAL_TMP_DIR")
BOTSABELO_CENSUS_PATH = os.getenv("CENSUS_CSV_PATH")
print(f"generating to {BOTSABELO_CENSUS_PATH}")

# Basotho Names for realism
first_names = ["Lethabo", "Thabo", "Mpho", "Rethabile", "Nthabiseng", "Lerato", "Kabelo", "Tsepang", "Mamello", "Tumelo"]
last_names = ["Mokoena", "Letseka", "Molapo", "Sebatane", "Ramohapi", "Lekhanya", "Khoza", "Tau"]

districts = ["Maseru", "Leribe", "Mafeteng", "Quthing", "Thaba-Tseka", "Mokhotlong"]
fash_outcomes = [
    "Normal - No free fluid or lymphadenopathy",
    "Positive - Pericardial Effusion (Fluid around heart)",
    "Positive - Pleural Effusion (Fluid in lung base)",
    "Positive - Splenic Microabscesses ('Starry Sky' appearance)",
    "Positive - Abdominal Lymphadenopathy (Enlarged nodes)",
    "Inconclusive - Poor window"
]

data = []
for i in range(1, 51):
    patient_id = f"BHTB-2026-{i:03d}"
    hiv_status = random.choices(["Positive", "Negative"], weights=[75, 25])[0]
    
    # Clinical Logic: FASH is usually performed on HIV+ patients
    if hiv_status == "Positive":
        # High probability of finding extra-pulmonary fluid/nodes
        fash_finding = random.choices(fash_outcomes, weights=[20, 25, 25, 15, 10, 5])[0]
        weight_loss = random.choice(["Severe", "Moderate"])
    else:
        # HIV- patients rarely have these ultrasound findings
        fash_finding = "Normal - No free fluid or lymphadenopathy"
        weight_loss = random.choice(["Moderate", "None"])

    data.append({
        "Patient_ID": patient_id,
        "Name": f"{random.choice(first_names)} {random.choice(last_names)}",
        "Age": random.randint(19, 62),
        "Gender": random.choice(["M", "F"]),
        "District": random.choice(districts),
        "HIV_Status": hiv_status,
        "CD4_Count": random.randint(40, 350) if hiv_status == "Positive" else "N/A",
        "MDR_Status": "Confirmed (Rifampicin Resistant)",
        "Weight_Loss": weight_loss,
        "FASH_Ultrasound_Finding": fash_finding,
        # Reference paths for your GCS bucket
        "Xray_GCP_Path": f"gs://{GCP_BUCKET_NAME}/botsabelo_processed/{patient_id}_Xray.dcm",
        "FASH_Clip_GCP_Path": f"gs://{GCP_BUCKET_NAME}/botsabelo_raw/ultrasound/{fash_finding.split(' - ')[0].lower()}.mp4"
    })

# Create DataFrame and Save
df = pd.DataFrame(data)
df.to_csv(BOTSABELO_CENSUS_PATH, index=False)

print(f"Successfully generated {BOTSABELO_CENSUS_PATH} with 50 clinical records.")
