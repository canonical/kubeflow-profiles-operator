# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.
"""Unit tests. Harness and Mocks are defined in test_operator_fixtures.py."""
from typing import Optional

import pytest
import yaml
from ops import MaintenanceStatus

from ops.model import ActiveStatus, BlockedStatus, WaitingStatus
from ops.testing import Harness

from .test_operator_fixtures import (  # noqa F401
    harness,
    mocked_kubernetes_service_patcher,
    mocked_lightkube_client,
    mocked_resource_handler,
)


@pytest.fixture()
def mocked_lightkube_client_in_sunbeam_kubernetes_resource_handler(mocker):
    mocked_resource_handler = mocker.patch("charm.")


def test_profiles_pebble_ready(harness):
    harness.begin_with_initial_hooks()

    container_name = "kubeflow-profiles"

    expected_plan = {
        "services": {
            "kubeflow-profiles": {
                "override": "replace",
                "summary": "entry point for kubeflow profiles",
                "command": (
                    "/manager " "-userid-header " "kubeflow-userid " "-userid-prefix " '""'
                ),
                "startup": "enabled",
            }
        }
    }

    # Simulate the container coming up and emission of pebble-ready event
    harness.container_pebble_ready(container_name)
    # Get the plan now that we've run PebbleReady
    updated_plan = harness.get_container_pebble_plan(container_name).to_dict()
    assert updated_plan == expected_plan
    assert harness.model.unit.get_container(container_name).get_service(container_name).is_running()


def test_kubeflow_profiles_provides_relation_success(harness: Harness, mocker):
    harness.set_leader(True)
    mocked_lightkube_client = mocker.patch("charm.lightkube.Client")
    harness.begin_with_initial_hooks()

    add_kubeflow_profiles_to_harness_with_version(harness)

    assert isinstance(harness.model.unit.status, MaintenanceStatus)

    harness.charm.on.update_status.emit()
    assert isinstance(harness.model.unit.status, ActiveStatus)


def test_kubeflow_profiles_provides_relation_no_version(harness: Harness):
    harness.set_leader(True)
    harness.begin_with_initial_hooks()

    kubeflow_profiles_relation_info = add_kubeflow_profiles_to_harness_no_version(harness)
    # Proc the data changed event.
    # Not sure why but this didn't work.
    harness.charm.on["kubeflow-profiles"].relation_changed.emit(harness.model.get_relation("kubeflow-profiles", kubeflow_profiles_relation_info["rel_id"]))

    assert isinstance(harness.model.unit.status, WaitingStatus)


def test_kubeflow_profiles_provides_relation_bad_version(harness: Harness):
    harness.set_leader(True)
    harness.begin_with_initial_hooks()

    kubeflow_profiles_relation_info = add_kubeflow_profiles_to_harness_with_bad_version(harness)
    # Proc the data changed event.
    # Not sure why but this didn't work.
    harness.charm.on["kubeflow-profiles"].relation_changed.emit(harness.model.get_relation("kubeflow-profiles", kubeflow_profiles_relation_info["rel_id"]))

    assert isinstance(harness.model.unit.status, BlockedStatus)


def add_kubeflow_profiles_to_harness_no_version(harness: Harness, other_app="other") -> dict:
    """Relates a new app and unit to the kubeflow-profiles relation but does not provide a version.

    Returns dict of:
    * other (str): The name of the other app
    * other_unit (str): The name of the other unit
    * rel_id (int): The relation id
    * data (dict): The relation data put to the relation
    """
    other_unit = f"{other_app}/0"
    rel_id = harness.add_relation("kubeflow-profiles", other_app)

    harness.add_relation_unit(rel_id, other_unit)
    data = {}

    return {
        "other_app": other_app,
        "other_unit": other_unit,
        "rel_id": rel_id,
        "data": data,
    }


def add_kubeflow_profiles_to_harness_with_version(harness: Harness, other_app="other") -> dict:
    """Relates a new app and unit to the kubeflow-profiles relation and provides a version.

    Returns dict of:
    * other (str): The name of the other app
    * other_unit (str): The name of the other unit
    * rel_id (int): The relation id
    * data (dict): The relation data put to the relation
    """
    other_unit = f"{other_app}/0"
    rel_id = harness.add_relation("kubeflow-profiles", other_app)

    harness.add_relation_unit(rel_id, other_unit)
    # Add data, in this case just empty data with a sdi version
    data = {}
    add_data_to_sdi_relation(harness, rel_id, other_app, data, supported_versions="- v1")

    return {
        "other_app": other_app,
        "other_unit": other_unit,
        "rel_id": rel_id,
        "data": data,
    }


def add_kubeflow_profiles_to_harness_with_bad_version(harness: Harness, other_app="other") -> dict:
    """Relates a new app and unit to the kubeflow-profiles relation and provides a version.

    Returns dict of:
    * other (str): The name of the other app
    * other_unit (str): The name of the other unit
    * rel_id (int): The relation id
    * data (dict): The relation data put to the relation
    """
    other_unit = f"{other_app}/0"
    rel_id = harness.add_relation("kubeflow-profiles", other_app)

    harness.add_relation_unit(rel_id, other_unit)
    # Add data, in this case just empty data with a sdi version
    data = {}
    add_data_to_sdi_relation(harness, rel_id, other_app, data, supported_versions="- v1000")

    return {
        "other_app": other_app,
        "other_unit": other_unit,
        "rel_id": rel_id,
        "data": data,
    }


def add_data_to_sdi_relation(
        harness: Harness,
        rel_id: str,
        other: str,
        data: Optional[dict] = None,
        supported_versions: str = "- v1",
) -> None:
    """Add data to an SDI-backed relation."""
    if data is None:
        data = {}

    harness.update_relation_data(
        rel_id,
        other,
        {"_supported_versions": supported_versions, "data": yaml.dump(data)},
    )
