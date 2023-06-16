from ops import CharmBase, StatusBase

from functional_base_charm.component import Component
from charms.kubeflow_profiles.v0.kubeflow_profiles import KubeflowProfilesProvides


# TODO: What of this can we abstract to something more general?  And what can be refactored?
#  Seems like the relation name could be more obvious, and should we validate that we can add
#  a handler like Sunbeam does or just skip that?

class KubeflowProfilesProvidesComponent(Component):
    """Wraps the logic needed to manage a relation in a charm main."""

    def __init__(self, charm: CharmBase, name: str):
        super().__init__(charm, name)

        self.kubeflow_profiles_provides = KubeflowProfilesProvides(
            charm=self._charm,
            relation_name=name,
            refresh_event=None,  # By default, it triggers on relation changed and config changed
        )

        self._events_to_observe += [
            self.kubeflow_profiles_provides.on.no_versions_listed,
            self.kubeflow_profiles_provides.on.no_compatible_versions,
            self.kubeflow_profiles_provides.on.data_sent,
        ]

    def _configure_unit(self, event):
        pass

    def _configure_app_leader(self, event):
        pass

    def _configure_app_non_leader(self, event):
        pass

    @property
    def status(self) -> StatusBase:
        return self.kubeflow_profiles_provides.get_status()
