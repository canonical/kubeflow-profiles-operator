from typing import Any, Dict, Literal

import ops
from charmed_kubeflow_chisme.exceptions import ErrorWithStatus
from pydantic import BaseModel, Field, ValidationError


class CharmConfig(BaseModel):
    """A model for validating the charm's configuration."""

    port: int = Field(gt=1024, lt=65535)
    manager_port: int = Field(gt=1024, lt=65535)
    security_policy: Literal["baseline", "privileged"]


def validate_config(config: Dict[str, Any]):
    """
    Validates all config options using the above model.

    Args:
        config: A dictionary of config values

    Raises:
        ErrorWithStatus: If the validation fails
    """
    try:
        CharmConfig(**config)
    except ValidationError as e:
        error_msg = f"Invalid config: {e}"
        raise ErrorWithStatus(error_msg, ops.BlockedStatus)
