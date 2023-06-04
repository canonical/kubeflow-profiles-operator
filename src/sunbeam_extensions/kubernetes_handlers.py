from typing import List

import logging

import lightkube
from charmed_kubeflow_chisme.kubernetes import KubernetesResourceHandler
from charmed_kubeflow_chisme.exceptions import GenericCharmRuntimeError
from lightkube import ApiError
from lightkube.generic_resource import load_in_cluster_generic_resources
from ops import MaintenanceStatus, EventBase, ActiveStatus, WaitingStatus
import ops.charm
import ops_sunbeam.compound_status as compound_status


logger = logging.getLogger(__name__)


class KubernetesHandler(ops.charm.Object):

    def __init__(
            self,
            charm: ops.charm.CharmBase,
            name: str,
            resource_templates: List[str],
            field_manager: str,
            lightkube_client: lightkube.Client = None,
    ):
        super().__init__(charm, None)
        self.charm = charm
        self.name = name
        self.resource_templates = resource_templates
        self.lightkube_field_manager = field_manager
        self._lightkube_client = lightkube_client

        self.status = compound_status.Status("kubernetes:" + self.name)
        self.charm.status_pool.add(self.status)

        self.framework.observe(
            self.charm.on.update_status, self._on_update_status
        )

    def init_resources(self):
        """Applies this handler's Kubernetes Resources."""
        self.status.set(MaintenanceStatus("Creating resources"))
        try:
            krh = self.get_kubernetes_resource_handler()
            krh.apply()
        except ApiError as e:
            # TODO: Blocked?
            raise GenericCharmRuntimeError("Failed to create Kubernetes resources") from e

        # Once done actively creating, this either takes us to Ready (if everything happened fast)
        # or shows what the problem is.
        # TODO: Does this feel right?  Should we expect the parent to call this after
        #  init_resources?
        self.update_status()

    @property
    def ready(self):
        """Returns boolean indicating if resources are considered ready."""
        return True

    def get_kubernetes_resource_handler(self) -> KubernetesResourceHandler:
        """Returns a KubernetesResourceHandler for this class."""
        k8s_resource_handler = KubernetesResourceHandler(
            field_manager=self.lightkube_field_manager,
            template_files=self.resource_templates,
            context=self.context_for_render(),
            lightkube_client=self.lightkube_client,
        )
        load_in_cluster_generic_resources(k8s_resource_handler.lightkube_client)
        return k8s_resource_handler

    def _on_update_status(self, event: EventBase):
        if self.ready:
            self.status.set(ActiveStatus())
        else:
            # TODO: Improve this
            self.status.set(WaitingStatus("Resources not ready"))

    def update_status(self):
        """Updates the handler's status to current state."""
        # TODO: this needs work.  Likely should do something to check resources and have an
        #  intelligent response error otherwise
        #  I think the guard is what's needed here, and then self.ready can have the check
        #  logic?
        if self.ready:
            self.status.set(ActiveStatus())
        else:
            raise NotImplementedError()

    def context_for_render(self) -> dict:
        """Defines the context that will be used for rendering the Kubernetes Resource templates.

        TODO: This should be combined with the other handler context concepts, but this is a simple
         first implementation where subclasses can just override this with a hard-coded context
         function.
        """
        # TODO: Unused?
        return {}

    @property
    def lightkube_client(self) -> lightkube.Client:
        if self._lightkube_client is None:
            self._lightkube_client = lightkube.Client(field_manager=self.lightkube_field_manager)
        return self._lightkube_client
