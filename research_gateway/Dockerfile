FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt research_gateway/requirements.txt
RUN pip install --no-cache-dir -r research_gateway/requirements.txt && useradd -m -u 1000 gw
COPY . research_gateway/
USER gw
EXPOSE 8000
CMD ["uvicorn", "research_gateway.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
