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
    template {
      containers {
        image = var.image_tag
        
        # Entry point defined in Dockerfile, receives REPORT_ID at runtime
        # command = ["python"]
        # args    = ["main.py"]

        env {
          name  = "CLOUD_SQL_CONNECTION_NAME"
          value = var.db_instance_connection_name
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
        
        resources {
          limits = {
            cpu    = "1"
            memory = "1Gi"
          }
        }
      }
      
      volumes {
        name = "cloudsql"
        cloud_sql_instance {
          instances = [var.db_instance_connection_name]
        }
      }
      
      timeout = "3600s"  # 1 hour max for analysis job
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
