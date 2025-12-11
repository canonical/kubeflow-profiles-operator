# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
"""Unit tests. Harness and Mocks are defined in test_operator_fixtures.py."""
from unittest.mock import ANY, patch

import pytest
from ops.model import ActiveStatus, BlockedStatus, WaitingStatus
from ops.testing import Harness


def test_log_forwarding(
    harness: Harness,
    mocked_kubernetes_service_patcher,
    mocked_resource_handler,
):
    """Test LogForwarder initialization."""
    with patch("charm.LogForwarder") as mock_logging:
        harness.begin()
        mock_logging.assert_called_once_with(charm=harness.charm)


def test_metrics(
    harness: Harness,
    mocked_kubernetes_service_patcher,
    mocked_resource_handler,
):
    """Test MetricsEndpointProvider initialization."""
    with patch("charm.MetricsEndpointProvider") as mocked_metrics_endpoint_provider:
        harness.begin()
        mocked_metrics_endpoint_provider.assert_called_once_with(
            harness.charm,
            jobs=[{"static_configs": [{"targets": ["*:8080", "*:8081"]}]}],
            refresh_event=[ANY, ANY],  # Note(rgildein): representing pebble_ready services
        )


def test_not_leader(
    harness: Harness,
    mocked_kubernetes_service_patcher,
    mocked_resource_handler,
):
    """Test not a leader scenario."""
    harness.set_leader(False)
    harness.begin_with_initial_hooks()
    harness.container_pebble_ready("kubeflow-profiles")
    harness.container_pebble_ready("kubeflow-kfam")
    assert harness.charm.model.unit.status == WaitingStatus("Waiting for leadership")


def test_storage_not_available(
    harness: Harness,
    mocked_kubernetes_service_patcher,
    mocked_resource_handler,
):
    """Test storage not available scenario."""
    # begin() is required to access charm attribute of harness
    harness.begin()
    # retrieve first (and only) storage ID for config-profiles storage
    storage_id = harness.charm.model.storages["config-profiles"][0].full_id
    # remove storage so that the storage check fails
    harness.remove_storage(storage_id)
    # trigger any event observed by the main hook handler
    harness.charm.on.config_changed.emit()
    assert isinstance(harness.charm.model.unit.status, WaitingStatus)
    assert "Waiting for storage" in harness.charm.model.unit.status.message


@pytest.mark.parametrize("invalid_port", [80, 100000])
def test_invalid_port(
    harness: Harness,
    mocked_kubernetes_service_patcher,
    mocked_resource_handler,
    invalid_port: int,
):
    """Test that the charm is properly blocking on invalid port."""
    harness.update_config({"port": invalid_port})
    harness.begin_with_initial_hooks()
    assert isinstance(harness.charm.model.unit.status, BlockedStatus)
    assert "Invalid config:" in harness.charm.model.unit.status.message


@pytest.mark.parametrize("invalid_port", [80, 100000])
def test_invalid_manager_port(
    harness: Harness, mocked_kubernetes_service_patcher, mocked_resource_handler, invalid_port: int
):
    """Test that the charm is properly blocking on an invalid manager port."""
    harness.update_config({"manager-port": invalid_port})
    harness.begin_with_initial_hooks()
    assert isinstance(harness.charm.model.unit.status, BlockedStatus)
    assert "Invalid config:" in harness.charm.model.unit.status.message


def test_invalid_security_policy(
    harness: Harness,
    mocked_kubernetes_service_patcher,
    mocked_resource_handler,
):
    """Test that the charm is properly blocking on invalid security policy."""
    harness.update_config({"security-policy": "invalid-value"})
    harness.begin_with_initial_hooks()
    assert isinstance(harness.charm.model.unit.status, BlockedStatus)
    assert "Invalid config:" in harness.charm.model.unit.status.message


def test_profiles_container_running(
    harness: Harness,
    mocked_kubernetes_service_patcher,
    mocked_resource_handler,
):
    """Test that kubeflow-profiles container is running."""
    harness.begin_with_initial_hooks()
    harness.container_pebble_ready("kubeflow-profiles")
    assert harness.charm.profiles_container.get_service("kubeflow-profiles").is_running()


def test_kfam_container_running(
    harness: Harness,
    mocked_kubernetes_service_patcher,
    mocked_resource_handler,
):
    """Test that kubeflow-kfam container is running."""
    harness.begin_with_initial_hooks()
    harness.container_pebble_ready("kubeflow-kfam")
    assert harness.charm.kfam_container.get_service("kubeflow-kfam").is_running()


def test_no_relation(
    harness: Harness,
    mocked_kubernetes_service_patcher,
    mocked_resource_handler,
):
    """Test no relation scenario."""
    harness.add_oci_resource(
        "profile-image", {"registrypath": "ci-test", "username": "", "password": ""}
    )
    harness.add_oci_resource(
        "kfam-image", {"registrypath": "ci-test", "username": "", "password": ""}
    )
    harness.begin_with_initial_hooks()
    assert harness.charm.model.unit.status == ActiveStatus("")


def test_profiles_pebble_ready_first_scenario(
    harness: Harness,
    mocked_kubernetes_service_patcher,
    mocked_resource_handler,
):
    """Test (install -> profiles pebble ready -> kfam pebble ready) reach Active.."""
    harness.begin()
    harness.charm.on.install.emit()
    harness.container_pebble_ready("kubeflow-profiles")
    harness.container_pebble_ready("kubeflow-kfam")
    assert harness.charm.model.unit.status == ActiveStatus("")


def test_kfam_pebble_ready_first_scenario(
    harness: Harness,
    mocked_kubernetes_service_patcher,
    mocked_resource_handler,
):
    """Test (install -> kfam pebble ready -> profiles pebble ready) reach Active."""
    harness.begin()
    harness.charm.on.install.emit()
    harness.container_pebble_ready("kubeflow-kfam")
    harness.container_pebble_ready("kubeflow-profiles")
    assert harness.charm.model.unit.status == ActiveStatus("")


def test_profiles_pebble_layer(
    harness: Harness,
    mocked_kubernetes_service_patcher,
    mocked_resource_handler,
):
    """Test creation of Profiles Pebble layer. Only testing specific items."""
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
    harness: Harness,
    mocked_kubernetes_service_patcher,
    mocked_resource_handler,
):
    """Test creation of kfam Pebble layer. Only testing specific items."""
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
