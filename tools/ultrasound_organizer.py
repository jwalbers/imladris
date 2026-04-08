import os
import shutil

# Path where your browser downloaded the clips
DOWNLOADS_DIR = "~/Downloads/fash_raw"
# Organized output for GCS
ORGANIZED_DIR = "./botsabelo-hospital-records/botsabelo_raw/ultrasound"

# Mapping logic for your Census CSV categories
categories = {
    "normal": ["normal_heart", "normal_spleen", "normal_liver"],
    "positive_pericardial": ["effusion_cardiac", "pericardial"],
    "positive_pleural": ["pleural_effusion", "spine_sign"],
    "positive_spleen": ["starry_sky", "splenic_abscess"],
    "positive_nodes": ["lymph_nodes", "adenopathy"]
}

def organize_clips():
    if not os.path.exists(ORGANIZED_DIR):
        os.makedirs(ORGANIZED_DIR)

    for filename in os.listdir(DOWNLOADS_DIR):
        # Clean up filenames for GCS compatibility
        clean_name = filename.lower().replace(" ", "_")
        
        # Check which clinical category it belongs to
        for cat, keywords in categories.items():
            if any(key in clean_name for key in keywords):
                cat_path = os.path.join(ORGANIZED_DIR, cat)
                if not os.path.exists(cat_path):
                    os.makedirs(cat_path)
                
                shutil.copy(os.path.join(DOWNLOADS_DIR, filename), os.path.join(cat_path, clean_name))
                print(f"Organized: {clean_name} into {cat}")

if __name__ == "__main__":
    organize_clips()
    
