# =============================================================================
# Phase 6 — Suggestions 系统 Cloud Scheduler + Cloud Run Jobs (Terraform only)
# =============================================================================
#
# DO NOT `terraform apply` this file in CI. Written as standalone .tf so
# the user can review + apply manually.
#
# Creates:
#   - Cloud Run Job `geo-analyzer-llm-batch-discovery` — invokes
#     `python -m src.jobs.llm_batch_discovery --window-hours 24`
#   - Cloud Run Job `geo-analyzer-ngram-discovery`     — invokes
#     `python -m src.jobs.ngram_discovery --window-hours 24`
#     (Requires --client-id; the scheduler-level iteration is left as a future
#      enhancement — for now this is runnable on demand.)
#   - Cloud Scheduler job triggering the LLM Batch job daily at 03:00 UTC
#     via the Cloud Run Jobs Execution API.
#
# Both jobs reuse the existing analyzer image; the entry point switch is done
# with `command` + `args` overriding the Dockerfile CMD.
#
# Auth: Cloud Scheduler authenticates to Cloud Run Jobs with an OIDC token
# minted by a dedicated service account (`suggestions_scheduler_sa`) that has
# `roles/run.admin` scoped to these two jobs.

# --- Service account for the scheduler -------------------------------------

resource "google_service_account" "suggestions_scheduler_sa" {
  account_id   = "geo-suggestions-sched"
  display_name = "Cloud Scheduler SA for GEO Suggestions jobs"
  description  = "Grants Cloud Scheduler permission to invoke the LLM batch discovery Cloud Run Job."
}

# --- Cloud Run Job: LLM Batch Discovery ------------------------------------

resource "google_cloud_run_v2_job" "geo_llm_batch_discovery" {
  name     = "geo-analyzer-llm-batch-discovery"
  location = var.region

  template {
    template {
      containers {
        image = var.image_tag
        # Override the Dockerfile entry to run the batch-discovery job module.
        command = ["python", "-m", "src.jobs.llm_batch_discovery"]
        args    = ["--window-hours", "24"]

        env {
          name  = "DB_INSTANCE_CONNECTION_NAME"
          value = var.db_instance_connection_name
        }
        env {
          name  = "CLOUD_SQL_CONNECTION_NAME"
          value = var.db_instance_connection_name
        }
        env {
          name  = "DB_PASSWORD"
          value = var.db_password
        }
        env {
          name  = "DB_PASS"
          value = var.db_password
        }
        env {
          name  = "DB_NAME"
          value = var.db_name
        }
        env {
          name  = "DB_USER"
          value = var.db_user
        }
        env {
          name  = "GCP_PROJECT_ID"
          value = var.project_id
        }
        env {
          name  = "GCP_REGION"
          value = var.region
        }
        env {
          name  = "GCP_REGION_GLOBAL"
          value = "global"
        }
        env {
          name  = "IS_CLOUD_RUN"
          value = "true"
        }

        resources {
          limits = {
            cpu    = "1"
            memory = "2Gi"
          }
        }

        volume_mounts {
          name       = "cloudsql"
          mount_path = "/cloudsql"
        }
      }

      volumes {
        name = "cloudsql"
        cloud_sql_instance {
          instances = [var.db_instance_connection_name]
        }
      }

      timeout     = "3600s"
      max_retries = 1
    }
  }
}

# --- Cloud Run Job: N-gram Discovery (on-demand) ---------------------------

resource "google_cloud_run_v2_job" "geo_ngram_discovery" {
  name     = "geo-analyzer-ngram-discovery"
  location = var.region

  template {
    template {
      containers {
        image   = var.image_tag
        command = ["python", "-m", "src.jobs.ngram_discovery"]
        # --client-id is required; intended to be provided at invocation time
        # via `gcloud run jobs execute ... --args="--client-id=..."`.

        env {
          name  = "DB_INSTANCE_CONNECTION_NAME"
          value = var.db_instance_connection_name
        }
        env {
          name  = "CLOUD_SQL_CONNECTION_NAME"
          value = var.db_instance_connection_name
        }
        env {
          name  = "DB_PASSWORD"
          value = var.db_password
        }
        env {
          name  = "DB_PASS"
          value = var.db_password
        }
        env {
          name  = "DB_NAME"
          value = var.db_name
        }
        env {
          name  = "DB_USER"
          value = var.db_user
        }
        env {
          name  = "GCP_PROJECT_ID"
          value = var.project_id
        }
        env {
          name  = "GCP_REGION"
          value = var.region
        }
        env {
          name  = "GCP_REGION_GLOBAL"
          value = "global"
        }
        env {
          name  = "IS_CLOUD_RUN"
          value = "true"
        }

        resources {
          limits = {
            cpu    = "1"
            memory = "1Gi"
          }
        }

        volume_mounts {
          name       = "cloudsql"
          mount_path = "/cloudsql"
        }
      }

      volumes {
        name = "cloudsql"
        cloud_sql_instance {
          instances = [var.db_instance_connection_name]
        }
      }

      timeout     = "1800s"
      max_retries = 1
    }
  }
}

# --- IAM: Scheduler SA can invoke the LLM Batch job -------------------------

resource "google_cloud_run_v2_job_iam_member" "suggestions_scheduler_invoker" {
  name     = google_cloud_run_v2_job.geo_llm_batch_discovery.name
  location = var.region
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.suggestions_scheduler_sa.email}"
}

# --- Cloud Scheduler: daily LLM Batch trigger -------------------------------
#
# v1.2 2026-04-20 — Per-client scheduling now supersedes this global job.
# `geo_admin/src/services/gcp_scheduler.py::sync_scheduler_job` dynamically
# creates/updates one Cloud Scheduler per client (name pattern:
# `geo-llm_discovery-<short_id>`) whenever the admin edits `cron_llm_discovery`
# on the Clients page. Those per-client jobs target the Admin API endpoint
# POST /api/clients/{client_id}/jobs/llm_discovery/run, which in turn calls
# `run_v2.JobsAsyncClient.run_job()` on the Cloud Run Job below with a
# CLIENT_ID env + --client-id CLI override.
#
# The global scheduler below is KEPT as a safety net for clients who haven't
# configured a per-client cron; disable it after all active clients have
# adopted per-client schedules.

resource "google_cloud_scheduler_job" "geo_suggestions_daily" {
  name        = "geo-suggestions-llm-batch-daily"
  description = "Global fallback: kicks LLM Batch candidate-discovery Cloud Run Job daily (per-client schedules preferred)."
  schedule    = "0 3 * * *" # 03:00 UTC every day
  time_zone   = "UTC"
  region      = var.region

  retry_config {
    retry_count          = 1
    min_backoff_duration = "60s"
    max_backoff_duration = "600s"
  }

  http_target {
    http_method = "POST"
    uri         = "https://${var.region}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${var.project_id}/jobs/${google_cloud_run_v2_job.geo_llm_batch_discovery.name}:run"
    oauth_token {
      service_account_email = google_service_account.suggestions_scheduler_sa.email
    }
  }

  depends_on = [
    google_cloud_run_v2_job_iam_member.suggestions_scheduler_invoker,
  ]
}

# --- Per-client invocation from Admin API ----------------------------------
#
# The Admin API (`geo-admin-api` Cloud Run service) executes this job via
# `run_v2.JobsAsyncClient.run_job()` when (a) the user clicks "Run LLM
# Discovery Now" in the Admin UI, or (b) the per-client Cloud Scheduler job
# hits `/api/clients/{id}/jobs/llm_discovery/run`. The API runs as the
# default compute SA — grant it developer access here.

data "google_project" "current" {}

resource "google_cloud_run_v2_job_iam_member" "admin_api_llm_batch_invoker" {
  name     = google_cloud_run_v2_job.geo_llm_batch_discovery.name
  location = var.region
  role     = "roles/run.developer"
  member   = "serviceAccount:${data.google_project.current.number}-compute@developer.gserviceaccount.com"
}

# --- Outputs ----------------------------------------------------------------

output "suggestions_llm_batch_job_name" {
  description = "LLM Batch discovery Cloud Run Job name"
  value       = google_cloud_run_v2_job.geo_llm_batch_discovery.name
}

output "suggestions_ngram_job_name" {
  description = "N-gram discovery Cloud Run Job name (on-demand)"
  value       = google_cloud_run_v2_job.geo_ngram_discovery.name
}

output "suggestions_scheduler_job" {
  description = "Cloud Scheduler job name for nightly LLM Batch"
  value       = google_cloud_scheduler_job.geo_suggestions_daily.name
}
