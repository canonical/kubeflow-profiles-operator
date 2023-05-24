#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""The Pebble handler wrapper classes for this charm"""

import logging

from ops.pebble import Layer
from ops_sunbeam.container_handlers import ServicePebbleHandler

logger = logging.getLogger(__name__)


class KubeflowProfilesPebbleHandler(ServicePebbleHandler):
    """Manage kubeflow-profiles container."""

    def get_layer(self) -> dict:
        """Pebble configuration layer for kubeflow-profiles.

        This method is required for subclassing ServicePebbleHandler
        """
        logger.info("KubeflowProfilesPebbleHandler.get_layer executing")
        return {
            "services": {
                self.service_name: {
                    "override": "replace",
                    "summary": "entry point for kubeflow profiles",
                    "command": (
                        "/manager " "-userid-header " "kubeflow-userid " "-userid-prefix " '""'
                    ),
                    "startup": "enabled",
                }
            },
            "checks": {
                "kubeflow-profiles-get": {
                    "override": "replace",
                    "period": "30s",
                    "http": {"url": "http://localhost:8080/metrics"},
                }
            },
        }

    # def write_config(self):
        # TODO: Should I override due to notes below?
        # Override this because the standard way is a bit openstack-specific.
        # Modelled after https://opendev.org/openstack/charm-ops-sunbeam/src/commit/f9fff19596a784d60be40d7076f4c6f40f677fb1/ops_sunbeam/container_handlers.py#L98
        # which used https://opendev.org/openstack/charm-ops-sunbeam/src/commit/6a7f80a2eee0d8626e9c09080b151f56a2f28b0e/ops_sunbeam/templating.py#L49
        # and has some built-in logic around the templates.
        # But maybe it is close enough... looks like just user, group, and permissions are default kwargs that are passed


class KFAMHandler(ServicePebbleHandler):
    """Manage kfam container."""

    def get_layer(self) -> dict:
        """Pebble configuration layer for kfam.

        This method is required for subclassing ServicePebbleHandler
        """
        logger.info("KFAMHandler.get_layer executing")
        return {
            "services": {
                self.service_name: {
                    "override": "replace",
                    "summary": "entry point for kubeflow access management",
                    "command": (
                        "/access-management "
                        "-cluster-admin "
                        "admin "
                        "-userid-header "
                        "kubeflow-userid "
                        "-userid-prefix "
                        '""'
                    ),
                    "startup": "enabled",
                }
            },
            "checks": {
                "kubeflow-kfam-get": {
                    "override": "replace",
                    "period": "30s",
                    "http": {"url": "http://localhost:8081/metrics"},
                }
            },
        }
