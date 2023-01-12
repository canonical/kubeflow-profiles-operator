#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""A Juju Charm for Kubeflow Profiles Operator."""

import logging
import traceback
from typing import List, Union

from charmed_kubeflow_chisme.exceptions import ErrorWithStatus
from charmed_kubeflow_chisme.kubernetes import KubernetesResourceHandler as KRH  # noqa: N817
from charmed_kubeflow_chisme.lightkube.batch import delete_many
from charmed_kubeflow_chisme.pebble import update_layer
from charmed_kubeflow_chisme.status_handling import get_first_worst_error
from charms.observability_libs.v1.kubernetes_service_patch import KubernetesServicePatch
from lightkube import ApiError
from lightkube.generic_resource import load_in_cluster_generic_resources
from lightkube.models.core_v1 import ServicePort
from ops.charm import CharmBase
from ops.framework import StoredState
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus, WaitingStatus, StatusBase
from ops.pebble import ChangeError, Layer
from serialized_data_interface import NoCompatibleVersions, NoVersionsListed, get_interfaces

K8S_RESOURCE_FILES = ["src/templates/auth_manifests.yaml.j2", "src/templates/crds.yaml.j2"]
NAMESPACE_LABELS_FILE = "src/templates/namespace-labels.yaml"

# TODO: Use this pattern (see obs charms)
RAISABLE_STATUSES = {
    "profiles_cannot_connect": WaitingStatus("Waiting to connect to profiles container"),
    "kfam_cannot_connect": WaitingStatus("Waiting to connect to kfam container")

}

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
        context = {
            "app_name": self.model.app.name,
            "model_name": self.model.name,
        }
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
                    },
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
                    },
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

    def _update_profiles_container(self) -> None:
        """Check leader and call the update profiles layer method."""
        if not self.profiles_container.can_connect():
            raise ErrorWithStatus("Waiting to connect to profiles container", WaitingStatus)

        self._check_leader()

        self.unit.status = MaintenanceStatus("Configuring Profiles layer")
        self._update_profiles_layer()
        self.unit.status = MaintenanceStatus("Profiles layer configured")

    def _update_kfam_container(self) -> None:
        """Update the kfam Pebble configuration layer if changed."""
        if not self.kfam.can_connect():
            raise ErrorWithStatus("Waiting to connect to kfam container", WaitingStatus)

        self._check_leader()

        self.unit.status = MaintenanceStatus("Configuring kfam layer")
        update_layer(
            self._kfam_container_name,
            self.kfam_container,
            self._kfam_pebble_layer,
            self.log,
            )
        self.unit.status = MaintenanceStatus("kfam layer configured")

    def _on_kubeflow_profiles_ready(self, event):
        """Update the live Profiles container."""
        self.main(event)

    def _on_kfam_ready(self, event):
        """Update the live kfam container."""
        self.main(event)

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

    def main(self, _):
        """Perform all required actions for the Charm."""
        try:
            self._check_leader()
        except ErrorWithStatus as e:
            # End early.  The charm should do nothing if it is not the leader
            self.log.error(e.message)
            self.unit.status = e.status

        errors_with_status = []
        try:
            self._update_profiles_container()
        except ErrorWithStatus as e:
            errors_with_status.append(e)

        try:
            self._update_kfam_container()
        except ErrorWithStatus as e:
            errors_with_status.append(e)

        try:
            self._deploy_k8s_resources()
        except ErrorWithStatus as e:
            errors_with_status.append(e)

        try:
            interfaces = self._get_interfaces()
            self._send_info(interfaces)
        except ErrorWithStatus as error:
            errors_with_status.append(error.status)

        if len(errors_with_status) > 0:
            # Log all statuses we've encountered, and set unit status based on the first, worst
            # status we saw
            self.log.error("Charm configuration encountered the following situations that prevented ActiveStatus:")
            worst_error = get_first_worst_error(errors_with_status)
            self.log.error("Setting Unit status to the first, worst encountered status")
            self.unit.status = worst_error.status

        # TODO: Do something here to figure out if we are actually alive and working properly
        # alive = self.am_I_active()
        alive = True  # temporarily override
        if alive:
            self.model.unit.status = ActiveStatus()
        else:
            # Do something here.  Maybe `WaitingStatus()` saying the charm is active but waiting
            # on the worload?
            # How would we ensure we eventually check this again and go fully active.
            # Update_status hook?
            pass


class CheckFailed(Exception):
    """Raise this exception if one of the checks in main fails."""

    def __init__(self, msg: str, status_type=None):
        """Initialize CheckFailed exception."""
        super().__init__()

        self.msg = str(msg)
        self.status_type = status_type
        self.status = status_type(self.msg)


def get_first_worst_status(statuses: List[Union[BlockedStatus, WaitingStatus, MaintenanceStatus, ActiveStatus]]):
    """Returns the first of the worst statuses in the list.

    TODO: This should be in Chisme. charmed_kubeflow_chisme.status_handling.get_first_worst_error
          is nearly identical, but parses statuses.  We should combine these

    Raises if List contains no Exceptions, or if any Exception does not have a .status

    Status are ranked, starting with the worst:
        BlockedStatus
        WaitingStatus
        ActiveStatus
    """
    if len(statuses) == 0:
        raise IndexError("No statuses provided")

    # Higher numbers are worse
    status_ranks = {
        BlockedStatus: 4,
        WaitingStatus: 3,
        MaintenanceStatus: 2,
        ActiveStatus: 1,
        # reserved for empty list: 0
    }
    worst_possible_status_rank = max(status_ranks.values())

    worst_status = None
    worst_status_rank = 0

    for status in statuses:
        if worst_status_rank < status_ranks[status.__class__]:
            worst_status = status
            worst_status_rank = status_ranks[status.__class__]

        if worst_status_rank == worst_possible_status_rank:
            break

    return worst_status


if __name__ == "__main__":
    main(KubeflowProfilesOperator)
