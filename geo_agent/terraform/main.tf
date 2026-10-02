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
# Artifact Registry Repository
# ============================================================================
resource "google_artifact_registry_repository" "geo_agent" {
  location      = var.region
  repository_id = var.repo_name
  description   = "Docker repository for GEO Agent"
  format        = "DOCKER"
}

# ============================================================================
# Cloud Run Service: Agent API
# ============================================================================
resource "google_cloud_run_v2_service" "geo_agent_api" {
  name     = "geo-agent-api"
  location = var.region

  template {
    containers {
      image = var.image_tag

      ports {
        container_port = 8080
      }

      env {
        name  = "DATABASE_URL"
        value = "postgresql://${var.db_user}:${var.db_password}@/${var.db_name}?host=/cloudsql/${var.db_instance_connection_name}"
      }

      env {
        name  = "GOOGLE_OAUTH_CLIENT_ID"
        value = var.google_oauth_client_id
      }

      env {
        name  = "AGENT_API_URL"
        value = var.agent_api_url
      }

      env {
        name  = "INVOKER_SERVICE_ACCOUNT"
        value = var.system_invoker_service_account
      }

      env {
        name  = "SERVICE_ACCOUNT_EMAIL"
        value = var.system_invoker_service_account
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
        name  = "ALLOWED_ORIGINS"
        value = var.allowed_origins
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

    scaling {
      min_instance_count = 1
      max_instance_count = 5
    }

    volumes {
      name = "cloudsql"
      cloud_sql_instance {
        instances = [var.db_instance_connection_name]
      }
    }
  }

  traffic {
    type    = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST"
    percent = 100
  }
}

# IAM: Allow unauthenticated access
resource "google_cloud_run_v2_service_iam_member" "agent_public" {
  count    = var.allow_unauthenticated ? 1 : 0
  location = google_cloud_run_v2_service.geo_agent_api.location
  name     = google_cloud_run_v2_service.geo_agent_api.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# ============================================================================
# Outputs
# ============================================================================
output "agent_api_url" {
  value = google_cloud_run_v2_service.geo_agent_api.uri
}
