#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""The Pebble handler wrapper classes for this charm"""
import logging
from typing import Callable

import ops.model
from ops.framework import (
    Object,
)

from kubeflow_profiles_relation_lib import SdiNoVersionsListedErrorEvent, SdiNoCompatibleVersionsEvent, \
    KubeflowProfilesProvides
from ops_sunbeam.relation_handlers import RelationHandler
from serialized_data_interface import (
    NoCompatibleVersions,
    NoVersionsListed,
)

from ops.model import (
    BlockedStatus,
    WaitingStatus,
)

logger = logging.getLogger(__name__)


class KubeflowProfilesProvidesHandler(RelationHandler):
    """Handler for Kubeflow Profiles Provides relation."""

    def __init__(
            self,
            charm: ops.charm.CharmBase,
            relation_name: str,
            callback_f: Callable,
    ):
        super().__init__(charm=charm, relation_name=relation_name, callback_f=callback_f)

    def setup_event_handler(self) -> Object:
        """Configure event handlers for a kubeflow-profiles relation."""
        logger.info("Setting up kubeflow-profiles event handler")

        # If I have a self-enclosed handler, I can just use it here
        # This subscribes to the relation-changed automatically
        kubeflow_profile_provides = KubeflowProfilesProvides(self.charm, self.relation_name)

        # If we didn't have a self-contained relation interface, we could add events here too:
        # _relation_name = self.relation_name.replace("-", "_")
        # db_relation_changed_event = getattr(self.charm.on, f"{_relation_name}_relation_changed")
        # self.framework.observe(db_relation_changed_event, self._on_relation_changed)

        # The SDI-backed KubeflowProfilesProvides relation also emits events when it hits known
        # exceptions.  Handle those here in this RelationHandler
        self.framework.observe(kubeflow_profile_provides.on.no_versions_listed, self._on_sdi_no_versions_listed_event)
        self.framework.observe(kubeflow_profile_provides.on.no_compatible_versions, self._on_sdi_no_compatible_versions_event)
        return kubeflow_profile_provides

    def _on_sdi_no_versions_listed_event(self, event: SdiNoVersionsListedErrorEvent) -> None:
        """Handles the SdiNoVersionsListed event, setting status to WaitingStatus."""
        logging.info("in KubeflowProfilesProvidesHandler._on_sdi_no_versions_listed_event")
        self.status.set(WaitingStatus(f"Relation {event.relation.name} reports NoVersionsListedError with message {event.message}."))

    def _on_sdi_no_compatible_versions_event(self, event: SdiNoCompatibleVersionsEvent) -> None:
        """Handles the SdiNoCompatibleVersions event, setting status to BlockedStatus."""
        logging.info("in KubeflowProfilesProvidesHandler._on_sdi_no_compatible_versions_event")
        self.status.set(BlockedStatus(f"Relation {event.relation.name} reports NoCompatibleVersionsError with message {event.message} - charm may be related to incompatible charm."))

    @property
    def ready(self) -> bool:
        """Report if the relation is ready for use."""
        # TODO: Could I just use the status value here?  Or maybe this triggers update_status, and
        #  then use the status value?
        logging.info("in KubeflowProfilesProvidesHandler.ready")
        interface, _ = self.get_interface()
        try:
            return interface.is_ready
        except NoVersionsListed as err:
            return False
        except NoCompatibleVersions as err:
            return False

        # TODO: This isn't really ready unless we've also sent our data out.  We should check for
        #  that too.
