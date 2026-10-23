FROM python:3.12-slim
WORKDIR /srv
# PyTorch și TorchVision trebuie instalate împreună din indexul CPU.
# O roată TorchVision CUDA lângă torch CPU blochează importul FlagEmbedding.
COPY constraints-cpu.txt .
RUN pip install --no-cache-dir -c constraints-cpu.txt torch torchvision \
    --index-url https://download.pytorch.org/whl/cpu
COPY requirements.txt .
RUN pip install --no-cache-dir -c constraints-cpu.txt -r requirements.txt
# Păstrat după pip pentru a reutiliza straturile mari deja construite la client.
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr tesseract-ocr-ron tesseract-ocr-eng libgl1 libglib2.0-0 libgomp1 \
    && rm -rf /var/lib/apt/lists/*
# Oprește build-ul înainte de instalare dacă dependențele ML nu se pot încărca.
RUN pip check && HF_HUB_OFFLINE=1 python -c \
    "import torch, torchvision; from FlagEmbedding import BGEM3FlagModel; from docling.document_converter import DocumentConverter; assert torch.version.cuda is None; torchvision.ops.nms(torch.tensor([[0., 0., 1., 1.]]), torch.tensor([1.]), 0.5); print('Importuri ML și operații TorchVision CPU: OK')"
COPY . .
EXPOSE 8000
# Aceeași imagine rulează și job-urile ingest / model-fetch (cu alt command în compose).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
