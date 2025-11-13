"""Constants for the Kubeflow Profiles Operator charm."""

K8S_RESOURCE_FILES = ["src/templates/crds.yaml.j2"]
NAMESPACE_LABELS_FILE = "src/templates/namespace-labels.yaml.j2"
PROFILE_CONFIG_FILES = ["src/templates/allow-minio.yaml", "src/templates/allow-mlflow.yaml"]

# List of resources to exclude from Velero backup/restore for user workloads.
# See: https://github.com/canonical/bundle-kubeflow/issues/1197
K8S_USER_WORKLOAD_EXCLUDE_RESOURCECS = [
    "pods",
    "deployments",
    "replicasets",
    "statefulsets",
    "services",
    "namespaces",
    "profiles.kubeflow.org",
    "workflowartifactgctasks.argoproj.io",
    "workfloweventbindings.argoproj.io",
    "workflows.argoproj.io",
    "workflowtaskresults.argoproj.io",
    "workflowtasksets.argoproj.io",
    "workflowtemplates.argoproj.io",
    "clusterworkflowtemplates.argoproj.io",
    "certificates.networking.internal.knative.dev",
    "clusterdomainclaims.networking.internal.knative.dev",
    "configurations.serving.knative.dev",
    "domainmappings.serving.knative.dev",
    "images.caching.internal.knative.dev",
    "ingresses.networking.internal.knative.dev",
    "metrics.autoscaling.internal.knative.dev",
    "podautoscalers.autoscaling.internal.knative.dev",
    "revisions.serving.knative.dev",
    "routes.serving.knative.dev",
    "serverlessservices.networking.internal.knative.dev",
    "services.serving.knative.dev",
    "virtualservices.networking.istio.io",
]
