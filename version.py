"""Central version identifier for EDMC Modern Overlay."""
from __future__ import annotations

import os
from typing import Optional

__all__ = ["__version__", "is_dev_build", "DEV_MODE_ENV_VAR"]

__version__ = "0.7.6"
DEV_MODE_ENV_VAR = "MODERN_OVERLAY_DEV_MODE"


def _coerce_bool(value: Optional[str]) -> Optional[bool]:
    if value is None:
        return None
    token = value.strip().lower()
    if token in {"1", "true", "yes", "on"}:
        return True
    if token in {"0", "false", "no", "off"}:
        return False
    return None


def is_dev_build(version: Optional[str] = None) -> bool:
    """Return True when the current build should enable developer-only behaviour."""

    env_override = _coerce_bool(os.getenv(DEV_MODE_ENV_VAR))
    if env_override is not None:
        return env_override

    identifier = (version or __version__ or "").strip().lower()
    if not identifier:
        return False

    # Accept common dev markers: "-dev", ".dev#", or an explicit "dev" segment.
    if identifier.endswith("-dev"):
        return True
    if ".dev" in identifier:
        return True
    return any(part == "dev" for part in identifier.replace(".", "-").split("-"))
