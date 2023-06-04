#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""A Juju Charm for Kubeflow Profiles Operator."""

import logging
from typing import List

import lightkube
from ops.framework import EventBase, StoredState
from ops.main import main

import sunbeam_extensions.kubernetes_handlers
from sunbeam_extensions.charm import OSBaseOperatorCharmK8SExtended
import ops_sunbeam.container_handlers as sunbeam_chandlers
import ops_sunbeam.core as sunbeam_core
import ops_sunbeam.relation_handlers as sunbeam_rhandlers

import pebble_handlers
import relation_handlers

logger = logging.getLogger(__name__)

K8S_RESOURCE_FILES = ["src/templates/auth_manifests.yaml.j2", "src/templates/crds.yaml.j2"]


class KubeflowProfilesOperator(OSBaseOperatorCharmK8SExtended):
    """A Juju Charm for Kubeflow Profiles Operator."""

    _stored = StoredState()

    # TODO: Not sure why this is really needed.  Added it for now to unblock the database features
    service_name = "kubeflow-profiles"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.framework.observe(self.on.describe_status_action, self._describe_status_action)

    def get_kubernetes_handlers(self) -> List[sunbeam_extensions.kubernetes_handlers.KubernetesHandler]:
        return [
            sunbeam_extensions.kubernetes_handlers.KubernetesHandler(
                charm=self,
                name="all-resources",
                resource_templates=K8S_RESOURCE_FILES,
                field_manager=self.app.name,
                lightkube_client=lightkube.Client(field_manager=self.lightkube_field_manager)
            )
        ]


    def get_pebble_handlers(self) -> List[sunbeam_chandlers.PebbleHandler]:
        """Pebble handlers for this charm."""
        return [
            pebble_handlers.KubeflowProfilesPebbleHandler(
                charm=self,
                # TODO: parametrize container_name and service_name
                container_name="kubeflow-profiles",
                service_name="kubeflow-profiles",
                container_configs=self.container_configs,
                template_dir=self.template_dir,  # defaults to /src/templates
                callback_f=lambda: '',  # Not sure what this does
            ),
            pebble_handlers.KFAMHandler(
                charm=self,
                # TODO: parametrize container_name and service_name
                container_name="kubeflow-kfam",
                service_name="kubeflow-kfam",
                container_configs=[],  # This has no templates to render
                template_dir=self.template_dir,  # defaults to /src/templates
                callback_f=lambda: '',  # Not sure what this does
            ),
        ]

    def get_relation_handlers(
        self, handlers: List[sunbeam_rhandlers.RelationHandler] = None
    ) -> List[sunbeam_rhandlers.RelationHandler]:
        return [
            relation_handlers.KubeflowProfilesProvidesHandler(
                charm=self,
                relation_name="kubeflow-profiles",
                callback_f=lambda: "",  # TODO: What does this do?
            )
        ]

    @property
    def container_configs(self) -> List[sunbeam_core.ContainerConfigFile]:
        """Computes configurations for the containers given context of the charm.

        This I think is just used by all the container handlers, and is attached to the class for
        convenience?  Kinda odd though when you have multiple containers.

        NOTE: This is container config FILES, not contexts.

        Returned here are NamedTuples of (path, user, group, permissions), where `path` is the
        destination path inside the container. When these are used,
        the handler looks in the template_dir defined in the Handler instantiation's template_dir
        arg and for each ContainerConfigFile tries to render basename(path) (or
        basename(path + ".j2")) with the contexts available.  See
        https://opendev.org/openstack/charm-ops-sunbeam/src/commit/6a7f80a2eee0d8626e9c09080b151f56a2f28b0e/ops_sunbeam/templating.py#L49
        """
        logger.info("in KubeflowProfilesOperator.container_configs")
        _container_configs = super().container_configs
        logger.info(f"got configs from parent: {_container_configs}")
        _container_configs.extend(
            [
                sunbeam_core.ContainerConfigFile(
                    path="/etc/profile-controller/namespace-labels.yaml",
                    user="root",
                    group="root"
                ),
            ]
        )
        logger.info(f"final configs are: {_container_configs}")

        _container_configs.extend([])
        return _container_configs

    def _describe_status_action(self, event: EventBase) -> None:
        event.set_results({"output": self.status_pool.summarise()})

    @property
    def lightkube_client(self) -> lightkube.Client:
        if self._lightkube_client is None:
            self._lightkube_client = lightkube.Client(self.lightkube_field_manager)
        return self._lightkube_client


if __name__ == "__main__":
    main(KubeflowProfilesOperator)
