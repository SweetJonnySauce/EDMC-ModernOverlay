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
    window_width: int = 1920
    window_height: int = 1080
    follow_elite_window: bool = True
    follow_x_offset: int = 20
    follow_y_offset: int = 40
    force_render: bool = False


@dataclass
class DeveloperHelperConfig:
    """Subset of overlay preferences that are considered developer helpers."""

    background_opacity: Optional[float] = None
    enable_drag: Optional[bool] = None
    legacy_scale_y: Optional[float] = None
    legacy_scale_x: Optional[float] = None
    client_log_retention: Optional[int] = None
    gridlines_enabled: Optional[bool] = None
    gridline_spacing: Optional[int] = None
    window_width: Optional[int] = None
    window_height: Optional[int] = None
    show_status: Optional[bool] = None
    follow_enabled: Optional[bool] = None
    follow_x_offset: Optional[int] = None
    follow_y_offset: Optional[int] = None
    force_render: Optional[bool] = None

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
            legacy_scale_y=_float(payload.get("legacy_scale_y"), None),
            legacy_scale_x=_float(payload.get("legacy_scale_x"), None),
            client_log_retention=_int(payload.get("client_log_retention"), None),
            gridlines_enabled=_bool(payload.get("gridlines_enabled"), None),
            gridline_spacing=_int(payload.get("gridline_spacing"), None),
            window_width=_int(payload.get("window_width"), None),
            window_height=_int(payload.get("window_height"), None),
            show_status=_bool(payload.get("show_status"), None),
            follow_enabled=_bool(payload.get("follow_game_window"), None),
            follow_x_offset=_int(payload.get("follow_x_offset"), None),
            follow_y_offset=_int(payload.get("follow_y_offset"), None),
            force_render=_bool(payload.get("force_render"), None),
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
    width = defaults.window_width
    height = defaults.window_height
    try:
        retention = int(data.get("client_log_retention", retention))
    except (TypeError, ValueError):
        retention = defaults.client_log_retention
    try:
        width = int(data.get("window_width", width))
    except (TypeError, ValueError):
        width = defaults.window_width
    try:
        height = int(data.get("window_height", height))
    except (TypeError, ValueError):
        height = defaults.window_height
    follow_mode = bool(data.get("follow_game_window", defaults.follow_elite_window))
    try:
        x_offset = int(data.get("follow_x_offset", defaults.follow_x_offset))
    except (TypeError, ValueError):
        x_offset = defaults.follow_x_offset
    try:
        y_offset = int(data.get("follow_y_offset", defaults.follow_y_offset))
    except (TypeError, ValueError):
        y_offset = defaults.follow_y_offset
    force_render = bool(data.get("force_render", defaults.force_render))

    return InitialClientSettings(
        client_log_retention=max(1, retention),
        window_width=max(640, width),
        window_height=max(360, height),
        follow_elite_window=follow_mode,
        follow_x_offset=max(0, x_offset),
        follow_y_offset=max(0, y_offset),
        force_render=force_render,
    )
