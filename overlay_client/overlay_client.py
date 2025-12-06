"""Standalone PyQt6 overlay client for EDMC Modern Overlay."""
from __future__ import annotations

# ruff: noqa: E402

import json
import logging
import math
import os
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

CLIENT_DIR = Path(__file__).resolve().parent
ROOT_DIR = CLIENT_DIR.parent

from PyQt6.QtGui import QPainter, QGuiApplication
from PyQt6.QtWidgets import QWidget

from overlay_client.payload_model import PayloadModel  # type: ignore

try:  # pragma: no cover - defensive fallback when running standalone
    from version import __version__ as MODERN_OVERLAY_VERSION, DEV_MODE_ENV_VAR
except Exception:  # pragma: no cover - fallback when module unavailable
    MODERN_OVERLAY_VERSION = "unknown"
    DEV_MODE_ENV_VAR = "MODERN_OVERLAY_DEV_MODE"

from overlay_client.data_client import OverlayDataClient  # type: ignore  # noqa: E402
from overlay_client.client_config import InitialClientSettings  # type: ignore  # noqa: E402
from overlay_client.platform_integration import MonitorSnapshot  # type: ignore  # noqa: E402
from overlay_client.window_tracking import WindowTracker  # type: ignore  # noqa: E402
from overlay_client.debug_config import DEBUG_CONFIG_ENABLED, DebugConfig  # type: ignore  # noqa: E402
from overlay_client.group_transform import GroupTransform  # type: ignore  # noqa: E402
from overlay_client.payload_transform import (
    PayloadTransformContext,
    remap_axis_value,
)  # type: ignore  # noqa: E402
from overlay_client.viewport_helper import BASE_HEIGHT, BASE_WIDTH  # type: ignore  # noqa: E402
from overlay_client.fonts import (  # type: ignore  # noqa: E402
    _apply_font_fallbacks,
    _resolve_emoji_font_families,
    _resolve_font_family,
)
from overlay_client.transform_helpers import (  # type: ignore  # noqa: E402
    apply_inverse_group_scale as util_apply_inverse_group_scale,
    compute_message_transform as util_compute_message_transform,
    compute_rect_transform as util_compute_rect_transform,
    compute_vector_transform as util_compute_vector_transform,
)
from overlay_client.window_utils import (  # type: ignore  # noqa: E402
    aspect_ratio_label as util_aspect_ratio_label,
    compute_legacy_mapper as util_compute_legacy_mapper,
    current_physical_size as util_current_physical_size,
    viewport_state as util_viewport_state,
)
from overlay_client.viewport_transform import (  # type: ignore  # noqa: E402
    FillViewport,
    LegacyMapper,
    ViewportState,
    build_viewport,
    map_anchor_axis,
    legacy_scale_components,
    scaled_point_size as viewport_scaled_point_size,
)
from overlay_client.render_surface import (  # type: ignore  # noqa: E402
    RenderSurfaceMixin,
    _OverlayBounds,
    _MeasuredText,
)
from overlay_client.follow_surface import FollowSurfaceMixin  # type: ignore  # noqa: E402
from overlay_client.control_surface import ControlSurfaceMixin  # type: ignore  # noqa: E402
from overlay_client.interaction_surface import InteractionSurfaceMixin  # type: ignore  # noqa: E402
from overlay_client.setup_surface import SetupSurfaceMixin  # type: ignore  # noqa: E402

_LOGGER_NAME = "EDMC.ModernOverlay.Client"
_CLIENT_LOGGER = logging.getLogger(_LOGGER_NAME)
_CLIENT_LOGGER.setLevel(logging.DEBUG if DEBUG_CONFIG_ENABLED else logging.INFO)
_CLIENT_LOGGER.propagate = False
# Opt-in propagation flag for environments/tests that want client logs upstream.
if os.environ.get("EDMC_OVERLAY_PROPAGATE_LOGS", "").lower() in {"1", "true", "yes", "on"}:
    _CLIENT_LOGGER.propagate = True
_RELEASE_FILTER_ENABLED = not DEBUG_CONFIG_ENABLED
_LOG_LEVEL_HINT: Optional[int] = None
_LOG_LEVEL_HINT_SOURCE: Optional[str] = None

__all__ = ["OverlayWindow", "OverlayClient", "_MeasuredText", "apply_log_level_hint"]


class _ReleaseLogLevelFilter(logging.Filter):
    """Promote debug logs to INFO in release builds so diagnostics stay visible."""

    def __init__(self, release_mode: bool) -> None:
        super().__init__()
        self._release_mode = release_mode

    def filter(self, record: logging.LogRecord) -> bool:  # pragma: no cover - logging shim
        if _RELEASE_FILTER_ENABLED and self._release_mode and record.levelno == logging.DEBUG:
            record.levelno = logging.INFO
            record.levelname = "INFO"
        return True


_CLIENT_LOGGER.addFilter(_ReleaseLogLevelFilter(release_mode=not DEBUG_CONFIG_ENABLED))


def apply_log_level_hint(level: Optional[int], *, source: Optional[str] = None) -> None:
    """Force the client logger level to the propagated EDMC level."""

    global _LOG_LEVEL_HINT, _LOG_LEVEL_HINT_SOURCE, _RELEASE_FILTER_ENABLED
    if level is None:
        return
    try:
        numeric = int(level)
    except (TypeError, ValueError):
        return
    original = numeric
    hint_source = source or "EDMC"
    dev_override_applied = False
    if DEBUG_CONFIG_ENABLED and numeric > logging.DEBUG:
        numeric = logging.DEBUG
        dev_override_applied = True
    _LOG_LEVEL_HINT = numeric
    _LOG_LEVEL_HINT_SOURCE = hint_source
    _RELEASE_FILTER_ENABLED = False
    _CLIENT_LOGGER.setLevel(numeric)
    level_name = logging.getLevelName(numeric)
    log_level = numeric if numeric >= logging.INFO else logging.INFO
    if dev_override_applied:
        _CLIENT_LOGGER.info(
            "Overlay client logger level forced to DEBUG via dev-mode override (original hint=%s from %s)",
            logging.getLevelName(original),
            hint_source,
        )
    else:
        _CLIENT_LOGGER.log(
            log_level,
            "Overlay client logger level forced to %s via %s",
            level_name,
            hint_source,
        )

DEFAULT_WINDOW_BASE_WIDTH = 1280
DEFAULT_WINDOW_BASE_HEIGHT = 960

_LINE_WIDTH_DEFAULTS: Dict[str, int] = {
    "grid": 1,
    "legacy_rect": 2,
    "group_outline": 1,
    "viewport_indicator": 4,
    "vector_line": 2,
    "vector_marker": 2,
    "vector_cross": 2,
    "cycle_connector": 2,
}


def _load_line_width_config() -> Dict[str, int]:
    config = dict(_LINE_WIDTH_DEFAULTS)
    path = CLIENT_DIR / "render_config.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        _CLIENT_LOGGER.debug("Line width config not found at %s; using defaults", path)
        return config
    except json.JSONDecodeError as exc:
        _CLIENT_LOGGER.warning("Failed to parse %s; using default line widths (%s)", path, exc)
        return config
    if isinstance(data, Mapping):
        for key, value in data.items():
            if key not in _LINE_WIDTH_DEFAULTS:
                continue
            try:
                width = int(round(float(value)))
            except (TypeError, ValueError):
                _CLIENT_LOGGER.warning("Ignoring invalid line width for '%s': %r", key, value)
                continue
            config[key] = max(0, width)
    else:
        _CLIENT_LOGGER.warning("Line width config at %s is not a JSON object; using defaults", path)
    return config

class OverlayWindow(SetupSurfaceMixin, InteractionSurfaceMixin, QWidget, RenderSurfaceMixin, FollowSurfaceMixin, ControlSurfaceMixin):
    """Transparent overlay that renders CMDR and location info."""

    _resolve_font_family = _resolve_font_family
    _resolve_emoji_font_families = _resolve_emoji_font_families
    _apply_font_fallbacks = _apply_font_fallbacks

    _WM_OVERRIDE_TTL = 1.25  # seconds
    _REPAINT_DEBOUNCE_MS = 33  # coalesce ingest/purge repaint storms
    _TEXT_CACHE_MAX = 512
    _TEXT_BLOCK_CACHE_MAX = 256

    def __init__(self, initial: InitialClientSettings, debug_config: DebugConfig) -> None:
        QWidget.__init__(self)
        self._setup_overlay(
            initial,
            debug_config,
            root_dir=ROOT_DIR,
            load_line_width_config=_load_line_width_config,
            line_width_defaults=_LINE_WIDTH_DEFAULTS,
            payload_model_factory=lambda callback: PayloadModel(callback),
        )

    def _current_physical_size(self) -> Tuple[float, float]:
        frame = self.frameGeometry()
        ratio = 1.0
        window = self.windowHandle()
        if window is not None:
            try:
                ratio = window.devicePixelRatio()
            except (AttributeError, RuntimeError) as exc:
                _CLIENT_LOGGER.debug("Failed to read devicePixelRatio, defaulting to 1.0: %s", exc)
                ratio = 1.0
        return util_current_physical_size(frame.width(), frame.height(), ratio)

    @staticmethod
    def _aspect_ratio_label(width: int, height: int) -> Optional[str]:
        return util_aspect_ratio_label(width, height)

    def _compute_legacy_mapper(self) -> LegacyMapper:
        width = max(float(self.width()), 1.0)
        height = max(float(self.height()), 1.0)
        mode_value = (self._scale_mode or "fit").strip().lower()
        return util_compute_legacy_mapper(mode_value, width, height)

    def _viewport_state(self) -> ViewportState:
        width = max(float(self.width()), 1.0)
        height = max(float(self.height()), 1.0)
        try:
            ratio = self.devicePixelRatioF()
        except (AttributeError, RuntimeError) as exc:
            _CLIENT_LOGGER.debug("devicePixelRatioF unavailable, defaulting to 1.0: %s", exc)
            ratio = 1.0
        return util_viewport_state(width, height, ratio)

    def _build_fill_viewport(
        self,
        mapper: LegacyMapper,
        group_transform: Optional[GroupTransform],
    ) -> FillViewport:
        state = self._viewport_state()
        return build_viewport(mapper, state, group_transform, BASE_WIDTH, BASE_HEIGHT)

    @classmethod
    def _group_anchor_point(
        cls,
        transform: Optional[GroupTransform],
        context: Optional[PayloadTransformContext],
        overlay_bounds: Optional[_OverlayBounds] = None,
        use_overlay_bounds_x: bool = False,
    ) -> Optional[Tuple[float, float]]:
        if transform is None or context is None:
            return None
        anchor_override = overlay_bounds if (use_overlay_bounds_x and overlay_bounds is not None and overlay_bounds.is_valid()) else None
        anchor_x = transform.band_anchor_x * BASE_WIDTH
        anchor_y = transform.band_anchor_y * BASE_HEIGHT
        anchor_x = remap_axis_value(anchor_x, context.axis_x)
        anchor_y = remap_axis_value(anchor_y, context.axis_y)
        if anchor_override is not None:
            mapped = cls._map_anchor_to_overlay_bounds(transform, anchor_override)
            if mapped is not None:
                anchor_x = mapped[0]
        if not (math.isfinite(anchor_x) and math.isfinite(anchor_y)):
            return None
        offset_x, offset_y = cls._group_offsets(transform)
        if anchor_override is None:
            anchor_x += offset_x
        anchor_y += offset_y
        return anchor_x, anchor_y

    @classmethod
    def _group_base_point(
        cls,
        transform: Optional[GroupTransform],
        context: Optional[PayloadTransformContext],
        overlay_bounds: Optional[_OverlayBounds] = None,
        use_overlay_bounds_x: bool = False,
    ) -> Optional[Tuple[float, float]]:
        if transform is None or context is None:
            return None
        if use_overlay_bounds_x and overlay_bounds is not None and overlay_bounds.is_valid():
            base_x = overlay_bounds.min_x
        else:
            base_x = remap_axis_value(transform.bounds_min_x, context.axis_x)
        base_y = remap_axis_value(transform.bounds_min_y, context.axis_y)
        if not (math.isfinite(base_x) and math.isfinite(base_y)):
            return None
        offset_x, offset_y = cls._group_offsets(transform)
        if not (use_overlay_bounds_x and overlay_bounds is not None and overlay_bounds.is_valid()):
            base_x += offset_x
        base_y += offset_y
        return base_x, base_y

    @staticmethod
    def _group_offsets(transform: Optional[GroupTransform]) -> Tuple[float, float]:
        if transform is None:
            return 0.0, 0.0
        offset_x = getattr(transform, "dx", 0.0) or 0.0
        offset_y = getattr(transform, "dy", 0.0) or 0.0
        try:
            offset_x = float(offset_x)
        except (TypeError, ValueError):
            offset_x = 0.0
        try:
            offset_y = float(offset_y)
        except (TypeError, ValueError):
            offset_y = 0.0
        return offset_x, offset_y

    @classmethod
    def _map_anchor_to_overlay_bounds(
        cls,
        transform: GroupTransform,
        bounds: _OverlayBounds,
    ) -> Optional[Tuple[float, float]]:
        if not bounds.is_valid():
            return None
        try:
            anchor_x = map_anchor_axis(
                transform.band_anchor_x,
                transform.band_min_x,
                transform.band_max_x,
                bounds.min_x,
                bounds.max_x,
                anchor_token=getattr(transform, "anchor_token", None),
                axis="x",
            )
        except Exception:
            return None
        anchor_y = transform.band_anchor_y * BASE_HEIGHT
        if not (math.isfinite(anchor_x) and math.isfinite(anchor_y)):
            return None
        return anchor_x, anchor_y


    @staticmethod
    def _apply_inverse_group_scale(
        value_x: float,
        value_y: float,
        anchor: Optional[Tuple[float, float]],
        base_anchor: Optional[Tuple[float, float]],
        fill: FillViewport,
    ) -> Tuple[float, float]:
        return util_apply_inverse_group_scale(value_x, value_y, anchor, base_anchor, fill)

    def _compute_message_transform(
        self,
        plugin_name: str,
        item_id: str,
        fill: FillViewport,
        transform_context: PayloadTransformContext,
        transform_meta: Any,
        mapper: LegacyMapper,
        group_transform: Optional[GroupTransform],
        overlay_bounds_hint: Optional[_OverlayBounds],
        raw_left: float,
        raw_top: float,
        offset_x: float,
        offset_y: float,
        selected_anchor: Optional[Tuple[float, float]],
        base_anchor_point: Optional[Tuple[float, float]],
        anchor_for_transform: Optional[Tuple[float, float]],
        base_translation_dx: float,
        base_translation_dy: float,
        trace_enabled: bool,
        collect_only: bool,
    ) -> Tuple[float, float, float, float, Optional[Tuple[float, float]], float, float]:
        trace_fn: Optional[Callable[[str, Mapping[str, Any]], None]]
        if trace_enabled and not collect_only:
            def trace_fn(stage: str, details: Mapping[str, Any]) -> None:
                self._log_legacy_trace(plugin_name, item_id, stage, details)
        else:
            trace_fn = None
        return util_compute_message_transform(
            plugin_name,
            item_id,
            fill,
            transform_context,
            transform_meta,
            mapper,
            group_transform,
            overlay_bounds_hint,
            raw_left,
            raw_top,
            offset_x,
            offset_y,
            selected_anchor,
            base_anchor_point,
            anchor_for_transform,
            base_translation_dx,
            base_translation_dy,
            trace_fn,
            collect_only,
        )

    def _compute_rect_transform(
        self,
        plugin_name: str,
        item_id: str,
        fill: FillViewport,
        transform_context: PayloadTransformContext,
        transform_meta: Any,
        mapper: LegacyMapper,
        group_transform: Optional[GroupTransform],
        raw_x: float,
        raw_y: float,
        raw_w: float,
        raw_h: float,
        offset_x: float,
        offset_y: float,
        selected_anchor: Optional[Tuple[float, float]],
        base_anchor_point: Optional[Tuple[float, float]],
        anchor_for_transform: Optional[Tuple[float, float]],
        base_translation_dx: float,
        base_translation_dy: float,
        trace_enabled: bool,
        collect_only: bool,
    ) -> Tuple[
        List[Tuple[float, float]],
        List[Tuple[float, float]],
        Optional[Tuple[float, float, float, float]],
        Optional[Tuple[float, float]],
    ]:
        trace_fn: Optional[Callable[[str, Mapping[str, Any]], None]]
        if trace_enabled and not collect_only:
            def trace_fn(stage: str, details: Mapping[str, Any]) -> None:
                self._log_legacy_trace(plugin_name, item_id, stage, details)
        else:
            trace_fn = None
        return util_compute_rect_transform(
            plugin_name,
            item_id,
            fill,
            transform_context,
            transform_meta,
            mapper,
            group_transform,
            raw_x,
            raw_y,
            raw_w,
            raw_h,
            offset_x,
            offset_y,
            selected_anchor,
            base_anchor_point,
            anchor_for_transform,
            base_translation_dx,
            base_translation_dy,
            trace_fn,
            collect_only,
        )

    def _compute_vector_transform(
        self,
        plugin_name: str,
        item_id: str,
        fill: FillViewport,
        transform_context: PayloadTransformContext,
        transform_meta: Any,
        mapper: LegacyMapper,
        group_transform: Optional[GroupTransform],
        item_data: Mapping[str, Any],
        raw_points: Sequence[Mapping[str, Any]],
        offset_x: float,
        offset_y: float,
        selected_anchor: Optional[Tuple[float, float]],
        base_anchor_point: Optional[Tuple[float, float]],
        anchor_for_transform: Optional[Tuple[float, float]],
        base_translation_dx: float,
        base_translation_dy: float,
        trace_enabled: bool,
        collect_only: bool,
    ) -> Tuple[
        Optional[Mapping[str, Any]],
        List[Tuple[int, int]],
        Optional[Tuple[float, float, float, float]],
        Optional[Tuple[float, float, float, float]],
        Optional[Tuple[float, float]],
        Optional[float],
        Optional[Callable[[str, Mapping[str, Any]], None]],
    ]:
        trace_fn: Optional[Callable[[str, Mapping[str, Any]], None]]
        if trace_enabled:
            def trace_fn(stage: str, details: Mapping[str, Any]) -> None:
                self._log_legacy_trace(plugin_name, item_id, stage, details)
        else:
            trace_fn = None
        return util_compute_vector_transform(
            plugin_name,
            item_id,
            fill,
            transform_context,
            transform_meta,
            mapper,
            group_transform,
            item_data,
            raw_points,
            offset_x,
            offset_y,
            selected_anchor,
            base_anchor_point,
            anchor_for_transform,
            base_translation_dx,
            base_translation_dy,
            trace_fn,
            collect_only,
        )

    def _update_message_font(self) -> None:
        mapper = self._compute_legacy_mapper()
        state = self._viewport_state()
        target_point = viewport_scaled_point_size(
            state,
            self._base_message_point_size,
            self._font_scale_diag,
            self._font_min_point,
            self._font_max_point,
            mapper,
            use_physical=True,
        )
        if not math.isclose(target_point, self._debug_message_point_size, rel_tol=1e-3):
            font = self.message_label.font()
            font.setPointSizeF(target_point)
            self.message_label.setFont(font)
            self._debug_message_point_size = target_point
            self._publish_metrics()

    def _update_label_fonts(self) -> None:
        """Refresh fonts for overlay labels after a bounds change."""
        self._update_message_font()
        if self._show_status and self._status:
            # Re-dispatch the status banner so legacy text picks up the new clamp.
            self._show_overlay_status_message(self._status)

    def _refresh_legacy_items(self) -> None:
        """Touch stored legacy items so repaints pick up new scaling bounds."""
        for item_id, item in list(self._payload_model.store.items()):
            self._payload_model.set(item_id, item)
        self._mark_legacy_cache_dirty()

    def _notify_font_bounds_changed(self) -> None:
        current = (self._font_min_point, self._font_max_point)
        if self._last_font_notice == current:
            return
        self._last_font_notice = current
        text = "Font bounds: {:.1f} – {:.1f} pt".format(*current)
        payload = {
            "type": "message",
            "id": "__font_bounds_notice__",
            "text": text,
            "color": "#80d0ff",
            "x": 40,
            "y": 60,
            "ttl": 5,
            "size": "normal",
        }
        self.handle_legacy_payload(payload)

    def _publish_metrics(self) -> None:
        client = self._data_client
        if client is None:
            return
        width_px, height_px = self._current_physical_size()
        mapper = self._compute_legacy_mapper()
        state = self._viewport_state()
        scale_x, scale_y = legacy_scale_components(mapper, state)
        frame = self.frameGeometry()
        payload = {
            "cli": "overlay_metrics",
            "width": int(round(width_px)),
            "height": int(round(height_px)),
            "frame": {
                "x": int(frame.x()),
                "y": int(frame.y()),
                "width": int(frame.width()),
                "height": int(frame.height()),
            },
            "scale": {
                "legacy_x": float(scale_x),
                "legacy_y": float(scale_y),
                "mode": self._scale_mode,
            },
            "device_pixel_ratio": float(self.devicePixelRatioF()),
        }
        client.send_cli_payload(payload)

    def format_scale_debug(self) -> str:
        width_px, height_px = self._current_physical_size()
        mapper = self._compute_legacy_mapper()
        state = self._viewport_state()
        scale_x, scale_y = legacy_scale_components(mapper, state)
        return "size={:.0f}x{:.0f}px scale_x={:.2f} scale_y={:.2f}".format(
            width_px,
            height_px,
            scale_x,
            scale_y,
        )

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        self._handle_show_event()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._paint_overlay(painter)
        painter.end()
        stats = getattr(self, "_paint_stats", None)
        if isinstance(stats, dict):
            stats["paint_count"] = stats.get("paint_count", 0) + 1
        super().paintEvent(event)

    # External control -----------------------------------------------------

    @property
    def gridlines_enabled(self) -> bool:
        return self._gridlines_enabled

    def set_data_client(self, client: OverlayDataClient) -> None:
        self._data_client = client
        self._publish_metrics()
        if self._window_tracker and hasattr(self._window_tracker, "set_monitor_provider"):
            try:
                self._window_tracker.set_monitor_provider(self.monitor_snapshots)  # type: ignore[attr-defined]
            except Exception as exc:
                _CLIENT_LOGGER.debug("Window tracker rejected monitor provider hook: %s", exc)
        if self._window_tracker and self._follow_enabled:
            self._start_tracking()
            self._refresh_follow_geometry()
        else:
            self._stop_tracking()

    def set_window_tracker(self, tracker: Optional[WindowTracker]) -> None:
        self._window_tracker = tracker
        if tracker and hasattr(tracker, "set_monitor_provider"):
            try:
                tracker.set_monitor_provider(self.monitor_snapshots)  # type: ignore[attr-defined]
            except Exception as exc:
                _CLIENT_LOGGER.debug("Window tracker rejected monitor provider hook: %s", exc)
        if tracker and self._follow_enabled:
            self._start_tracking()
            self._refresh_follow_geometry()
        else:
            self._stop_tracking()

    def set_follow_enabled(self, enabled: bool) -> None:
        if not enabled:
            _CLIENT_LOGGER.debug("Follow mode cannot be disabled; ignoring request.")
            return
        if self._follow_enabled:
            return
        self._follow_enabled = True
        self._lost_window_logged = False
        self._suspend_follow(0.5)
        self._start_tracking()
        self._update_follow_visibility(True)

    def set_origin(self, origin_x: int, origin_y: int) -> None:
        _CLIENT_LOGGER.debug(
            "Ignoring origin request (%s,%s); overlay position follows game window.",
            origin_x,
            origin_y,
        )

    def get_origin(self) -> Tuple[int, int]:
        return 0, 0

    def _apply_origin_position(self) -> None:
        return

    def monitor_snapshots(self) -> List[MonitorSnapshot]:
        return self._platform_controller.monitors()

    def _is_wayland(self) -> bool:
        platform_name = (QGuiApplication.platformName() or "").lower()
        return "wayland" in platform_name


def resolve_port_file(args_port: Optional[str]) -> Path:
    """Compatibility shim; real implementation lives in overlay_client.launcher."""
    from overlay_client.launcher import resolve_port_file as _resolve_port_file

    return _resolve_port_file(args_port)


def main(argv: Optional[list[str]] = None) -> int:
    """Compatibility shim; delegates to overlay_client.launcher.main."""
    from overlay_client.launcher import main as _launcher_main

    return _launcher_main(argv)


OverlayClient = OverlayWindow

if __name__ == "__main__":
    import sys

    sys.modules.setdefault("overlay_client.overlay_client", sys.modules[__name__])

    from overlay_client.launcher import main as _launcher_main

    raise SystemExit(_launcher_main())
