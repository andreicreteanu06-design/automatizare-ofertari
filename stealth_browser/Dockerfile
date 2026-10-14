FROM python:3.12-slim
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \
    camoufox fetch && \
    playwright install-deps firefox && \
    rm -rf /var/lib/apt/lists/*
COPY . /srv/stealth_browser
EXPOSE 8000
CMD ["uvicorn", "stealth_browser.app:app", "--host", "0.0.0.0", "--port", "8000"]
