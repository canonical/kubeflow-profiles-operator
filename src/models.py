"""Module to validate the charm configuration using pydantic."""

from typing import Literal

from pydantic import BaseModel, Field


class CharmConfig(BaseModel):
    """A model for validating the charm's configuration."""

    # Restrict to non-privileged ports (>= 1024) since the process doesn't run as superuser
    # Cap at the maximum allowable port number (<= 65535)
    port: int = Field(ge=1024, le=65535)
    manager_port: int = Field(ge=1024, le=65535)
    security_policy: Literal["privileged", "baseline", "restricted"]
