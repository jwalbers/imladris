FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY dx.py minxray_sim.py ./

ENV LIBRARY_DIR=/library OUTPUT_DIR=/output PYTHONUNBUFFERED=1
ENTRYPOINT ["python", "/app/minxray_sim.py"]
CMD ["worklist"]
