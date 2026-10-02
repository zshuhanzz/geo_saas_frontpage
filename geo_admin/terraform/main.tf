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
resource "google_artifact_registry_repository" "geo_admin" {
  location      = var.region
  repository_id = var.repo_name
  description   = "Docker repository for GEO Admin"
  format        = "DOCKER"
}

# ============================================================================
# Cloud Run Service: API
# ============================================================================
resource "google_cloud_run_v2_service" "geo_admin_api" {
  name     = "geo-admin-api"
  location = var.region

  template {
    containers {
      image = var.api_image_tag

      ports {
        container_port = 8080
      }

      env {
        name  = "DATABASE_URL"
        value = "postgresql+asyncpg://${var.db_user}:${var.db_password}@/${var.db_name}?host=/cloudsql/${var.db_instance_connection_name}"
      }

      env {
        name  = "GOOGLE_OAUTH_CLIENT_ID"
        value = var.google_oauth_client_id
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
        name  = "ADMIN_API_URL"
        value = "https://geo-admin-api-uj5wohdjgq-uc.a.run.app"
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
        name  = "AGENT_API_URL"
        value = var.agent_api_url
      }

      env {
        name  = "ALLOWED_ORIGINS"
        value = var.allowed_origins
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
      }

      volume_mounts {
        name       = "cloudsql"
        mount_path = "/cloudsql"
      }
    }

    scaling {
      min_instance_count = 0
      max_instance_count = 2
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

# IAM: Allow unauthenticated access to API
resource "google_cloud_run_v2_service_iam_member" "api_public" {
  count    = var.allow_unauthenticated ? 1 : 0
  location = google_cloud_run_v2_service.geo_admin_api.location
  name     = google_cloud_run_v2_service.geo_admin_api.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# ============================================================================
# Cloud Run Service: Web Frontend
# ============================================================================
resource "google_cloud_run_v2_service" "geo_admin_web" {
  name     = "geo-admin-web"
  location = var.region

  template {
    containers {
      image = var.web_image_tag

      ports {
        container_port = 80
      }

      # API URL for frontend to call (baked into static build or runtime config)
      env {
        name  = "API_URL"
        value = google_cloud_run_v2_service.geo_admin_api.uri
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
      }
    }

    scaling {
      min_instance_count = 0
      max_instance_count = 2
    }
  }

  traffic {
    type    = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST"
    percent = 100
  }
}

# IAM: Allow unauthenticated access to Web
resource "google_cloud_run_v2_service_iam_member" "web_public" {
  count    = var.allow_unauthenticated ? 1 : 0
  location = google_cloud_run_v2_service.geo_admin_web.location
  name     = google_cloud_run_v2_service.geo_admin_web.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# ============================================================================
# Outputs
# ============================================================================
output "api_url" {
  description = "GEO Admin API URL"
  value       = google_cloud_run_v2_service.geo_admin_api.uri
}

output "web_url" {
  description = "GEO Admin Web URL"
  value       = google_cloud_run_v2_service.geo_admin_web.uri
}

output "artifact_registry" {
  description = "Artifact Registry repository URL"
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${var.repo_name}"
}
