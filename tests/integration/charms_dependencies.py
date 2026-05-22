"""Charms dependencies for tests."""

from charmed_kubeflow_chisme.testing import CharmSpec

ISTIO_PILOT = CharmSpec(charm="istio-pilot", channel="1.28/edge", trust=True)
KUBEFLOW_DASHBOARD = CharmSpec(charm="kubeflow-dashboard", channel="2.0/edge", trust=True)
