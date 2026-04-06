"""
acquisition_loop.py — Headless acquisition daemon (runs inside container).

Polls the OpenMRS MWL on a fixed interval and auto-sends matched studies
to the Cloud PACS via Orthanc.  The GUI (modality_console.py) provides
the manual/interactive version of the same workflow.
"""

import os
import time
import logging
from datetime import datetime

import dicom_client as dc

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("acquisition_loop")

POLL_MINUTES = int(os.getenv("POLL_INTERVAL_MINUTES", "5"))


def run_cycle():
    log.info("Starting acquisition cycle …")
    try:
        entries = dc.query_mwl()
        log.info(f"MWL returned {len(entries)} scheduled exam(s).")
    except Exception as e:
        log.error(f"MWL query failed: {e}")
        return

    for entry in entries:
        log.info(
            f"Processing: {entry.patient_name} ({entry.patient_id}) "
            f"— {entry.study_desc}  Accession: {entry.accession}"
        )
        try:
            uid = dc.match_tb_study(entry.patient_id, entry.modality)
            if not uid:
                log.warning(
                    f"No matching study in Orthanc for "
                    f"PatientID={entry.patient_id} Modality={entry.modality} — skipping."
                )
                continue
            dc.send_study_to_pacs(uid)
            log.info(f"✓  Sent study {uid} for {entry.patient_name} to {dc.CLOUD_PACS_AE}.")
        except Exception as e:
            log.error(f"Failed to process {entry.accession}: {e}")


if __name__ == "__main__":
    log.info(
        f"Imladris acquisition loop starting  "
        f"(poll every {POLL_MINUTES} min, "
        f"MWL={dc.MWL_HOST}:{dc.MWL_PORT}, "
        f"Orthanc={dc.ORTHANC_URL}, "
        f"PACS AE={dc.CLOUD_PACS_AE})"
    )
    while True:
        run_cycle()
        log.info(f"Sleeping {POLL_MINUTES} min until next cycle …")
        time.sleep(POLL_MINUTES * 60)
