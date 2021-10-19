import logging
from pathlib import Path
from subprocess import run

import yaml

import pytest

log = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())


@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test):
    my_charm = await ops_test.build_charm(".")
    kfam_image_path = METADATA["resources"]["kfam-image"]["upstream-source"]
    profile_image_path = METADATA["resources"]["profile-image"]["upstream-source"]
    resources = {
        "kfam-image": kfam_image_path,
        "profile-image": profile_image_path,
    }

    await ops_test.model.deploy(my_charm, resources=resources)
    await ops_test.model.deploy("cs:kubeflow-dashboard")
    await ops_test.model.add_relation("kubeflow-profiles", "kubeflow-dashboard")

    await ops_test.model.block_until(
        lambda: all(
            (unit.workload_status == "active") and unit.agent_status == "idle"
            for _, application in ops_test.model.applications.items()
            for unit in application.units
        ),
        timeout=600,
    )


async def test_status(ops_test):
    charm_name = METADATA["name"]
    assert ops_test.model.applications[charm_name].units[0].workload_status == "active"


async def test_profile_creation(ops_test):
    run(["juju", "switch", ops_test.model_full_name])
    run(["juju", "kubectl", "apply", "-f", "./tests/integration/profile.yaml"])
    # TODO: This does not assert anything, and may be failing in CI.  This should assert that a
    #  namespace with the expected metadata (see label CRD) is created
