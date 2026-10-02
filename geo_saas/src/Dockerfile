FROM python:3.12-slim

WORKDIR /app

# Install gcloud CLI for triggering jobs (optional for SaaS API but good for parity)
RUN apt-get update && apt-get install -y curl gnupg && \
    echo "deb [signed-by=/usr/share/keyrings/cloud.google.gpg] https://packages.cloud.google.com/apt cloud-sdk main" | tee -a /etc/apt/sources.list.d/google-cloud-sdk.list && \
    curl https://packages.cloud.google.com/apt/doc/apt-key.gpg | gpg --dearmor -o /usr/share/keyrings/cloud.google.gpg && \
    apt-get update && apt-get install -y google-cloud-cli && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# --- Build context is the repository root (see cloudbuild.yaml). ---

# 1. Shared geo_common package (installed first — rarely changes, leverages Docker layer cache).
COPY geo_common/ /geo_common/
RUN pip install --no-cache-dir -e /geo_common

# 2. Module-specific Python deps.
COPY geo_saas/src/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# 3. Module source.
COPY geo_saas/src/ /app/

EXPOSE 8080

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
