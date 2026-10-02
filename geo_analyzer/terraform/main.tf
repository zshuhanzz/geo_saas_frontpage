terraform {
  required_version = ">= 1.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

# ============================================================================
# Artifact Registry Repository (shared with other modules or create new)
# ============================================================================
resource "google_artifact_registry_repository" "geo_analyzer" {
  location      = var.region
  repository_id = var.repo_name
  description   = "Docker repository for GEO Analyzer"
  format        = "DOCKER"
}

# ============================================================================
# Cloud Run Job: GEO Analyzer
# ============================================================================
resource "google_cloud_run_v2_job" "geo_analyzer" {
  name     = "geo-analyzer"
  location = var.region

  template {
    task_count  = 8
    parallelism = 8

    template {
      containers {
        image = var.image_tag

        # Entry point defined in Dockerfile, receives REPORT_ID at runtime
        # command = ["python"]
        # args    = ["main.py"]

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

      timeout     = "10800s" # 3 hours max for large analysis jobs
      max_retries = 1
    }
  }
}

# ============================================================================
# Outputs
# ============================================================================
output "analyzer_job_name" {
  description = "GEO Analyzer Cloud Run Job name"
  value       = google_cloud_run_v2_job.geo_analyzer.name
}

output "artifact_registry" {
  description = "Artifact Registry repository URL"
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${var.repo_name}"
}
