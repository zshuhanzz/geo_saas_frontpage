FROM python:3.11-slim

WORKDIR /app

# --- Build context is the repository root (see cloudbuild.yaml). ---

# 1. Shared geo_common package.
COPY geo_common/ /geo_common/
RUN pip install --no-cache-dir -e /geo_common

# 2. Module-specific Python deps.
COPY geo_analyzer/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# 3. Module source. Analyzer ships as a Cloud Run Job; main.py lives at module root
#    (not under src/), alongside src/ subpackage + scripts/ + tests/.
COPY geo_analyzer/ /app/

# Run the analyzer (Cloud Run Job)
CMD ["python", "main.py"]
