#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""A Juju Charm for Kubeflow Profiles Operator."""

import logging

import lightkube
from lightkube.resources.apiextensions_v1 import CustomResourceDefinition
from lightkube.resources.rbac_authorization_v1 import ClusterRole
from ops import EventBase

from charmed_kubeflow_chisme.kubernetes import create_charm_default_labels
from charmed_kubeflow_chisme.components.charm_reconciler import CharmReconciler
from charmed_kubeflow_chisme.components.kubernetes_component import KubernetesComponent

from ops.charm import CharmBase
from ops.framework import StoredState
from ops.main import main

from charmed_kubeflow_chisme.components.pebble_component import ContainerFileTemplate
from other_components import LeadershipGate
from pebble_components import KubeflowProfilesContainerComponent, KubeflowKfamContainerComponent
from relation_component import KubeflowProfilesProvidesComponent

logger = logging.getLogger(__name__)

NAMESPACE_LABELS_TEMPLATE_FILE = "src/templates/namespace-labels.yaml"
NAMESPACE_LABELS_DESTINATION_PATH = "/etc/profile-controller/namespace-labels.yaml"
K8S_RESOURCE_FILES = ["src/templates/auth_manifests.yaml.j2", "src/templates/crds.yaml.j2"]


class KubeflowProfilesOperator(CharmBase):
    """A Juju Charm for Kubeflow Profiles Operator."""

    _stored = StoredState()

    def __init__(self, *args, **kwargs):
        """Initialize charm and setup the container."""
        super().__init__(*args, **kwargs)

        # Actions
        self.framework.observe(self.on.describe_status_action, self._describe_status_action)

        # Charm logic
        self.charm_executor = CharmReconciler(self)
        self.charm_executor.install(self)

        self.leadership_gate_component_item = self.charm_executor.add(
            component=LeadershipGate(
                charm=self,
                name="leadership-gate",
            ),
            depends_on=[]
        )

        self.kubernetes_resources_component_item = self.charm_executor.add(
            component=KubernetesComponent(
                charm=self,
                name="kubernetes:auth-and-crds",
                resource_templates=K8S_RESOURCE_FILES,
                krh_resource_types={CustomResourceDefinition, ClusterRole},
                krh_labels=create_charm_default_labels(self.app.name, self.model.name, scope="auth-and-crds"),
                # TODO: Make this better
                context_callable=lambda: {"app_name": self.app.name},
                lightkube_client=lightkube.Client(),  # TODO: Make this easier to test on
            ),
            depends_on=[self.leadership_gate_component_item]
        )

        self.kubeflow_profiles_container_item = self.charm_executor.add(
            component=KubeflowProfilesContainerComponent(
                charm=self,
                name="container:kubeflow-profiles",  # This feels a bit redundant, but will read
                container_name="kubeflow-profiles",  # well in the statuses.  Thoughts?
                service_name="kubeflow-profiles",
                files_to_push=[
                    ContainerFileTemplate(
                        source_template_path=NAMESPACE_LABELS_TEMPLATE_FILE,
                        destination_path=NAMESPACE_LABELS_DESTINATION_PATH,
                    )
                ]
            ),
            depends_on=[self.leadership_gate_component_item, self.kubernetes_resources_component_item],  # Not really needed.  But for fun!
        )

        self.kubeflow_kfam_container_item = self.charm_executor.add(
            component=KubeflowKfamContainerComponent(
                charm=self,
                name="container:kubeflow-kfam",
                container_name="kubeflow-kfam",
                service_name="kubeflow-kfam"
            ),
            depends_on=[self.leadership_gate_component_item, self.kubernetes_resources_component_item],
        )

        self.kubeflow_profiles_provides_container_item = self.charm_executor.add(
            component=KubeflowProfilesProvidesComponent(
                charm=self,
                name="relation:kubeflow-profiles",
                relation_name="kubeflow-profiles",
            ),
            depends_on=[self.leadership_gate_component_item]
        )

    # Debugging code
    def _describe_status_action(self, event: EventBase) -> None:
        event.set_results({"output": str(self.get_all_status())})

    def get_all_status(self):
        """Convenience function for getting a list of all statuses for this charm's executor.

        This is more for debugging.  Having an action would be useful to summarise this too on a
        running charm.
        """
        return self.charm_executor.component_graph.status_prioritiser.all()


if __name__ == "__main__":
    main(KubeflowProfilesOperator)
