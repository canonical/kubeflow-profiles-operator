import logging

from ops import StatusBase, ActiveStatus, WaitingStatus
from ops.pebble import Layer

from functional_base_charm.component import Component
from functional_base_charm.pebble_component import PebbleServiceComponent


logger = logging.getLogger(__name__)


class LeadershipGate(Component):
    """This Component checks that we are the leader, otherwise sets WaitingStatus.

    TODO: This is a hack to let charms function like they have traditionally in Kubeflow.  A more
     nuanced way to handle this would be to use the Component.configure_app/configure_unit methods,
     similar to how Sunbeam does this.  But until that is thought through, this is an easy
     implementation.
    """

    def _configure_unit(self, event):
        pass

    def _configure_app_leader(self, event):
        pass

    def _configure_app_non_leader(self, event):
        pass

    def ready_for_execution(self) -> bool:
        """Returns True if this is the leader, else False."""
        return self._charm.unit.is_leader()

    @property
    def status(self) -> StatusBase:
        if not self._charm.unit.is_leader():
            return WaitingStatus("Waiting for leadership")

        return ActiveStatus()
