terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
    null = {
      source  = "hashicorp/null"
      version = "~> 3.2"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

locals {
  # Unique tag per apply forces a Cloud Run revision rollout (a string-stable
  # `:latest` tag wouldn't, even after a fresh image push).
  image_tag = formatdate("YYYYMMDDhhmmss", timestamp())
  image     = "${var.region}-docker.pkg.dev/${var.project_id}/cloud-run-source-deploy/${var.service_name}:${local.image_tag}"
}

# Build the container image. The bash wrapper cd's to repo root, so
# working_dir gets us back to it from the terraform module directory.
resource "null_resource" "build_image" {
  triggers = {
    image = local.image
  }
  provisioner "local-exec" {
    working_dir = "${path.module}/.."
    command     = "bash terraform/build_image.sh ${var.project_id} ${var.region} ${local.image}"
  }
}

resource "google_cloud_run_v2_service" "unified" {
  name                = var.service_name
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false

  template {
    containers {
      image = local.image
    }
    scaling {
      max_instance_count = 1
    }
  }

  depends_on = [null_resource.build_image]
}

resource "google_cloud_run_v2_service_iam_member" "public_invoker" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.unified.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}
