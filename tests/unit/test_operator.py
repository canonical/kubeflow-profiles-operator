# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.
"""Unit tests. Harness and Mocks are defined in test_operator_fixtures.py."""
from dataclasses import dataclass
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest
import yaml
from ops.model import ActiveStatus, WaitingStatus
from ops.testing import Harness

from charm import NAMESPACE_LABELS_DESTINATION_PATH

from .test_operator_fixtures import (  # noqa F401
    harness,
    mocked_lightkube_client,
)


def test_not_leader(
    harness,  # noqa F811
    mocked_lightkube_client,  # noqa F811
    # mocked_kubernetes_service_patcher,  # noqa F811
    # mocked_resource_handler,  # noqa F811
):
    """Test not a leader scenario."""
    harness.begin_with_initial_hooks()
    assert harness.charm.model.unit.status == WaitingStatus("[leadership-gate] Waiting for leadership")


def test_profiles_container_running(
    harness,  # noqa F811
    mocked_lightkube_client,
):
    """Test that kubeflow-profiles container is running."""
    harness.set_leader(True)
    harness.begin()
    # Mock get_missing_kubernetes_resources to always return an empty list.
    harness.charm.kubernetes_resources_component_item.component._get_missing_kubernetes_resources = MagicMock(return_value=[])

    harness.charm.on.install.emit()

    assert isinstance(harness.charm.unit.status, ActiveStatus)

    # Assert that we created the expected Kubernetes resources
    assert mocked_lightkube_client.apply.call_count == 3

    # Assert that our containers are up and services are running
    assert harness.charm.unit.get_container("kubeflow-profiles").get_service("kubeflow-profiles").is_running()
    assert harness.charm.unit.get_container("kubeflow-kfam").get_service("kubeflow-kfam").is_running()

    # TODO: Assert that we've pushed the expected files into the containers
    assert len(harness.charm.unit.get_container("kubeflow-profiles").list_files(path=NAMESPACE_LABELS_DESTINATION_PATH)) == 1

@pytest.mark.parametrize(
    "containers_not_yet_ready",
    [
        ("kubeflow-profiles", ),
        ("kubeflow-kfam", ),
        ("kubeflow-profiles", "kubeflow-kfam", ),
    ]
)
def test_install_first(harness, mocked_lightkube_client, containers_not_yet_ready):
    """Tests scenario where install event happens before containers are ready."""
    harness.set_leader(True)
    harness.begin()
    for container in containers_not_yet_ready:
        harness.set_can_connect(container, False)
    # Mock get_missing_kubernetes_resources to always return an empty list.
    harness.charm.kubernetes_resources_component_item.component._get_missing_kubernetes_resources = MagicMock(return_value=[])

    harness.charm.on.install.emit()

    # Assert that Kubernetes resources were created
    assert mocked_lightkube_client.apply.call_count == 3

    # but charm is waiting on PebbleComponents and thus is not active
    unit_status = harness.charm.unit.status
    assert isinstance(unit_status, WaitingStatus)
    assert "Waiting for Pebble" in unit_status.message


def test_with_kubeflow_profiles_relation(harness, mocked_lightkube_client):
    harness.set_leader(True)
    harness.begin()

    relation_data = add_kubeflow_relations_to_harness(harness, "other")

    # Assert that our charm has published the expected data to the related app
    assert harness.get_relation_data(relation_data.rel_id, harness.charm.app)




# Helpers


@dataclass
class AddRelationReturnData:
    other_app_name: str
    other_unit_name: str
    rel_id: int
    data: dict


def add_data_to_sdi_relation(
        harness: Harness,
        rel_id: str,
        other_app: str,
        data: Optional[dict] = None,
        supported_versions: str = "- v1",
) -> None:
    """Add data to the an SDI-backed relation."""
    if data is None:
        data = {}

    harness.update_relation_data(
        rel_id,
        other_app,
        {"_supported_versions": supported_versions, "data": yaml.dump(data)},
    )


def add_kubeflow_relations_to_harness(harness: Harness, other_app="other") -> AddRelationReturnData:
    """Relates a new app an unit to the kubeflow-profiles relation."""
    other_unit = f"{other_app}/0"
    rel_id = harness.add_relation("kubeflow-profiles", other_app)

    harness.add_relation_unit(rel_id, other_unit)
    data = {}
    add_data_to_sdi_relation(harness, rel_id, other_app, data)

    return AddRelationReturnData(
        other_app_name=other_app,
        other_unit_name=other_unit,
        rel_id=rel_id,
        data=data
    )
