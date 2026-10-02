FROM python:3.11-slim

WORKDIR /app

# --- Build context is the repository root (see cloudbuild.yaml). ---

# 1. Shared geo_common package.
COPY geo_common/ /geo_common/
RUN pip install --no-cache-dir -e /geo_common

# 2. Module-specific Python deps.
COPY geo_collector/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# 3. Module source. Collector has no top-level main.py — each Cloud Run
#    service gets its own uvicorn entrypoint via Terraform-injected command.
COPY geo_collector/src/ /app/src/

# NOTE: No default CMD.
# This image serves three Cloud Run services (cloro_callback, cloro_dispatcher,
# result_ingestor) — the actual uvicorn entrypoint is injected at deploy time
# by Terraform (see geo_collector/terraform/main.tf, each service's
# `containers.command`/`args`). If you ever need to `docker run` locally, pass:
#   docker run geo-collector:xxx \
#     uvicorn src.cloro_callback:app --host 0.0.0.0 --port 8080
# (substitute the module you want: cloro_callback / cloro_dispatcher / result_ingestor)
