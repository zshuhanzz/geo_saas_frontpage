terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 4.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

# --- 0. Artifact Registry ---
resource "google_artifact_registry_repository" "geo_repo" {
  location      = var.region
  repository_id = var.repo_name
  description   = "Docker repository for GEO Collector"
  format        = "DOCKER"
}

# --- 1. Pub/Sub Topics ---
# Cloro callback results -> Result Ingestor
resource "google_pubsub_topic" "geo_cloro_callbacks" {
  name = "geo-cloro-callbacks"
}

# Tasks pending dispatch -> Cloro Dispatcher
resource "google_pubsub_topic" "geo_tasks_pending" {
  name = "geo-tasks-pending"
}

# --- 2. Service Account for Pub/Sub ---
resource "google_service_account" "pubsub_invoker" {
  account_id   = "pubsub-invoker"
  display_name = "Pub/Sub Invoker Service Account"
}

# --- 3. Cloro Callback Service (receives Cloro callbacks) ---
resource "google_cloud_run_v2_service" "cloro_callback" {
  name     = "geo-cloro-callback"
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"
  
  deletion_protection = false

  template {
    containers {
      image = var.image_tag
      
      command = ["uvicorn"]
      args    = ["src.cloro_callback:app", "--host", "0.0.0.0", "--port", "8080"]

      env {
        name  = "DB_INSTANCE_CONNECTION_NAME"
        value = var.db_instance_connection_name
      }
      env {
        name  = "DB_PASSWORD"
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
        name  = "PUBSUB_PROJECT_ID"
        value = var.project_id
      }
      env {
        name  = "CLORO_API_KEY"
        value = var.cloro_api_key
      }
      env {
        name  = "WEBHOOK_PUBLIC_URL"
        value = var.webhook_public_url
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
        name  = "GEMINI_MODEL_ID"
        value = var.gemini_model_id
      }
    }
    
    volumes {
      name = "cloudsql"
      cloud_sql_instance {
        instances = [var.db_instance_connection_name]
      }
    }
  }
}

# Allow public access (Cloro callbacks are public)
resource "google_cloud_run_service_iam_member" "cloro_callback_public" {
  service  = google_cloud_run_v2_service.cloro_callback.name
  location = google_cloud_run_v2_service.cloro_callback.location
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# --- 4. Result Ingestor Service (ingests callback data) ---
resource "google_cloud_run_v2_service" "result_ingestor" {
  name     = "geo-result-ingestor"
  location = var.region
  
  deletion_protection = false

  template {
    containers {
      image = var.image_tag
      
      command = ["uvicorn"]
      args    = ["src.result_ingestor:app", "--host", "0.0.0.0", "--port", "8080"]

      env {
        name  = "DB_INSTANCE_CONNECTION_NAME"
        value = var.db_instance_connection_name
      }
      env {
        name  = "DB_PASSWORD"
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
        name  = "PUBSUB_PROJECT_ID"
        value = var.project_id
      }
      env {
        name  = "CLORO_API_KEY"
        value = var.cloro_api_key
      }
      env {
        name  = "WEBHOOK_PUBLIC_URL"
        value = var.webhook_public_url
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
        name  = "GEMINI_MODEL_ID"
        value = var.gemini_model_id
      }
    }
    
    volumes {
      name = "cloudsql"
      cloud_sql_instance {
        instances = [var.db_instance_connection_name]
      }
    }
  }
}

# Pub/Sub -> Result Ingestor
resource "google_cloud_run_service_iam_member" "result_ingestor_invoker" {
  service  = google_cloud_run_v2_service.result_ingestor.name
  location = google_cloud_run_v2_service.result_ingestor.location
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.pubsub_invoker.email}"
}

resource "google_pubsub_subscription" "callbacks_to_ingestor" {
  name  = "geo-callbacks-to-ingestor"
  topic = google_pubsub_topic.geo_cloro_callbacks.name

  push_config {
    push_endpoint = "${google_cloud_run_v2_service.result_ingestor.uri}/ingest/result"
    
    oidc_token {
      service_account_email = google_service_account.pubsub_invoker.email
    }
  }

  ack_deadline_seconds = 600
}

# --- 5. Cloro Dispatcher Service (dispatches tasks to Cloro) ---
resource "google_cloud_run_v2_service" "cloro_dispatcher" {
  name     = "geo-cloro-dispatcher"
  location = var.region
  
  deletion_protection = false

  template {
    containers {
      image = var.image_tag
      
      command = ["uvicorn"]
      args    = ["src.cloro_dispatcher:app", "--host", "0.0.0.0", "--port", "8080"]

      env {
        name  = "DB_INSTANCE_CONNECTION_NAME"
        value = var.db_instance_connection_name
      }
      env {
        name  = "DB_PASSWORD"
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
        name  = "CLORO_API_KEY"
        value = var.cloro_api_key
      }
      env {
        name  = "WEBHOOK_PUBLIC_URL"
        value = var.webhook_public_url
      }
      env {
        name  = "PUBSUB_PROJECT_ID"
        value = var.project_id
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
        name  = "GEMINI_MODEL_ID"
        value = var.gemini_model_id
      }
    }
    
    volumes {
      name = "cloudsql"
      cloud_sql_instance {
        instances = [var.db_instance_connection_name]
      }
    }
  }
}

# Pub/Sub -> Cloro Dispatcher
resource "google_cloud_run_service_iam_member" "cloro_dispatcher_invoker" {
  service  = google_cloud_run_v2_service.cloro_dispatcher.name
  location = google_cloud_run_v2_service.cloro_dispatcher.location
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.pubsub_invoker.email}"
}

resource "google_pubsub_subscription" "tasks_to_dispatcher" {
  name  = "geo-tasks-to-dispatcher"
  topic = google_pubsub_topic.geo_tasks_pending.name

  push_config {
    push_endpoint = "${google_cloud_run_v2_service.cloro_dispatcher.uri}/dispatch/task"
    
    oidc_token {
      service_account_email = google_service_account.pubsub_invoker.email
    }
  }

  ack_deadline_seconds = 600
  
  retry_policy {
    minimum_backoff = "10s"
    maximum_backoff = "600s"
  }
}

# --- 6. Prompt Expander Job (entry point) ---
resource "google_cloud_run_v2_job" "prompt_expander" {
  name     = "geo-prompt-expander"
  location = var.region
  
  deletion_protection = false

  template {
    template {
      containers {
        image = var.image_tag
        
        command = ["python"]
        args    = ["-m", "src.expander"]

        env {
          name  = "DB_INSTANCE_CONNECTION_NAME"
          value = var.db_instance_connection_name
        }
        env {
          name  = "DB_PASSWORD"
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
          name  = "CLORO_API_KEY"
          value = var.cloro_api_key
        }
        env {
          name  = "WEBHOOK_PUBLIC_URL"
          value = var.webhook_public_url
        }
        env {
          name  = "PUBSUB_PROJECT_ID"
          value = var.project_id
        }
        env {
          name  = "IS_CLOUD_RUN"
          value = "true"
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
          name  = "GEMINI_MODEL_ID"
          value = var.gemini_model_id
        }
      }
      
      volumes {
        name = "cloudsql"
        cloud_sql_instance {
          instances = [var.db_instance_connection_name]
        }
      }
    }
  }
}

# --- 7. Cloud Scheduler (optional: trigger Expander periodically) ---
resource "google_cloud_scheduler_job" "expander_cron" {
  name             = "geo-expander-cron"
  region           = var.region
  schedule         = "*/10 * * * *"
  time_zone        = "UTC"
  attempt_deadline = "320s"
  paused           = true  # Default paused, manual trigger only

  http_target {
    http_method = "POST"
    uri         = "https://${var.region}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${var.project_id}/jobs/${google_cloud_run_v2_job.prompt_expander.name}:run"

    oauth_token {
      service_account_email = google_service_account.pubsub_invoker.email
    }
  }
}