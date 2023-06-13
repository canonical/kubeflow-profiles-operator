# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
"""Define Unit tests fixtures."""
from unittest.mock import MagicMock

import pytest
from ops.testing import Harness

from charm import KubeflowProfilesOperator


@pytest.fixture
def harness():
    """Initialize Harness instance."""
    harness = Harness(KubeflowProfilesOperator)
    harness.set_can_connect("kubeflow-profiles", True)
    harness.set_can_connect("kubeflow-kfam", True)
    return harness


@pytest.fixture()
def mocked_lightkube_client(mocker):
    """Mocks the Lightkube Client in charm.py, returning a mock instead."""
    mocked_lightkube_client = MagicMock()
    mocked_lightkube_client_class = mocker.patch("charm.lightkube.Client", return_value=mocked_lightkube_client)
    yield mocked_lightkube_client
