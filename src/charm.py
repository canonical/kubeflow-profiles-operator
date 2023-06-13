#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""A Juju Charm for Kubeflow Profiles Operator."""

import logging

import lightkube
from lightkube.resources.apiextensions_v1 import CustomResourceDefinition
from lightkube.resources.rbac_authorization_v1 import ClusterRole

from charmed_kubeflow_chisme.kubernetes import create_charm_default_labels
from functional_base_charm.charm_main import CharmMain
from functional_base_charm.component_graph import ComponentGraph
from functional_base_charm.kubernetes_component import KubernetesComponent

from ops.charm import CharmBase
from ops.framework import StoredState
from ops.main import main

from other_components import LeadershipGate
from pebble_components import KubeflowProfilesContainerComponent, KubeflowKfamContainerComponent


logger = logging.getLogger(__name__)

K8S_RESOURCE_FILES = ["src/templates/auth_manifests.yaml.j2", "src/templates/crds.yaml.j2"]


class KubeflowProfilesOperator(CharmBase):
    """A Juju Charm for Kubeflow Profiles Operator."""

    _stored = StoredState()

    def __init__(self, *args, **kwargs):
        """Initialize charm and setup the container."""
        super().__init__(*args, **kwargs)

        self.component_graph = ComponentGraph()

        self.leadership_gate_component_item = self.component_graph.add(
            component=LeadershipGate(
                charm=self,
                name="leadership-gate",
            ),
            name="leadership-gate",
            depends_on=[]
        )

        self.kubernetes_resources_component_item = self.component_graph.add(
            component=KubernetesComponent(
                charm=self,
                name="k8s-auth-and-crds",
                resource_templates=K8S_RESOURCE_FILES,
                krh_child_resource_types=[CustomResourceDefinition, ClusterRole],
                krh_labels=create_charm_default_labels(self.app.name, self.model.name, scope="auth-and-crds"),
                # TODO: Make this better
                context_callable=lambda: {"app_name": self.app.name},
                lightkube_client=lightkube.Client(),  # TODO: Make this easier to test on
            ),
            name="kubernetes-resources",
            depends_on=[self.leadership_gate_component_item]
        )

        self.kubeflow_profiles_container_item = self.component_graph.add(
            component=KubeflowProfilesContainerComponent(
                charm=self,
                container_name="kubeflow-profiles",
                service_name="kubeflow-profiles"
            ),
            name="kubeflow-profiles",
            depends_on=[self.leadership_gate_component_item, self.kubernetes_resources_component_item],  # Not really needed.  But for fun!
        )

        self.kubeflow_kfam_container_item = self.component_graph.add(
            component=KubeflowKfamContainerComponent(
                charm=self,
                container_name="kubeflow-kfam",
                service_name="kubeflow-kfam"
            ),
            name="kubeflow-kfam",
            depends_on=[self.leadership_gate_component_item, self.kubernetes_resources_component_item],
        )

        self.charm_executor = CharmMain(self, self.component_graph)
        self.charm_executor.install(self)

        # Hack to install Prioritiser.  See Prioritiser.install() for explanation
        # Nevermind, this doesn't work either.  In unit tests, on.commit never fires.
        self.framework.observe(self.framework.on.commit, self._on_commit)

        # TODO:
        #  * Some more k8s resources to add
        #  * actions
        #  * sdi relation

    def _on_commit(self, event):
        status = self.charm_executor.component_graph.status_prioritiser.highest()
        logger.info(f"Got status {status} from Prioritiser - updating unit status")
        self.unit.status = status


if __name__ == "__main__":
    main(KubeflowProfilesOperator)
