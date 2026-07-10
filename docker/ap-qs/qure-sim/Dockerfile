FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY qure_sim.py .

# DICOM SCP port
EXPOSE 5252

CMD ["python", "qure_sim.py"]
