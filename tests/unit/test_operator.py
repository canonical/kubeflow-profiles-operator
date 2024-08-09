# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
"""Unit tests. Harness and Mocks are defined in test_operator_fixtures.py."""
import json
from unittest.mock import MagicMock, patch

from lightkube.generic_resource import create_global_resource
from lightkube.models.meta_v1 import ObjectMeta
from lightkube.resources.core_v1 import Secret
from ops.charm import ActionEvent
from ops.model import ActiveStatus, WaitingStatus

from charm import KubeflowProfilesOperator


def test_log_forwarding(
    harness,
    mocked_kubernetes_service_patcher,
    mocked_resource_handler,
):
    """Test LogForwarder initialization."""
    with patch("charm.LogForwarder") as mock_logging:
        harness.begin()
        mock_logging.assert_called_once_with(charm=harness.charm)


def test_metrics(
    harness,
    mocked_kubernetes_service_patcher,
    mocked_resource_handler,
):
    """Test MetricsEndpointProvider initialization."""
    with patch("charm.MetricsEndpointProvider") as mocked_metrics_endpoint_provider:
        harness.begin()
        mocked_metrics_endpoint_provider.assert_called_once_with(
            harness.charm,
            jobs=[{"static_configs": [{"targets": ["*:8080", "*:8081"]}]}],
        )


def test_not_leader(
    harness,
    mocked_kubernetes_service_patcher,
    mocked_resource_handler,
):
    """Test not a leader scenario."""
    harness.begin_with_initial_hooks()
    harness.container_pebble_ready("kubeflow-profiles")
    harness.container_pebble_ready("kubeflow-kfam")
    assert harness.charm.model.unit.status == WaitingStatus("Waiting for leadership")


def test_profiles_container_running(
    harness,
    mocked_kubernetes_service_patcher,
    mocked_resource_handler,
):
    """Test that kubeflow-profiles container is running."""
    harness.set_leader(True)
    harness.begin_with_initial_hooks()
    harness.container_pebble_ready("kubeflow-profiles")
    assert harness.charm.profiles_container.get_service("kubeflow-profiles").is_running()


def test_kfam_container_running(
    harness,
    mocked_kubernetes_service_patcher,
    mocked_resource_handler,
):
    """Test that kubeflow-kfam container is running."""
    harness.set_leader(True)
    harness.begin_with_initial_hooks()
    harness.container_pebble_ready("kubeflow-kfam")
    assert harness.charm.kfam_container.get_service("kubeflow-kfam").is_running()


def test_no_relation(
    harness,
    mocked_kubernetes_service_patcher,
    mocked_resource_handler,
):
    """Test no relation scenario."""
    harness.set_leader(True)
    harness.add_oci_resource(
        "profile-image", {"registrypath": "ci-test", "username": "", "password": ""}
    )
    harness.add_oci_resource(
        "kfam-image", {"registrypath": "ci-test", "username": "", "password": ""}
    )
    harness.begin_with_initial_hooks()
    assert harness.charm.model.unit.status == ActiveStatus("")


def test_profiles_pebble_ready_first_scenario(
    harness,
    mocked_kubernetes_service_patcher,
    mocked_resource_handler,
):
    """Test (install -> profiles pebble ready -> kfam pebble ready) reach Active.."""
    harness.set_leader(True)
    harness.begin()
    harness.charm.on.install.emit()
    harness.container_pebble_ready("kubeflow-profiles")
    harness.container_pebble_ready("kubeflow-kfam")
    assert harness.charm.model.unit.status == ActiveStatus("")


def test_kfam_pebble_ready_first_scenario(
    harness,
    mocked_kubernetes_service_patcher,
    mocked_resource_handler,
):
    """Test (install -> kfam pebble ready -> profiles pebble ready) reach Active."""
    harness.set_leader(True)
    harness.begin()
    harness.charm.on.install.emit()
    harness.container_pebble_ready("kubeflow-kfam")
    harness.container_pebble_ready("kubeflow-profiles")
    assert harness.charm.model.unit.status == ActiveStatus("")


def test_profiles_pebble_layer(
    harness,
    mocked_kubernetes_service_patcher,
    mocked_resource_handler,
):
    """Test creation of Profiles Pebble layer. Only testing specific items."""
    harness.set_leader(True)
    harness.set_model_name("test_kubeflow")
    harness.begin_with_initial_hooks()
    harness.container_pebble_ready("kubeflow-profiles")
    pebble_plan = harness.get_container_pebble_plan("kubeflow-profiles")
    assert pebble_plan
    assert pebble_plan._services
    pebble_plan_info = pebble_plan.to_dict()
    assert (
        pebble_plan_info["services"]["kubeflow-profiles"]["command"] == "/manager "
        "-userid-header "
        "kubeflow-userid "
        "-userid-prefix "
        '""'
    )


def test_kfam_pebble_layer(
    harness,
    mocked_kubernetes_service_patcher,
    mocked_resource_handler,
):
    """Test creation of kfam Pebble layer. Only testing specific items."""
    harness.set_leader(True)
    harness.set_model_name("test_kubeflow")
    harness.begin_with_initial_hooks()
    harness.container_pebble_ready("kubeflow-kfam")
    pebble_plan = harness.get_container_pebble_plan("kubeflow-kfam")
    assert pebble_plan
    assert pebble_plan._services
    pebble_plan_info = pebble_plan.to_dict()
    assert (
        pebble_plan_info["services"]["kubeflow-kfam"]["command"]
        == "/access-management "  # noqa: W503
        "-cluster-admin "
        "admin "
        "-userid-header "
        "kubeflow-userid "
        "-userid-prefix "
        '""'
    )


@patch.object(KubeflowProfilesOperator, "create_profile")
def test_on_create_profile_action(
    create_profile,
    harness,
    mocked_kubernetes_service_patcher,
    mocked_resource_handler,
):
    """Test that create_profile method is called on create-profile action."""
    harness.begin()
    harness.set_leader(True)

    auth_username = "admin"
    profile_name = "username"
    resource_quota = """
    {
    "hard": {
        "cpu": "2",
        "memory": "2Gi",
        "requests.nvidia.com/gpu": "1",
        "persistentvolumeclaims": "1",
        "requests.storage": "5Gi"
                }
        }
    """
    create_global_resource(
        group="kubeflow.org", version="v1alpha1", kind="PodDefault", plural="poddefaults"
    )
    formatted_quota = json.loads(resource_quota)
    event = MagicMock(spec=ActionEvent)
    event.params = {
        "username": auth_username,
        "profilename": profile_name,
        "resourcequota": formatted_quota,
    }
    harness.charm.on_create_profile_action(event)

    create_profile.assert_called_with(auth_username, profile_name, formatted_quota, event)


@patch.object(KubeflowProfilesOperator, "configure_profile")
def test_on_initialise_profile_action(
    configure_profile,
    harness,
    mocked_kubernetes_service_patcher,
    mocked_resource_handler,
):
    """Test that configure_profile method is called on initialise-profile action."""
    harness.begin()
    harness.set_leader(True)
    event = MagicMock(spec=ActionEvent)
    profile_name = "username"
    event.params = {
        "profilename": profile_name,
    }
    harness.charm.on_initialise_profile_action(event)

    configure_profile.assert_called_with(profile_name, event)


def test_copy_seldon_secret(
    harness,
    mocked_kubernetes_service_patcher,
    mocked_resource_handler,
    mocked_lightkube_client,
):
    """Test that seldon secret is copied to the profile's namespace with the correct values."""
    profile_name = "username"
    seldon_secret = Secret(
        metadata=ObjectMeta(name="mlflow-server-seldon-init-container-s3-credentials"),
        kind="Secret",
        apiVersion="v1",
        data={
            "RCLONE_CONFIG_S3_TYPE": "s3",
            "RCLONE_CONFIG_S3_PROVIDER": "minio",
            "RCLONE_CONFIG_S3_ACCESS_KEY_ID": "minio",
            "RCLONE_CONFIG_S3_SECRET_ACCESS_KEY": "minio123",
            "RCLONE_CONFIG_S3_ENDPOINT": "http://minio.kubeflow.svc.cluster.local:9000",
            "RCLONE_CONFIG_S3_ENV_AUTH": "false",
        },
        type="Opaque",
    )
    mocked_lightkube_client.get.return_value = seldon_secret
    event = MagicMock(spec=ActionEvent)
    harness.begin()
    harness.set_leader(True)
    harness.charm.k8s_resource_handler.lightkube_client = mocked_lightkube_client
    harness.charm._copy_seldon_secret(profile_name, event)
    harness.charm.k8s_resource_handler.lightkube_client.create.assert_called_with(
        Secret(
            metadata=ObjectMeta(name="seldon-init-container-secret"),
            kind="Secret",
            apiVersion=seldon_secret.apiVersion,
            data=seldon_secret.data,
            type=seldon_secret.type,
        ),
        namespace=profile_name,
    )
