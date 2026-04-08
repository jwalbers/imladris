#!/bin/bash

# Directory for organized storage
DEST="/Users/jalbers/git/Fastpilot/imladris/botsabelo-hospital-records/botsabelo_raw/ultrasound"
mkdir -p "$DEST"

echo "--- Starting Botsabelo FASH Clip Download ---"

# --- CATEGORY: NORMAL CONTROLS (FASH NEGATIVE) ---
# Use these for patients with no extra-pulmonary TB findings.
curl -L -o "$DEST/normal_heart_01.gif" "https://images.squarespace-cdn.com/content/v1/58118909e3df282037abfad7/1603202538120-87UL3B1IZ4E9YS6VDRMV/image-asset.gif/?format=750w"
curl -L -o "$DEST/normal_spleen_01.gif" "https://images.squarespace-cdn.com/content/v1/58118909e3df282037abfad7/1507764829676-NUGHFB858VEPHHW5EY9S/bowra+neg+fast+luq.gif/?format=750w"
curl -L -o "$DEST/normal_liver_01.gif" "https://images.squarespace-cdn.com/content/v1/58118909e3df282037abfad7/1507764829676-NUGHFB858VEPHHW5EY9S/bowra+neg+fast+luq.gif/?format=750w"
curl -L -o "$DEST/normal_liver_02.gif" "https://images.squarespace-cdn.com/content/v1/58118909e3df282037abfad7/1533340837831-96B9SO0G3BZYRAU7H8F6/subxi+normal+2.gif/?format=1000w"

# --- CATEGORY: POSITIVE PERICARDIAL (HEART) ---
# High priority for HIV+ MDR-TB triage.
#
curl -L -o "$DEST/pos_pericardial_large_01.gif" "https://images.squarespace-cdn.com/content/v1/58118909e3df282037abfad7/1598022615747-O8B4ZRJZSJYJYA12KZUZ/image-asset.gif/?format=750w"
#
curl -L -o "$DEST/pos_pericardial_small_02.gif" "https://images.squarespace-cdn.com/content/v1/58118909e3df282037abfad7/1625844429315-LKZXZ7W1TBK4HQVL3WWI/image-asset.gif/?format=750w"
# https://www.thepocusatlas.com/pericardial-disease/2017/11/15/cardiac-tamponade 
curl -L -o "$DEST/pos_pericardial_small_03.gif" "https://images.squarespace-cdn.com/content/v1/58118909e3df282037abfad7/1510783742149-K6F7JUMUZ1RU1KP9PWTN/alerhand+tamponade.gif?format=1500w"

# --- CATEGORY: POSITIVE PLEURAL (LUNG BASE) ---
# Common in advanced MDR-TB cases in Lesotho.
# https://www.thepocusatlas.com/lung/ktezkgf3z4ivtelvcq8nks6ecrmfiu
curl -L -o "$DEST/pos_pleural_effusion_01.gif" "https://images.squarespace-cdn.com/content/v1/58118909e3df282037abfad7/1533325032109-P5UMVA5XOPJA3EM9BTAG/pleural+effusion.gif/?format=750w"
# https://www.thepocusatlas.com/lung/242oedq3kksddb0g52chwfexa7atj9
curl -L -o "$DEST/pos_pleural_spine_sign_02.gif" "https://images.squarespace-cdn.com/content/v1/58118909e3df282037abfad7/1567929251076-8KWEM7T7I8ZD7W9R7IK5/pleural-space.gif?format=1000w"

# --- CATEGORY: POSITIVE ABDOMINAL (SPLEEN/NODES) ---
# Simulates the 'starry sky' or lymphadenopathy findings.
# https://www.thepocusatlas.com/bowel/splenic-abscess
curl -L -o "$DEST/pos_spleen_microabscess_01.gif" "https://images.squarespace-cdn.com/content/v1/58118909e3df282037abfad7/1607602190955-WCMI53O4AAX49MXEP4R6/image-asset.gif/?format=1000w"
# https://www.thepocusatlas.com/softtissuemsk/supraclavicular-lymphadenopathy
curl -L -o "$DEST/pos_abdominal_nodes_01.gif" "https://images.squarespace-cdn.com/content/v1/58118909e3df282037abfad7/1616226957677-2QDSEII7IFXRUHKRTV03/image-asset.gif?format=750w"

echo "--- Download Complete. Files located in $DEST ---"

