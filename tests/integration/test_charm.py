# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from pathlib import Path

import lightkube
import pytest
import yaml
from lightkube import codecs
from lightkube.generic_resource import create_global_resource
from lightkube.resources.core_v1 import Namespace
from lightkube.types import PatchType
from tenacity import retry, stop_after_delay, wait_exponential

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


# Parameterize to two different profiles?
async def test_profile_creation(lightkube_client, profile):
    # Test whether a namespace was created for this profile
    profile_name = profile
    validate_profile_namespace(lightkube_client, profile_name)


# Helpers
@pytest.fixture(scope="session")
def lightkube_client() -> lightkube.Client:
    client = lightkube.Client()
    create_global_resource(group="kubeflow.org", version="v1", kind="Profile", plural="profiles")
    return client


def _safe_load_file_to_text(filename: str):
    """Returns the contents of filename if it is an existing file, else it returns filename"""
    try:
        text = Path(filename).read_text()
    except FileNotFoundError:
        text = filename
    return text


@pytest.fixture()
def profile(lightkube_client):
    """Creates a Profile object in cluster, cleaning it up after"""
    profile_file = "./tests/integration/profile.yaml"
    yaml_text = _safe_load_file_to_text(profile_file)
    yaml_rendered = yaml.safe_load(yaml_text)
    profilename = yaml_rendered["metadata"]["name"]

    create_all_from_yaml(yaml_file=yaml_text, lightkube_client=lightkube_client)
    yield profilename

    delete_all_from_yaml(yaml_text, lightkube_client)


ALLOWED_IF_EXISTS = (None, "replace", "patch")


def _validate_if_exists(if_exists):
    if if_exists in ALLOWED_IF_EXISTS:
        return if_exists
    else:
        raise ValueError(
            f"Invalid value for if_exists '{if_exists}'.  Must be one of {ALLOWED_IF_EXISTS}"
        )


def create_all_from_yaml(
    yaml_file: str,
    if_exists: [str, None] = None,
    lightkube_client: lightkube.Client = None,
):
    """Creates all k8s resources listed in a YAML file via lightkube

    Args:
        yaml_file (str or Path): Either a string filename or a string of valid YAML.  Will attempt
                                 to open a filename at this path, failing back to interpreting the
                                 string directly as YAML.
        if_exists (str): If an object to create already exists, do one of:
            patch: Try to lightkube.patch the existing resource
            replace: Try to lightkube.replace the existing resource (not yet implemented)
            None: Do nothing (lightkube.core.exceptions.ApiError will be raised)
        lightkube_client: Instantiated lightkube client or None
    """
    _validate_if_exists(if_exists)

    yaml_text = _safe_load_file_to_text(yaml_file)

    if lightkube_client is None:
        lightkube_client = lightkube.Client()

    for obj in codecs.load_all_yaml(yaml_text):
        try:
            lightkube_client.create(obj)
        except lightkube.core.exceptions.ApiError as e:
            if if_exists is None:
                raise e
            else:
                log.info(
                    f"Caught {e.status} when creating {obj.metadata.name}.  Trying to {if_exists}"
                )
                if if_exists == "replace":
                    raise NotImplementedError()
                    # Not sure what is wrong with this syntax but it wouldn't work
                elif if_exists == "patch":
                    lightkube_client.patch(
                        type(obj),
                        obj.metadata.name,
                        obj.to_dict(),
                        patch_type=PatchType.MERGE,
                    )
                else:
                    raise ValueError(
                        f"Invalid value for if_exists '{if_exists}'.  "
                        f"Must be one of {ALLOWED_IF_EXISTS}"
                    )


def delete_all_from_yaml(yaml_file: str, lightkube_client: lightkube.Client = None):
    """Deletes all k8s resources listed in a YAML file via lightkube

    Args:
        yaml_file (str or Path): Either a string filename or a string of valid YAML.  Will attempt
                                 to open a filename at this path, failing back to interpreting the
                                 string directly as YAML.
        lightkube_client: Instantiated lightkube client or None
    """
    yaml_text = _safe_load_file_to_text(yaml_file)

    if lightkube_client is None:
        lightkube_client = lightkube.Client()

    for obj in codecs.load_all_yaml(yaml_text):
        lightkube_client.delete(type(obj), obj.metadata.name)


@retry(
    wait=wait_exponential(multiplier=1, min=1, max=10),
    stop=stop_after_delay(30),
    reraise=True,
)
def validate_profile_namespace(
    client: lightkube.Client,
    profile_name: str,
    namespace_label_file: str = "./files/namespace-labels.yaml",
):
    """Validates that a namespace for a Profile exists and has the expected properties

    Retries multiple times using tenacity to allow time for profile-controller to create the
    namespace
    """
    # Get required labels
    namespace_label_file = Path(namespace_label_file)
    namespace_labels = yaml.safe_load(namespace_label_file.read_text())

    # Check namespace exists and has labels
    namespace = client.get(Namespace, profile_name)
    for name, expected_value in namespace_labels.items():
        assert (
            name in namespace.metadata.labels
        ), f"Label '{name}' missing from Profile's Namespace"
        actual_value = namespace.metadata.labels[name]
        assert expected_value == actual_value, (
            f"Label '{name}' on Profile's Namespace has value '{actual_value}', "
            f"expected '{expected_value}'"
        )
