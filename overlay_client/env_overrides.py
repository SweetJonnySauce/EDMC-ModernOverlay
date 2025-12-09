from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Mapping


@dataclass
class MergeResult:
    applied: list[str] = field(default_factory=list)
    skipped_env: list[str] = field(default_factory=list)
    skipped_existing: list[str] = field(default_factory=list)
    provenance: Mapping[str, object] = field(default_factory=dict)


def load_overrides(path: Path) -> Mapping[str, object]:
    """Load overrides JSON, returning {} on errors."""
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError:
        return {}
    try:
        data = json.loads(raw)
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    env_block = data.get("env")
    if not isinstance(env_block, dict):
        env_block = {}
    provenance = data.get("provenance")
    if not isinstance(provenance, dict):
        provenance = {}
    return {"env": env_block, "provenance": provenance}


def apply_overrides(
    env: Dict[str, str],
    overrides: Mapping[str, object],
    *,
    logger: object | None = None,
) -> MergeResult:
    """Merge overrides into env without clobbering already-set keys."""
    result = MergeResult()
    env_block = {}
    if isinstance(overrides, dict):
        candidate = overrides.get("env")
        if isinstance(candidate, dict):
            env_block = candidate
        provenance = overrides.get("provenance")
        if isinstance(provenance, dict):
            result.provenance = provenance
    for key, value in env_block.items():
        if key in os.environ:
            result.skipped_env.append(key)
            continue
        if key in env:
            result.skipped_existing.append(key)
            continue
        env[key] = str(value)
        result.applied.append(key)
    if logger and result.applied:
        try:
            logger.debug("Applied env overrides: %s", ", ".join(result.applied))
        except Exception:
            pass
    if logger and (result.skipped_env or result.skipped_existing):
        try:
            logger.debug(
                "Skipped env overrides (already set): env=%s existing=%s",
                ", ".join(result.skipped_env) if result.skipped_env else "none",
                ", ".join(result.skipped_existing) if result.skipped_existing else "none",
            )
        except Exception:
            pass
    return result
