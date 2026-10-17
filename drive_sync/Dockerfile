FROM node:22-alpine
RUN apk add --no-cache python3 py3-yaml && npm install --global @googleworkspace/cli@0.22.5
WORKDIR /srv
COPY drive_sync/sync.py .
COPY research_gateway/egress_guard.py research_gateway/egress_guard.py
ENV GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE=/secrets/drive.json
CMD ["python3", "sync.py"]
