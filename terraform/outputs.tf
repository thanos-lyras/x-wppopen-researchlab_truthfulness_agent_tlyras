output "bucket_name" {
  description = "The uploads/SFT-staging bucket. Also written to GCS_BUCKET in .env by deployment/deploy.py."
  value       = google_storage_bucket.uploads.name
}

output "artifact_registry" {
  description = "Full AR repo path. `deployment/deploy.py` pushes each service's image here as <repo>/truthfulness-<svc>:latest."
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.images.repository_id}"
}

output "deploy_command" {
  description = "The command the deploy_all null_resource runs. Handy to invoke standalone (e.g. `make deploy-all`) without terraform in the loop."
  value       = "uv run python deployment/deploy.py all"
}
