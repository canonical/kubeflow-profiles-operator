"""Constants for the Kubeflow Profiles Operator charm."""

K8S_RESOURCE_FILES = ["src/templates/crds.yaml.j2"]
NAMESPACE_LABELS_FILE = "src/templates/namespace-labels.yaml.j2"
PROFILE_CONFIG_FILES = ["src/templates/allow-minio.yaml", "src/templates/allow-mlflow.yaml"]
