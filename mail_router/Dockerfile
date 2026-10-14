# O imagine, două servicii: mail-fetch (egress) și mail-classify (internal) — vezi docker-compose.yml.
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt mail_router/requirements.txt
RUN pip install --no-cache-dir -r mail_router/requirements.txt && useradd -m -u 1000 mail
COPY . mail_router/
USER mail
CMD ["python", "-m", "mail_router.fetch"]
