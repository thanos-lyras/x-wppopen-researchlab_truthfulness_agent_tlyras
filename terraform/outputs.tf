output "service_url" {
  value       = google_cloud_run_v2_service.unified.uri
  description = "Public HTTPS URL of the deployed unified service."
}
