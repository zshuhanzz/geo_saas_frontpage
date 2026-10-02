variable "project_id" {
  description = "GCP Project ID"
  type        = string
}

variable "region" {
  description = "GCP Region"
  type        = string
  default     = "us-central1"
}

variable "repo_name" {
  description = "Artifact Registry repository name"
  type        = string
  default     = "geo-saas-repo"
}

variable "api_image_tag" {
  description = "Docker image tag for SaaS API service"
  type        = string
}

variable "web_image_tag" {
  description = "Docker image tag for SaaS Web service"
  type        = string
}

variable "db_instance_connection_name" {
  description = "Cloud SQL instance connection name (project:region:instance)"
  type        = string
}

variable "db_user" {
  description = "Database username"
  type        = string
  default     = "answer-x-geo-db-user"
}

variable "db_password" {
  description = "Database password"
  type        = string
  sensitive   = true
}

variable "db_name" {
  description = "Database name"
  type        = string
  default     = "answer-x-geo-db"
}

variable "google_oauth_client_id" {
  description = "Google OAuth Web client ID used by the API to verify ID tokens"
  type        = string
}

variable "allow_unauthenticated" {
  description = "Allow unauthenticated access to services"
  type        = bool
  default     = true
}

variable "allowed_origins" {
  description = "Comma-separated CORS allowed origins for the API"
  type        = string
  default     = "http://localhost:5173"
}

variable "agent_api_url" {
  description = "GEO Agent API Cloud Run URL (for nginx proxy)"
  type        = string
  default     = ""
}

variable "saas_api_url" {
  description = "Public SaaS API URL used as Cloud Scheduler OIDC audience"
  type        = string
  default     = ""
}

variable "system_invoker_service_account" {
  description = "Service account email allowed to invoke system-triggered jobs"
  type        = string
  default     = ""
}

variable "api_db_pool_max_size" {
  description = "Maximum asyncpg connections per SaaS API Cloud Run instance"
  type        = number
  default     = 8

  validation {
    condition     = var.api_db_pool_max_size >= 8
    error_message = "api_db_pool_max_size must be at least 8 to preserve the static-report connection budget."
  }
}

variable "static_report_snapshot_concurrency" {
  description = "Maximum parallel snapshot query workers per report, excluding the coordinator"
  type        = number
  default     = 2


  validation {
    condition     = var.static_report_snapshot_concurrency >= 1 && var.static_report_snapshot_concurrency <= 2
    error_message = "static_report_snapshot_concurrency must be between 1 and 2."
  }
}

variable "static_report_db_connection_reserve" {
  description = "Connections reserved for normal SaaS traffic while a static report is generated"
  type        = number
  default     = 5


  validation {
    condition     = var.static_report_db_connection_reserve >= 5
    error_message = "static_report_db_connection_reserve must reserve at least five connections."
  }
}

variable "static_report_work_mem_mb" {
  description = "Transaction-local PostgreSQL work_mem for static report aggregation queries"
  type        = number
  default     = 32


  validation {
    condition     = var.static_report_work_mem_mb >= 16 && var.static_report_work_mem_mb <= 64
    error_message = "static_report_work_mem_mb must be between 16 and 64 MB."
  }
}

variable "api_db_query_timeout_seconds" {
  description = "API database command and statement timeout in seconds"
  type        = number
  default     = 60
}

variable "api_db_pool_acquire_timeout_seconds" {
  description = "Maximum seconds an API request waits for a database pool connection"
  type        = number
  default     = 10
}
