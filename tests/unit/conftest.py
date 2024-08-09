# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
"""Define Unit tests fixtures."""
from unittest.mock import MagicMock

import pytest
from ops.testing import Harness

from charm import KubeflowProfilesOperator, KubernetesServicePatch


@pytest.fixture
def harness():
    """Initialize Harness instance."""
    harness = Harness(KubeflowProfilesOperator)
    harness.set_can_connect("kubeflow-profiles", True)
    harness.set_can_connect("kubeflow-kfam", True)
    return harness


@pytest.fixture()
def mocked_kubernetes_service_patcher(mocker):
    """Mock K8S Service Patch and Namespace."""
    mocker.patch.object(KubernetesServicePatch, "_namespace", lambda x, y: "")
    mocker.patch.object(KubernetesServicePatch, "_patch", lambda x, y: None)

    yield


@pytest.fixture()
def mocked_resource_handler(mocker):
    """Mock K8S Resource Handler."""
    mocked_resource_handler = mocker.patch("charm.KRH")
    mocked_resource_handler.return_value = MagicMock()
    yield mocked_resource_handler


@pytest.fixture()
def mocked_lightkube_client(mocker, mocked_resource_handler):
    """Prevents lightkube clients from being created, returning a mock instead."""
    mocked_resource_handler.lightkube_client = MagicMock()
    yield mocked_resource_handler.lightkube_client
