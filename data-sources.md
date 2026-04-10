# Xray Images

https://console.cloud.google.com/storage/browser/botsabelo-hospital-records/botsabelo_raw/TB_Chest_Radiography_Database?pageState=(%22StorageObjectListTable%22:(%22f%22:%22%255B%255D%22))&authuser=1&project=imladris-492521

gs://botsabelo-hospital-records/botsabelo_raw/TB_Chest_Radiography_Database


# Ultrasound Clips

Save to gs://botsabelo-hospital-records/botsabelo_raw/ultrasound

Need to create a reference set of ultrasound images like we did for CR xrays.  After a lot of digging, it looks like many of the images originally available with the springer-verlag paper on FASH are no longer online.


## A. The "Normal" Controls (Essential for Triage Simulation)
Go to The POCUS Atlas https://www.thepocusatlas.com/ and grab these:

### Normal Cardiac (PLAX):
Download 5 different clips of a clear, fluid-free heart. These will represent your "FASH Negative" HIV+ patients.

Normal PLAX
https://images.squarespace-cdn.com/content/v1/58118909e3df282037abfad7/1603202538120-87UL3B1IZ4E9YS6VDRMV/image-asset.gif/?format=750w

Paraesophageal Abscess
https://images.squarespace-cdn.com/content/v1/58118909e3df282037abfad7/1638667863536-5209MN76A9RJXV59CGKR/image-asset.gif/?format=1000w

Ventricular Fibrillation
https://images.squarespace-cdn.com/content/v1/58118909e3df282037abfad7/1516664212670-22U2YKBGF7JTYVZO0PFH/ezgif.com-optimize+%282%29.gif/?format=1000w

Takotsubo Cardiomyopathy in a Patient with Chest Pain
https://images.squarespace-cdn.com/content/v1/58118909e3df282037abfad7/1569011291998-5X46M3UO8MZ2NZWNS488/Takotsubo.gif/?format=750w


### Normal Liver/Kidney (RUQ):
Download 5 clips showing a clear Morison’s Pouch (no fluid between liver and kidney).

### Normal Spleen:
Download 5 clips of a solid, uniform spleen (no "starry sky" microabscesses).

## B. Lung/Pleural Fluid (The "Spine Sign")
Go to Core Ultrasound: https://www.google.com/search?q=https://www.coreultrasound.com/tag/pleural-effusion/

## Pleural Effusion:
Download 10 clips. Look for the "Anechoic" (black) areas above the diaphragm. In the context of Lesotho, this is a major indicator for extra-pulmonary TB.

## C. Abdominal Nodes & Spleen Variety
Go to Radiopaedia: https://www.google.com/search?q=https://radiopaedia.org/articles/abdominal-lymphadenopathy-1

### Mesenteric Lymphadenopathy:
Search for "Ultrasound Lymph Nodes." Download 12 clips/images. These represent the "Abdominal Lymphadenopathy" finding in your census.

### Splenic Microabscesses:
Search for "Candidiasis Spleen" or "Splenic Infarct." While the etiology differs, the ultrasound morphology is a perfect visual match for the TB microabscesses seen at Botsabelo.


# Focused assessment with sonography for HIV-associated tuberculosis (FASH): a short protocol and a pictorial review

**ARGH all these clips seem to be no longer available**

## Video 1: Pericardial Effusion (Positive)

Finding: An anechoic (black) rim surrounding the heart.

Condition: Highly suggestive of pericardial TB in high-prevalence settings.

Detail: Note the fibrin streaks or "fibrinous material" floating within the fluid, which is a classic sonographic sign of tuberculous serositis.

Additional file 1: 1648916589731330_add1.mpeg, 1640K
http://www.criticalultrasoundjournal.com/imedia/1945178084853762/supp1.mpeg


## Video 2: Pericardial Tamponade (Positive / Critical)

Finding: Diastolic collapse of the right ventricle (the ventricle appears to "caved in" when the heart should be filling).

Condition: "Pre-tamponade" or active tamponade, requiring urgent clinical intervention.

Additional file 2: 1648916589731330_add2.mpeg, 1472K
http://www.criticalultrasoundjournal.com/imedia/7211682648537622/supp2.mpeg

## Video 3: Enlarged Abdominal Lymph Nodes (Positive)

Finding: Multiple hypoechoic (dark), rounded structures near the liver or aorta.

Condition: Abdominal TB. The protocol specifically looks for nodes >1.5 cm in diameter.

Additional file 3: 1648916589731330_add3.mpeg, 1896K
http://www.criticalultrasoundjournal.com/imedia/1986168424853762/supp3.mpeg


## Video 4: Pleural Effusion (Positive)

Finding: Fluid (anechoic space) seen in the pleural cavity, often above the diaphragm or spleen.

Condition: Tuberculous pleurisy. Like the pericardial clip, these often show floating fibrin strands.

Additional file 4: 1648916589731330_add4.mpeg, 1748K
http://www.criticalultrasoundjournal.com/imedia/1320361706853762/supp4.mpeg

## Video 5: Splenic Microabscesses (Positive)

Finding: Multiple small, hypoechoic (dark) nodules scattered throughout the spleen, often referred to as a "starry sky" or "reticulo-nodular" pattern.

Condition: Disseminated TB.

Additional file 5: 1648916589731330_add5.mpeg, 1640K
http://www.criticalultrasoundjournal.com/imedia/1975159506853762/supp5.mpeg

## Additional Files (6-8): Ascites and Focal Liver Lesions (Positive)

Finding: Free fluid in the abdominal cavity (ascites) or dark spots within the liver parenchyma.

Condition: Abdominal or disseminated TB.

Additional file 6: 1648916589731330_add6.mpeg, 1750K
http://www.criticalultrasoundjournal.com/imedia/7212170108537623/supp6.mpeg
Additional file 7: 1648916589731330_add7.mpeg, 1888K
http://www.criticalultrasoundjournal.com/imedia/6749078158537624/supp7.mpeg
Additional file 8: 1648916589731330_add8.mpeg, 1792K
http://www.criticalultrasoundjournal.com/imedia/3809225468537624/supp8.mpeg


Gemini said
To keep your Botsabelo MDR-TB Hospital dataset consistent and compatible with your trial_run.py logic, I recommend renaming those 8 original MPEG files using the Condition-Finding-Index convention.

This naming scheme ensures that your Python script can use simple string matching (e.g., if "pos_pericardial" in filename) to select the correct clinical clip for each patient's row in the CSV.


Recommended Filenames for the 8 FASH Clips
Original Clip	Pathological Finding	Proposed New Filename
Video 1	Pericardial Effusion with Fibrin	pos_pericardial_fibrin_01.mp4
Video 2	Right Ventricle Diastolic Collapse	pos_pericardial_tamponade_02.mp4
Video 3	Enlarged Abdominal Lymph Nodes	pos_abdominal_nodes_01.mp4
Video 4	Pleural Effusion with Fibrin Strands	pos_pleural_effusion_01.mp4
Video 5	Splenic Microabscesses (Starry Sky)	pos_spleen_microabscess_01.mp4
Video 6	Ascites (Free Abdominal Fluid)	pos_abdominal_ascites_01.mp4
Video 7	Focal Liver Lesion	pos_liver_lesion_01.mp4
Video 8	Hepatomegaly / Congested IVC	pos_abdominal_ivc_01.mp4


cd botsabelo-hospital-records/ultrasound
curl -L -O http://www.criticalultrasoundjournal.com/imedia/1945178084853762/supp1.mpeg
curl -L -O http://www.criticalultrasoundjournal.com/imedia/7211682648537622/supp2.mpeg
curl -L -O http://www.criticalultrasoundjournal.com/imedia/1986168424853762/supp3.mpeg
curl -L -O http://www.criticalultrasoundjournal.com/imedia/1320361706853762/supp4.mpeg
curl -L -O http://www.criticalultrasoundjournal.com/imedia/1975159506853762/supp5.mpeg
curl -L -O http://www.criticalultrasoundjournal.com/imedia/7212170108537623/supp6.mpeg
curl -L -O http://www.criticalultrasoundjournal.com/imedia/6749078158537624/supp7.mpeg
curl -L -O http://www.criticalultrasoundjournal.com/imedia/3809225468537624/supp8.mpeg

**these are no longer available**


## The Mapping Logic

To make this realistic for Botsabelo Hospital, we will follow this clinical "logic gate":

HIV Positive Patient: High probability of being assigned a Symptomatic X-ray AND a Positive FASH Ultrasound (e.g., pericardial effusion).

HIV Negative Patient: High probability of being assigned a Symptomatic X-ray (classic cavitary TB) but a Normal Ultrasound.

Triage/Control Patient: Assigned a Normal X-ray and Normal Ultrasound.


## Papers

Focused assessment with sonography for HIV-associated tuberculosis (FASH): a short protocol and a pictorial review
2012, Critical Ultrasound Journal https://doi.org/10.1186/2036-7902-4-21

Diagnostic Utility and Impact on Clinical Decision Making of  Focused Assessment With Sonography for HIV-Associated...  by Mayamiko Chimombo | 2020 | 12 views
Abdominal ultrasound findings of disseminated tuberculosis in  AIDS  by Antonio Martínez-nog... | 1997 | 19 views
Remote Training and Oversight of Sonography for Human  Immunodeficiency Virus-Associated Tuberculosis in Malawi  by levison longwe | 2018 | 4 views
Ultrasound findings in cases of extrapulmonary TB in patients with  HIV infection in Jeddah, Saudi Arabia  by Claudia Wallrauch | 2014 | 1 view
