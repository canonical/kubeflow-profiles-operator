"""Charms dependencies for tests."""

from charmed_kubeflow_chisme.testing import CharmSpec

ISTIO_PILOT = CharmSpec(charm="istio-pilot", channel="1.24/stable", trust=True)
