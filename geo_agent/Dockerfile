FROM python:3.12-slim

WORKDIR /app

# --- Build context is the repository root (see cloudbuild.yaml). ---

# 1. Shared geo_common package.
COPY geo_common/ /geo_common/
RUN pip install --no-cache-dir -e /geo_common

# 2. Module-specific Python deps.
COPY geo_agent/src/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# 3. Module source.
COPY geo_agent/src/ /app/

EXPOSE 8080

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
