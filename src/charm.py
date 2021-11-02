#!/usr/bin/env python3

import logging
import yaml
from pathlib import Path

from ops.charm import CharmBase
from ops.main import main
from ops.model import ActiveStatus, WaitingStatus, BlockedStatus, StatusBase
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
        ]:
            self.framework.observe(event, self.install)

        # This was on relation_changed - should it be on relation_joined?  Or both?
        # Can sending data on relation_changed lead to an infinite loop?
        self.framework.observe(self.on["kubeflow-profiles"].relation_joined, self.provide_profiles_relation)
        self.framework.observe(self.on["kubeflow-profiles"].relation_changed, self.provide_profiles_relation)

        self.framework.observe(self.on.update_status, self.update_status)

    def install(self, event):
        # I think we've discussed not wanting to set status in helpers, so helpers here return
        # status.  I could also see a case for using `self._some_status_helper(raise_status=True)`
        # that would set self.model.unit.status automatically if != Active

        # Check if we have anything we depend on
        if not isinstance(dependency_status := self._check_dependencies(), ActiveStatus):
            self.model.unit.status = dependency_status
            return

        if not isinstance(is_leader := self._check_is_leader(), ActiveStatus):
            self.model.unit.status = is_leader
            return

        self._set_pod_spec()

        self.update_status(event)

    def provide_profiles_relation(self, event):
        # This charm provides a relation - should this validation happen on the provider side or
        # the client side?  Kubeflow Profiles works properly regardless of whether this relation
        # is established, the only thing that is blocked is any user of the profile.
        # At most, these feel like warnings that should still leave profiles Active

        # Validate relation versions
        try:
            self.interfaces = get_interfaces(self)
        except NoVersionsListed as err:
            self.model.unit.status = WaitingStatus(str(err))
            return
        except NoCompatibleVersions as err:
            self.model.unit.status = BlockedStatus(str(err))

        self._send_relation_data()

        # If we leave the validation of relation versions in this function, we need to also do:
        self.update_status(event)

    def _send_relation_data(self):
        if self.interfaces["kubeflow-profiles"]:
            self.interfaces["kubeflow-profiles"].send_data(
                {
                    "service-name": self.model.app.name,
                    "service-port": str(self.model.config["port"]),
                }
            )

    def update_status(self, event):
        self.model.unit.status = self._get_application_status()
        # This could also try to fix a broken application if status != Active

    def _check_dependencies(self) -> StatusBase:
        # TODO: Check if any dependencies required by this charm are available and Block otherwise
        #       This charm would check for Istio CRDs, maybe other stuff

        # This might make sense to return a list of statuses in case we're missing multiple things
        return ActiveStatus()

    def _get_application_status(self) -> StatusBase:
        # TODO: Do whatever checks are needed to confirm we are actually working correctly
        #       Maybe check for key deployments, etc?

        # Until we have a real check - cheat :)  Note that this needs to be fleshed out if actually
        # used by a relation hook
        return ActiveStatus()

    # TODO: I think there's a better way to do the return type hint here
    def _check_is_leader(self) -> StatusBase:
        if not self.unit.is_leader():
            return WaitingStatus("Waiting for leadership")
        else:
            # Or we could return None. It felt odd that this function would return a status or None
            return ActiveStatus()

    def _set_pod_spec(self):
        namespace_labels_filename = "namespace-labels.yaml"

        # Let this on its own as I think it is just valid for install?
        try:
            profile_image_details = self.profile_image.fetch()
            kfam_image_details = self.kfam_image.fetch()
        except OCIImageResourceError as e:
            self.model.unit.status = e.status
            self.log.info(e)
            return

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


if __name__ == "__main__":
    main(Operator)
