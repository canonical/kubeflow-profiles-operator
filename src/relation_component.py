from ops import CharmBase, StatusBase

from functional_base_charm.component import Component
from charms.kubeflow_profiles.v0.kubeflow_profiles import KubeflowProfilesProvides


# TODO: What of this can we abstract to something more general?  And what can be refactored?
#  Seems like the relation name could be more obvious, and should we validate that we can add
#  a handler like Sunbeam does or just skip that?

class KubeflowProfilesProvidesComponent(Component):
    """Wraps the logic needed to manage a relation in a charm main.

    For this case, it is a simple wrapper that instantiates the KubeflowProfilesProvides charm
    library and adds a status method to report status.  All other function is handled from within
    the KubeflowProfilesProvides lib.
    """

    def __init__(self, charm: CharmBase, name: str, relation_name: str):
        super().__init__(charm, name)
        self.relation_name = relation_name

        self.kubeflow_profiles_provides = KubeflowProfilesProvides(
            charm=self._charm,
            relation_name=self.relation_name,
            refresh_event=None,  # By default, it triggers on relation changed and config changed
        )

        # TODO: There is nothing to do in the charm, so this really isn't needed here.  Left it for
        #  now because this is an example of how other relations could work, but this is not needed
        self._events_to_observe += [
            self.kubeflow_profiles_provides.on.no_versions_listed,
            self.kubeflow_profiles_provides.on.no_compatible_versions,
            self.kubeflow_profiles_provides.on.data_sent,
        ]

    @property
    def status(self) -> StatusBase:
        return self.kubeflow_profiles_provides.get_status()
