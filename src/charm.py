#!/usr/bin/env python3

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
        if not self.unit.is_leader():
            # We can't do anything useful when not the leader, so do nothing.
            self.model.unit.status = WaitingStatus("Waiting for leadership")
            return
        self.log = logging.getLogger(__name__)
        self.profile_image = OCIImageResource(self, "profile-image")
        self.kfam_image = OCIImageResource(self, "kfam-image")
        try:
            self.interfaces = get_interfaces(self)
        except NoVersionsListed as err:
            self.model.unit.status = WaitingStatus(str(err))
            return
        except NoCompatibleVersions as err:
            self.model.unit.status = BlockedStatus(str(err))
            return

        for event in [
            self.on.install,
            self.on.leader_elected,
            self.on.upgrade_charm,
            self.on.config_changed,
        ]:
            self.framework.observe(event, self.main)

        self.framework.observe(
            self.on["kubeflow-profiles"].relation_changed, self.send_info
        )

    def send_info(self, event):
        if self.interfaces["kubeflow-profiles"]:
            self.interfaces["kubeflow-profiles"].send_data(
                {
                    "service-name": self.model.app.name,
                    "service-port": str(self.model.config["port"]),
                }
            )

    def main(self, event):
        try:
            profile_image_details = self.profile_image.fetch()
            kfam_image_details = self.kfam_image.fetch()
        except OCIImageResourceError as e:
            self.model.unit.status = e.status
            self.log.info(e)
            return

        self.model.pod.set_spec(
            {
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
            {
                "kubernetesResources": {
                    "customResourceDefinitions": [
                        {"name": crd["metadata"]["name"], "spec": crd["spec"]}
                        for crd in yaml.safe_load_all(
                            Path("files/crds.yaml").read_text()
                        )
                    ],
                }
            },
        )

        self.model.unit.status = ActiveStatus()


if __name__ == "__main__":
    main(Operator)
