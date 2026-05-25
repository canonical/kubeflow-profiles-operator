# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration test configuration and shared fixtures."""

from _pytest.config.argparsing import Parser


def pytest_addoption(parser: Parser):
    """Register custom command-line options for integration tests."""
    parser.addoption(
        "--charm-path",
        help="Path to charm file for performing tests on.",
    )
