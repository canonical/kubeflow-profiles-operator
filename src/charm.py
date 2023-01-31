#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""A Juju Charm for Kubeflow Profiles Operator."""

import json
import logging
import traceback
from pathlib import Path

from charmed_kubeflow_chisme.exceptions import ErrorWithStatus
from charmed_kubeflow_chisme.kubernetes import KubernetesResourceHandler as KRH  # noqa: N817
from charmed_kubeflow_chisme.lightkube.batch import delete_many
from charmed_kubeflow_chisme.pebble import update_layer
from charms.observability_libs.v1.kubernetes_service_patch import KubernetesServicePatch
from lightkube import ApiError, codecs
from lightkube.generic_resource import create_global_resource, load_in_cluster_generic_resources
from lightkube.models.core_v1 import ServicePort
from lightkube.models.meta_v1 import ObjectMeta
from lightkube.resources.core_v1 import Namespace, Secret
from ops.charm import ActionEvent, CharmBase
from ops.framework import StoredState
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus, WaitingStatus
from ops.pebble import ChangeError, Layer
from serialized_data_interface import NoCompatibleVersions, NoVersionsListed, get_interfaces
from tenacity import RetryError, Retrying, stop_after_attempt, stop_after_delay, wait_exponential

K8S_RESOURCE_FILES = ["src/templates/auth_manifests.yaml.j2", "src/templates/crds.yaml.j2"]
NAMESPACE_LABELS_FILE = "src/templates/namespace-labels.yaml"
PROFILE_CONFIG_FILES = ["src/templates/allow-minio.yaml", "src/templates/allow-mlflow.yaml"]


class KubeflowProfilesOperator(CharmBase):
    """A Juju Charm for Kubeflow Profiles Operator."""

    _stored = StoredState()

    def __init__(self, *args):
        """Initialize charm and setup the container."""
        super().__init__(*args)

        self.log = logging.getLogger(__name__)

        self._manager_port = self.model.config["manager-port"]
        self._kfam_port = self.model.config["port"]

        manager_port = ServicePort(int(self._manager_port), name="manager")
        kfam_port = ServicePort(int(self._kfam_port), name="http")
        self.service_patcher = KubernetesServicePatch(
            self, [manager_port, kfam_port], service_name=f"{self.model.app.name}"
        )

        self._profiles_container_name = "kubeflow-profiles"
        self._profiles_container = self.unit.get_container(self._profiles_container_name)

        self._kfam_container_name = "kubeflow-kfam"
        self._kfam_container = self.unit.get_container(self._kfam_container_name)

        self._namespace = self.model.name
        self._name = self.model.app.name
        self._lightkube_field_manager = "lightkube"
        self._k8s_resource_handler = None

        self.framework.observe(self.on.config_changed, self.service_patcher._patch)
        self.framework.observe(self.on.remove, self._on_remove)

        for event in [
            self.on.install,
            self.on.leader_elected,
            self.on.upgrade_charm,
            self.on["kubeflow-profiles"].relation_changed,
            self.on.config_changed,
        ]:
            self.framework.observe(event, self.main)
        self.framework.observe(
            self.on.kubeflow_profiles_pebble_ready, self._on_kubeflow_profiles_ready
        )
        self.framework.observe(self.on.kubeflow_kfam_pebble_ready, self._on_kfam_ready)
        self.framework.observe(self.on.create_profile_action, self.on_create_profile_action)
        self.framework.observe(
            self.on.initialise_profile_action, self.on_initialise_profile_action
        )

    @property
    def profiles_container(self):
        """Return profiles container."""
        return self._profiles_container

    @property
    def kfam_container(self):
        """Return kfam container."""
        return self._kfam_container

    @property
    def _context(self):
        """Set up the context to be used for updating K8S resources."""
        context = {"app_name": self.model.app.name, "model_name": self.model.name}
        return context

    @property
    def k8s_resource_handler(self):
        """Update K8S with K8S resources."""
        if not self._k8s_resource_handler:
            self._k8s_resource_handler = KRH(
                field_manager=self._lightkube_field_manager,
                template_files=K8S_RESOURCE_FILES,
                context=self._context,
                logger=self.log,
            )
        load_in_cluster_generic_resources(self._k8s_resource_handler.lightkube_client)
        return self._k8s_resource_handler

    @k8s_resource_handler.setter
    def k8s_resource_handler(self, handler: KRH):
        """Set K8S resource handler."""
        self._k8s_resource_handler = handler

    @property
    def _profiles_pebble_layer(self) -> Layer:
        """Return the Profiles Pebble layer for the workload."""
        return Layer(
            {
                "services": {
                    self._profiles_container_name: {
                        "override": "replace",
                        "summary": "entry point for kubeflow profiles",
                        "command": (
                            "/manager "
                            "-userid-header "
                            "kubeflow-userid "
                            "-userid-prefix "
                            " "
                            "-workload-identity "
                            " "
                        ),
                        "startup": "enabled",
                    }
                },
                "checks": {
                    "kubeflow-profiles-get": {
                        "override": "replace",
                        "period": "30s",
                        "http": {"url": "http://localhost:8080/metrics"},
                    }
                },
            }
        )

    @property
    def _kfam_pebble_layer(self) -> Layer:
        """Return the kfam Pebble layer for the workload."""
        return Layer(
            {
                "services": {
                    self._kfam_container_name: {
                        "override": "replace",
                        "summary": "entry point for kubeflow access management",
                        "command": (
                            "/access-management "
                            "-cluster-admin "
                            "admin "
                            "-userid-header "
                            "kubeflow-userid "
                            "-userid-prefix "
                            '""'
                        ),
                        "startup": "enabled",
                    }
                },
                "checks": {
                    "kubeflow-kfam-get": {
                        "override": "replace",
                        "period": "30s",
                        "http": {"url": "http://localhost:8081/metrics"},
                    }
                },
            }
        )

    def _deploy_k8s_resources(self):
        """Deploy K8S resources."""
        try:
            self.unit.status = MaintenanceStatus("Creating K8S resources")
            self.k8s_resource_handler.apply()

        except ApiError:
            raise ErrorWithStatus("K8S resources creation failed", BlockedStatus)
        self.model.unit.status = MaintenanceStatus("K8S resources created")

    def _update_profiles_layer(self) -> None:
        """Update the Profile Pebble layer if changed.

        Push the namespace labels file to the container
        Add the Pebble layer and Replan
        """
        if not self.profiles_container.can_connect():
            raise ErrorWithStatus("Waiting for pod startup to complete", MaintenanceStatus)

        current_layer = self.profiles_container.get_plan()

        if current_layer.services != self._profiles_pebble_layer.services:
            with open(NAMESPACE_LABELS_FILE, encoding="utf-8") as labels_file:
                labels = labels_file.read()
            self.profiles_container.push(
                "/etc/profile-controller/namespace-labels.yaml", labels, make_dirs=True
            )
            self.profiles_container.add_layer(
                self._profiles_container_name, self._profiles_pebble_layer, combine=True
            )
            try:
                self.log.info("Pebble plan updated with new configuration, replanning")
                self.profiles_container.replan()
            except ChangeError:
                self.log.error(traceback.format_exc())
                raise ErrorWithStatus("Failed to replan", BlockedStatus)

    def _update_profiles_container(self, event) -> None:
        """Check leader and call the update profiles layer method."""
        if not self.profiles_container.can_connect():
            self.unit.status = WaitingStatus("Waiting to connect to Profiles container")
            event.defer()
            return

        try:
            self._check_leader()
            self.unit.status = MaintenanceStatus("Configuring Profiles layer")
            self._update_profiles_layer()
        except ErrorWithStatus as error:
            raise error
        self.unit.status = MaintenanceStatus("Profiles layer configured")

    def _update_kfam_container(self, event) -> None:
        """Update the kfam Pebble configuration layer if changed."""
        if not self.profiles_container.can_connect():
            self.unit.status = WaitingStatus("Waiting to connect to kfam container")
            event.defer()
            return

        try:
            self._check_leader()
            self.unit.status = MaintenanceStatus("Configuring kfam layer")
            update_layer(
                self._kfam_container_name, self.kfam_container, self._kfam_pebble_layer, self.log
            )
        except ErrorWithStatus as error:
            raise error
        self.unit.status = MaintenanceStatus("kfam layer configured")

    def _on_kubeflow_profiles_ready(self, event):
        """Update the started Profiles container."""
        try:
            self._update_profiles_container(event)

        except ErrorWithStatus as e:
            self.model.unit.status = e.status
            if isinstance(e.status, BlockedStatus):
                self.log.error(str(e.msg))
            else:
                self.log.info(str(e.msg))

    def _on_kfam_ready(self, event):
        """Update the started kfam container."""
        try:
            self._update_kfam_container(event)

        except ErrorWithStatus as e:
            self.model.unit.status = e.status
            if isinstance(e.status, BlockedStatus):
                self.log.error(str(e.msg))
            else:
                self.log.info(str(e.msg))

    def _on_remove(self, event):
        """Remove all resources."""
        self.unit.status = MaintenanceStatus("Removing k8s resources")
        manifests = self.k8s_resource_handler.render_manifests()
        try:
            delete_many(self.k8s_resource_handler.lightkube_client, manifests)
        except ApiError as e:
            self.log.warning(f"Failed to delete resources: {manifests} with: {e}")
            raise e
        self.unit.status = MaintenanceStatus("K8s resources removed")

    def _send_info(self, interfaces):
        """Send Kubeflow Profiles interface info."""
        if interfaces["kubeflow-profiles"]:
            interfaces["kubeflow-profiles"].send_data(
                {
                    "service-name": self.model.app.name,
                    "service-port": str(self.model.config["port"]),
                }
            )

    def _check_leader(self):
        """Check if this unit is a leader."""
        if not self.unit.is_leader():
            # We can't do anything useful when not the leader, so do nothing.
            self.log.info("Not a leader, skipping setup")
            raise ErrorWithStatus("Waiting for leadership", WaitingStatus)

    def _check_container_connection(self, container):
        """Check if connection can be made with container."""
        if not container.can_connect():
            raise ErrorWithStatus("Pod startup is not complete", MaintenanceStatus)

    def _get_interfaces(self):
        """Retrieve interface object."""
        try:
            interfaces = get_interfaces(self)
        except NoVersionsListed as err:
            raise CheckFailed(err, WaitingStatus)
        except NoCompatibleVersions as err:
            raise CheckFailed(err, BlockedStatus)
        return interfaces

    def on_initialise_profile_action(self, event: ActionEvent) -> None:
        """Handle the action to initialise an existing profile."""
        profile_name = event.params.get("profilename")
        self.configure_profile(profile_name)

    def on_create_profile_action(self, event: ActionEvent) -> None:
        """Handle the action to create a new profile."""
        auth_username = event.params.get("authusername")
        profile_name = event.params.get("profilename")
        resource_quota = event.params.get("resourcequota")
        self.log.info(
            f"Running action create-profile with parameters auth_username={auth_username}, profile_name={profile_name}, resource_quota={resource_quota}"  # noqa E501
        )
        self.create_profile(auth_username, profile_name, resource_quota)

    def create_profile(self, auth_username, profile_name, resource_quota):
        """Create new profile object."""
        formatted_quota = None
        if resource_quota:
            formatted_quota = self._load_text_to_dict(resource_quota)  # preprocess resource quota
        profile = create_global_resource(
            group="kubeflow.org", version="v1", kind="Profile", plural="profiles"
        )
        # check if profile already exists
        try:
            existing_profile = self.k8s_resource_handler.lightkube_client.get(
                profile, name=profile_name, namespace=self._namespace
            )
            if existing_profile:
                self.log.warning(
                    f"Failed to create profile: profile with name {profile_name} already exists."
                )
                return
        except ApiError as e:
            self.log.info(
                f"Profile doesn't exist, action will proceed to create profile. Error: {str(e)}"
            )
        my_profile = profile(
            metadata={"name": profile_name},
            spec={
                "owner": {"kind": "User", "name": auth_username},
                "resourceQuotaSpec": formatted_quota,
            },
        )
        self.k8s_resource_handler.lightkube_client.create(my_profile)

        self.configure_profile(profile_name)

    def _load_text_to_dict(self, text):
        return json.loads(text)

    def configure_profile(self, profile_name):
        """Add missing configurations to profile."""
        create_global_resource(
            group="kubeflow.org", version="v1", kind="Profile", plural="profiles"
        )
        # attempt to get namespace
        try:
            for attempt in Retrying(
                stop=(stop_after_attempt(5) | stop_after_delay(30)),
                wait=wait_exponential(multiplier=1, min=5, max=10),
                reraise=True,
            ):
                with attempt:
                    self.k8s_resource_handler.lightkube_client.get(Namespace, name=profile_name)
        except RetryError:
            self.log.error(f"Action failed. namespace {profile_name} was not created")
            return

        for file in PROFILE_CONFIG_FILES:
            # TODO figure out which integrations are needed
            yaml_text = self._safe_load_file_to_text(file)
            self._apply_manifest(yaml_text, profile_name)
        self._copy_seldon_secret(profile_name)

    def _copy_seldon_secret(self, namespace):
        """Copy Seldon deployment secret from kubeflow namespace to the profile's namespace."""
        seldon_secret = None
        # check if seldon-core-mlflow integration secret exists in kubeflow namespace
        try:
            seldon_secret = self.k8s_resource_handler.lightkube_client.get(
                Secret,
                name="mlflow-server-seldon-init-container-s3-credentials",
                namespace="kubeflow",
            )
        except ApiError as e:
            self.log.warning(f"seldon secret not found in kubeflow namespace. error:{e}")

        if seldon_secret:
            try:
                self.k8s_resource_handler.lightkube_client.create(
                    Secret(
                        metadata=ObjectMeta(name="seldon-init-container-secret"),
                        kind="Secret",
                        apiVersion=seldon_secret.apiVersion,
                        data=seldon_secret.data,
                        type=seldon_secret.type,
                    ),
                    namespace=namespace,
                )
            except ApiError as e:
                self.log.error(
                    f"Failed to apply secret {seldon_secret.metadata.name} to namespace {namespace}. error:{e}"  # noqa E501
                )

    def _apply_manifest(self, manifest, namespace=None):
        """Apply manifest to namespace."""
        for obj in codecs.load_all_yaml(manifest):
            try:
                self.k8s_resource_handler.lightkube_client.apply(obj, namespace=namespace)
            except ApiError as e:
                self.log.error(
                    f"Failed to apply manifest: {obj.metadata.name} to namespace: {namespace}. Error: {e}"
                )

    def _safe_load_file_to_text(self, filename: str):
        """Return the contents of filename if it is an existing file, else it returns filename."""
        try:
            text = Path(filename).read_text()
        except FileNotFoundError:
            text = filename
        return text

    def main(self, event):
        """Perform all required actions for the Charm."""
        try:
            self._update_profiles_container(event)
            self._update_kfam_container(event)
            self._deploy_k8s_resources()
            interfaces = self._get_interfaces()

        except ErrorWithStatus as error:
            self.model.unit.status = error.status
            return

        self._send_info(interfaces)

        self.model.unit.status = ActiveStatus()


class CheckFailed(Exception):
    """Raise this exception if one of the checks in main fails."""

    def __init__(self, msg: str, status_type=None):
        """Initialize CheckFailed exception."""
        super().__init__()

        self.msg = str(msg)
        self.status_type = status_type
        self.status = status_type(self.msg)


if __name__ == "__main__":
    main(KubeflowProfilesOperator)
