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
RUN pip install --no-cache-dir pynetdicom pydicom requests

COPY dicom_client.py .
COPY acquisition_loop.py .

ENV ORTHANC_URL=http://orthanc-modality:8042
ENV MWL_HOST=openmrs
ENV MWL_PORT=4242
ENV MODALITY_AET=MODALITY_SIM
ENV CLOUD_PACS_AE=CLOUD_PACS
ENV POLL_INTERVAL_MINUTES=5

CMD ["python", "acquisition_loop.py"]
