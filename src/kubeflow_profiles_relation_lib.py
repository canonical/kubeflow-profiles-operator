import logging
from typing import Optional, Dict

import ops.framework
import ops.model
from ops import RelationEvent, ObjectEvents, EventSource, Object, StoredState
from serialized_data_interface import SerializedDataInterface, get_interface, NoVersionsListed, NoCompatibleVersions
from serialized_data_interface.errors import UnversionedRelation

from relation_handlers import logger


class SdiErrorEvent(RelationEvent):
    """Event triggers when an SDI relation catches an exception.

    This is a base object and not meant to be used directly.
    """

    def __init__(
            self,
            handle: ops.framework.Handle,
            relation: ops.Relation,
            app: Optional[ops.model.Application] = None,
            unit: Optional[ops.model.Unit] = None,
            message: Optional[str] = None,
    ):
        super().__init__(handle=handle, relation=relation, app=app, unit=unit)
        # TODO: message here doesn't work.  It gets removed during serialisation of the event.
        #  There might be a solution [here](https://github.com/canonical/traefik-k8s-operator/blob/main/lib/charms/traefik_k8s/v1/ingress.py#LL185C1-L224C1)
        #  but I dont understand
        self.message = message

    def snapshot(self) -> Dict:
        """Save SdiErrorEvent information."""
        snapshot = super().snapshot()
        additional_data = {"message": self.message}
        snapshot.update(additional_data)
        return snapshot

    def restore(self, snapshot) -> None:
        """Restore SdiErrorEvent information."""
        super().restore(snapshot)
        self.message = snapshot["message"]


class SdiNoVersionsListedErrorEvent(SdiErrorEvent):
    """Event triggers when an SDI relation catches a NoVersionsListed exception."""


class SdiNoCompatibleVersionsEvent(SdiErrorEvent):
    """Event triggers when an SDI relation catches a NoCompatibleVersions exception."""


class SdiRelationProviderEvents(ObjectEvents):
    """Container for events for SDI relation errors."""
    no_versions_listed = EventSource(SdiNoVersionsListedErrorEvent)
    no_compatible_versions = EventSource(SdiNoCompatibleVersionsEvent)


class KubeflowProfilesProvides(Object):
    """kubeflow-profiles Provides Class.

    Example based on [this class](https://opendev.org/openstack/charm-keystone-k8s/src/branch/main/lib/charms/keystone_k8s/v1/identity_service.py#L406)
    handled by [this handler](https://opendev.org/openstack/charm-keystone-k8s/src/branch/main/src/charm.py#L133)
    """
    _stored = StoredState()
    on = SdiRelationProviderEvents()

    def __init__(self, charm, relation_name):
        logger.info(f"Instantiating KubeflowProfilesProvides object for {relation_name}.")
        super().__init__(charm, relation_name)
        self.charm = charm
        self.relation_name = relation_name

        self.framework.observe(
            self.charm.on[relation_name].relation_changed,
            self._on_relation_changed,
        )

    def get_interface(self) -> Optional[SerializedDataInterface]:
        """Returns the SerializedDataInterface object for this interface."""
        return get_interface(self.charm, self.relation_name)

        # try:
        #     return get_interface(self.charm, self.relation_name)
        # except NoVersionsListed as err:
        #     self.on.no_versions_listed.emit(message=str(err))
        # TODO: Add NoCompaibleVersions
        # except NoCompatibleVersions:

    def _on_relation_changed(self, event: ops.framework.EventBase) -> None:
        """Implements a relation-changed handler for the Provides side of kubeflow-profiles.

        If there was already a self-contained library to implement this, we could have skipped
        this entirely.
        """
        logger.info("KubeflowProfilesProvides._on_relation_changed handling relation-changed "
                    "event for kubeflow-profiles")

        try:
            interface = self.get_interface()
        except (NoVersionsListed, UnversionedRelation) as err:
            # TODO: message here doesn't work.  It gets removed during serialisation of the event.
            #  There might be a solution [here](https://github.com/canonical/traefik-k8s-operator/blob/main/lib/charms/traefik_k8s/v1/ingress.py#LL185C1-L224C1)
            #  but I dont understand
            self.on.no_versions_listed.emit(event.relation, message=str(err))
            return
        except NoCompatibleVersions as err:
            self.on.no_compatible_versions.emit(event.relation, message=str(err))
            return

        # Can these also refer to self.model...?  Are self.model and self.charm.model equivalent?
        # I think they should be
        interface.send_data(
            {
                "service-name": self.charm.model.app.name,
                "service-port": str(self.charm.model.config["port"]),
            }
        )

        # TODO: Where does my charm set itself to active if this succeeds?  I guess it later polls
        #   the is_ready?

    @property
    def is_ready(self) -> bool:
        """Returns True if the relation is ready and our side of the relation is completed."""
        # TODO: Refactor this
        logging.info("in KubeflowProfileProvides.is_ready")
        required_attributes = ['service-name', 'service-port']

        try:
            interface = self.get_interface()
            logging.info(f"got interface {interface}")
        except Exception:
            logging.info(
                "Caught exception while checking readiness.  KubeflowProfilesProvides SDI "
                "interface raised an error")
            return False

        try:
            # TODO: Handle this differently when you know the syntax is correct
            # We check whether we've sent, on our application side of the relation, the required
            # attributes
            interface_data_dict = interface.get_data()
            logging.info(f"got interface_data {interface_data_dict}")
            logging.info(f"self.relation_name = {self.relation_name}")
            logging.info(f"self.charm.app = {self.charm.app}")
            this_apps_interface_data = interface_data_dict[(self.model.get_relation(self.relation_name), self.charm.app)]
            logging.info(f"got this_apps_interface_data {this_apps_interface_data}")

            for attribute in required_attributes:
                logging.info(f"Checking attribute {attribute}")
                logging.info(f"attribute in interface_data = {attribute in this_apps_interface_data}")
                if not (attribute in this_apps_interface_data and this_apps_interface_data[attribute] is not None and this_apps_interface_data[attribute] != ""):
                    return False

            return True
        except Exception:
            logging.info(
                "Caught exception while checking readiness.  Did not find required attribute in"
                " relation data"
            )
            return False
