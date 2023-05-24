#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""A Juju Charm for Kubeflow Profiles Operator."""

import logging
from typing import List

from ops.framework import StoredState
from ops.main import main
import ops_sunbeam.charm as sunbeam_charm
import ops_sunbeam.container_handlers as sunbeam_chandlers
import ops_sunbeam.core as sunbeam_core

from charms.observability_libs.v1.kubernetes_service_patch import KubernetesServicePatch
import pebble_handlers

logger = logging.getLogger(__name__)


class KubeflowProfilesOperator(sunbeam_charm.OSBaseOperatorCharmK8S):
    """A Juju Charm for Kubeflow Profiles Operator."""

    _stored = StoredState()

    # TODO: Not sure why this is really needed.  Added it for now to unblock the database features
    service_name = "kubeflow-profiles"

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


if __name__ == "__main__":
    main(KubeflowProfilesOperator)
