# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.
"""Integration tests for Kueflow Profiles Operator."""
import logging
from pathlib import Path

import jinja2
import lightkube
import pytest
import requests
import yaml
from charmed_kubeflow_chisme.testing import (
    assert_alert_rules,
    assert_logging,
    assert_metrics_endpoint,
    assert_path_reachable_through_ingress,
    deploy_and_assert_grafana_agent,
    deploy_and_integrate_service_mesh_charms,
    get_alert_rules,
)
from charms_dependencies import KUBEFLOW_DASHBOARD
from lightkube import codecs
from lightkube.generic_resource import create_global_resource, create_namespaced_resource
from lightkube.resources.core_v1 import Namespace
from lightkube.types import PatchType
from pytest_operator.plugin import OpsTest
from tenacity import retry, stop_after_delay, wait_exponential

log = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
CHARM_NAME = METADATA["name"]

CONFIG_DATA = yaml.safe_load(Path("./config.yaml").read_text())
DEFAULT_SECURITY_POLICY = CONFIG_DATA["options"]["security-policy"]["default"]

ISTIO_GATEWAY_PRINCIPAL = "cluster.local/ns/kubeflow/sa/istio-ingress-k8s-istio"
JUPYTER_CONTROLLER_PRINCIPAL = "cluster.local/ns/kubeflow/sa/jupyter-controller"
KFP_UI_PRINCIPAL = "cluster.local/ns/kubeflow/sa/kfp-ui"
AMBIENT_CONFIG = {
    "service-mesh-mode": "istio-ambient",
    "istio-gateway-principal": ISTIO_GATEWAY_PRINCIPAL,
}

AUTHORIZATION_POLICY = create_namespaced_resource(
    group="security.istio.io",
    version="v1",
    kind="AuthorizationPolicy",
    plural="authorizationpolicies",
)

GATEWAY = create_namespaced_resource(
    group="gateway.networking.k8s.io",
    version="v1",
    kind="Gateway",
    plural="gateways",
)

AUTH_POLICY_NAME = "ns-owner-access-istio"


@pytest.mark.abort_on_fail
@pytest.mark.skip_if_deployed
async def test_build_and_deploy(ops_test: OpsTest):
    """Build and deploy the charm and its dependencies."""
    my_charm = await ops_test.build_charm(".")
    kfam_image_path = METADATA["resources"]["kfam-image"]["upstream-source"]
    profile_image_path = METADATA["resources"]["profile-image"]["upstream-source"]
    resources = {"kfam-image": kfam_image_path, "profile-image": profile_image_path}

    await ops_test.model.deploy(my_charm, resources=resources, config=AMBIENT_CONFIG, trust=True)

    await ops_test.model.wait_for_idle(
        apps=[CHARM_NAME], status="active", raise_on_blocked=True, timeout=600
    )

    await deploy_and_integrate_service_mesh_charms(
        app=CHARM_NAME, model=ops_test.model, relate_to_ingress=False
    )

    # Deploying grafana-agent-k8s and add all relations
    await deploy_and_assert_grafana_agent(
        ops_test.model, CHARM_NAME, metrics=True, dashboard=False, logging=True
    )

    # Deploy Kubeflow Dashboard and relate to the charm
    ops_test.model.deploy(
        KUBEFLOW_DASHBOARD.charm,
        channel=KUBEFLOW_DASHBOARD.channel,
        trust=KUBEFLOW_DASHBOARD.trust,
    )

    await ops_test.model.relate(KUBEFLOW_DASHBOARD.charm, CHARM_NAME)

    # Wait for everything to be active and idle
    await ops_test.model.wait_for_idle(
        [KUBEFLOW_DASHBOARD.charm, CHARM_NAME],
        status="active",
        raise_on_error=True,
        timeout=600,
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
    validate_profile_namespace(lightkube_client, profile_name, DEFAULT_SECURITY_POLICY)


async def test_config_option_propagation(ops_test, lightkube_client, profile):
    """Test that changes to the security policy are properly propagated."""
    new_security_policy = "baseline"
    await ops_test.model.applications[CHARM_NAME].set_config(
        {"security-policy": new_security_policy}
    )

    await ops_test.model.wait_for_idle(
        apps=[CHARM_NAME], status="active", raise_on_blocked=True, timeout=600
    )

    profile_name = profile
    validate_profile_namespace(lightkube_client, profile_name, new_security_policy)

    # Change back to the default value
    await ops_test.model.applications[CHARM_NAME].set_config(
        {"security-policy": DEFAULT_SECURITY_POLICY}
    )
    await ops_test.model.wait_for_idle(
        apps=[CHARM_NAME], status="active", raise_on_blocked=True, timeout=600
    )

    profile_name = profile
    validate_profile_namespace(lightkube_client, profile_name, DEFAULT_SECURITY_POLICY)


@retry(wait=wait_exponential(multiplier=1, min=1, max=10), stop=stop_after_delay(60), reraise=True)
async def test_waypoint_gateway_created_for_profile(
    ops_test: OpsTest, lightkube_client: lightkube.Client, profile
):
    """Test whether the waypoint gateway is created in the profile namespace."""
    gateway_objects = list(lightkube_client.list(res=GATEWAY, namespace=profile))
    assert (
        len(gateway_objects) == 1
    ), f"Expected 1 Gateway object in namespace '{profile}', found {len(gateway_objects)}"


async def test_authorization_policy_has_correct_principals(
    ops_test: OpsTest, lightkube_client: lightkube.Client, profile
):
    """Test whether the authorization policy contains the three configured principals."""

    @retry(
        wait=wait_exponential(multiplier=1, min=1, max=10), stop=stop_after_delay(60), reraise=True
    )
    def get_auth_policy():
        return lightkube_client.get(
            res=AUTHORIZATION_POLICY, name=AUTH_POLICY_NAME, namespace=profile
        )

    ns_owner_auth_policy = get_auth_policy()

    # Convert the policy to a string to search for principals
    policy_str = str(ns_owner_auth_policy.to_dict())

    # Check that all three principals are mentioned in the policy
    assert (
        ISTIO_GATEWAY_PRINCIPAL in policy_str
    ), f"Expected principal {ISTIO_GATEWAY_PRINCIPAL} not found in authorization policy"
    assert (
        JUPYTER_CONTROLLER_PRINCIPAL in policy_str
    ), f"Expected principal {JUPYTER_CONTROLLER_PRINCIPAL} not found in authorization policy"
    assert (
        KFP_UI_PRINCIPAL in policy_str
    ), f"Expected principal {KFP_UI_PRINCIPAL} not found in authorization policy"


async def test_dashboard_to_kfam_communication(ops_test: OpsTest):
    """
    Test dashboard -> Central Dashboard -> KFAM communication via the ambient mesh.

    The frontend (browser) that shows the profiles dropdown sends a request to the
    Central Dashboard API (`/api/workgroup/exists`) to obtain profile
    information. The Central Dashboard will in turn make a request to KFAM to resolve
    or validate the requested workgroup information. This test exercises that
    end-to-end path through the ambient service mesh so we verify the Central Dashboard
    can reach KFAM and return information to the frontend.
    """
    await assert_path_reachable_through_ingress(
        http_path="/api/workgroup/exists",
        namespace=ops_test.model.name,
        headers={"kubeflow-userid": "test"},
        expected_status=200,
    )


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
    yaml_file: str, if_exists: str | None = None, lightkube_client: lightkube.Client = None
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
    security_policy_value: str,
    namespace_label_file: str = "./src/templates/namespace-labels.yaml.j2",
):
    """Validate that a namespace for a Profile exists and has the expected properties.

    Retries multiple times using tenacity to allow time for profile-controller to create the
    namespace
    """
    # Get required labels
    with open(namespace_label_file, encoding="utf-8") as labels_file:
        labels = labels_file.read()
    template = jinja2.Template(labels)
    rendered_string = template.render(security_policy=security_policy_value)
    namespace_labels = yaml.safe_load(rendered_string)

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
