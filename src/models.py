"""Module to validate the charm configuration using pydantic."""

from typing import Literal

from pydantic import BaseModel, Field


class CharmConfig(BaseModel):
    """A model for validating the charm's configuration."""

    port: int = Field(ge=1024, lt=65535)
    manager_port: int = Field(ge=1024, lt=65535)
    security_policy: Literal["privileged", "baseline", "restricted"]
