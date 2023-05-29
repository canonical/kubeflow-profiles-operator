#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""The Pebble handler wrapper classes for this charm"""
import logging
from typing import Callable, Optional

import ops.charm
import ops.model
from ops.charm import RelationEvent
from ops.framework import (
    Handle,

    BoundEvent,
    EventBase,
    EventSource,
    Object,
    StoredState,
    ObjectEvents,
)
from ops.pebble import Layer
from ops_sunbeam.relation_handlers import RelationHandler
from ops_sunbeam.guard import BlockedExceptionError, WaitingExceptionError, guard
from serialized_data_interface import (
    SerializedDataInterface,
    NoCompatibleVersions,
    NoVersionsListed,
    get_interface,
)

from ops.model import (
    ActiveStatus,
    BlockedStatus,
    UnknownStatus,
    WaitingStatus,
)

logger = logging.getLogger(__name__)


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
        # TODO: Needed?  Or does the event already have enough?
        self.message = message


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
        except NoVersionsListed as err:
            self.on.no_versions_listed.emit(message=str(err))
            return
        except NoCompatibleVersions as err:
            self.on.no_compatible_versions.emit(message=str(err))
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
        required_attributes = ['service-name', 'service-port']
        try:
            interface = self.get_interface()
        except Exception:
            logging.info(
                "Caught exception while checking readiness.  KubeflowProfilesProvides SDI "
                "interface raised an error")
            return False

        try:
            # TODO: Handle this differently when you know the syntax is correct
            interface_data = interface.get_data()
            for attribute in required_attributes:
                if not (attribute in interface_data and interface_data[attribute] is not None and interface_data[attribute] != ""):
                    return False

            return True
        except Exception:
            logging.info(
                "Caught exception while checking readiness.  Did not find required attribute in"
                " relation data"
            )
            return False


class KubeflowProfilesProvidesHandler(RelationHandler):
    """Handler for Kubeflow Profiles Provides relation."""

    def __init__(
            self,
            charm: ops.charm.CharmBase,
            relation_name: str,
            callback_f: Callable,
    ):
        super().__init__(charm=charm, relation_name=relation_name, callback_f=callback_f)
        # TODO: Added this so we can use the Provides again later.  Is this ok?
        self._relation = None

    def setup_event_handler(self) -> Object:
        """Configure event handlers for a kubeflow-profiles relation."""
        logger.info("Setting up kubeflow-profiles event handler")

        # If I have a self-enclosed handler, I can just use it here
        # This subscribes to the relation-changed automatically
        self._relation = KubeflowProfilesProvides(self.charm, self.relation_name)
        logger.info(f"KubeflowProfilesProvidesHandler._relation = {self._relation}")

        # If we didn't have a self-contained relation interface, we could add events here too:
        # _relation_name = self.relation_name.replace("-", "_")
        # db_relation_changed_event = getattr(self.charm.on, f"{_relation_name}_relation_changed")
        # self.framework.observe(db_relation_changed_event, self._on_relation_changed)

        # The SDI-backed KubeflowProfilesProvides relation also emits events when it hits known
        # exceptions.  Handle those here in this RelationHandler
        self.framework.observe(self._relation.on.no_versions_listed, self._on_sdi_no_versions_listed_event)
        self.framework.observe(self._relation.on.no_compatible_versions, self._on_sdi_no_compatible_versions_event)
        return self._relation

    def _on_sdi_no_versions_listed_event(self, event: SdiNoVersionsListedErrorEvent) -> None:
        """Handles the SdiNoVersionsListed event, setting status to WaitingStatus."""
        logging.info("in KubeflowProfilesProvidesHandler._on_sdi_no_versions_listed_event")
        self.status.set(WaitingStatus(event.message))

    def _on_sdi_no_compatible_versions_event(self, event: SdiNoCompatibleVersionsEvent) -> None:
        """Handles the SdiNoCompatibleVersions event, setting status to BlockedStatus."""
        logging.info("in KubeflowProfilesProvidesHandler._on_sdi_no_compatible_versions_event")
        self.status.set(BlockedStatus(event.message))

    @property
    def ready(self) -> bool:
        """Report if the relation is ready for use."""
        # TODO: Could I just use the status value here?  Or maybe this triggers update_status, and
        #  then use the status value?
        logging.info("in KubeflowProfilesProvidesHandler.ready")
        try:
            return self._relation.is_ready
        except NoVersionsListed as err:
            # self.status.set(WaitingStatus(err))
            return False
        except NoCompatibleVersions as err:
            # self.status.set(BlockedStatus(err))
            return False

        # TODO: This isn't really ready unless we've also sent our data out.  We should check for
        #  that too.
