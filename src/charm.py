#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import yaml
import tempfile
from pathlib import Path
from subprocess import check_call

from ops.charm import CharmBase
from ops.main import main
from ops.pebble import Layer, ChangeError
from ops.model import ActiveStatus, WaitingStatus, BlockedStatus, MaintenanceStatus
from ops.framework import StoredState
from charms.observability_libs.v1.kubernetes_service_patch import KubernetesServicePatch
from charmed_kubeflow_chisme.kubernetes import KubernetesResourceHandler as KRH
from charmed_kubeflow_chisme.pebble import update_layer
from charmed_kubeflow_chisme.exceptions import ErrorWithStatus
from lightkube.models.core_v1 import ServicePort
from lightkube.generic_resource import load_in_cluster_generic_resources
from lightkube import ApiError

from oci_image import OCIImageResource, OCIImageResourceError
from serialized_data_interface import (
    NoCompatibleVersions,
    NoVersionsListed,
    get_interfaces,
)

K8S_RESOURCE_FILES=[
    "src/files/auth_manifests.yaml.j2",
    "src/files/crds.yaml.j2",
]

SSL_CONFIG_FILE="/files/ssl.conf.j2"

class KubeflowProfilesOperator(CharmBase):
    _stored = StoredState()

    def __init__(self, *args):
        super().__init__(*args)

        self.log = logging.getLogger(__name__)

        self._manager_port = self.model.config["manager-port"]
        self._kfam_port = self.model.config["port"]

        manager_port = ServicePort(int(self._manager_port), name="manager")
        kfam_port = ServicePort(int(self._kfam_port), name="http")
        self.service_patcher = KubernetesServicePatch(
            self,
            [manager_port, kfam_port],
            service_name=f"{self.model.app.name}",
        )

        self._profiles_container_name="kubeflow-profiles"
        self._profiles_container=self.unit.get_container(self._profiles_container_name)

        self._kfam_container_name="kubeflow-kfam"
        self._kfam_container=self.unit.get_container(self._kfam_container_name)

        self._namespace=self.model.name
        self._name=self.model.app.name
        self._lightkube_field_manager = "lightkube"
        self._k8s_resource_handler = None

        #generate certs
        #self._stored.set_default(**self._gen_certs())

        for event in [
            self.on.install,
            self.on.leader_elected,
            self.on.upgrade_charm,
            self.on.config_changed,
            self.on["kubeflow-profiles"].relation_changed,
        ]:
            self.framework.observe(event, self.main)
        self.framework.observe(self.on.kubeflow_profiles_pebble_ready, self._on_kubeflow_profiles_ready)
        self.framework.observe(self.on.kubeflow_kfam_pebble_ready, self._on_kfam_ready)

    @property
    def profiles_container(self):
        """"Return profile container"""
        return self._profiles_container

    @property
    def kfam_container(self):
        """"Return kfam container"""
        return self._kfam_container

    @property
    def k8s_resource_handler(self):
        if not self._k8s_resource_handler:
            self._k8s_resource_handler = KRH(
                field_manager=self._lightkube_field_manager,
                template_files=K8S_RESOURCE_FILES,
                context=self._context,
                logger=self.log,
            )
        load_in_cluster_generic_resources(self._k8s_resource_handler.lightkube_client)
        return self._k8s_resource_handler

    @k8s_resource_handler.setter
    def k8s_resource_handler(self, handler: KRH):
        self._k8s_resource_handler = handler

    def _deploy_k8s_resources(self):
        try:
            self.unit.status = MaintenanceStatus("Creating K8S resources")
            self.k8s_resource_handler.apply()
        except ApiError:
            raise ErrorWithStatus("K8S resources creation failed", BlockedStatus)
        self.model.unit.status = MaintenanceStatus("K8S resources created")

    def _on_install(self, _):
        """Perform installation only actions."""
        self._check_container_connection(self.profiles_container)
        self._check_container_connection(self.kfam_container)
        #self._upload_certs_to_container()

        # proceed with other actions
        self.main(_)

    @property
    def _context(self):
        context = {
            "app_name": self.model.app.name,
            "namespace": self.model.name
        }
        return context

    def _upload_certs_to_container(self):
        """Upload generated certs to container."""
        self.container.push(
            "/tmp/k8s-webhook-server/serving-certs/tls.key",
            self._stored.key,
            make_dirs=True,
        )
        self.container.push(
            "/tmp/k8s-webhook-server/serving-certs/tls.crt",
            self._stored.cert,
            make_dirs=True,
        )
        self.container.push(
            "/tmp/k8s-webhook-server/serving-certs/ca.crt",
            self._stored.ca,
            make_dirs=True,
        )


    @property
    def _profiles_pebble_layer(self)-> Layer:
        """Return the Pebble layer for the workload."""
        return Layer(
            {
                "services": {
                    self._profiles_container_name: {
                        "override": "replace",
                        "summary": "entry point for kubeflow profiles",
                        "command": ("/manager "
                        "-userid-header "
                        "kubeflow-userid "
                        "-userid-prefix "
                        " "
                        "-workload-identity "
                        " "),
                        "startup": "enabled",
                    },
                },
        #         "checks": {
        #             "kubeflow-profiles-ready": {
        #                 "override": "replace",
        #                 "http": {"url": "http://localhost:8080/metrics/health/ready"},
        #                 },
        #             "kubeflow-profiles-alive": {
        #                 "override": "replace",
        #                 "http": {"url": "http://localhost:8080/metrics/health/alive"},
        #     },
        # },
            }
        )

    @property
    def _kfam_pebble_layer(self)-> Layer:
        """Return the Pebble layer for the workload."""
        return Layer(
            {
                "services": {
                    self._kfam_container_name: {
                        "override": "replace",
                        "summary": "entry point for kubeflow access management",
                        "command": ("/access-management "
                        "-cluster-admin "
                        "admin "
                        "-userid-header "
                        "kubeflow-userid "
                        "-userid-prefix "
                        " "
                        ),
                        "startup": "enabled",
                    }
                },
        #         "checks": {
        #             "kubeflow-kfam-ready": {
        #                 "override": "replace",
        #                 "http": {"url": "http://localhost:8081/metrics/health/ready"},
        #                 },
        #             "kubeflow-kfam-alive": {
        #                 "override": "replace",
        #                 "http": {"url": "http://localhost:8081/metrics/health/alive"},
        #     },
        # },
            }
        )

    def _on_kubeflow_profiles_ready(self, event):
        """Define and start a workload using the Pebble API.
        Learn more about Pebble layers at https://github.com/canonical/pebble
        """
        try:
            with open("files/namespace-labels.yaml", encoding="utf-8") as labels_file:
                labels = labels_file.read()
                self.profiles_container.push('/etc/profile-/namespace-labels.yaml', labels, make_dirs=True)

            update_layer(
                self._profiles_container_name,
                self.profiles_container,
                self._profiles_pebble_layer,
                self.log,
            )

        except ErrorWithStatus as e:
            self.model.unit.status = e.status
            if isinstance(e.status, BlockedStatus):
                self.log.error(str(e.msg))
            else:
                self.log.info(str(e.msg))

        self.unit.status = ActiveStatus()

    def _on_kfam_ready(self,event):
        """Define and start a workload using the Pebble API.
        Learn more about Pebble layers at https://github.com/canonical/pebble
        """
        try:    
            update_layer(
                self._kfam_container_name,
                self.kfam_container,
                self._kfam_pebble_layer,
                self.log,
            )

        except ErrorWithStatus as e:
            self.model.unit.status = e.status
            if isinstance(e.status, BlockedStatus):
                self.log.error(str(e.msg))
            else:
                self.log.info(str(e.msg))

        self.unit.status = ActiveStatus()


    # self.model.pod.set_spec(
    #     spec={
    #         "version": 3,
    #         "serviceAccount": {
    #             "roles": [
    #                 {
    #                     "global": True,
    #                     "rules": [
    #                         {
    #                             "apiGroups": ["*"],
    #                             "resources": ["*"],
    #                             "verbs": ["*"],
    #                         },
    #                         {"nonResourceURLs": ["*"], "verbs": ["*"]},
    #                     ],
    #                 }
    #             ]
    #         },
    #         "containers": [
    #             {
    #                 "name": "kubeflow-profiles",
    #                 "imageDetails": profile_image_details,
    #                 "command": ["/manager"],
    #                 "args": [
    #                     "-userid-header",
    #                     "kubeflow-userid",
    #                     "-userid-prefix",
    #                     "",
    #                     "-workload-identity",
    #                     "",
    #                 ],
    #                 "ports": [
    #                     {
    #                         "name": "manager",
    #                         "containerPort": self.model.config["manager-port"],
    #                     }
    #                 ],
    #                 "kubernetes": {
    #                     "livenessProbe": {
    #                         "httpGet": {
    #                             "path": "/metrics",
    #                             "port": self.model.config["manager-port"],
    #                         },
    #                         "initialDelaySeconds": 30,
    #                         "periodSeconds": 30,
    #                     }
    #                 },
    #                 "volumeConfig": [
    #                     {
    #                         "name": "namespace-labels-data",
    #                         "mountPath": "/etc/profile-controller",
    #                         "configMap": {
    #                             "name": "namespace-labels-data",
    #                             "files": [
    #                                 {
    #                                     "key": namespace_labels_filename,
    #                                     "path": namespace_labels_filename,
    #                                 }
    #                             ],
    #                         },
    #                     }
    #                 ],
    #             },
    #             {
    #                 "name": "kubeflow-kfam",
    #                 "imageDetails": kfam_image_details,
    #                 "command": ["/access-management"],
    #                 "args": [
    #                     "-cluster-admin",
    #                     "admin",
    #                     "-userid-header",
    #                     "kubeflow-userid",
    #                     "-userid-prefix",
    #                     "",
    #                 ],
    #                 "ports": [
    #                     {"name": "http", "containerPort": self.model.config["port"]}
    #                 ],
    #                 "kubernetes": {
    #                     "livenessProbe": {
    #                         "httpGet": {
    #                             "path": "/metrics",
    #                             "port": self.model.config["port"],
    #                         },
    #                         "initialDelaySeconds": 30,
    #                         "periodSeconds": 30,
    #                     }
    #                 },
    #             },
    #         ],
    #     },
    #     k8s_resources={
    #         "kubernetesResources": {
    #             "customResourceDefinitions": [
    #                 {"name": crd["metadata"]["name"], "spec": crd["spec"]}
    #                 for crd in yaml.safe_load_all(
    #                     Path("files/crds.yaml").read_text()
    #                 )
    #             ],
    #         },
    #         "configMaps": {
    #             "namespace-labels-data": {
    #                 namespace_labels_filename: Path(
    #                     f"files/{namespace_labels_filename}"
    #                 ).read_text(),
    #             }
    #         },
    #     },
    # )
    #self.log.info("pod.set_spec() completed without errors")

    #self.model.unit.status = ActiveStatus()

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

    def _check_container_connection(self, container):
        if not container.can_connect():
            raise CheckFailed("Pod startup is not complete", MaintenanceStatus)

    def _get_interfaces(self):
        try:
            interfaces = get_interfaces(self)
        except NoVersionsListed as err:
            raise CheckFailed(err, WaitingStatus)
        except NoCompatibleVersions as err:
            raise CheckFailed(err, BlockedStatus)
        return interfaces

    def _gen_certs(self):
        """Generate certificates."""
        # generate SSL configuration based on template
        model = self.model.name

        try:
            ssl_conf_template = open(SSL_CONFIG_FILE)
            ssl_conf = ssl_conf_template.read()
        except ApiError as error:
            self.log.warning(f"Failed to open SSL config file: {error}")

        ssl_conf = ssl_conf.replace("{{ namespace }}", str(self._namespace))
        ssl_conf = ssl_conf.replace("{{ service_name }}", str(self._name))
        with tempfile.TemporaryDirectory() as tmp_dir:
            Path(tmp_dir + "/profiles-cert-gen-ssl.conf").write_text(ssl_conf)

            # execute OpenSSL commands
            check_call(["openssl", "genrsa", "-out", tmp_dir + "/profiles-cert-gen-ca.key", "2048"])
            check_call(
                ["openssl", "genrsa", "-out", tmp_dir + "/profiles-cert-gen-server.key", "2048"]
            )
            check_call(
                [
                    "openssl",
                    "req",
                    "-x509",
                    "-new",
                    "-sha256",
                    "-nodes",
                    "-days",
                    "3650",
                    "-key",
                    tmp_dir + "/profiles-cert-gen-ca.key",
                    "-subj",
                    "/CN=127.0.0.1",
                    "-out",
                    tmp_dir + "/profiles-cert-gen-ca.crt",
                ]
            )
            check_call(
                [
                    "openssl",
                    "req",
                    "-new",
                    "-sha256",
                    "-key",
                    tmp_dir + "/profiles-cert-gen-server.key",
                    "-out",
                    tmp_dir + "/profiles-cert-gen-server.csr",
                    "-config",
                    tmp_dir + "/profiles-cert-gen-ssl.conf",
                ]
            )
            check_call(
                [
                    "openssl",
                    "x509",
                    "-req",
                    "-sha256",
                    "-in",
                    tmp_dir + "/profiles-cert-gen-server.csr",
                    "-CA",
                    tmp_dir + "/profiles-cert-gen-ca.crt",
                    "-CAkey",
                    tmp_dir + "/profiles-cert-gen-ca.key",
                    "-CAcreateserial",
                    "-out",
                    tmp_dir + "/profiles-cert-gen-cert.pem",
                    "-days",
                    "365",
                    "-extensions",
                    "v3_ext",
                    "-extfile",
                    tmp_dir + "/profiles-cert-gen-ssl.conf",
                ]
            )

            ret_certs = {
                "cert": Path(tmp_dir + "/profiles-cert-gen-cert.pem").read_text(),
                "key": Path(tmp_dir + "/profiles-cert-gen-server.key").read_text(),
                "ca": Path(tmp_dir + "/profiles-cert-gen-ca.crt").read_text(),
            }

            # cleanup temporary files
            check_call(["rm", "-f", tmp_dir + "/profiles-cert-gen-*"])

        return ret_certs

    def main(self, event):
        try:
            self._check_container_connection(self.profiles_container)
            self._check_container_connection(self.kfam_container)
            self._check_leader()
            self._deploy_k8s_resources()

            interfaces = self._get_interfaces()

        except (CheckFailed, OCIImageResourceError) as error:
            self.model.unit.status = error.status
            return

        self._send_info(event, interfaces)

        namespace_labels_filename = "namespace-labels.yaml"


class CheckFailed(Exception):
    """Raise this exception if one of the checks in main fails."""

    def __init__(self, msg: str, status_type=None):
        super().__init__()

        self.msg = str(msg)
        self.status_type = status_type
        self.status = status_type(self.msg)


if __name__ == "__main__":
    main(KubeflowProfilesOperator)
