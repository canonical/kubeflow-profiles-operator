output "app_name" {
  value = juju_application.kubeflow_profiles.name
}

output "provides" {
  value = {
	kubeflow_profiles = "kubeflow-profiles"
	metrics_endpoint  = "metrics-endpoint"
  }
}

output "requires" {
  value = {
    logging         = "logging"
  }
}
