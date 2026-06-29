variable "project_id" {
  description = "GCP project ID hosting the unified Cloud Run service."
  type        = string
  default     = "x-wppai-dataspine-choreo-dev"
}

variable "region" {
  description = "GCP region for Cloud Run."
  type        = string
  default     = "us-central1"
}

variable "service_name" {
  description = "Cloud Run service name."
  type        = string
  default     = "truthfulness-unified"
}
