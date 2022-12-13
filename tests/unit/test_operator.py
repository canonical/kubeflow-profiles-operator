# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.
from ops.model import ActiveStatus, WaitingStatus


def test_not_leader(
    harness,
    mocked_kubernetes_service_patcher,
    mocked_resource_handler,
):
    harness.begin_with_initial_hooks()
    harness.container_pebble_ready("kubeflow-profiles")
    harness.container_pebble_ready("kubeflow-kfam")
    assert harness.charm.model.unit.status == WaitingStatus("Waiting for leadership")


def test_profiles_container_running(
    harness,
    mocked_kubernetes_service_patcher,
    mocked_resource_handler,
):
    harness.set_leader(True)
    harness.begin_with_initial_hooks()
    harness.container_pebble_ready("kubeflow-profiles")
    assert harness.charm.profiles_container.get_service(
        "kubeflow-profiles"
    ).is_running()


def test_kfam_container_running(
    harness,
    mocked_kubernetes_service_patcher,
    mocked_resource_handler,
):
    harness.set_leader(True)
    harness.begin_with_initial_hooks()
    harness.container_pebble_ready("kubeflow-kfam")
    assert harness.charm.kfam_container.get_service("kubeflow-kfam").is_running()


def test_no_relation(
    harness,
    mocked_kubernetes_service_patcher,
    mocked_resource_handler,
):
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
    harness,
    mocked_kubernetes_service_patcher,
    mocked_resource_handler,
):
    """Test creation of Pebble layer. Only testing specific items."""
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
    harness,
    mocked_kubernetes_service_patcher,
    mocked_resource_handler,
):
    """Test creation of Pebble layer. Only testing specific items."""
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
