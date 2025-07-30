#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""A Juju Charm for Kubeflow Profiles Operator."""

import logging
from pathlib import Path
from typing import List

from charmed_kubeflow_chisme.exceptions import ErrorWithStatus, GenericCharmRuntimeError
from charmed_kubeflow_chisme.kubernetes import KubernetesResourceHandler as KRH  # noqa: N817
from charmed_kubeflow_chisme.lightkube.batch import delete_many
from charmed_kubeflow_chisme.pebble import update_layer
from charms.loki_k8s.v1.loki_push_api import LogForwarder
from charms.observability_libs.v1.kubernetes_service_patch import KubernetesServicePatch
from charms.prometheus_k8s.v0.prometheus_scrape import MetricsEndpointProvider
from charms.velero_libs.v0.velero_backup_config import VeleroBackupRequirer, VeleroBackupSpec
from lightkube import ApiError, codecs
from lightkube.generic_resource import load_in_cluster_generic_resources
from lightkube.models.core_v1 import ServicePort
from lightkube.resources.core_v1 import Namespace
from ops import main
from ops.charm import ActionEvent, CharmBase
from ops.framework import StoredState
from ops.model import ActiveStatus, BlockedStatus, Container, MaintenanceStatus, WaitingStatus
from ops.pebble import ChangeError, Layer
from serialized_data_interface import NoCompatibleVersions, NoVersionsListed, get_interfaces

K8S_RESOURCE_FILES = ["src/templates/auth_manifests.yaml.j2", "src/templates/crds.yaml.j2"]
NAMESPACE_LABELS_FILE = "src/templates/namespace-labels.yaml"
PROFILE_CONFIG_FILES = ["src/templates/allow-minio.yaml", "src/templates/allow-mlflow.yaml"]

K8S_USER_WORKLOAD_RESOURCECS = [
    "persistentvolumeclaims",
    "persistentvolumes",
    "secrets",
    "authcodes.dex.coreos.com",
    "authorizationpolicies.security.istio.io",
    "certificaterequests.cert-manager.io",
    "certificates.cert-manager.io",
    "challenges.acme.cert-manager.io",
    "clusterissuers.cert-manager.io",
    "clusterservingruntimes.serving.kserve.io",
    "clusterstoragecontainers.serving.kserve.io",
    "compositecontrollers.metacontroller.k8s.io",
    "controllerrevisions.metacontroller.k8s.io",
    "cron",
    "decoratorcontrollers.metacontroller.k8s.io",
    "destinationrules.networking.istio.io",
    "envoyfilters.networking.istio.io",
    "experiments.kubeflow.org",
    "gateways.networking.istio.io",
    "inferencegraphs.serving.kserve.io",
    "inferenceservices.serving.kserve.io",
    "issuers.cert-manager.io",
    "mpijobs.kubeflow.org",
    "mxjobs.kubeflow.org",
    "notebooks.kubeflow.org",
    "orders.acme.cert-manager.io",
    "paddlejobs.kubeflow.org",
    "peerauthentications.security.istio.io",
    "poddefaults.kubeflow.org",
    "profiles.kubeflow.org",
    "proxyconfigs.networking.istio.io",
    "pvcviewers.kubeflow.org",
    "pytorchjobs.kubeflow.org",
    "requestauthentications.security.istio.io",
    "scheduledworkflows.kubeflow.org",
    "serviceentries.networking.istio.io",
    "servingruntimes.serving.kserve.io",
    "sidecars.networking.istio.io",
    "suggestions.kubeflow.org",
    "telemetries.telemetry.istio.io",
    "tensorboards.tensorboard.kubeflow.org",
    "tfjobs.kubeflow.org",
    "trainedmodels.serving.kserve.io",
    "trials.kubeflow.org",
    "viewers.kubeflow.org",
    "wasmplugins.extensions.istio.io",
    "workloadentries.networking.istio.io",
    "workloadgroups.networking.istio.io",
    "xgboostjobs.kubeflow.org",
]


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
        self._k8s_resource_handler = None
        self._lightkube_field_manager = "lightkube"
        self._profile_namespaces = self._get_profile_namespaces()

        # service account names are hardcoded
        # TODO: implement relation and get from relation data
        # tracked in https://github.com/canonical/kubeflow-profiles-operator/issues/156
        self._istio_gateway_principal = (
            "cluster.local/ns/kubeflow/sa/istio-ingressgateway-workload-service-account"
        )
        self._notebook_controller_principal = "cluster.local/ns/kubeflow/sa/jupyter-controller"
        self._kfp_ui_principal = "cluster.local/ns/kubeflow/sa/kfp-ui"

        # setup events to be handled by specific event handlers
        self.framework.observe(self.on.install, self._on_install)
        self.framework.observe(self.on.remove, self._on_remove)
        self.framework.observe(self.on.config_changed, self.service_patcher._patch)
        self.framework.observe(
            self.on.kubeflow_profiles_pebble_ready, self._on_profiles_pebble_ready
        )
        self.framework.observe(self.on.kubeflow_kfam_pebble_ready, self._on_kfam_pebble_ready)

        # setup events to be handled by main event handler
        self.framework.observe(self.on.upgrade_charm, self._on_event)
        self.framework.observe(self.on.config_changed, self._on_event)

        for rel in self.model.relations.keys():
            self.framework.observe(self.on[rel].relation_changed, self._on_event)

        self._logging = LogForwarder(charm=self)
        self.prometheus_provider = MetricsEndpointProvider(
            self,
            jobs=[{"static_configs": [{"targets": ["*:8080", "*:8081"]}]}],
            refresh_event=[
                self.on.kubeflow_profiles_pebble_ready,
                self.on.kubeflow_kfam_pebble_ready,
            ],
        )

        # setup Velero backup relations
        self.profiles_backup = VeleroBackupRequirer(
            self,
            app_name=self._name,
            relation_name="profiles-backup-config",
            spec=VeleroBackupSpec(include_resources=["profiles.kubeflow.org"]),
        )
        if self._profile_namespaces:
            self.user_workload_backup = VeleroBackupRequirer(
                self,
                app_name=self._name,
                relation_name="user-workloads-backup-config",
                spec=VeleroBackupSpec(
                    include_namespaces=self._profile_namespaces,
                    include_resources=K8S_USER_WORKLOAD_RESOURCECS
                ),
                refresh_event=[self.on.config_changed, self.on.update_status],
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
    def _profiles_service_environment(self):
        """Return environment variables for kubeflow-profiles container."""
        return {
            "ISTIO_INGRESS_GATEWAY_PRINCIPAL": self._istio_gateway_principal,  # noqa E501
            "NOTEBOOK_CONTROLLER_PRINCIPAL": self._notebook_controller_principal,
            "KFP_UI_PRINCIPAL": self._kfp_ui_principal,
        }

    @property
    def _kfam_service_environment(self):
        """Return environment variables for kubeflow-kfam container."""
        return {
            "ISTIO_INGRESS_GATEWAY_PRINCIPAL": self._istio_gateway_principal,  # noqa E501
            "KFP_UI_PRINCIPAL": self._kfp_ui_principal,
        }

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
                            "/manager " "-userid-header " "kubeflow-userid " "-userid-prefix " '""'
                        ),
                        "environment": self._profiles_service_environment,
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
                        "environment": self._kfam_service_environment,
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

    def _get_profile_namespaces(self) -> List[str]:
        """Get the list of profile namespaces."""
        try:
            namespaces = self.k8s_resource_handler.lightkube_client.list(
                Namespace, labels={"app.kubernetes.io/part-of": "kubeflow-profile"}
            )
            return [
                ns.metadata.name
                for ns in namespaces
                if ns.metadata and ns.metadata.name and ns.metadata.name != "kubeflow"
            ]
        except ApiError as e:
            raise GenericCharmRuntimeError("Failed to list profile namespaces") from e

    def _deploy_k8s_resources(self):
        """Deploy K8S resources."""
        try:
            self.unit.status = MaintenanceStatus("Creating K8S resources")
            self.k8s_resource_handler.apply()

        except ApiError as e:
            raise GenericCharmRuntimeError("Failed to create K8S resources") from e
        self.model.unit.status = MaintenanceStatus("K8S resources created")

    def _check_container_connection(self, container: Container) -> None:
        """Check if connection can be made with container.

        Args:
            container: the named container in a unit to check.

        Raises:
            ErrorWithStatus if the connection cannot be made.
        """
        if not container.can_connect():
            raise ErrorWithStatus("Pod startup is not complete", MaintenanceStatus)

    def _on_install(self, _):
        """Installation only tasks."""
        # deploy K8S resources to speed up deployment
        self._deploy_k8s_resources()

    def _update_profiles_layer(self) -> None:
        """Update the Profile Pebble layer if changed.

        Push the namespace labels file to the container
        Add the Pebble layer and Replan
        """
        if not self.profiles_container.can_connect():
            raise ErrorWithStatus("Waiting for pod startup to complete", MaintenanceStatus)

        current_layer = self.profiles_container.get_plan()

        if current_layer.services != self._profiles_pebble_layer.services:
            self._push_namespace_labels()
            self.profiles_container.add_layer(
                self._profiles_container_name, self._profiles_pebble_layer, combine=True
            )
            try:
                self.log.info("Pebble plan updated with new configuration, replanning")
                self.profiles_container.replan()
            except ChangeError as e:
                raise GenericCharmRuntimeError("Failed to replan") from e

    def _on_profiles_pebble_ready(self, event):
        """Update the started Profiles container."""
        # TODO: extract exception handling to _check_container_connection()
        try:
            self._check_container_connection(self.profiles_container)
        except ErrorWithStatus as error:
            self.model.unit = error.status
            return
        self._on_event(event)

    def _push_namespace_labels(self):
        """Push namespace labels to Profile container."""
        with open(NAMESPACE_LABELS_FILE, encoding="utf-8") as labels_file:
            labels = labels_file.read()
        self.profiles_container.push(
            "/etc/profile-controller/namespace-labels.yaml", labels, make_dirs=True
        )

    def _on_kfam_pebble_ready(self, event):
        """Update the started kfam container."""
        try:
            self._check_container_connection(self.kfam_container)
        except ErrorWithStatus as error:
            self.model.unit = error.status
            return
        self._on_event(event)

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

    def _get_interfaces(self):
        """Retrieve interface object."""
        try:
            interfaces = get_interfaces(self)
        except NoVersionsListed as err:
            raise ErrorWithStatus(err, WaitingStatus)
        except NoCompatibleVersions as err:
            raise ErrorWithStatus(err, BlockedStatus)
        return interfaces

    def _apply_manifest(self, manifest, event: ActionEvent, namespace=None):
        """Apply manifest to namespace."""
        for obj in codecs.load_all_yaml(manifest):
            try:
                self.k8s_resource_handler.lightkube_client.apply(obj, namespace=namespace)
            except ApiError as e:
                event.log(
                    f"Failed to apply manifest: {obj.metadata.name} to namespace: {namespace}. Error: {e}"  # noqa E501
                )

    def _safe_load_file_to_text(self, filename: str):
        """Return the contents of filename if it is an existing file, else it returns filename."""
        try:
            text = Path(filename).read_text()
        except FileNotFoundError:
            text = filename
        return text

    def _on_event(self, event) -> None:
        """Perform all required actions for the Charm."""
        try:
            self._check_leader()
            interfaces = self._get_interfaces()
            self._send_info(interfaces)
            self._deploy_k8s_resources()
            self._update_profiles_layer()
            update_layer(
                self._kfam_container_name, self.kfam_container, self._kfam_pebble_layer, self.log
            )
        except ErrorWithStatus as err:
            self.model.unit.status = err.status
            self.log.info(f"Failed to handle {event} with error: {str(err)}")
            return

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
