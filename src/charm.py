#!/usr/bin/env python3

import logging
import yaml
from pathlib import Path

from ops.charm import CharmBase, HookEvent, EventSource, ObjectEvents
from ops.main import main
from ops.model import ActiveStatus, WaitingStatus, BlockedStatus
from ops.framework import StoredState

from oci_image import OCIImageResource, OCIImageResourceError
from serialized_data_interface import (
    NoCompatibleVersions,
    NoVersionsListed,
    get_interfaces,
)


class CustomEvent(HookEvent):
    def __init__(self, handle, message="No message"):
        super().__init__(handle)
        self.i_am_custom = True
        self.message = message


# class CharmCustomEvents(ObjectEvents):
#     custom_event = EventSource(CustomEvent)


class Operator(CharmBase):
    # custom_events = CharmCustomEvents()
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

        self.custom_event = CustomEvent

        # self.on.define_event("custom_event", self.custom_events.custom_event)
        self.on.define_event("custom_event", self.custom_event)
        self.framework.observe(self.on.custom_event, self._handle_custom_event)
        # self.custom_events.custom_event.emit("from __init__")
        # self.custom_event.emit()
        self.on.custom_event.emit()

    # def _handle_custom_event(self, event, message):
    def _handle_custom_event(self, event):
        self.log.error("HANDLING CUSTOM EVENT!")
        # self.log.error(f"message: '{message}")

    def send_info(self, event):
        if self.interfaces["kubeflow-profiles"]:
            self.interfaces["kubeflow-profiles"].send_data(
                {
                    "service-name": self.model.app.name,
                    "service-port": str(self.model.config["port"]),
                }
            )

    def main(self, event):
        # self.custom_events.custom_event.emit("from set_pod_spec")
        # self.custom_event.emit()
        self.on.custom_event.emit()

        try:
            profile_image_details = self.profile_image.fetch()
            kfam_image_details = self.kfam_image.fetch()
        except OCIImageResourceError as e:
            self.model.unit.status = e.status
            self.log.info(e)
            return

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
                            "cluster-admin",  # This might be needed for multiuser kfp?  Without it I get kfp errors in UI when loading experiments page, with error that says we don't have a cluster admin.
                            "admin",
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
                            "admin",  # Is this the name used for the profile that is generated automatically before any logins?
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


if __name__ == "__main__":
    main(Operator)
