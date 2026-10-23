FROM python:3.12-slim
WORKDIR /srv
# torch CPU întâi: altfel pip trage roțile CUDA (~5 GB) degeaba.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Păstrat după pip pentru a reutiliza straturile mari deja construite la client.
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr tesseract-ocr-ron tesseract-ocr-eng libgl1 libglib2.0-0 libgomp1 \
    && rm -rf /var/lib/apt/lists/*
COPY . .
EXPOSE 8000
# Aceeași imagine rulează și job-urile ingest / model-fetch (cu alt command în compose).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
