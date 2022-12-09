# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

from unittest.mock import MagicMock

import pytest
from ops.testing import Harness

from charm import KubernetesServicePatch, KubeflowProfilesOperator


@pytest.fixture
def harness():
    harness = Harness(KubeflowProfilesOperator)
    # harness.set_leader(True)
    harness.set_can_connect("kubeflow-profiles", True)
    harness.set_can_connect("kubeflow-kfam", True)
    return harness


@pytest.fixture()
def mocked_kubernetes_service_patcher(mocker):
    mocker.patch.object(KubernetesServicePatch, "_namespace", lambda x, y: "")
    mocker.patch.object(KubernetesServicePatch, "_patch", lambda x, y: None)

    yield


@pytest.fixture()
def mocked_resource_handler(mocker):
    mocked_resource_handler = mocker.patch("charm.KRH")
    mocked_resource_handler.return_value = MagicMock()
    yield mocked_resource_handler
