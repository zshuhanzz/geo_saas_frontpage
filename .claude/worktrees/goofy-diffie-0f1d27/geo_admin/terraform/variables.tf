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
  default     = "geo-admin-repo"
}

variable "api_image_tag" {
  description = "Docker image tag for API service"
  type        = string
}

variable "web_image_tag" {
  description = "Docker image tag for Web service"
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

variable "allow_unauthenticated" {
  description = "Allow unauthenticated access to services"
  type        = bool
  default     = true
}
