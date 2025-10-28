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
    min_font_point: float = 6.0
    max_font_point: float = 24.0
    status_bottom_margin: int = 20
    debug_overlay_corner: str = "NW"
    status_corner: str = "SW"
    title_bar_enabled: bool = False
    title_bar_height: int = 0


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
    min_font_point: Optional[float] = None
    max_font_point: Optional[float] = None
    status_bottom_margin: Optional[int] = None
    debug_overlay_corner: Optional[str] = None
    status_corner: Optional[str] = None
    title_bar_enabled: Optional[bool] = None
    title_bar_height: Optional[int] = None

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

        def _str(value: Any, fallback: Optional[str]) -> Optional[str]:
            if value is None:
                return fallback
            try:
                text = str(value).strip().upper()
                if text in {"NW", "NE", "SW", "SE"}:
                    return text
                return fallback
            except Exception:
                return fallback

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
            min_font_point=_float(payload.get("min_font_point"), None),
            max_font_point=_float(payload.get("max_font_point"), None),
            status_bottom_margin=_int(payload.get("status_bottom_margin"), None),
            debug_overlay_corner=_str(payload.get("debug_overlay_corner"), None),
            title_bar_enabled=_bool(payload.get("title_bar_enabled"), None),
            title_bar_height=_int(payload.get("title_bar_height"), None),
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
    try:
        min_font = float(data.get("min_font_point", defaults.min_font_point))
    except (TypeError, ValueError):
        min_font = defaults.min_font_point
    try:
        max_font = float(data.get("max_font_point", defaults.max_font_point))
    except (TypeError, ValueError):
        max_font = defaults.max_font_point
    min_font = max(1.0, min(min_font, 48.0))
    max_font = max(min_font, min(max_font, 72.0))
    try:
        bottom_margin = int(data.get("status_bottom_margin", defaults.status_bottom_margin))
    except (TypeError, ValueError):
        bottom_margin = defaults.status_bottom_margin
    bottom_margin = max(0, bottom_margin)
    corner_value = str(data.get("debug_overlay_corner", defaults.debug_overlay_corner) or "NW").strip().upper()
    if corner_value not in {"NW", "NE", "SW", "SE"}:
        corner_value = defaults.debug_overlay_corner
    title_bar_enabled = bool(data.get("title_bar_enabled", defaults.title_bar_enabled))
    try:
        bar_height = int(data.get("title_bar_height", defaults.title_bar_height))
    except (TypeError, ValueError):
        bar_height = defaults.title_bar_height
    bar_height = max(0, bar_height)

    return InitialClientSettings(
        client_log_retention=max(1, retention),
        force_render=force_render,
        force_xwayland=force_xwayland,
        show_debug_overlay=show_debug_overlay,
        min_font_point=min_font,
        max_font_point=max_font,
        status_bottom_margin=bottom_margin,
        debug_overlay_corner=corner_value,
        title_bar_enabled=title_bar_enabled,
        title_bar_height=bar_height,
    )
