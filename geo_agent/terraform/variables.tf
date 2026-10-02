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
  default     = "geo-agent-repo"
}

variable "image_tag" {
  description = "Docker image tag for Agent API service"
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
  description = "Allow unauthenticated access to the agent API"
  type        = bool
  default     = true
}

variable "allowed_origins" {
  description = "Comma-separated CORS allowed origins"
  type        = string
  default     = "http://localhost:5173"
}

variable "agent_api_url" {
  description = "Public Agent API URL used as Cloud Scheduler OIDC audience"
  type        = string
  default     = ""
}

variable "system_invoker_service_account" {
  description = "Service account email allowed to invoke system-triggered jobs"
  type        = string
  default     = ""
}
