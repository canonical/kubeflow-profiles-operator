#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import traceback

from ops.charm import CharmBase
from ops.main import main
from ops.pebble import Layer, ChangeError
from ops.model import ActiveStatus, WaitingStatus, BlockedStatus, MaintenanceStatus
from ops.framework import StoredState
from charms.observability_libs.v1.kubernetes_service_patch import KubernetesServicePatch
from charmed_kubeflow_chisme.kubernetes import KubernetesResourceHandler as KRH
from charmed_kubeflow_chisme.pebble import update_layer
from charmed_kubeflow_chisme.exceptions import ErrorWithStatus
from charmed_kubeflow_chisme.lightkube.batch import delete_many
from lightkube.models.core_v1 import ServicePort
from lightkube.generic_resource import load_in_cluster_generic_resources
from lightkube import ApiError

from serialized_data_interface import (
    NoCompatibleVersions,
    NoVersionsListed,
    get_interfaces,
)

K8S_RESOURCE_FILES = ["src/files/auth_manifests.yaml.j2", "src/files/crds.yaml.j2"]


class KubeflowProfilesOperator(CharmBase):
    _stored = StoredState()

    def __init__(self, *args):
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
        self._profiles_container = self.unit.get_container(
            self._profiles_container_name
        )

        self._kfam_container_name = "kubeflow-kfam"
        self._kfam_container = self.unit.get_container(self._kfam_container_name)

        self._namespace = self.model.name
        self._name = self.model.app.name
        self._lightkube_field_manager = "lightkube"
        self._k8s_resource_handler = None

        self.framework.observe(self.on.install, self._on_install)
        self.framework.observe(self.on.config_changed, self._on_config_changed)
        self.framework.observe(self.on.config_changed, self.service_patcher._patch)

        for event in [
            self.on.leader_elected,
            self.on.upgrade_charm,
            self.on["kubeflow-profiles"].relation_changed,
        ]:
            self.framework.observe(event, self.main)
        self.framework.observe(
            self.on.kubeflow_profiles_pebble_ready, self._on_kubeflow_profiles_ready
        )
        self.framework.observe(self.on.kubeflow_kfam_pebble_ready, self._on_kfam_ready)

    @property
    def profiles_container(self):
        """Return profile container"""
        return self._profiles_container

    @property
    def kfam_container(self):
        """Return kfam container"""
        return self._kfam_container

    @property
    def _context(self):
        context = {
            "app_name": self.model.app.name,
            "model_name": self.model.name,
        }
        return context

    @property
    def k8s_resource_handler(self):
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
        self._k8s_resource_handler = handler

    @property
    def _profiles_pebble_layer(self) -> Layer:
        """Return the Pebble layer for the workload."""
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
                #         "checks": {
                #             "kubeflow-profiles-alive": {
                #                 "override": "replace",
                #                 "http": {"url": "http://localhost:8080/metrics"},
                #     },
                # },
            }
        )

    @property
    def _kfam_pebble_layer(self) -> Layer:
        """Return the Pebble layer for the workload."""
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
                #         "checks": {
                #             "kubeflow-kfam-alive": {
                #                 "override": "replace",
                #                 "http": {"url": "http://localhost:8081/metrics"},
                #     },
                # },
            }
        )

    def _deploy_k8s_resources(self):
        try:
            self.unit.status = MaintenanceStatus("Creating K8S resources")
            self.k8s_resource_handler.apply()

        except ApiError:
            raise ErrorWithStatus("K8S resources creation failed", BlockedStatus)
        self.model.unit.status = MaintenanceStatus("K8S resources created")

    def _update_profiles_layer(self) -> None:
        """Updates the Pebble configuration layer if changed."""
        if not self.profiles_container.can_connect():
            raise ErrorWithStatus(
                "Waiting for pod startup to complete", MaintenanceStatus
            )

        current_layer = self.profiles_container.get_plan()

        if current_layer.services != self._profiles_pebble_layer.services:
            with open(
                "src/files/namespace-labels.yaml", encoding="utf-8"
            ) as labels_file:
                labels = labels_file.read()
                self.profiles_container.push(
                    "/etc/profile-controller/namespace-labels.yaml",
                    labels,
                    make_dirs=True,
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
        """Updates the Profiles Pebble configuration layer if changed."""
        if not self.profiles_container.can_connect():
            self.unit.status = WaitingStatus("Waiting to connect to Profiles container")
            event.defer()
            return

        try:
            self._check_leader()
        except ErrorWithStatus as error:
            self.model.unit.status = error.status
            return

        self.unit.status = MaintenanceStatus("Configuring Profiles layer")
        self._update_profiles_layer()

        # TODO determine status checking if kfam is also up
        self.unit.status = ActiveStatus()

    def _update_kfam_container(self, event) -> None:
        """Updates the kfam Pebble configuration layer if changed."""
        if not self.profiles_container.can_connect():
            self.unit.status = WaitingStatus("Waiting to connect to kfam container")
            event.defer()
            return

        try:
            self._check_leader()
        except ErrorWithStatus as error:
            self.model.unit.status = error.status
            return

        self.unit.status = MaintenanceStatus("Configuring kfam layer")

        update_layer(
            self._kfam_container_name,
            self.kfam_container,
            self._kfam_pebble_layer,
            self.log,
        )

        # TODO determine status checking if profiles is also up
        self.unit.status = ActiveStatus()

    def _on_install(self, event):
        """Perform installation only actions."""

        self._update_profiles_container(event)
        self._update_kfam_container(event)

        try:
            self._deploy_k8s_resources()
            interfaces = self._get_interfaces()
            self._send_info(event, interfaces)
        except (ApiError, ErrorWithStatus, CheckFailed) as e:
            if isinstance(e, ApiError):
                self.log.error(
                    f"Applying resources failed with ApiError status code {e.status.code}"
                )
                self.unit.status = BlockedStatus(f"ApiError: {e.status.code}")
            else:
                self.log.info(e.msg)
                self.unit.status = e.status
        else:
            self.unit.status = ActiveStatus()

    def _on_config_changed(self, event):
        self._update_profiles_container(event)
        self._update_kfam_container(event)

        try:
            interfaces = self._get_interfaces()
        except CheckFailed as error:
            self.model.unit.status = error.status
            return

        self._send_info(event, interfaces)

    def _on_kubeflow_profiles_ready(self, event):
        """Define and start a workload using the Pebble API.
        Learn more about Pebble layers at https://github.com/canonical/pebble
        """
        try:
            with open(
                "src/files/namespace-labels.yaml", encoding="utf-8"
            ) as labels_file:
                labels = labels_file.read()
                self.profiles_container.push(
                    "/etc/profile-controller/namespace-labels.yaml",
                    labels,
                    make_dirs=True,
                )

            self._update_profiles_container(event)

        except ErrorWithStatus as e:
            self.model.unit.status = e.status
            if isinstance(e.status, BlockedStatus):
                self.log.error(str(e.msg))
            else:
                self.log.info(str(e.msg))

        # self.unit.status = ActiveStatus()

    def _on_kfam_ready(self, event):
        """Define and start a workload using the Pebble API.
        Learn more about Pebble layers at https://github.com/canonical/pebble
        """
        try:
            self._update_kfam_container(event)

        except ErrorWithStatus as e:
            self.model.unit.status = e.status
            if isinstance(e.status, BlockedStatus):
                self.log.error(str(e.msg))
            else:
                self.log.info(str(e.msg))

        # self.unit.status = ActiveStatus()

    def _on_remove(self, event):
        self.unit.status = MaintenanceStatus("Removing k8s resources")
        manifests = self.k8s_resource_handler.render_manifests()
        try:
            delete_many(self.k8s_resource_handler.lightkube_client, manifests)
        except ApiError as e:
            self.log.warning(f"Failed to delete resources: {manifests} with: {e}")
            raise e
        self.unit.status = MaintenanceStatus("K8s resources removed")

    def _send_info(self, event, interfaces):
        if interfaces["kubeflow-profiles"]:
            interfaces["kubeflow-profiles"].send_data(
                {
                    "service-name": self.model.app.name,
                    "service-port": str(self.model.config["port"]),
                }
            )

    def _check_leader(self):
        if not self.unit.is_leader():
            # We can't do anything useful when not the leader, so do nothing.
            self.log.info("Not a leader, skipping setup")
            raise ErrorWithStatus("Waiting for leadership", WaitingStatus)

    def _check_container_connection(self, container):
        """Check if connection can be made with container."""
        if not container.can_connect():
            raise ErrorWithStatus("Pod startup is not complete", MaintenanceStatus)

    def _get_interfaces(self):
        try:
            interfaces = get_interfaces(self)
        except NoVersionsListed as err:
            raise CheckFailed(err, WaitingStatus)
        except NoCompatibleVersions as err:
            raise CheckFailed(err, BlockedStatus)
        return interfaces

    def main(self, event):
        try:
            self._check_container_connection(self.profiles_container)
            self._check_container_connection(self.kfam_container)
            self._check_leader()
            self._deploy_k8s_resources()

            interfaces = self._get_interfaces()

        except ErrorWithStatus as error:
            self.model.unit.status = error.status
            return

        self._send_info(event, interfaces)

        self.model.unit.status = ActiveStatus()


class CheckFailed(Exception):
    """Raise this exception if one of the checks in main fails."""

    def __init__(self, msg: str, status_type=None):
        super().__init__()

        self.msg = str(msg)
        self.status_type = status_type
        self.status = status_type(self.msg)


if __name__ == "__main__":
    main(KubeflowProfilesOperator)
