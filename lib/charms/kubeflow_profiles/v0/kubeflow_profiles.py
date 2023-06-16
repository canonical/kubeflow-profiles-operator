import logging
from typing import Optional, Dict, Union, List

import ops.model
from ops import RelationEvent, ObjectEvents, EventSource, Object, StoredState, CharmBase, BoundEvent, StatusBase, \
    WaitingStatus, BlockedStatus, ActiveStatus
from serialized_data_interface import SerializedDataInterface, get_interface, NoVersionsListed, NoCompatibleVersions
from serialized_data_interface.errors import UnversionedRelation


logger = logging.getLogger(__name__)


# TODO: full docstring showing usage

# The unique Charmhub library identifier, never change it
LIBID = "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"

# Increment this major API version when introducing breaking changes
LIBAPI = 0

# Increment this PATCH version before using `charmcraft publish-lib` or reset
# to 0 if you are raising the major API version
LIBPATCH = 1


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
        self.message = message

    def snapshot(self) -> Dict:
        """Save SdiErrorEvent information.

        This allows for adding a custom `message` attribute.
        """
        snapshot = super().snapshot()
        additional_data = {"message": self.message}
        snapshot.update(additional_data)
        return snapshot

    def restore(self, snapshot) -> None:
        """Restore SdiErrorEvent information.

        This allows for adding a custom `message` attribute.
        """
        super().restore(snapshot)
        self.message = snapshot["message"]


class KubeflowProfilesSdiNoVersionsListedErrorEvent(SdiErrorEvent):
    """Event triggered when an SDI relation catches a NoVersionsListed exception."""


class KubeflowProfilesSdiNoCompatibleVersionsEvent(SdiErrorEvent):
    """Event triggered when an SDI relation catches a NoCompatibleVersions exception."""


class KubeflowProfilesDataSent(RelationEvent):
    """Event triggered when this Provider sends new data out on the relation."""


class KubeflowProfilesProviderEvents(ObjectEvents):
    """Container for events for SDI relation errors."""
    no_versions_listed = EventSource(KubeflowProfilesSdiNoVersionsListedErrorEvent)
    no_compatible_versions = EventSource(KubeflowProfilesSdiNoCompatibleVersionsEvent)
    data_sent = EventSource(KubeflowProfilesDataSent)


class KubeflowProfilesProvides(Object):
    """kubeflow-profiles Provides Class.

    Example based on [this class](https://opendev.org/openstack/charm-keystone-k8s/src/branch/main/lib/charms/keystone_k8s/v1/identity_service.py#L406)
    handled by [this handler](https://opendev.org/openstack/charm-keystone-k8s/src/branch/main/src/charm.py#L133)
    """
    _stored = StoredState()
    on = KubeflowProfilesProviderEvents()

    def __init__(
            self,
            charm: CharmBase,
            relation_name: str,
            refresh_event: Optional[Union[BoundEvent, List[BoundEvent]]] = None,
    ):
        """Instantiate the Kubeflow Profiles Provides side handler.

        This library subscribes to:
        * on[relation_name].relation_changed
        * on.config_changed
        * any events listed in refresh_event

        This library emits:
        * KubeflowProfilesSdiNoVersionsListedErrorEvent:
            When the opposite side of the relation has not posted a version
        * KubeflowProfilesSdiNoCompatibleVersionsEvent:
            When the opposite side of the relation has not posted a version that is compatible with
            this charm
        * KubeflowProfilesDataSent:
            When we send new data on this relation (useful to subscribe to to update your charm
            status).

        """
        logger.info(f"Instantiating KubeflowProfilesProvides object for {relation_name}.")
        super().__init__(charm, relation_name)
        self.charm = charm
        self.relation_name = relation_name

        self.framework.observe(
            self.charm.on[relation_name].relation_changed,
            self._on_relation_changed,
        )

        # TODO: Should this just be a custom event that the charm should emit whenever it wants the
        #  relation lib to do something?  That way we don't always execute, just when asked?
        self.framework.observe(self.charm.on.config_changed, self._on_relation_changed)

        # apply user defined events
        if refresh_event:
            if not isinstance(refresh_event, (tuple, list)):
                refresh_event = [refresh_event]

            for evt in refresh_event:
                self.framework.observe(evt, self._on_relation_changed)

    def get_interface(self) -> Optional[SerializedDataInterface]:
        """Returns the SerializedDataInterface object for this interface."""
        return get_interface(self.charm, self.relation_name)

    def _on_relation_changed(self, event: ops.framework.EventBase) -> None:
        """Implements a relation-changed handler for the Provides side of kubeflow-profiles.

        If there was already a self-contained library to implement this, we could have skipped
        this entirely.
        """
        # TODO: SDI only works from the leader.  If this procs before we get leadership, it will
        #  fail.  How do we handle that?
        logger.info("KubeflowProfilesProvides._on_relation_changed handling relation-changed "
                    "event for kubeflow-profiles")

        try:
            interface = self.get_interface()
        except (NoVersionsListed, UnversionedRelation) as err:
            self.on.no_versions_listed.emit(event.relation, message=str(err))
            return
        except NoCompatibleVersions as err:
            self.on.no_compatible_versions.emit(event.relation, message=str(err))
            return

        if interface is None:
            # Nothing related to us.  No work to be done
            return

        # TODO: Check if the data is different.  If it is, send.  If not, don't.

        # Can these also refer to self.model...?  Are self.model and self.charm.model equivalent?
        # I think they should be
        interface.send_data(
            {
                "service-name": self.charm.model.app.name,
                "service-port": str(self.charm.model.config["port"]),
            }
        )
        self.on.data_sent.emit(event.relation)

    def get_status(self) -> StatusBase:
        """Returns the status of this relation.

        Use this in the charm to inspect the state of the relation and its data.

        Will return:
            * BlockedStatus: if we have no compatible versions on the relation
            * WaitingStatus: if we have not yet received a version from the opposite relation
            * ActiveStatus: if:
                * nothing is related to us (as there is no work to do)
                * we have one or more relations, and we have sent data to all of them
        """
        # TODO: What does this do when no related apps are present?
        logging.info("in KubeflowProfileProvides.is_ready")
        required_attributes = ['service-name', 'service-port']

        unknown_error_message = (
            "Caught unknown exception while checking readiness of Kubeflow Profiles relation."
            "  KubeflowProfilesProvides SDI interface raised an error: "
        )

        try:
            interface = self.get_interface()
            logging.info(f"got interface {interface}")
        # TODO: These messages should be tested and cleaned up
        except (NoVersionsListed, UnversionedRelation) as err:
            return WaitingStatus(str(err))
        except NoCompatibleVersions as err:
            return BlockedStatus(str(err))
        except Exception as err:
            logging.info(unknown_error_message)
            return BlockedStatus(str(unknown_error_message + str(err)))

        if interface is None:
            # Nothing is related to us, so we have nothing to send out.  Relation is Active
            return ActiveStatus()

        try:
            # TODO: Handle this differently when you know the syntax is correct
            # We check whether we've sent, on our application side of the relation, the required
            # attributes
            interface_data_dict = interface.get_data()
            this_apps_interface_data = interface_data_dict[(self.model.get_relation(self.relation_name), self.charm.app)]

            missing_attributes = []
            # TODO: This could validate the data sent, not just confirm there is something sent.
            #  Would that be too much?
            for attribute in required_attributes:
                if not (attribute in this_apps_interface_data and this_apps_interface_data[attribute] is not None and this_apps_interface_data[attribute] != ""):
                    missing_attributes.append(attribute)

            if missing_attributes:
                msg = f"Relation is missing attributes {missing_attributes} that we send out." \
                      f"  This likely is a transient error but if it persistes, there could be" \
                      f" something wrong."

                return WaitingStatus(msg)

            return ActiveStatus()
        except Exception as err:
            logging.info(unknown_error_message)
            return BlockedStatus(str(unknown_error_message + str(err)))
