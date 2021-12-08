#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import yaml
from pathlib import Path

from ops.charm import CharmBase
from ops.main import main
from ops.model import ActiveStatus, WaitingStatus, BlockedStatus
from ops.framework import StoredState

from oci_image import OCIImageResource, OCIImageResourceError
from serialized_data_interface import (
    NoCompatibleVersions,
    NoVersionsListed,
    get_interfaces,
)


class Operator(CharmBase):
    _stored = StoredState()

    def __init__(self, *args):
        super().__init__(*args)

        self.log = logging.getLogger(__name__)

        self.profile_image = OCIImageResource(self, "profile-image")
        self.kfam_image = OCIImageResource(self, "kfam-image")

        for event in [
            self.on.install,
            self.on.leader_elected,
            self.on.upgrade_charm,
            self.on.config_changed,
            self.on["kubeflow-profiles"].relation_changed,
        ]:
            self.framework.observe(event, self.main)

    def main(self, event):
        try:
            self._check_leader()

            interfaces = self._get_interfaces()

            profile_image_details = self.profile_image.fetch()
            kfam_image_details = self.kfam_image.fetch()

        except (CheckFailed, OCIImageResourceError) as error:
            self.model.unit.status = error.status
            return

        self._send_info(event, interfaces)

        namespace_labels_filename = "namespace-labels.yaml"

        self.model.pod.set_spec(
            spec={
                "version": 3,
                "serviceAccount": {
                    "roles": [
                        {
                            "global": True,
                            "rules": [
                                {
                                    "apiGroups": ["*"],
                                    "resources": ["*"],
                                    "verbs": ["*"],
                                },
                                {"nonResourceURLs": ["*"], "verbs": ["*"]},
                            ],
                        }
                    ]
                },
                "containers": [
                    {
                        "name": "kubeflow-profiles",
                        "imageDetails": profile_image_details,
                        "command": ["/manager"],
                        "args": [
                            "-userid-header",
                            "kubeflow-userid",
                            "-userid-prefix",
                            "",
                            "-workload-identity",
                            "",
                        ],
                        "ports": [
                            {
                                "name": "manager",
                                "containerPort": self.model.config["manager-port"],
                            }
                        ],
                        "kubernetes": {
                            "livenessProbe": {
                                "httpGet": {
                                    "path": "/metrics",
                                    "port": self.model.config["manager-port"],
                                },
                                "initialDelaySeconds": 30,
                                "periodSeconds": 30,
                            }
                        },
                        "volumeConfig": [
                            {
                                "name": "namespace-labels-data",
                                "mountPath": "/etc/profile-controller",
                                "configMap": {
                                    "name": "namespace-labels-data",
                                    "files": [
                                        {
                                            "key": namespace_labels_filename,
                                            "path": namespace_labels_filename,
                                        }
                                    ],
                                },
                            }
                        ],
                    },
                    {
                        "name": "kubeflow-kfam",
                        "imageDetails": kfam_image_details,
                        "command": ["/access-management"],
                        "args": [
                            "-cluster-admin",
                            "admin",
                            "-userid-header",
                            "kubeflow-userid",
                            "-userid-prefix",
                            "",
                        ],
                        "ports": [
                            {"name": "http", "containerPort": self.model.config["port"]}
                        ],
                        "kubernetes": {
                            "livenessProbe": {
                                "httpGet": {
                                    "path": "/metrics",
                                    "port": self.model.config["port"],
                                },
                                "initialDelaySeconds": 30,
                                "periodSeconds": 30,
                            }
                        },
                    },
                ],
            },
            k8s_resources={
                "kubernetesResources": {
                    "customResourceDefinitions": [
                        {"name": crd["metadata"]["name"], "spec": crd["spec"]}
                        for crd in yaml.safe_load_all(
                            Path("files/crds.yaml").read_text()
                        )
                    ],
                },
                "configMaps": {
                    "namespace-labels-data": {
                        namespace_labels_filename: Path(
                            f"files/{namespace_labels_filename}"
                        ).read_text(),
                    }
                },
            },
        )
        self.log.info("pod.set_spec() completed without errors")

        self.model.unit.status = ActiveStatus()

    def _send_info(self, event, interfaces):
        if interfaces["kubeflow-profiles"]:
            interfaces["kubeflow-profiles"].send_data(
                {
                    "service-name": self.model.app.name,
                    "service-port": str(self.model.config["port"]),
                }
            )

    def _check_leader(self):
        if not self.unit.is_leader():
            # We can't do anything useful when not the leader, so do nothing.
            raise CheckFailed("Waiting for leadership", WaitingStatus)

    def _get_interfaces(self):
        try:
            interfaces = get_interfaces(self)
        except NoVersionsListed as err:
            raise CheckFailed(err, WaitingStatus)
        except NoCompatibleVersions as err:
            raise CheckFailed(err, BlockedStatus)
        return interfaces


class CheckFailed(Exception):
    """ Raise this exception if one of the checks in main fails. """

    def __init__(self, msg: str, status_type=None):
        super().__init__()

        self.msg = str(msg)
        self.status_type = status_type
        self.status = status_type(self.msg)


if __name__ == "__main__":
    main(Operator)
