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
