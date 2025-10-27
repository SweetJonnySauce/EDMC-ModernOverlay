"""Configuration helpers for the Modern Overlay PyQt client."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional


@dataclass
class InitialClientSettings:
    """Values used to bootstrap the client before config payloads arrive."""

    client_log_retention: int = 5
    force_render: bool = False
    force_xwayland: bool = False
    show_debug_overlay: bool = False


@dataclass
class DeveloperHelperConfig:
    """Subset of overlay preferences that are considered developer helpers."""

    background_opacity: Optional[float] = None
    enable_drag: Optional[bool] = None
    client_log_retention: Optional[int] = None
    gridlines_enabled: Optional[bool] = None
    gridline_spacing: Optional[int] = None
    show_status: Optional[bool] = None
    force_render: Optional[bool] = None
    force_xwayland: Optional[bool] = None
    show_debug_overlay: Optional[bool] = None

    @classmethod
    def from_payload(cls, payload: Dict[str, Any]) -> "DeveloperHelperConfig":
        """Create an instance from an OverlayConfig payload."""
        def _float(value: Any, fallback: Optional[float]) -> Optional[float]:
            if value is None:
                return fallback
            try:
                return float(value)
            except (TypeError, ValueError):
                return fallback

        def _int(value: Any, fallback: Optional[int]) -> Optional[int]:
            if value is None:
                return fallback
            try:
                return int(value)
            except (TypeError, ValueError):
                return fallback

        def _bool(value: Any, fallback: Optional[bool]) -> Optional[bool]:
            if value is None:
                return fallback
            return bool(value)

        return cls(
            background_opacity=_float(payload.get("opacity"), None),
            enable_drag=_bool(payload.get("enable_drag"), None),
            client_log_retention=_int(payload.get("client_log_retention"), None),
            gridlines_enabled=_bool(payload.get("gridlines_enabled"), None),
            gridline_spacing=_int(payload.get("gridline_spacing"), None),
            show_status=_bool(payload.get("show_status"), None),
            force_render=_bool(payload.get("force_render"), None),
            force_xwayland=_bool(payload.get("force_xwayland"), None),
            show_debug_overlay=_bool(payload.get("show_debug_overlay"), None),
        )


def load_initial_settings(settings_path: Path) -> InitialClientSettings:
    """Read bootstrap defaults from overlay_settings.json if it exists."""
    defaults = InitialClientSettings()
    try:
        raw = settings_path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return defaults

    try:
        data: Dict[str, Any] = json.loads(raw)
    except json.JSONDecodeError:
        return defaults

    retention = defaults.client_log_retention
    try:
        retention = int(data.get("client_log_retention", retention))
    except (TypeError, ValueError):
        retention = defaults.client_log_retention
    force_render = bool(data.get("force_render", defaults.force_render))
    force_xwayland = bool(data.get("force_xwayland", defaults.force_xwayland))
    show_debug_overlay = bool(data.get("show_debug_overlay", defaults.show_debug_overlay))

    return InitialClientSettings(
        client_log_retention=max(1, retention),
        force_render=force_render,
        force_xwayland=force_xwayland,
        show_debug_overlay=show_debug_overlay,
    )
