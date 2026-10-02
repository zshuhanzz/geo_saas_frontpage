output "cloro_callback_url" {
  description = "The public URL of the Cloro Callback Service"
  value       = google_cloud_run_v2_service.cloro_callback.uri
}

output "result_ingestor_url" {
  description = "The internal URL of the Result Ingestor Service"
  value       = google_cloud_run_v2_service.result_ingestor.uri
}

output "cloro_dispatcher_url" {
  description = "The internal URL of the Cloro Dispatcher Service"
  value       = google_cloud_run_v2_service.cloro_dispatcher.uri
}

output "prompt_expander_job_name" {
  description = "The name of the Prompt Expander Job"
  value       = google_cloud_run_v2_job.prompt_expander.name
}