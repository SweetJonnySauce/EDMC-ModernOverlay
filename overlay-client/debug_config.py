"""Debug configuration loader for overlay tracing."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class DebugConfig:
    trace_enabled: bool = False
    trace_plugin: Optional[str] = None
    trace_payload_ids: tuple[str, ...] = ()
    fill_group_debug: bool = False
    overlay_outline: bool = False
    group_bounds_outline: bool = False


def load_debug_config(path: Path) -> DebugConfig:
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

    trace_enabled = bool(data.get("trace_enabled", False))
    trace_plugin = data.get("plugin")
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

    if trace_plugin is not None:
        trace_plugin = str(trace_plugin).strip() or None

    fill_group_debug = bool(data.get("fill_group_debug", False))
    overlay_outline = bool(data.get("overlay_outline", False))
    group_bounds_outline = bool(data.get("group_bounds_outline", False))

    return DebugConfig(
        trace_enabled=trace_enabled,
        trace_plugin=trace_plugin,
        trace_payload_ids=payload_ids,
        fill_group_debug=fill_group_debug,
        overlay_outline=overlay_outline,
        group_bounds_outline=group_bounds_outline,
    )
