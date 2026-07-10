terraform {
  required_version = ">= 1.6.0"
  required_providers {
    google = { source = "hashicorp/google", version = "~> 6.0" }
    null   = { source = "hashicorp/null", version = "~> 3.2" }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

data "google_project" "this" {
  project_id = var.project_id
}

# 1. Artifact Registry — image target for `make build-*` and `deployment/deploy.py`.
resource "google_artifact_registry_repository" "images" {
  location      = var.region
  repository_id = var.artifact_registry_repo
  format        = "DOCKER"
  description   = "Container images for the truthfulness-agent Cloud Run services."
}

# 2. GCS bucket — used by /invoke uploads and SFT dataset staging.
resource "google_storage_bucket" "uploads" {
  name                        = var.bucket_name
  location                    = var.region
  uniform_bucket_level_access = true
  force_destroy               = false
}

# Runtime compute SA needs objectAdmin so the orchestrator's /invoke handler
# can write and delete per-request upload objects. Mirrors
# deployment/bootstrap_bucket.py.
resource "google_storage_bucket_iam_member" "uploads_compute_object_admin" {
  bucket = google_storage_bucket.uploads.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${data.google_project.this.number}-compute@developer.gserviceaccount.com"
}

# 3. Private Google Access on the default subnet — required so Cloud Run
# services with --vpc-egress=all-traffic can still reach Vertex, GCS, and
# Secret Manager. Terraform can't own the default subnet without importing,
# so we shell out to gcloud. Idempotent — no-op when PGA is already on.
resource "null_resource" "enable_pga_on_default_subnet" {
  triggers = {
    project = var.project_id
    region  = var.region
  }

  provisioner "local-exec" {
    command = "gcloud compute networks subnets update default --region=${var.region} --project=${var.project_id} --enable-private-ip-google-access"
  }
}

# 4. Deploy the 5 Cloud Run services via the existing Python pipeline.
# `deployment/deploy.py all` handles: Cloud Build for all 5 images, Cloud Run
# deploy with the right ingress/VPC/env-var posture per service, the gateway
# SA invoker grant on the orchestrator, and .env write-back for MCP_SERVER_URL
# / *_A2A_URL.
resource "null_resource" "deploy_all" {
  triggers = {
    deploy_trigger = var.deploy_trigger
    # Recreate on bucket recreation — "delete bucket + terraform apply" becomes
    # a self-healing fresh bootstrap without needing -replace=null_resource.deploy_all.
    bucket_id = google_storage_bucket.uploads.id
  }

  provisioner "local-exec" {
    working_dir = "${path.module}/.."
    command     = "uv run python deployment/deploy.py all"
    environment = {
      PYTHONPATH = "."
    }
  }

  depends_on = [
    google_artifact_registry_repository.images,
    google_storage_bucket_iam_member.uploads_compute_object_admin,
    null_resource.enable_pga_on_default_subnet,
  ]
}
