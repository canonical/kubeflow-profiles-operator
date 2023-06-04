"""Extensions to the sunbeam.charm module."""

import logging
from typing import List

import ops.framework
from ops_sunbeam.charm import OSBaseOperatorCharmK8S
from ops_sunbeam import guard as sunbeam_guard
from sunbeam_extensions.kubernetes_handlers import KubernetesHandler


class OSBaseOperatorCharmK8SExtended(OSBaseOperatorCharmK8S):
    """Base charm class for k8s based charms, including deployment of k8s manifests."""

    def __init__(self, framework: ops.framework.Framework) -> None:
        """Run constructor."""
        super().__init__(framework)
        # TODO: How could this be configurable?
        self.lightkube_field_manager = self.app.name
        self.kubernetes_handlers = self.get_kubernetes_handlers()

    # # TODO: Don't think we need to modify this, but put here as a reminder for now
    # def configure_app(self, event):
    #     raise NotImplementedError()

    def configure_app_leader(self, event):
        # TODO: Configure all kubernetes resources here.  They are (usually) meant to be global/shared across all units
        #  This likely needs a rethink in future, but is good for a first pass
        # In this function, if anything is amiss (eg: handlers are not ready) then we fail fast
        # and never get to other things.
        super().configure_app_leader(event)
        self.init_kubernetes_resources()

    # # TODO: Don't think we need to modify this, but put here as a reminder for now
    # def configure_app_non_leader(self, event):
    #     raise NotImplementedError()

    # # TODO: Don't think we need to modify this, but put here as a reminder for now
    # def configure_charm(self, event: ops.framework.EventBase) -> None:
    #     raise NotImplementedError()

    def check_kubernetes_handlers_ready(self):
        """Check if Kubernetes handlers are ready."""
        for kh in self.kubernetes_handlers:
            if not kh.ready:
                logging.debug(f"Kubernetes resources for {kh.name} not ready")
                raise sunbeam_guard.WaitingExceptionError("Resources not ready")

        return True

    def update_and_check_kubernetes_handlers_ready(self):
        """Prompts all Kubernetes Handlers to update their Status, and returns if they're .ready

        TODO: Similar to check_kubernetes_handlers_ready, but has the side effect of updating the
        handler .status fields.  Is this side effect bad?  A `check_` having a side effect feels
        odd, but checking and not updating Status also feels odd.
        """
        for kh in self.kubernetes_handlers:
            kh.status
            if not kh.ready:
                logging.debug(f"Kubernetes resources for {kh.name} not ready")
                raise sunbeam_guard.WaitingExceptionError("Resources not ready")

        return True


    def get_kubernetes_handlers(self) -> List[KubernetesHandler]:
        """Kubernetes handlers for the charm."""
        return []

    def init_kubernetes_resources(self) -> None:
        """Run init on Kubernetes handlers."""
        # Set up kubernetes resources
        for kh in self.kubernetes_handlers:
            kh.init_resources()
        self.check_kubernetes_handlers_ready()
