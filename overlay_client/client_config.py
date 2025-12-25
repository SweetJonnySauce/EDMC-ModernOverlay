"""Configuration helpers for the Modern Overlay PyQt client."""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional


@dataclass
class InitialClientSettings:
    """Values used to bootstrap the client before config payloads arrive."""

    client_log_retention: int = 5
    global_payload_opacity: int = 100
    force_render: bool = False
    force_xwayland: bool = False
    physical_clamp_enabled: bool = False
    physical_clamp_overrides: Dict[str, float] = field(default_factory=dict)
    show_debug_overlay: bool = False
    min_font_point: float = 6.0
    max_font_point: float = 24.0
    legacy_font_step: float = 2.0
    status_bottom_margin: int = 20
    debug_overlay_corner: str = "NW"
    status_corner: str = "SW"
    title_bar_enabled: bool = False
    title_bar_height: int = 0
    cycle_payload_ids: bool = False
    copy_payload_id_on_cycle: bool = False
    scale_mode: str = "fit"
    nudge_overflow_payloads: bool = False
    payload_nudge_gutter: int = 30
    payload_log_delay_seconds: float = 0.0
    edmc_log_level: Optional[int] = None
    edmc_log_level_name: Optional[str] = None
    edmc_log_level_source: Optional[str] = None


@dataclass
class DeveloperHelperConfig:
    """Subset of overlay preferences that are considered developer helpers."""

    background_opacity: Optional[float] = None
    global_payload_opacity: Optional[int] = None
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
    legacy_font_step: Optional[float] = None
    status_bottom_margin: Optional[int] = None
    debug_overlay_corner: Optional[str] = None
    status_corner: Optional[str] = None
    title_bar_enabled: Optional[bool] = None
    title_bar_height: Optional[int] = None
    cycle_payload_ids: Optional[bool] = None
    copy_payload_id_on_cycle: Optional[bool] = None
    scale_mode: Optional[str] = None
    nudge_overflow_payloads: Optional[bool] = None
    payload_nudge_gutter: Optional[int] = None
    payload_log_delay_seconds: Optional[float] = None

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

        mode_value = payload.get("scale_mode")
        if mode_value is not None:
            try:
                mode_token = str(mode_value).strip().lower()
            except Exception:
                mode_token = None
            else:
                if mode_token not in {"fit", "fill"}:
                    mode_token = None
        else:
            mode_token = None

        return cls(
            background_opacity=_float(payload.get("opacity"), None),
            global_payload_opacity=_int(payload.get("global_payload_opacity"), None),
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
            legacy_font_step=_float(payload.get("legacy_font_step"), None),
            status_bottom_margin=_int(payload.get("status_bottom_margin"), None),
            debug_overlay_corner=_str(payload.get("debug_overlay_corner"), None),
            title_bar_enabled=_bool(payload.get("title_bar_enabled"), None),
            title_bar_height=_int(payload.get("title_bar_height"), None),
            cycle_payload_ids=_bool(payload.get("cycle_payload_ids"), None),
            copy_payload_id_on_cycle=_bool(payload.get("copy_payload_id_on_cycle"), None),
            scale_mode=mode_token,
            nudge_overflow_payloads=_bool(payload.get("nudge_overflow_payloads"), None),
            payload_nudge_gutter=_int(payload.get("payload_nudge_gutter"), None),
            payload_log_delay_seconds=_float(payload.get("payload_log_delay_seconds"), None),
        )


def load_initial_settings(settings_path: Path) -> InitialClientSettings:
    """Read bootstrap defaults from overlay_settings.json if it exists."""
    defaults = InitialClientSettings()
    min_override_scale = 0.5
    max_override_scale = 3.0
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
    try:
        payload_opacity = int(data.get("global_payload_opacity", defaults.global_payload_opacity))
    except (TypeError, ValueError):
        payload_opacity = defaults.global_payload_opacity
    payload_opacity = max(0, min(payload_opacity, 100))
    force_render = bool(data.get("force_render", defaults.force_render))
    force_xwayland = bool(data.get("force_xwayland", defaults.force_xwayland))
    physical_clamp_enabled = bool(data.get("physical_clamp_enabled", defaults.physical_clamp_enabled))
    show_debug_overlay = bool(data.get("show_debug_overlay", defaults.show_debug_overlay))
    try:
        min_font = float(data.get("min_font_point", defaults.min_font_point))
    except (TypeError, ValueError):
        min_font = defaults.min_font_point
    try:
        max_font = float(data.get("max_font_point", defaults.max_font_point))
    except (TypeError, ValueError):
        max_font = defaults.max_font_point
    try:
        legacy_font_step = float(data.get("legacy_font_step", defaults.legacy_font_step))
    except (TypeError, ValueError):
        legacy_font_step = defaults.legacy_font_step
    min_font = max(1.0, min(min_font, 48.0))
    max_font = max(min_font, min(max_font, 72.0))
    legacy_font_step = max(0.0, min(legacy_font_step, 10.0))
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
    cycle_payload_ids = bool(data.get("cycle_payload_ids", defaults.cycle_payload_ids))
    copy_payload_id_on_cycle = bool(data.get("copy_payload_id_on_cycle", defaults.copy_payload_id_on_cycle))
    mode = str(data.get("scale_mode", defaults.scale_mode) or defaults.scale_mode).strip().lower()
    if mode not in {"fit", "fill"}:
        mode = defaults.scale_mode
    nudge_overflow = bool(data.get("nudge_overflow_payloads", defaults.nudge_overflow_payloads))
    try:
        gutter = int(data.get("payload_nudge_gutter", defaults.payload_nudge_gutter))
    except (TypeError, ValueError):
        gutter = defaults.payload_nudge_gutter
    gutter = max(0, min(gutter, 500))
    try:
        log_delay = float(data.get("payload_log_delay_seconds", defaults.payload_log_delay_seconds))
    except (TypeError, ValueError):
        log_delay = defaults.payload_log_delay_seconds
    log_delay = max(0.0, log_delay)
    overrides_raw = data.get("physical_clamp_overrides", defaults.physical_clamp_overrides)
    overrides: Dict[str, float] = {}
    if isinstance(overrides_raw, dict):
        candidates = overrides_raw
    else:
        candidates = {}
    for name, raw_scale in candidates.items():
        try:
            screen_name = str(name).strip()
        except Exception:
            continue
        if not screen_name:
            continue
        try:
            scale = float(raw_scale)
        except (TypeError, ValueError):
            continue
        if not (scale > 0.0) or not math.isfinite(scale):
            continue
        clamped = max(min_override_scale, min(max_override_scale, scale))
        overrides[screen_name] = clamped

    return InitialClientSettings(
        client_log_retention=max(1, retention),
        global_payload_opacity=payload_opacity,
        force_render=force_render,
        force_xwayland=force_xwayland,
        show_debug_overlay=show_debug_overlay,
        min_font_point=min_font,
        max_font_point=max_font,
        legacy_font_step=legacy_font_step,
        status_bottom_margin=bottom_margin,
        debug_overlay_corner=corner_value,
        title_bar_enabled=title_bar_enabled,
        title_bar_height=bar_height,
        cycle_payload_ids=cycle_payload_ids,
        copy_payload_id_on_cycle=copy_payload_id_on_cycle,
        scale_mode=mode,
        nudge_overflow_payloads=nudge_overflow,
        payload_nudge_gutter=gutter,
        payload_log_delay_seconds=log_delay,
        physical_clamp_enabled=physical_clamp_enabled,
        physical_clamp_overrides=overrides,
    )
