FROM python:3.12-slim
WORKDIR /srv
# torch CPU întâi: altfel pip trage roțile CUDA (~5 GB) degeaba.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
# Aceeași imagine rulează și job-urile ingest / model-fetch (cu alt command în compose).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
