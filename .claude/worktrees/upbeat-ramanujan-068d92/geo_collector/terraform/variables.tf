variable "project_id" {
  description = "GCP Project ID"
  type        = string
}

variable "region" {
  description = "GCP Region for resources"
  type        = string
  default     = "us-central1"
}

variable "repo_name" {
  description = "Artifact Registry Repository Name"
  type        = string
  default     = "answer-x-geo-repo"
}

variable "db_instance_connection_name" {
  description = "Cloud SQL Instance Connection Name (PROJECT:REGION:INSTANCE)"
  type        = string
}

variable "cloro_api_key" {
  description = "API Key for Cloro.dev"
  type        = string
  sensitive   = true
}

variable "db_password" {
  description = "Database user password"
  type        = string
  sensitive   = true
}

variable "image_tag" {
  description = "Docker image tag to deploy (e.g., us-central1-docker.pkg.dev/.../geo-collector:v1)"
  type        = string
}

variable "db_name" {
  description = "Database name"
  type        = string
  default     = "answer-x-geo-db"
}

variable "db_user" {
  description = "Database user"
  type        = string
  default     = "answer-x-geo-db-user"
}

variable "webhook_public_url" {
  description = "The public URL of the Webhook Service (Update this after first apply)"
  type        = string
  default     = "https://placeholder-url-update-after-deploy"
}

variable "gemini_model_id" {
  description = "Gemini model ID for Vertex AI"
  type        = string
  default     = "gemini-2.5-flash"
}