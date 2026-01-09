"""Charms dependencies for tests."""

from charmed_kubeflow_chisme.testing import CharmSpec

ISTIO_PILOT = CharmSpec(charm="istio-pilot", channel="latest/edge", trust=True)
KUBEFLOW_DASHBOARD = CharmSpec(charm="kubeflow-dashboard", channel="latest/edge", trust=True)
