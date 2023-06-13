import logging

from ops.pebble import Layer

from functional_base_charm.pebble_component import PebbleServiceComponent


logger = logging.getLogger(__name__)


class KubeflowProfilesContainerComponent(PebbleServiceComponent):
    # TODO: Should this be something we subclass to define settings, or should PebbleServiceComponent just have
    #  .add_service, .add_check, etc?
    def get_layer(self) -> Layer:
        """Pebble configuration layer for kubeflow-profiles.

        This method is required for subclassing PebbleServiceComponent
        """
        logger.info("KubeflowProfilesContainerComponent.get_layer executing")
        return Layer({
            "services": {
                # TODO: should this be an attribute?  Or handled somehow else?
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
        })


class KubeflowKfamContainerComponent(PebbleServiceComponent):
    # TODO: Should this be something we subclass to define settings, or should PebbleServiceComponent just have
    #  .add_service, .add_check, etc?
    def get_layer(self) -> Layer:
        """Pebble configuration layer for kubeflow-profiles.

        This method is required for subclassing PebbleServiceComponent
        """
        logger.info("KubeflowKfamContainerComponent.get_layer executing")
        return Layer({
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
        })
