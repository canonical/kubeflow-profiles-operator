output "app_name" {
  value = juju_application.kubeflow_profiles.name
}

output "provides" {
  value = {
    kubeflow_profiles            = "kubeflow-profiles",
    metrics_endpoint             = "metrics-endpoint",
    profiles_backup_config       = "profiles-backup-config",
    provide_cmr_mesh             = "provide-cmr-mesh",
    user_workloads_backup_config = "user-workloads-backup-config"
  }
}

output "requires" {
  value = {
    ingress          = "ingress",
    logging          = "logging",
    require_cmr_mesh = "require-cmr-mesh",
    service_mesh     = "service-mesh"
  }
}
