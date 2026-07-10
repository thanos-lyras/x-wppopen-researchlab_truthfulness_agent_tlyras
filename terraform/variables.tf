variable "project_id" {
  description = "GCP project ID"
  type        = string
  default     = "x-wppai-dataspine-choreo-dev"
}

variable "region" {
  description = "GCP region. Must match GOOGLE_CLOUD_LOCATION in .env."
  type        = string
  default     = "europe-west1"
}

variable "bucket_name" {
  description = "GCS bucket for /invoke uploads and SFT dataset staging."
  type        = string
  default     = "x-wppai-dataspine-choreo-dev-truthfulness-uploads-europe-west1"
}

variable "artifact_registry_repo" {
  description = "Artifact Registry repo name where deploy.py pushes the 5 service images."
  type        = string
  default     = "cloud-run-source-deploy"
}

variable "deploy_trigger" {
  description = "Change this value (e.g. to a git SHA or new timestamp) to force `terraform apply` to re-run `deployment/deploy.py all`. Default keeps deploys idempotent — you'll only get a new run when this changes."
  type        = string
  default     = "manual"
}
