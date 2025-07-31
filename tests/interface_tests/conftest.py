# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Define Interface tests fixtures."""

import pytest
from interface_tester.plugin import InterfaceTester
from ops.framework import Object

from charm import KubeflowProfilesOperator


@pytest.fixture(autouse=True)
def patch_kubernetes_service_patch(mocker):
    """Patch KubernetesServicePatch to avoid actual Kubernetes interactions."""

    class DummyPatcher(Object):
        def __init__(
            self,
            charm,
            ports,
            service_name=None,
            service_type="",
            additional_labels=None,
            additional_selectors=None,
            additional_annotations=None,
            *,
            refresh_event=None,
        ):
            super().__init__(charm, "dummy-service-patcher")

        def _patch(self, event):
            pass

    mocker.patch("charm.KubernetesServicePatch", new=DummyPatcher)


@pytest.fixture
def interface_tester(interface_tester: InterfaceTester):
    """Fixture to configure the interface tester for KubeflowProfilesOperator."""
    interface_tester.configure(charm_type=KubeflowProfilesOperator)
    yield interface_tester
