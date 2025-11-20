"""Debug configuration loader for overlay tracing."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

try:  # pragma: no cover - overlay client may run without package metadata
    from version import __version__ as MODERN_OVERLAY_VERSION, DEV_MODE_ENV_VAR, is_dev_build
except Exception:  # pragma: no cover - fallback when version module unavailable
    MODERN_OVERLAY_VERSION = None
    DEV_MODE_ENV_VAR = "MODERN_OVERLAY_DEV_MODE"

    def is_dev_build(version: Optional[str] = None) -> bool:
        value = os.getenv(DEV_MODE_ENV_VAR)
        if value is None:
            return False
        token = value.strip().lower()
        if token in {"1", "true", "yes", "on"}:
            return True
        if token in {"0", "false", "no", "off"}:
            return False
        return False


DEBUG_CONFIG_ENABLED = is_dev_build(MODERN_OVERLAY_VERSION)
CLIENT_LOG_RETENTION_MIN = 1
CLIENT_LOG_RETENTION_MAX = 20


@dataclass(frozen=True)
class DebugConfig:
    trace_enabled: bool = False
    trace_payload_ids: tuple[str, ...] = ()
    overlay_outline: bool = False
    group_bounds_outline: bool = False
    payload_vertex_markers: bool = False
    overlay_logs_to_keep: Optional[int] = None


def load_debug_config(path: Path) -> DebugConfig:
    if not DEBUG_CONFIG_ENABLED:
        return DebugConfig()
    try:
        raw_text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return DebugConfig()
    except OSError:
        return DebugConfig()

    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError:
        return DebugConfig()

    if not isinstance(data, dict):
        return DebugConfig()

    tracing_section = data.get("tracing")
    if isinstance(tracing_section, dict):
        trace_enabled = bool(tracing_section.get("enabled", False))
        payload_value = tracing_section.get("payload_ids")
        if payload_value is None:
            payload_value = tracing_section.get("payload_id") or tracing_section.get("payload")
    else:
        trace_enabled = bool(data.get("trace_enabled", False))
        payload_value = data.get("payload_ids")
        if payload_value is None:
            payload_value = data.get("payload_id") or data.get("payload")

    payload_ids: tuple[str, ...] = ()
    if isinstance(payload_value, (list, tuple, set)):
        cleaned = [str(item).strip() for item in payload_value if isinstance(item, (str, int, float))]
        payload_ids = tuple(filter(None, cleaned))
    elif payload_value is not None:
        single = str(payload_value).strip()
        if single:
            payload_ids = (single,)

    overlay_outline = bool(data.get("overlay_outline", False))
    group_bounds_outline = bool(data.get("group_bounds_outline", False))
    payload_vertex_markers = bool(data.get("payload_vertex_markers", False))

    def _coerce_log_retention(value: Any) -> Optional[int]:
        if value is None:
            return None
        try:
            numeric = int(value)
        except (TypeError, ValueError):
            return None
        if numeric <= 0:
            return CLIENT_LOG_RETENTION_MIN
        if numeric > CLIENT_LOG_RETENTION_MAX:
            return CLIENT_LOG_RETENTION_MAX
        return numeric

    overlay_logs_to_keep = _coerce_log_retention(data.get("overlay_logs_to_keep"))

    return DebugConfig(
        trace_enabled=trace_enabled,
        trace_payload_ids=payload_ids,
        overlay_outline=overlay_outline,
        group_bounds_outline=group_bounds_outline,
        payload_vertex_markers=payload_vertex_markers,
        overlay_logs_to_keep=overlay_logs_to_keep,
    )
