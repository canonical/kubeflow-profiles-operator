# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import pytest
from ops.model import ActiveStatus, BlockedStatus, WaitingStatus
from ops.testing import Harness

from charm import KubeflowProfilesOperator


@pytest.fixture
def harness():
    return Harness(KubeflowProfilesOperator)


def test_not_leader(harness):
    harness.begin_with_initial_hooks()
    assert harness.charm.model.unit.status == WaitingStatus("Waiting for leadership")


def test_missing_image(harness):
    harness.set_leader(True)
    harness.begin_with_initial_hooks()
    assert harness.charm.model.unit.status == BlockedStatus(
        "Missing resource: profile-image"
    )


def test_no_relation(harness):
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

    _ = harness.get_pod_spec()
    assert harness.charm.model.unit.status == ActiveStatus("")
