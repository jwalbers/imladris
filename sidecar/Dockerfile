# Imladris modality sidecar
# Runs the order poller, acquisition loop, PACS change watcher,
# and modality console web UI (port 5001).

FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv .venv
ENV PATH="/app/.venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir pynetdicom pydicom requests flask

COPY dicom_client.py .
COPY acquisition_loop.py .
COPY mwl_manager.py .
COPY order_poller.py .
COPY hl7_bridge.py .
COPY modality_console_web.py .
COPY main.py .

# Acquisition loop
ENV ORTHANC_URL=http://orthanc-modality:8042
ENV MWL_HOST=orthanc-modality
ENV MWL_PORT=4242
ENV MODALITY_AET=MODALITY_SIM
ENV CLOUD_PACS_AE=CLOUD_PACS
ENV POLL_INTERVAL_MINUTES=5

# Order poller (OpenMRS REST → MWL)
ENV OPENMRS_URL=http://openmrs:8080/openmrs
ENV OPENMRS_USER=admin
ENV OPENMRS_PASSWORD=Admin123
ENV ORDER_POLL_SEC=30
ENV ORDER_STATE_FILE=/data/order_poller_state.json

# PACS change watcher (ORU^R01 back to OpenMRS)
ENV OPENMRS_HL7_HOST=openmrs
ENV OPENMRS_HL7_PORT=8066
ENV PACS_URL=http://orthanc-pacs:8042
ENV PACS_USER=admin
ENV PACS_PASSWORD=admin
ENV WL_FOLDER=/worklist
ENV CHANGE_POLL_SEC=15

# Modality console web UI
ENV CONSOLE_PORT=5001
ENV XRAY_DIR=/hospital-records/xray
ENV US_DIR=/hospital-records/ultrasound_cine

CMD ["python", "main.py"]
