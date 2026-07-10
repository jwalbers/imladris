# Imladris modality sidecar
# Services: order_poller, fhir_mwl_poller, acquisition_loop,
#           scp_relay (DICOM SCP), modality_console_web, hl7_bridge

FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv .venv
ENV PATH="/app/.venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY dicom_client.py .
COPY acquisition_loop.py .
COPY fhir_mwl_poller.py .
COPY mwl_manager.py .
COPY order_poller.py .
COPY scp_relay.py .
COPY hl7_bridge.py .
COPY modality_console_web.py .
COPY main.py .
COPY favicon.ico .

# Modality AE titles
ENV MODALITY_AET=IML_CR_01
ENV CR_AET=IML_CR_01
ENV US_AET=IML_US_01
ENV CT_AET=IML_CT_01
ENV INSTITUTION="Bophelong MDR-TB Hospital"
ENV POLL_INTERVAL_MINUTES=5
ENV WL_FOLDER=/worklist
ENV HOSPITAL_RECORDS=/hospital-records

# AdvaPACS gateway
ENV ADVAPACS_GW_HOST=host.docker.internal
ENV ADVAPACS_GW_PORT=11112
ENV ADVAPACS_GW_AE=ADVAPACS_GW_01

# Qure.ai simulator
ENV QURE_HOST=imladris-qure-sim
ENV QURE_PORT=5252
ENV QURE_AE=QUREAI
ENV ENABLE_QURE=true

# SCP relay (receives SC from qure-sim, forwards to AdvaPACS)
ENV SCP_AE=IML_CR_01
ENV SCP_PORT=4242

# Order poller (OpenMRS REST → AdvaPACS ORM^O01)
ENV OPENMRS_URL=http://openmrs:8080/openmrs
ENV OPENMRS_USER=admin
ENV OPENMRS_PASSWORD=Admin123
ENV ORDER_POLL_SEC=30
ENV ORDER_STATE_FILE=/data/order_poller_state.json
ENV FHIR_BASE_URL=https://usa1.api.integration.advapacs.com/fhir/R5

# PACS change watcher (ORU^R01 back to OpenMRS)
ENV OPENMRS_HL7_HOST=openmrs
ENV OPENMRS_HL7_PORT=8066
ENV PACS_URL=http://orthanc-pacs:8042
ENV PACS_USER=admin
ENV PACS_PASSWORD=admin
ENV CHANGE_POLL_SEC=15

# Modality console web UI
ENV CONSOLE_PORT=5001

CMD ["python", "main.py"]
