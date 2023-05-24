# Copyright 2021 Canonical Ltd.
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

from .test_operator_fixtures import (  # noqa F401
    harness,
    mocked_kubernetes_service_patcher,
    mocked_lightkube_client,
    mocked_resource_handler,
)


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
    # Get the plan now tha we've run PebbleReady
    updated_plan = harness.get_container_pebble_plan(container_name).to_dict()
    assert updated_plan == expected_plan
    assert harness.model.unit.get_container(container_name).get_service(container_name).is_running()
