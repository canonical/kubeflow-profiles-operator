# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.
"""Unit tests. Harness and Mocks are defined in test_operator_fixtures.py."""
from ops.model import ActiveStatus, WaitingStatus
from unittest.mock import patch, MagicMock
from ops.charm import ActionEvent
from lightkube.generic_resource import create_global_resource
from charmed_kubeflow_chisme.kubernetes import KubernetesResourceHandler as KRH

from .test_operator_fixtures import (  # noqa F401
    harness,
    mocked_kubernetes_service_patcher,
    mocked_resource_handler,
)
from charm import KubeflowProfilesOperator


def test_not_leader(
    harness,  # noqa F811
    mocked_kubernetes_service_patcher,  # noqa F811
    mocked_resource_handler,  # noqa F811
):
    """Test not a leader scenario."""
    harness.begin_with_initial_hooks()
    harness.container_pebble_ready("kubeflow-profiles")
    harness.container_pebble_ready("kubeflow-kfam")
    assert harness.charm.model.unit.status == WaitingStatus("Waiting for leadership")


def test_profiles_container_running(
    harness,  # noqa F811
    mocked_kubernetes_service_patcher,  # noqa F811
    mocked_resource_handler,  # noqa F811
):
    """Test that kubeflow-profiles container is running."""
    harness.set_leader(True)
    harness.begin_with_initial_hooks()
    harness.container_pebble_ready("kubeflow-profiles")
    assert harness.charm.profiles_container.get_service("kubeflow-profiles").is_running()


def test_kfam_container_running(
    harness,  # noqa F811
    mocked_kubernetes_service_patcher,  # noqa F811
    mocked_resource_handler,  # noqa F811
):
    """Test that kubeflow-kfam container is running."""
    harness.set_leader(True)
    harness.begin_with_initial_hooks()
    harness.container_pebble_ready("kubeflow-kfam")
    assert harness.charm.kfam_container.get_service("kubeflow-kfam").is_running()


def test_no_relation(
    harness,  # noqa F811
    mocked_kubernetes_service_patcher,  # noqa F811
    mocked_resource_handler,  # noqa F811
):
    """Test no relation scenario."""
    harness.set_leader(True)
    harness.add_oci_resource(
        "profile-image",
        {
            "registrypath": "ci-test",
            "username": "",
            "password": "",
        },
    )
    harness.add_oci_resource(
        "kfam-image",
        {
            "registrypath": "ci-test",
            "username": "",
            "password": "",
        },
    )
    harness.begin_with_initial_hooks()
    assert harness.charm.model.unit.status == ActiveStatus("")


def test_profiles_pebble_layer(
    harness,  # noqa F811
    mocked_kubernetes_service_patcher,  # noqa F811
    mocked_resource_handler,  # noqa F811
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
        " "
        "-workload-identity "
        " "
    )


def test_kfam_pebble_layer(
    harness,  # noqa F811
    mocked_kubernetes_service_patcher,  # noqa F811
    mocked_resource_handler,  # noqa F811
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

@patch.object(KubeflowProfilesOperator,'create_profile')
def test_on_create_profile_action(
    create_profile,
    harness,  # noqa F811
    mocked_kubernetes_service_patcher,  # noqa F811
    mocked_resource_handler,  # noqa F811
):
    """Test that create_profile method is called on create-profile action."""

    harness.begin()
    harness.set_leader(True)

    auth_username = "admin"
    profile_name = "username"
    resource_quota="resourcequota"
    event = MagicMock(spec=ActionEvent)
    event.params = {
        "auth_username": auth_username,
        "profile_name": profile_name,
        "resource_quota":resource_quota
    }
    harness.charm.on_create_profile_action(event)

    create_profile.assert_called_with(auth_username,profile_name,resource_quota)