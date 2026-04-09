# Imladris modality sidecar
# Runs the acquisition loop daemon (no GUI).
# The modality_console.py GUI runs natively on the rad-tech Windows 11 VM.

FROM python:3.11-slim

WORKDIR /app

# System deps for pynetdicom
RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment and activate it for all subsequent steps.
# ENV PATH persists across RUN / CMD / ENTRYPOINT — equivalent to
# "source .venv/bin/activate" for the lifetime of the container.
RUN python -m venv .venv
ENV PATH="/app/.venv/bin:$PATH"

COPY requirements.txt .
# Install headless deps only (exclude wxPython — not needed in container)
RUN pip install --no-cache-dir pynetdicom pydicom requests hl7

COPY dicom_client.py .
COPY acquisition_loop.py .
COPY mwl_manager.py .
COPY hl7_bridge.py .
COPY main.py .

# Acquisition loop
ENV ORTHANC_URL=http://orthanc-modality:8042
ENV MWL_HOST=openmrs
ENV MWL_PORT=4242
ENV MODALITY_AET=MODALITY_SIM
ENV CLOUD_PACS_AE=CLOUD_PACS
ENV POLL_INTERVAL_MINUTES=5

# HL7 bridge
ENV MLLP_PORT=2575
ENV OPENMRS_HL7_HOST=openmrs
ENV OPENMRS_HL7_PORT=8066
ENV PACS_URL=http://orthanc-pacs:8042
ENV PACS_USER=admin
ENV PACS_PASSWORD=admin
ENV WL_FOLDER=/worklist
ENV CHANGE_POLL_SEC=15

CMD ["python", "main.py"]
