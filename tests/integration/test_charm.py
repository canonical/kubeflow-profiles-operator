# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
"""Integration tests for Kueflow Profiles Operator."""
import logging
from pathlib import Path

import lightkube
import pytest
import requests
import yaml
from charmed_kubeflow_chisme.testing import (
    assert_alert_rules,
    assert_logging,
    assert_metrics_endpoint,
    deploy_and_assert_grafana_agent,
    get_alert_rules,
)
from lightkube import codecs
from lightkube.generic_resource import create_global_resource
from lightkube.resources.core_v1 import Namespace
from lightkube.types import PatchType
from pytest_operator.plugin import OpsTest
from tenacity import retry, stop_after_delay, wait_exponential

log = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
CHARM_NAME = METADATA["name"]
ADMISSION_WEBHOOK_NAME = "admission-webhook"


@pytest.mark.abort_on_fail
@pytest.mark.skip_if_deployed
async def test_build_and_deploy(ops_test):
    """Build the charm-under-test and deploy it."""
    my_charm = await ops_test.build_charm(".")
    kfam_image_path = METADATA["resources"]["kfam-image"]["upstream-source"]
    profile_image_path = METADATA["resources"]["profile-image"]["upstream-source"]
    resources = {"kfam-image": kfam_image_path, "profile-image": profile_image_path}

    await ops_test.model.deploy(my_charm, resources=resources, trust=True)

    await ops_test.model.wait_for_idle(
        apps=[CHARM_NAME], status="active", raise_on_blocked=True, timeout=600
    )

    # Deploying grafana-agent-k8s and add all relations
    await deploy_and_assert_grafana_agent(
        ops_test.model, CHARM_NAME, metrics=True, dashboard=False, logging=True
    )


async def test_status(ops_test):
    """Assert on the unit status."""
    assert ops_test.model.applications[CHARM_NAME].units[0].workload_status == "active"


async def test_logging(ops_test: OpsTest):
    """Test logging is defined in relation data bag."""
    app = ops_test.model.applications[CHARM_NAME]
    await assert_logging(app)


async def test_alert_rules(ops_test):
    """Test check charm alert rules and rules defined in relation data bag."""
    app = ops_test.model.applications[CHARM_NAME]
    alert_rules = get_alert_rules()
    await assert_alert_rules(app, alert_rules)


async def test_metrics_enpoint(ops_test):
    """Test metrics_endpoints are defined in relation data bag and their accessibility.

    This function gets all the metrics_endpoints from the relation data bag, checks if
    they are available in current defined targets in Grafana agent.
    """
    app = ops_test.model.applications[CHARM_NAME]
    await assert_metrics_endpoint(app, metrics_port=8080, metrics_path="/metrics")
    await assert_metrics_endpoint(app, metrics_port=8081, metrics_path="/metrics")


# Parameterize to two different profiles?
async def test_profile_creation(lightkube_client, profile):
    """Test whether a namespace was created for this profile."""
    profile_name = profile
    validate_profile_namespace(lightkube_client, profile_name)


async def test_health_check_profiles(ops_test):
    """Test whether the profiles health check endpoint responds with 200."""
    status = await ops_test.model.get_status()
    profiles_units = status["applications"]["kubeflow-profiles"]["units"]
    profiles_url = profiles_units["kubeflow-profiles/0"]["address"]
    result = requests.get(f"http://{profiles_url}:8080/metrics")
    assert result.status_code == 200


async def test_health_check_kfam(ops_test):
    """Test whether the kfam health check endpoint responds with 200."""
    status = await ops_test.model.get_status()
    profiles_units = status["applications"]["kubeflow-profiles"]["units"]
    profiles_url = profiles_units["kubeflow-profiles/0"]["address"]
    result = requests.get(f"http://{profiles_url}:8081/metrics")
    assert result.status_code == 200


# Helpers
@pytest.fixture(scope="session")
def lightkube_client() -> lightkube.Client:
    """Initialize lightkube and create Profile resource."""
    client = lightkube.Client()
    create_global_resource(group="kubeflow.org", version="v1", kind="Profile", plural="profiles")
    return client


def _safe_load_file_to_text(filename: str):
    """Return the contents of filename if it is an existing file, else return filename."""
    try:
        text = Path(filename).read_text()
    except FileNotFoundError:
        text = filename
    return text


@pytest.fixture(scope="session")
def profile(lightkube_client):
    """Create a Profile object in cluster, cleaning it up after."""
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
    yaml_file: str, if_exists: [str, None] = None, lightkube_client: lightkube.Client = None
):
    """Create all k8s resources listed in a YAML file via lightkube.

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
                        type(obj), obj.metadata.name, obj.to_dict(), patch_type=PatchType.MERGE
                    )
                else:
                    raise ValueError(
                        f"Invalid value for if_exists '{if_exists}'.  "
                        f"Must be one of {ALLOWED_IF_EXISTS}"
                    )


def delete_all_from_yaml(yaml_file: str, lightkube_client: lightkube.Client = None):
    """Delete all k8s resources listed in a YAML file via lightkube.

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


@retry(wait=wait_exponential(multiplier=1, min=1, max=10), stop=stop_after_delay(30), reraise=True)
def validate_profile_namespace(
    client: lightkube.Client,
    profile_name: str,
    namespace_label_file: str = "./src/templates/namespace-labels.yaml",
):
    """Validate that a namespace for a Profile exists and has the expected properties.

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
