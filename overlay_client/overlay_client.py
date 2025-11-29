"""Standalone PyQt6 overlay client for EDMC Modern Overlay."""
from __future__ import annotations

# ruff: noqa: E402

import argparse
import json
import logging
import math
import os
import sys
import time
from pathlib import Path
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple, Set

CLIENT_DIR = Path(__file__).resolve().parent
ROOT_DIR = CLIENT_DIR.parent

from PyQt6.QtCore import Qt, QTimer, QPoint, QRect, QSize
from PyQt6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QPainter,
    QPen,
    QBrush,
    QCursor,
    QPixmap,
    QGuiApplication,
    QScreen,
    QWindow,
)
from PyQt6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

from overlay_client.follow_controller import FollowController  # type: ignore
from overlay_client.payload_model import PayloadModel  # type: ignore
from overlay_client.render_pipeline import LegacyRenderPipeline, PayloadSnapshot, RenderContext, RenderSettings  # type: ignore
from overlay_client.grouping_adapter import GroupingAdapter  # type: ignore

try:  # pragma: no cover - defensive fallback when running standalone
    from version import __version__ as MODERN_OVERLAY_VERSION, DEV_MODE_ENV_VAR
except Exception:  # pragma: no cover - fallback when module unavailable
    MODERN_OVERLAY_VERSION = "unknown"
    DEV_MODE_ENV_VAR = "MODERN_OVERLAY_DEV_MODE"

from overlay_client.data_client import OverlayDataClient  # type: ignore  # noqa: E402
from overlay_client.client_config import InitialClientSettings, load_initial_settings  # type: ignore  # noqa: E402
from overlay_client.developer_helpers import DeveloperHelperController  # type: ignore  # noqa: E402
from overlay_client.platform_integration import MonitorSnapshot, PlatformContext, PlatformController  # type: ignore  # noqa: E402
from overlay_client.window_tracking import WindowState, WindowTracker, create_elite_window_tracker  # type: ignore  # noqa: E402
from overlay_client.legacy_store import LegacyItem  # type: ignore  # noqa: E402
from overlay_client.legacy_processor import TraceCallback  # type: ignore  # noqa: E402
from overlay_client.plugin_overrides import PluginOverrideManager  # type: ignore  # noqa: E402
from overlay_client.debug_config import DEBUG_CONFIG_ENABLED, DebugConfig, load_debug_config  # type: ignore  # noqa: E402
from overlay_client.group_transform import GroupTransform, GroupKey  # type: ignore  # noqa: E402
from group_cache import GroupPlacementCache, resolve_cache_path  # type: ignore  # noqa: E402
from overlay_client.viewport_helper import (
    BASE_HEIGHT,
    BASE_WIDTH,
    ScaleMode,
)  # type: ignore  # noqa: E402
from overlay_client.grouping_helper import FillGroupingHelper  # type: ignore  # noqa: E402
from overlay_client.payload_transform import (
    build_payload_transform_context,
    PayloadTransformContext,
    remap_axis_value,
    transform_components,
)  # type: ignore  # noqa: E402
from overlay_client.platform_context import _initial_platform_context  # type: ignore  # noqa: E402
from overlay_client.fonts import (  # type: ignore  # noqa: E402
    _apply_font_fallbacks,
    _resolve_emoji_font_families,
    _resolve_font_family,
)
from overlay_client.paint_commands import (  # type: ignore  # noqa: E402
    _LegacyPaintCommand,
    _MessagePaintCommand,
    _RectPaintCommand,
    _VectorPaintCommand,
)
from overlay_client.anchor_helpers import CommandContext, compute_justification_offsets, build_baseline_bounds  # type: ignore  # noqa: E402
from overlay_client.payload_builders import build_group_context  # type: ignore  # noqa: E402
from overlay_client.debug_cycle_overlay import CycleOverlayView, DebugOverlayView  # type: ignore  # noqa: E402
from overlay_client.follow_geometry import (  # type: ignore  # noqa: E402
    ScreenInfo,
    _apply_aspect_guard,
    _apply_title_bar_offset,
    _convert_native_rect_to_qt,
)
from overlay_client.group_coordinator import GroupCoordinator  # type: ignore  # noqa: E402
from overlay_client.transform_helpers import (  # type: ignore  # noqa: E402
    apply_inverse_group_scale as util_apply_inverse_group_scale,
    compute_message_transform as util_compute_message_transform,
    compute_rect_transform as util_compute_rect_transform,
    compute_vector_transform as util_compute_vector_transform,
)
from overlay_client.window_controller import WindowController  # type: ignore  # noqa: E402
from overlay_client.window_utils import (  # type: ignore  # noqa: E402
    aspect_ratio_label as util_aspect_ratio_label,
    compute_legacy_mapper as util_compute_legacy_mapper,
    current_physical_size as util_current_physical_size,
    legacy_preset_point_size as util_legacy_preset_point_size,
    line_width as util_line_width,
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

_LOGGER_NAME = "EDMC.ModernOverlay.Client"
_CLIENT_LOGGER = logging.getLogger(_LOGGER_NAME)
_CLIENT_LOGGER.setLevel(logging.DEBUG if DEBUG_CONFIG_ENABLED else logging.INFO)
_CLIENT_LOGGER.propagate = False


class _ReleaseLogLevelFilter(logging.Filter):
    """Promote debug logs to INFO in release builds so diagnostics stay visible."""

    def __init__(self, release_mode: bool) -> None:
        super().__init__()
        self._release_mode = release_mode

    def filter(self, record: logging.LogRecord) -> bool:  # pragma: no cover - logging shim
        if self._release_mode and record.levelno == logging.DEBUG:
            record.levelno = logging.INFO
            record.levelname = "INFO"
        return True


_CLIENT_LOGGER.addFilter(_ReleaseLogLevelFilter(release_mode=not DEBUG_CONFIG_ENABLED))

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


@dataclass
class _ScreenBounds:
    min_x: float = float("inf")
    min_y: float = float("inf")
    max_x: float = float("-inf")
    max_y: float = float("-inf")

    def include_rect(self, left: float, top: float, right: float, bottom: float) -> None:
        self.min_x = min(self.min_x, left, right)
        self.max_x = max(self.max_x, left, right)
        self.min_y = min(self.min_y, top, bottom)
        self.max_y = max(self.max_y, top, bottom)

    def is_valid(self) -> bool:
        return self.min_x <= self.max_x and self.min_y <= self.max_y

    def translate(self, dx: float, dy: float) -> None:
        if not (math.isfinite(dx) and math.isfinite(dy)):
            return
        self.min_x += dx
        self.max_x += dx
        self.min_y += dy
        self.max_y += dy


@dataclass
class _OverlayBounds:
    min_x: float = float("inf")
    min_y: float = float("inf")
    max_x: float = float("-inf")
    max_y: float = float("-inf")

    def include_rect(self, left: float, top: float, right: float, bottom: float) -> None:
        self.min_x = min(self.min_x, left, right)
        self.max_x = max(self.max_x, left, right)
        self.min_y = min(self.min_y, top, bottom)
        self.max_y = max(self.max_y, top, bottom)

    def is_valid(self) -> bool:
        return self.min_x <= self.max_x and self.min_y <= self.max_y

    def translate(self, dx: float, dy: float) -> None:
        if not (math.isfinite(dx) and math.isfinite(dy)):
            return
        self.min_x += dx
        self.max_x += dx
        self.min_y += dy
        self.max_y += dy


@dataclass
class _GroupDebugState:
    anchor_token: str
    justification: str
    use_transformed: bool
    anchor_point: Optional[Tuple[float, float]]
    anchor_logical: Optional[Tuple[float, float]]
    nudged: bool


@dataclass(frozen=True)
class _MeasuredText:
    width: int
    ascent: int
    descent: int


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

class OverlayWindow(QWidget):
    """Transparent overlay that renders CMDR and location info."""

    _resolve_font_family = _resolve_font_family
    _resolve_emoji_font_families = _resolve_emoji_font_families
    _apply_font_fallbacks = _apply_font_fallbacks

    _WM_OVERRIDE_TTL = 1.25  # seconds

    def __init__(self, initial: InitialClientSettings, debug_config: DebugConfig) -> None:
        super().__init__()
        self._font_family = self._resolve_font_family()
        self._font_fallbacks: Tuple[str, ...] = self._resolve_emoji_font_families()
        self._status_raw = "Initialising"
        self._status = self._status_raw
        self._state: Dict[str, Any] = {
            "message": "",
        }
        self._debug_config = debug_config
        self._payload_model = PayloadModel(self._trace_legacy_store_event)
        self._background_opacity: float = 0.0
        self._gridlines_enabled: bool = False
        self._gridline_spacing: int = 120
        self._grid_pixmap: Optional[QPixmap] = None
        self._grid_pixmap_params: Optional[Tuple[int, int, int, int]] = None
        self._drag_enabled: bool = False
        self._drag_active: bool = False
        self._drag_offset: QPoint = QPoint()
        self._move_mode: bool = False
        self._cursor_saved: bool = False
        self._saved_cursor: QCursor = self.cursor()
        self._transparent_input_supported = hasattr(Qt.WindowType, "WindowTransparentForInput")
        self._show_status: bool = False
        self._base_height: int = DEFAULT_WINDOW_BASE_HEIGHT
        self._base_width: int = DEFAULT_WINDOW_BASE_WIDTH
        self._log_retention: int = max(1, int(initial.client_log_retention))
        self._force_render: bool = bool(getattr(initial, "force_render", False))
        self._window_tracker: Optional[WindowTracker] = None
        self._data_client: Optional[OverlayDataClient] = None
        self._last_follow_state: Optional[WindowState] = None
        self._lost_window_logged: bool = False
        self._last_tracker_state: Optional[Tuple[str, int, int, int, int]] = None
        self._last_geometry_log: Optional[Tuple[int, int, int, int]] = None
        self._last_move_log: Optional[Tuple[int, int]] = None
        self._last_screen_name: Optional[str] = None
        self._last_set_geometry: Optional[Tuple[int, int, int, int]] = None
        self._last_visibility_state: Optional[bool] = None
        self._last_raw_window_log: Optional[Tuple[int, int, int, int]] = None
        self._last_normalised_tracker: Optional[
            Tuple[Tuple[int, int, int, int], Tuple[int, int, int, int], str, float, float]
        ] = None
        self._last_device_ratio_log: Optional[Tuple[str, float, float, float]] = None
        self._enforcing_follow_size: bool = False
        self._transient_parent_id: Optional[str] = None
        self._transient_parent_window: Optional[QWindow] = None
        self._fullscreen_hint_logged: bool = False
        self._follow_enabled: bool = True
        self._last_logged_scale: Optional[Tuple[float, float, float]] = None
        self._platform_context = _initial_platform_context(initial)
        self._platform_controller = PlatformController(self, _CLIENT_LOGGER, self._platform_context)
        _CLIENT_LOGGER.debug(
            "Platform controller initialised: session=%s compositor=%s force_xwayland=%s",
            self._platform_context.session_type or "unknown",
            self._platform_context.compositor or "unknown",
            self._platform_context.force_xwayland,
        )
        self._window_controller = WindowController(log_fn=_CLIENT_LOGGER.debug)
        self._title_bar_enabled: bool = bool(getattr(initial, "title_bar_enabled", False))
        self._title_bar_height: int = self._coerce_non_negative(getattr(initial, "title_bar_height", 0), default=0)
        self._last_title_bar_offset: int = 0
        self._aspect_guard_skip_logged: bool = False
        self._cycle_payload_enabled: bool = False
        self._cycle_payload_ids: List[str] = []
        self._cycle_current_id: Optional[str] = None
        self._cycle_anchor_points: Dict[str, Tuple[int, int]] = {}
        self._cycle_copy_clipboard: bool = bool(getattr(initial, "copy_payload_id_on_cycle", False))
        self._last_font_notice: Optional[Tuple[float, float]] = None
        self._scale_mode: str = "fit"
        self._line_widths: Dict[str, int] = _load_line_width_config()
        self._payload_nudge_enabled: bool = False
        self._payload_nudge_gutter: int = 30
        self._text_measurer: Optional[Callable[[str, float, str], _MeasuredText]] = None
        self._offscreen_payloads: Set[str] = set()
        dev_mode_active = (
            DEBUG_CONFIG_ENABLED
            or debug_config.overlay_outline
            or debug_config.group_bounds_outline
            or debug_config.payload_vertex_markers
            or debug_config.trace_enabled
        )
        self._dev_mode_enabled: bool = dev_mode_active
        _CLIENT_LOGGER.debug(
            "Debug config loaded: dev_mode_enabled=%s group_bounds_outline=%s overlay_outline=%s payload_vertex_markers=%s (DEBUG_CONFIG_ENABLED=%s)",
            self._dev_mode_enabled,
            getattr(self._debug_config, "group_bounds_outline", False),
            getattr(self._debug_config, "overlay_outline", False),
            getattr(self._debug_config, "payload_vertex_markers", False),
            DEBUG_CONFIG_ENABLED,
        )
        self._debug_group_filter: Optional[Tuple[str, Optional[str]]] = None
        self._debug_group_bounds_final: Dict[Tuple[str, Optional[str]], _OverlayBounds] = {}
        self._debug_group_state: Dict[Tuple[str, Optional[str]], _GroupDebugState] = {}
        self._payload_log_delay = max(0.0, float(getattr(initial, "payload_log_delay_seconds", 0.0) or 0.0))
        self._group_log_pending_base: Dict[Tuple[str, Optional[str]], Dict[str, Any]] = {}
        self._group_log_pending_transform: Dict[Tuple[str, Optional[str]], Dict[str, Any]] = {}
        self._group_log_next_allowed: Dict[Tuple[str, Optional[str]], float] = {}
        self._logged_group_bounds: Dict[Tuple[str, Optional[str]], Tuple[float, float, float, float]] = {}
        self._logged_group_transforms: Dict[Tuple[str, Optional[str]], Tuple[float, float, float, float]] = {}
        self._group_cache = GroupPlacementCache(
            resolve_cache_path(ROOT_DIR),
            debounce_seconds=1.0 if DEBUG_CONFIG_ENABLED else 5.0,
            logger=_CLIENT_LOGGER,
        )
        self._group_coordinator = GroupCoordinator(cache=self._group_cache, logger=_CLIENT_LOGGER)
        self._render_pipeline = LegacyRenderPipeline(self)

        self._legacy_timer = QTimer(self)
        self._legacy_timer.setInterval(250)
        self._legacy_timer.timeout.connect(self._purge_legacy)
        self._legacy_timer.start()

        self._modifier_timer = QTimer(self)
        self._modifier_timer.setInterval(100)
        self._modifier_timer.timeout.connect(self._poll_modifiers)
        self._modifier_timer.start()

        self._tracking_timer = QTimer(self)
        self._tracking_timer.setInterval(500)
        self._follow_controller = FollowController(
            poll_fn=lambda: self._window_tracker.poll() if self._window_tracker else None,
            logger=_CLIENT_LOGGER,
            tracking_timer=self._tracking_timer,
            debug_suffix=self.format_scale_debug,
        )
        self._tracking_timer.timeout.connect(self._refresh_follow_geometry)

        self._message_clear_timer = QTimer(self)
        self._message_clear_timer.setSingleShot(True)
        self._message_clear_timer.timeout.connect(self._clear_message)

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        window_flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Window
        )
        if sys.platform.startswith("linux"):
            window_flags |= Qt.WindowType.X11BypassWindowManagerHint
        self.setWindowFlags(window_flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

        message_font = QFont(self._font_family, 16)
        self._apply_font_fallbacks(message_font)
        message_font.setWeight(QFont.Weight.Normal)
        self.message_label = QLabel("")
        self.message_label.setFont(message_font)
        self.message_label.setStyleSheet("color: #80d0ff; background: transparent;")
        self.message_label.setWordWrap(True)
        self.message_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.message_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._base_message_point_size = message_font.pointSizeF()

        self._debug_message_point_size = message_font.pointSizeF()
        self._debug_status_point_size = message_font.pointSizeF()
        self._debug_legacy_point_size = 0.0
        self._show_debug_overlay = bool(getattr(initial, "show_debug_overlay", False))
        self._status_bottom_margin = self._coerce_non_negative(getattr(initial, "status_bottom_margin", 20), default=20)
        self._debug_overlay_corner: str = self._normalise_debug_corner(getattr(initial, "debug_overlay_corner", "NW"))
        self._font_scale_diag = 1.0
        min_font = getattr(initial, "min_font_point", 6.0)
        max_font = getattr(initial, "max_font_point", 24.0)
        self._font_min_point = max(1.0, min(float(min_font), 48.0))
        self._font_max_point = max(self._font_min_point, min(float(max_font), 72.0))
        self._override_manager = PluginOverrideManager(
            ROOT_DIR / "overlay_groupings.json",
            _CLIENT_LOGGER,
            debug_config=self._debug_config,
        )
        self._grouping_helper = FillGroupingHelper(
            self,
            self._override_manager,
            _CLIENT_LOGGER,
            self._debug_config,
        )
        self._grouping_adapter = GroupingAdapter(self._grouping_helper, self)
        self._debug_overlay_view = DebugOverlayView(self._apply_font_fallbacks, self._line_width)
        self._cycle_overlay_view = CycleOverlayView()
        layout = QVBoxLayout()
        layout.addWidget(self.message_label, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        layout.addStretch(1)
        layout.setContentsMargins(20, 20, 20, 40)
        self._apply_drag_state()
        self.setLayout(layout)

        self.set_scale_mode(getattr(initial, "scale_mode", "fit"))
        self.set_cycle_payload_enabled(getattr(initial, "cycle_payload_ids", False))
        self.set_payload_nudge(
            getattr(initial, "nudge_overflow_payloads", False),
            getattr(initial, "payload_nudge_gutter", 30),
        )

        width_px, height_px = self._current_physical_size()
        _CLIENT_LOGGER.debug(
            "Overlay window initialised; log retention=%d size=%.0fx%.0fpx; %s",
            self._log_retention,
            width_px,
            height_px,
            self.format_scale_debug(),
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
        self._apply_legacy_scale()
        self._platform_controller.prepare_window(self.windowHandle())
        _CLIENT_LOGGER.debug(
            "Platform controller initialised: session=%s compositor=%s force_xwayland=%s",
            self._platform_context.session_type or "unknown",
            self._platform_context.compositor or "unknown",
            self._platform_context.force_xwayland,
        )
        self._platform_controller.apply_click_through(True)
        screen = self.windowHandle().screen() if self.windowHandle() else None
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        if screen is not None:
            geometry = screen.geometry()
            self._update_auto_legacy_scale(max(geometry.width(), 1), max(geometry.height(), 1))
        self._publish_metrics()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        bg_opacity = max(0.0, min(1.0, self._background_opacity))
        if bg_opacity > 0.0:
            alpha = int(255 * bg_opacity)
            painter.setBrush(QColor(0, 0, 0, alpha))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(self.rect(), 12, 12)
        grid_alpha = int(255 * max(0.0, min(1.0, self._background_opacity)))
        render_grid = self._gridlines_enabled and self._gridline_spacing > 0 and grid_alpha > 0
        if render_grid:
            spacing = self._gridline_spacing
            grid_pixmap = self._grid_pixmap_for(self.width(), self.height(), spacing, grid_alpha)
            if grid_pixmap is not None:
                painter.drawPixmap(0, 0, grid_pixmap)
        self._paint_legacy(painter)
        self._paint_overlay_outline(painter)
        self._paint_cycle_overlay(painter)
        if self._show_debug_overlay:
            self._paint_debug_overlay(painter)
        painter.end()
        super().paintEvent(event)

    def _grid_pixmap_for(self, width: int, height: int, spacing: int, grid_alpha: int) -> Optional[QPixmap]:
        if width <= 0 or height <= 0 or spacing <= 0 or grid_alpha <= 0:
            return None
        line_width = self._line_width("grid")
        params = (width, height, spacing, grid_alpha, line_width)
        if self._grid_pixmap is not None and self._grid_pixmap_params == params:
            return self._grid_pixmap

        pixmap = QPixmap(width, height)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        grid_color = QColor(200, 200, 200, grid_alpha)
        grid_pen = QPen(grid_color)
        grid_pen.setWidth(line_width)
        painter.setPen(grid_pen)

        for x in range(spacing, width, spacing):
            painter.drawLine(x, 0, x, height)
        for y in range(spacing, height, spacing):
            painter.drawLine(0, y, width, y)

        painter.save()
        label_font = painter.font()
        label_font.setPointSizeF(max(6.0, label_font.pointSizeF() * 0.8))
        painter.setFont(label_font)
        painter.setPen(grid_color)
        metrics = painter.fontMetrics()
        top_baseline = metrics.ascent() + 2
        painter.drawText(2, top_baseline, "0")
        for x in range(spacing, width, spacing):
            text = str(x)
            text_rect = metrics.boundingRect(text)
            text_x = x + 2
            if text_x + text_rect.width() > width - 2:
                text_x = max(2, x - text_rect.width() - 2)
            painter.drawText(text_x, top_baseline, text)
        for y in range(spacing, height, spacing):
            text = str(y)
            text_rect = metrics.boundingRect(text)
            baseline = y + metrics.ascent()
            if baseline + 2 > height:
                baseline = y - 2
            painter.drawText(2, baseline, text)
        painter.restore()
        painter.end()

        self._grid_pixmap = pixmap
        self._grid_pixmap_params = params
        return pixmap

    # Interaction -------------------------------------------------

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._invalidate_grid_cache()
        size = event.size()
        if self._enforcing_follow_size:
            self._enforcing_follow_size = False
            self._update_auto_legacy_scale(max(size.width(), 1), max(size.height(), 1))
            return
        expected_size: Optional[Tuple[int, int]] = None
        if (
            self._follow_enabled
            and self._last_set_geometry is not None
            and (self._window_tracker is not None or self._last_follow_state is not None)
        ):
            expected_size = (self._last_set_geometry[2], self._last_set_geometry[3])
        if expected_size and (size.width(), size.height()) != expected_size:
            self._enforcing_follow_size = True
            target_rect = QRect(*self._last_set_geometry)
            self.setGeometry(target_rect)
            return
        self._update_auto_legacy_scale(max(size.width(), 1), max(size.height(), 1))
        self._publish_metrics()

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self._drag_enabled
            and self._move_mode
        ):
            self._drag_active = True
            self._follow_controller.set_drag_state(self._drag_active, self._move_mode)
            self._suspend_follow(1.0)
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            if not self._cursor_saved:
                self._saved_cursor = self.cursor()
                self._cursor_saved = True
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            _CLIENT_LOGGER.debug(
                "Drag initiated at pos=%s offset=%s (from %s) move_mode=%s",
                self.frameGeometry().topLeft(),
                self._drag_offset,
                event.globalPosition().toPoint(),
                self._move_mode,
            )
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        if self._drag_active:
            new_pos = event.globalPosition().toPoint() - self._drag_offset
            self.move(new_pos)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        if self._drag_active and event.button() == Qt.MouseButton.LeftButton:
            self._drag_active = False
            self._follow_controller.set_drag_state(self._drag_active, self._move_mode)
            self._suspend_follow(0.5)
            self.raise_()
            if self._cursor_saved:
                self.setCursor(self._saved_cursor)
                self._cursor_saved = False
            self._apply_drag_state()
            _CLIENT_LOGGER.debug("Drag finished; overlay frame=%s", self.frameGeometry())
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def moveEvent(self, event) -> None:  # type: ignore[override]
        super().moveEvent(event)
        frame = self.frameGeometry()
        current = (frame.x(), frame.y())
        if current != self._last_move_log:
            screen_desc = self._describe_screen(self.windowHandle().screen() if self.windowHandle() else None)
            _CLIENT_LOGGER.debug(
                "Overlay moveEvent: pos=(%d,%d) frame=%s last_set=%s monitor=%s; %s",
                frame.x(),
                frame.y(),
                (frame.x(), frame.y(), frame.width(), frame.height()),
                self._last_set_geometry,
                screen_desc,
                self.format_scale_debug(),
            )
            if (
                self._follow_enabled
                and self._last_set_geometry is not None
                and (frame.x(), frame.y(), frame.width(), frame.height()) != self._last_set_geometry
            ):
                self._set_wm_override(
                    (frame.x(), frame.y(), frame.width(), frame.height()),
                    tracker_tuple=None,
                    reason="moveEvent delta",
                    classification="wm_intervention",
                )
            self._last_move_log = current

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

    def set_force_render(self, force: bool) -> None:
        flag = bool(force)
        if flag == self._force_render:
            return
        self._force_render = flag
        if flag:
            if sys.platform.startswith("linux") and self._is_wayland():
                window_handle = self.windowHandle()
                if window_handle is not None:
                    try:
                        window_handle.setTransientParent(None)
                    except Exception:
                        pass
                self._transient_parent_window = None
                self._transient_parent_id = None
            self._update_follow_visibility(True)
            if sys.platform.startswith("linux"):
                self._platform_controller.apply_click_through(True)
                self._restore_drag_interactivity()
            if self._last_follow_state:
                self._apply_follow_state(self._last_follow_state)
        else:
            if (
                self._follow_enabled
                and self._last_follow_state
                and not self._last_follow_state.is_foreground
            ):
                self._update_follow_visibility(False)

    def set_debug_overlay(self, enabled: bool) -> None:
        flag = bool(enabled)
        if flag == self._show_debug_overlay:
            return
        self._show_debug_overlay = flag
        _CLIENT_LOGGER.debug("Debug overlay %s", "enabled" if flag else "disabled")
        self.update()

    def set_scale_mode(self, mode: str) -> None:
        value = str(mode or "fit").strip().lower()
        if value not in {"fit", "fill"}:
            value = "fit"
        if value == self._scale_mode:
            return
        self._scale_mode = value
        _CLIENT_LOGGER.debug("Overlay scale mode set to %s", value)
        self._publish_metrics()
        self.update()

    def set_payload_nudge(self, enabled: Optional[bool], gutter: Optional[int] = None) -> None:
        changed = False
        if enabled is not None:
            flag = bool(enabled)
            if flag != self._payload_nudge_enabled:
                self._payload_nudge_enabled = flag
                changed = True
        if gutter is not None:
            try:
                numeric = int(gutter)
            except (TypeError, ValueError):
                numeric = self._payload_nudge_gutter
            numeric = max(0, min(numeric, 500))
            if numeric != self._payload_nudge_gutter:
                self._payload_nudge_gutter = numeric
                changed = True
        if changed:
            _CLIENT_LOGGER.debug(
                "Payload nudge updated: enabled=%s gutter=%d",
                self._payload_nudge_enabled,
                self._payload_nudge_gutter,
            )
            self.update()

    def set_payload_log_delay(self, delay_seconds: Optional[float]) -> None:
        try:
            numeric = float(delay_seconds)
        except (TypeError, ValueError):
            numeric = self._payload_log_delay
        numeric = max(0.0, numeric)
        if math.isclose(numeric, self._payload_log_delay, rel_tol=1e-9, abs_tol=1e-9):
            return
        self._payload_log_delay = numeric
        now = time.monotonic()
        for key in self._group_log_pending_base.keys():
            self._group_log_next_allowed[key] = now + self._payload_log_delay
        _CLIENT_LOGGER.debug("Payload log delay updated to %.2fs", self._payload_log_delay)

    def set_cycle_payload_enabled(self, enabled: Optional[bool]) -> None:
        flag = bool(enabled)
        if flag == self._cycle_payload_enabled:
            return
        self._cycle_payload_enabled = flag
        if flag:
            _CLIENT_LOGGER.debug("Payload ID cycling enabled")
            self._sync_cycle_items()
        else:
            _CLIENT_LOGGER.debug("Payload ID cycling disabled")
            self._cycle_payload_ids = []
            self._cycle_current_id = None
        self.update()

    def set_cycle_payload_copy_enabled(self, enabled: Optional[bool]) -> None:
        if enabled is None:
            return
        flag = bool(enabled)
        if flag == self._cycle_copy_clipboard:
            return
        self._cycle_copy_clipboard = flag
        _CLIENT_LOGGER.debug("Copy payload ID on cycle %s", "enabled" if flag else "disabled")

    def cycle_payload_step(self, step: int) -> None:
        if not self._cycle_payload_enabled:
            return
        self._sync_cycle_items()
        if not self._cycle_payload_ids:
            return
        current_id = self._cycle_current_id
        try:
            index = self._cycle_payload_ids.index(current_id) if current_id else 0
        except ValueError:
            index = 0
        next_index = (index + step) % len(self._cycle_payload_ids)
        self._cycle_current_id = self._cycle_payload_ids[next_index]
        _CLIENT_LOGGER.debug(
            "Cycle payload step=%s index=%d/%d id=%s",
            step,
            next_index + 1,
            len(self._cycle_payload_ids),
            self._cycle_current_id,
        )
        if self._cycle_copy_clipboard and self._cycle_current_id:
            try:
                clipboard = QGuiApplication.clipboard()
                if clipboard is not None:
                    clipboard.setText(self._cycle_current_id)
            except Exception as exc:
                _CLIENT_LOGGER.warning("Failed to copy payload ID '%s' to clipboard: %s", self._cycle_current_id, exc)
        self.update()

    def handle_cycle_action(self, action: str) -> None:
        if not action:
            return
        action_lower = action.lower()
        if action_lower == "next":
            self.cycle_payload_step(1)
        elif action_lower == "prev":
            self.cycle_payload_step(-1)
        elif action_lower == "reset":
            self._sync_cycle_items()
            self.update()

    def _sync_cycle_items(self) -> None:
        if not self._cycle_payload_enabled:
            return
        ids = [item_id for item_id, _ in self._payload_model.store.items()]
        previous_id = self._cycle_current_id
        self._cycle_payload_ids = ids
        if not ids:
            self._cycle_current_id = None
            return
        if previous_id in ids:
            self._cycle_current_id = previous_id
        else:
            self._cycle_current_id = ids[0]

    def _register_cycle_anchor(self, item_id: str, x: int, y: int) -> None:
        self._cycle_anchor_points[item_id] = (int(x), int(y))

    def _resolve_group_override_pattern(
        self,
        legacy_item: Optional[LegacyItem],
    ) -> Optional[str]:
        if legacy_item is None:
            return None
        override_manager = getattr(self, "_override_manager", None)
        if override_manager is None:
            return None
        plugin_name = legacy_item.plugin
        group_key = override_manager.grouping_key_for(plugin_name, legacy_item.item_id)
        if group_key is None:
            return None
        plugin_label, suffix = group_key
        if not override_manager.group_is_configured(plugin_label, suffix):
            return None
        if isinstance(suffix, str) and suffix:
            return f"group:{suffix}"
        label = plugin_label if isinstance(plugin_label, str) and plugin_label else (legacy_item.plugin or "plugin")
        label = str(label).strip() or "plugin"
        return f"group:{label}"

    def _format_override_lines(self, legacy_item: Optional[LegacyItem]) -> List[str]:
        if legacy_item is None:
            return []
        data = legacy_item.data
        if not isinstance(data, Mapping):
            return []
        transform_meta = data.get("__mo_transform__")
        lines: List[str] = []
        pattern_value: Optional[str] = None
        if isinstance(transform_meta, Mapping):
            for section_name in ("scale", "offset", "pivot"):
                block = transform_meta.get(section_name)
                if not isinstance(block, Mapping):
                    continue
                parts: List[str] = []
                for key, value in block.items():
                    if not isinstance(value, (int, float)):
                        continue
                    if section_name == "scale":
                        if math.isclose(value, 1.0, rel_tol=1e-6, abs_tol=1e-6):
                            continue
                    else:
                        if math.isclose(value, 0.0, rel_tol=1e-6, abs_tol=1e-6):
                            continue
                    parts.append(f"{key}={value:g}")
                if parts:
                    lines.append(f"{section_name}: " + ", ".join(parts))
            pattern = transform_meta.get("pattern")
            if isinstance(pattern, str) and pattern:
                pattern_value = pattern
        group_pattern = self._resolve_group_override_pattern(legacy_item)
        if pattern_value:
            lines.append(f"override pattern: {pattern_value}")
        elif group_pattern:
            lines.append(f"override pattern: {group_pattern}")
        return lines

    def _format_transform_chain(
        self,
        legacy_item: Optional[LegacyItem],
        mapper: LegacyMapper,
        group_transform: Optional[GroupTransform],
    ) -> List[str]:
        if legacy_item is None:
            return []
        data = legacy_item.data
        if not isinstance(data, Mapping):
            return []

        lines: List[str] = []
        transform_meta = data.get("__mo_transform__")
        pivot_x_meta, pivot_y_meta, scale_x_meta, scale_y_meta, offset_x_meta, offset_y_meta = transform_components(transform_meta)

        state = self._viewport_state()
        fill = build_viewport(mapper, state, group_transform, BASE_WIDTH, BASE_HEIGHT)
        transform_context = build_payload_transform_context(fill)
        transform_context = build_payload_transform_context(fill)
        transform_context = build_payload_transform_context(fill)

        if mapper.transform.mode is ScaleMode.FILL:
            lines.append(
                "fill overflow: x={}, y={}".format(
                    "yes" if fill.overflow_x else "no",
                    "yes" if fill.overflow_y else "no",
                )
            )
            band_line = (
                "fill band: x={:.3f}..{:.3f}, y={:.3f}..{:.3f}, anchor=({:.3f},{:.3f})".format(
                    fill.band_min_x,
                    fill.band_max_x,
                    fill.band_min_y,
                    fill.band_max_y,
                    fill.band_anchor_x,
                    fill.band_anchor_y,
                )
            )
            lines.append(band_line)
            if group_transform is not None:
                logical_anchor_x = group_transform.band_anchor_x * BASE_WIDTH
                logical_anchor_y = group_transform.band_anchor_y * BASE_HEIGHT
                anchor_overlay_x = remap_axis_value(logical_anchor_x, transform_context.axis_x)
                anchor_overlay_y = remap_axis_value(logical_anchor_y, transform_context.axis_y)
                if (
                    math.isfinite(logical_anchor_x)
                    and math.isfinite(logical_anchor_y)
                    and math.isfinite(anchor_overlay_x)
                    and math.isfinite(anchor_overlay_y)
                ):
                    lines.append(
                        "group anchor: logical=({:.1f},{:.1f}) overlay=({:.1f},{:.1f}) norm=({:.3f},{:.3f})".format(
                            logical_anchor_x,
                            logical_anchor_y,
                            anchor_overlay_x,
                            anchor_overlay_y,
                            group_transform.band_anchor_x,
                            group_transform.band_anchor_y,
                        )
                    )

        if not math.isclose(scale_x_meta, 1.0, rel_tol=1e-6, abs_tol=1e-6) or not math.isclose(scale_y_meta, 1.0, rel_tol=1e-6, abs_tol=1e-6):
            lines.append("override scale: x={:.3f}, y={:.3f}".format(scale_x_meta, scale_y_meta))
        if not math.isclose(offset_x_meta, 0.0, rel_tol=1e-6, abs_tol=1e-6) or not math.isclose(offset_y_meta, 0.0, rel_tol=1e-6, abs_tol=1e-6):
            lines.append("override offset: x={:.1f}, y={:.1f}".format(offset_x_meta, offset_y_meta))
        if not math.isclose(pivot_x_meta, 0.0, rel_tol=1e-6, abs_tol=1e-6) or not math.isclose(pivot_y_meta, 0.0, rel_tol=1e-6, abs_tol=1e-6):
            lines.append("override pivot: x={:.1f}, y={:.1f}".format(pivot_x_meta, pivot_y_meta))

        return lines

    def _paint_cycle_overlay(self, painter: QPainter) -> None:
        self._cycle_current_id, ids = self._cycle_overlay_view.sync_cycle_items(
            cycle_enabled=self._cycle_payload_enabled,
            payload_model=self._payload_model,
            cycle_current_id=self._cycle_current_id,
        )
        self._cycle_payload_ids = ids
        self._cycle_overlay_view.paint_cycle_overlay(
            painter,
            cycle_enabled=self._cycle_payload_enabled,
            cycle_current_id=self._cycle_current_id,
            compute_legacy_mapper=self._compute_legacy_mapper,
            cycle_anchor_points=self._cycle_anchor_points,
            payload_model=self._payload_model,
            grouping_helper=self._grouping_helper,
        )

    def set_font_bounds(self, min_point: Optional[float], max_point: Optional[float]) -> None:
        changed = False
        if min_point is not None:
            try:
                min_value = float(min_point)
            except (TypeError, ValueError):
                min_value = self._font_min_point
            min_value = max(1.0, min(min_value, 48.0))
            if not math.isclose(min_value, self._font_min_point, rel_tol=1e-3):
                self._font_min_point = min_value
                changed = True
        if max_point is not None:
            try:
                max_value = float(max_point)
            except (TypeError, ValueError):
                max_value = self._font_max_point
            max_value = max(self._font_min_point, min(max_value, 72.0))
            if not math.isclose(max_value, self._font_max_point, rel_tol=1e-3):
                self._font_max_point = max_value
                changed = True
        if self._font_max_point < self._font_min_point:
            self._font_max_point = self._font_min_point
            changed = True
        if changed:
            _CLIENT_LOGGER.debug(
                "Font bounds updated: min=%.1f max=%.1f",
                self._font_min_point,
                self._font_max_point,
            )
            self._update_label_fonts()
            self._refresh_legacy_items()
            self.update()
            self._notify_font_bounds_changed()

    def display_message(self, message: str, *, ttl: Optional[float] = None) -> None:
        self._message_clear_timer.stop()
        self._state["message"] = message
        self.message_label.setText(message)
        if ttl is not None and ttl > 0:
            self._message_clear_timer.start(int(ttl * 1000))

    def _clear_message(self) -> None:
        self._state["message"] = ""
        self.message_label.clear()

    def set_status_text(self, status: str) -> None:
        self._status_raw = status
        self._status = self._format_status_message(status)
        if self._show_status:
            self._show_overlay_status_message(self._status)

    def _format_status_message(self, status: str) -> str:
        message = status or ""
        if "Connected to 127.0.0.1:" not in message:
            return message
        platform_label = self._platform_controller.platform_label()
        suffix = f" on {platform_label}"
        if message.endswith(suffix):
            return message
        return f"{message}{suffix}"

    def set_show_status(self, show: bool) -> None:
        flag = bool(show)
        if flag == self._show_status:
            return
        self._show_status = flag
        if flag:
            self._show_overlay_status_message(self._status)
        else:
            self._dismiss_overlay_status_message()

    def set_status_bottom_margin(self, margin: Optional[int]) -> None:
        value = self._coerce_non_negative(margin, default=self._status_bottom_margin)
        if value == self._status_bottom_margin:
            return
        self._status_bottom_margin = value
        _CLIENT_LOGGER.debug("Status bottom margin updated to %spx", self._status_bottom_margin)
        if self._show_status and self._status:
            self._show_overlay_status_message(self._status)

    def set_debug_overlay_corner(self, corner: Optional[str]) -> None:
        normalised = self._normalise_debug_corner(corner)
        if normalised == self._debug_overlay_corner:
            return
        self._debug_overlay_corner = normalised
        _CLIENT_LOGGER.debug("Debug overlay corner updated to %s", self._debug_overlay_corner)
        if self._show_debug_overlay:
            self.update()

    def _show_overlay_status_message(self, status: str) -> None:
        message = (status or "").strip()
        if not message:
            return
        bottom_margin = max(0, self._status_bottom_margin)
        x_pos = 10
        y_pos = max(0, DEFAULT_WINDOW_BASE_HEIGHT - bottom_margin)
        payload = {
            "type": "message",
            "id": "__status_banner__",
            "text": message,
            "color": "#ffffff",
            "x": x_pos,
            "y": y_pos,
            "ttl": 0,
            "size": "normal",
            "plugin": "EDMCModernOverlay",
        }
        _CLIENT_LOGGER.debug(
            "Legacy status message dispatched: text='%s' ttl=%s x=%s y=%s",
            message,
            payload["ttl"],
            payload["x"],
            payload["y"],
        )
        self.handle_legacy_payload(payload)

    def _dismiss_overlay_status_message(self) -> None:
        payload = {
            "type": "message",
            "id": "__status_banner__",
            "text": "",
            "ttl": 0,
            "plugin": "EDMCModernOverlay",
        }
        self.handle_legacy_payload(payload)

    def _normalise_debug_corner(self, corner: Optional[str]) -> str:
        if not corner:
            return "NW"
        value = str(corner).strip().upper()
        return value if value in {"NW", "NE", "SW", "SE"} else "NW"

    @staticmethod
    def _coerce_non_negative(value: Optional[int], *, default: int) -> int:
        try:
            numeric = int(value) if value is not None else default
        except (TypeError, ValueError):
            numeric = default
        return max(0, numeric)

    def _invalidate_grid_cache(self) -> None:
        self._grid_pixmap = None
        self._grid_pixmap_params = None

    def _mark_legacy_cache_dirty(self) -> None:
        self._render_pipeline.mark_dirty()

    def set_background_opacity(self, opacity: float) -> None:
        try:
            value = float(opacity)
        except (TypeError, ValueError):
            value = 0.0
        value = max(0.0, min(1.0, value))
        if value != self._background_opacity:
            self._background_opacity = value
            self._invalidate_grid_cache()
            self.update()

    def set_drag_enabled(self, enabled: bool) -> None:
        enabled_flag = bool(enabled)
        if enabled_flag != self._drag_enabled:
            self._drag_enabled = enabled_flag
            _CLIENT_LOGGER.debug(
                "Drag enabled set to %s (platform=%s); %s",
                self._drag_enabled,
                QGuiApplication.platformName(),
                self.format_scale_debug(),
            )
            self._apply_drag_state()

    def set_legacy_scale_y(self, scale: float, *, auto: bool = False) -> None:
        _CLIENT_LOGGER.debug("Legacy scale control ignored (requested scale_y=%s)", scale)

    def set_legacy_scale_x(self, scale: float, *, auto: bool = False) -> None:
        _CLIENT_LOGGER.debug("Legacy scale control ignored (requested scale_x=%s)", scale)

    def set_gridlines(self, *, enabled: bool, spacing: Optional[int] = None) -> None:
        self._gridlines_enabled = bool(enabled)
        if spacing is not None:
            try:
                numeric = int(spacing)
            except (TypeError, ValueError):
                numeric = self._gridline_spacing
            self._gridline_spacing = max(10, numeric)
        self._invalidate_grid_cache()
        self.update()

    def set_title_bar_compensation(self, enabled: Optional[bool], height: Optional[int]) -> None:
        changed = False
        if enabled is not None:
            flag = bool(enabled)
            if flag != self._title_bar_enabled:
                self._title_bar_enabled = flag
                changed = True
        if height is not None:
            try:
                numeric = int(height)
            except (TypeError, ValueError):
                numeric = self._title_bar_height
            numeric = max(0, numeric)
            if numeric != self._title_bar_height:
                self._title_bar_height = numeric
                changed = True
        if changed:
            if self._follow_controller.wm_override is not None:
                self._clear_wm_override(reason="title_bar_compensation_changed")
            _CLIENT_LOGGER.debug(
                "Title bar compensation updated: enabled=%s height=%d",
                self._title_bar_enabled,
                self._title_bar_height,
            )
            self._follow_controller.reset_resume_window()
            if self._follow_enabled and self._window_tracker is not None:
                self._refresh_follow_geometry()
            elif self._last_follow_state is not None:
                self._apply_follow_state(self._last_follow_state)
            else:
                self.update()

    def set_window_dimensions(self, width: Optional[int], height: Optional[int]) -> None:
        _CLIENT_LOGGER.debug(
            "Ignoring explicit window size request (%s x %s); overlay follows game window geometry.",
            width,
            height,
        )

    def set_log_retention(self, retention: int) -> None:
        try:
            value = int(retention)
        except (TypeError, ValueError):
            value = self._log_retention
        value = max(1, value)
        self._log_retention = value

    def handle_legacy_payload(self, payload: Dict[str, Any]) -> None:
        self._handle_legacy(payload)

    def update_platform_context(self, context_payload: Optional[Dict[str, Any]]) -> None:
        if context_payload is None:
            return
        session = str(context_payload.get("session_type") or self._platform_context.session_type)
        compositor = str(context_payload.get("compositor") or self._platform_context.compositor)
        force_value = context_payload.get("force_xwayland")
        if force_value is None:
            force_flag = self._platform_context.force_xwayland
        else:
            force_flag = bool(force_value)
        flatpak_value = context_payload.get("flatpak")
        if flatpak_value is None:
            flatpak_flag = self._platform_context.flatpak
        else:
            flatpak_flag = bool(flatpak_value)
        flatpak_app_value = context_payload.get("flatpak_app")
        if flatpak_app_value is None:
            flatpak_app_label = self._platform_context.flatpak_app
        else:
            flatpak_app_label = str(flatpak_app_value)
        new_context = PlatformContext(
            session_type=session,
            compositor=compositor,
            force_xwayland=force_flag,
            flatpak=flatpak_flag,
            flatpak_app=flatpak_app_label,
        )
        if new_context == self._platform_context:
            return
        self._platform_context = new_context
        self._platform_controller.update_context(new_context)
        self._platform_controller.prepare_window(self.windowHandle())
        self._platform_controller.apply_click_through(True)
        self._restore_drag_interactivity()
        _CLIENT_LOGGER.debug(
            "Platform context updated: session=%s compositor=%s force_xwayland=%s flatpak=%s",
            new_context.session_type or "unknown",
            new_context.compositor or "unknown",
            new_context.force_xwayland,
            new_context.flatpak,
        )
        self._status = self._format_status_message(self._status_raw)
        if self._show_status and self._status:
            self._show_overlay_status_message(self._status)

    # Platform integration -------------------------------------------------

    def _apply_drag_state(self) -> None:
        window = self.windowHandle()
        _CLIENT_LOGGER.debug(
            "Applying drag state: drag_enabled=%s transparent=%s move_mode=%s window=%s flags=%s",
            self._drag_enabled,
            not self._drag_enabled,
            self._move_mode,
            bool(window),
            hex(int(window.flags())) if window is not None else "none",
        )
        self._set_click_through(not self._drag_enabled)
        if not self._drag_enabled:
            self._move_mode = False
            self._drag_active = False
            self._follow_controller.set_drag_state(self._drag_active, self._move_mode)
            if self._cursor_saved:
                self.setCursor(self._saved_cursor)
                self._cursor_saved = False
        self.raise_()

    def _poll_modifiers(self) -> None:
        if not self._drag_enabled or self._drag_active:
            return
        modifiers = QApplication.queryKeyboardModifiers()
        alt_down = bool(modifiers & Qt.KeyboardModifier.AltModifier)
        if alt_down and not self._move_mode:
            self._move_mode = True
            self._suspend_follow(0.75)
            if not self._cursor_saved:
                self._saved_cursor = self.cursor()
                self._cursor_saved = True
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        elif not alt_down and self._move_mode:
            self._move_mode = False
            if self._cursor_saved:
                self.setCursor(self._saved_cursor)
                self._cursor_saved = False

    def _set_click_through(self, transparent: bool) -> None:
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, transparent)
        for child_name in ("message_label",):
            child = getattr(self, child_name, None)
            if child is not None:
                try:
                    child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, transparent)
                except Exception:
                    pass
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        if self._is_wayland():
            self.setWindowFlag(Qt.WindowType.Tool, False)
        else:
            self.setWindowFlag(Qt.WindowType.Tool, True)
        if not self.isVisible():
            self.show()
        window = self.windowHandle()
        _CLIENT_LOGGER.debug(
            "Set click-through to %s (WA_Transparent=%s window_flag=%s)",
            transparent,
            self.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents),
            hex(int(window.flags())) if window is not None else "none",
        )
        if window is not None:
            self._platform_controller.prepare_window(window)
            self._platform_controller.apply_click_through(transparent)
            if self._transparent_input_supported:
                window.setFlag(Qt.WindowType.WindowTransparentForInput, transparent)
        if self.isVisible():
            self.raise_()

    def _restore_drag_interactivity(self) -> None:
        if not self._drag_enabled or self._drag_active:
            return
        _CLIENT_LOGGER.debug("Restoring interactive overlay input because drag is enabled; %s", self.format_scale_debug())
        self._set_click_through(False)

    # Follow mode ----------------------------------------------------------

    def _start_tracking(self) -> None:
        if not self._window_tracker or not self._follow_enabled:
            return
        self._follow_controller.set_follow_enabled(True)
        self._follow_controller.set_drag_state(self._drag_active, self._move_mode)
        self._follow_controller.start()

    def _stop_tracking(self) -> None:
        self._follow_controller.stop()

    def _set_wm_override(
        self,
        rect: Tuple[int, int, int, int],
        tracker_tuple: Optional[Tuple[int, int, int, int]],
        reason: str,
        classification: str = "wm_intervention",
    ) -> None:
        self._follow_controller.record_override(rect, tracker_tuple, reason, classification)

    def _clear_wm_override(self, reason: str) -> None:
        self._follow_controller.clear_override(reason)

    def _suspend_follow(self, delay: float = 0.75) -> None:
        self._follow_controller.suspend(delay)

    def _refresh_follow_geometry(self) -> None:
        state = self._follow_controller.refresh()
        if state is None:
            if self._follow_controller.last_poll_attempted and self._follow_controller.last_state_missing:
                self._handle_missing_follow_state()
            return
        self._last_tracker_state = self._follow_controller.last_tracker_state
        self._apply_follow_state(state)

    def _convert_native_rect_to_qt(
        self,
        rect: Tuple[int, int, int, int],
    ) -> Tuple[Tuple[int, int, int, int], Optional[Tuple[str, float, float, float]]]:
        screen_info = self._screen_info_for_native_rect(rect)
        return _convert_native_rect_to_qt(rect, screen_info)

    def _apply_title_bar_offset(
        self,
        geometry: Tuple[int, int, int, int],
        *,
        scale_y: float = 1.0,
    ) -> Tuple[Tuple[int, int, int, int], int]:
        adjusted, offset = _apply_title_bar_offset(
            geometry,
            title_bar_enabled=self._title_bar_enabled,
            title_bar_height=self._title_bar_height,
            scale_y=scale_y,
            previous_offset=self._last_title_bar_offset,
        )
        self._last_title_bar_offset = offset
        return adjusted, offset

    def _apply_aspect_guard(
        self,
        geometry: Tuple[int, int, int, int],
        *,
        original_geometry: Optional[Tuple[int, int, int, int]] = None,
        applied_title_offset: int = 0,
    ) -> Tuple[int, int, int, int]:
        adjusted, self._aspect_guard_skip_logged = _apply_aspect_guard(
            geometry,
            base_width=DEFAULT_WINDOW_BASE_WIDTH,
            base_height=DEFAULT_WINDOW_BASE_HEIGHT,
            original_geometry=original_geometry,
            applied_title_offset=applied_title_offset,
            aspect_guard_skip_logged=self._aspect_guard_skip_logged,
        )
        return adjusted

    def _apply_follow_state(self, state: WindowState) -> None:
        self._lost_window_logged = False

        tracker_qt_tuple, tracker_native_tuple, normalisation_info, desired_tuple = self._normalise_tracker_geometry(state)

        target_tuple = self._resolve_and_apply_geometry(tracker_qt_tuple, desired_tuple)
        self._post_process_follow_state(state, target_tuple)

    def _normalise_tracker_geometry(
        self,
        state: WindowState,
    ) -> Tuple[
        Tuple[int, int, int, int],
        Tuple[int, int, int, int],
        Optional[Tuple[str, float, float, float]],
        Tuple[int, int, int, int],
    ]:
        tracker_global_x = state.global_x if state.global_x is not None else state.x
        tracker_global_y = state.global_y if state.global_y is not None else state.y
        width = max(1, state.width)
        height = max(1, state.height)
        tracker_native_tuple = (
            tracker_global_x,
            tracker_global_y,
            width,
            height,
        )
        if tracker_native_tuple != self._last_raw_window_log:
            _CLIENT_LOGGER.debug(
                "Raw tracker window geometry: pos=(%d,%d) size=%dx%d",
                tracker_global_x,
                tracker_global_y,
                width,
                height,
            )
            self._last_raw_window_log = tracker_native_tuple

        tracker_qt_tuple, normalisation_info = self._convert_native_rect_to_qt(tracker_native_tuple)
        if normalisation_info is not None and tracker_qt_tuple != tracker_native_tuple:
            screen_name, norm_scale_x, norm_scale_y, device_ratio = normalisation_info
            snapshot = (tracker_native_tuple, tracker_qt_tuple, screen_name, norm_scale_x, norm_scale_y)
            if snapshot != self._last_normalised_tracker:
                _CLIENT_LOGGER.debug(
                    "Normalised tracker geometry using screen '%s': native=%s scale=%.3fx%.3f dpr=%.3f -> qt=%s",
                    screen_name,
                    tracker_native_tuple,
                    norm_scale_x,
                    norm_scale_y,
                    device_ratio,
                    tracker_qt_tuple,
                )
                self._last_normalised_tracker = snapshot
        else:
            self._last_normalised_tracker = None

        window_handle = self.windowHandle()
        if window_handle is not None:
            try:
                window_dpr = window_handle.devicePixelRatio()
            except Exception:
                window_dpr = 0.0
            if window_dpr and normalisation_info is not None:
                screen_name, norm_scale_x, norm_scale_y, device_ratio = normalisation_info
                snapshot = (screen_name, float(window_dpr), norm_scale_x, norm_scale_y)
                if snapshot != self._last_device_ratio_log:
                    _CLIENT_LOGGER.debug(
                        "Device pixel ratio diagnostics: window_dpr=%.3f screen='%s' scale_x=%.3f scale_y=%.3f device_ratio=%.3f",
                        float(window_dpr),
                        screen_name,
                        norm_scale_x,
                        norm_scale_y,
                        device_ratio,
                    )
                    self._last_device_ratio_log = snapshot

        scale_y = normalisation_info[2] if normalisation_info is not None else 1.0
        desired_tuple, applied_title_offset = self._apply_title_bar_offset(tracker_qt_tuple, scale_y=scale_y)
        desired_tuple = self._apply_aspect_guard(
            desired_tuple,
            original_geometry=tracker_qt_tuple,
            applied_title_offset=applied_title_offset,
        )
        return tracker_qt_tuple, tracker_native_tuple, normalisation_info, desired_tuple

    def _resolve_and_apply_geometry(
        self,
        tracker_qt_tuple: Tuple[int, int, int, int],
        desired_tuple: Tuple[int, int, int, int],
    ) -> Tuple[int, int, int, int]:
        override_rect = self._follow_controller.wm_override
        override_tracker = self._follow_controller.wm_override_tracker
        override_expired = self._follow_controller.override_expired()

        def _current_geometry() -> Tuple[int, int, int, int]:
            current_rect = self.frameGeometry()
            return (
                current_rect.x(),
                current_rect.y(),
                current_rect.width(),
                current_rect.height(),
            )

        def _move_to_screen(target: Tuple[int, int, int, int]) -> None:
            self._move_to_screen(QRect(*target))

        def _set_geometry(target: Tuple[int, int, int, int]) -> None:
            self._last_set_geometry = target
            self.setGeometry(QRect(*target))
            self.raise_()

        def _classify_override(target: Tuple[int, int, int, int], actual: Tuple[int, int, int, int]) -> str:
            classification = self._classify_geometry_override(target, actual)
            if classification == "layout":
                try:
                    size_hint = self.sizeHint()
                except Exception:
                    size_hint = None
                try:
                    min_hint = self.minimumSizeHint()
                except Exception:
                    min_hint = None
                _CLIENT_LOGGER.debug(
                    "Adopting layout-constrained geometry from WM: tracker=%s actual=%s sizeHint=%s minimumSizeHint=%s",
                    tracker_qt_tuple,
                    actual,
                    size_hint,
                    min_hint,
                )
            else:
                _CLIENT_LOGGER.debug(
                    "Adopting WM authoritative geometry: tracker=%s actual=%s (classification=%s)",
                    tracker_qt_tuple,
                    actual,
                    classification,
                )
            return classification

        target_tuple = self._window_controller.resolve_and_apply_geometry(
            tracker_qt_tuple,
            desired_tuple,
            override_rect=override_rect,
            override_tracker=override_tracker,
            override_expired=override_expired,
            current_geometry_fn=_current_geometry,
            move_to_screen_fn=_move_to_screen,
            set_geometry_fn=_set_geometry,
            sync_base_dimensions_fn=self._sync_base_dimensions_to_widget,
            classify_override_fn=_classify_override,
            clear_override_fn=self._clear_wm_override,
            set_override_fn=self._set_wm_override,
            format_scale_debug_fn=self.format_scale_debug,
        )

        self._last_geometry_log = target_tuple
        return target_tuple

    def _post_process_follow_state(
        self,
        state: WindowState,
        target_tuple: Tuple[int, int, int, int],
    ) -> None:
        def _ensure_parent(identifier: str) -> None:
            self._ensure_transient_parent(state)

        def _fullscreen_hint() -> bool:
            if (
                not sys.platform.startswith("linux")
                or self._fullscreen_hint_logged
                or self._window_controller._fullscreen_hint_logged  # internal flag mirrors hint emission
                or not state.is_foreground
            ):
                return False
            screen = self.windowHandle().screen() if self.windowHandle() else None
            if screen is None:
                screen = QGuiApplication.primaryScreen()
            if screen is None:
                return False
            geometry = screen.geometry()
            if state.width >= geometry.width() and state.height >= geometry.height():
                _CLIENT_LOGGER.info(
                    "Overlay running in compositor-managed mode; for true fullscreen use borderless windowed in Elite or enable compositor vsync. (%s)",
                    self.format_scale_debug(),
                )
                self._fullscreen_hint_logged = True
                return True
            return False

        normalized_state = WindowState(
            x=state.x,
            y=state.y,
            width=state.width,
            height=state.height,
            is_foreground=state.is_foreground,
            is_visible=state.is_visible,
            identifier=state.identifier,
            global_x=state.global_x if state.global_x is not None else state.x,
            global_y=state.global_y if state.global_y is not None else state.y,
        )

        self._window_controller.post_process_follow_state(
            normalized_state,
            target_tuple,
            force_render=self._force_render,
            update_follow_visibility_fn=self._update_follow_visibility,
            update_auto_scale_fn=self._update_auto_legacy_scale,
            ensure_transient_parent_fn=_ensure_parent,
            fullscreen_hint_fn=_fullscreen_hint,
        )
        # Mirror controller flag back to overlay state for future checks.
        self._fullscreen_hint_logged = self._window_controller._fullscreen_hint_logged

    def _ensure_transient_parent(self, state: WindowState) -> None:
        if not sys.platform.startswith("linux"):
            return
        if self._is_wayland():
            if self._transient_parent_window is not None:
                window_handle = self.windowHandle()
                if window_handle is not None:
                    try:
                        window_handle.setTransientParent(None)
                    except Exception:
                        pass
                self._transient_parent_window = None
                self._transient_parent_id = None
            return
        identifier = state.identifier
        if not identifier or identifier == self._transient_parent_id:
            return
        window_handle = self.windowHandle()
        if window_handle is None:
            return
        try:
            native_id = int(identifier, 16)
        except ValueError:
            return
        try:
            parent_window = QWindow.fromWinId(native_id)
        except Exception as exc:  # pragma: no cover - defensive guard
            _CLIENT_LOGGER.debug("Failed to wrap native window %s: %s; %s", identifier, exc, self.format_scale_debug())
            return
        if parent_window is None:
            return
        window_handle.setTransientParent(parent_window)
        self._transient_parent_window = parent_window
        self._transient_parent_id = identifier
        _CLIENT_LOGGER.debug("Set overlay transient parent to Elite window %s; %s", identifier, self.format_scale_debug())

    def _handle_missing_follow_state(self) -> None:
        if not self._lost_window_logged:
            _CLIENT_LOGGER.debug("Elite Dangerous window not found; waiting for window to appear; %s", self.format_scale_debug())
            self._lost_window_logged = True
        if self._last_follow_state is None:
            if self._force_render:
                self._update_follow_visibility(True)
                if sys.platform.startswith("linux"):
                    self._platform_controller.apply_click_through(True)
                    self._restore_drag_interactivity()
            else:
                self._update_follow_visibility(False)
            return
        if self._force_render:
            self._update_follow_visibility(True)
            if sys.platform.startswith("linux"):
                self._platform_controller.apply_click_through(True)
                self._restore_drag_interactivity()
        else:
            self._last_follow_state = None
            self._clear_wm_override(reason="follow state lost")
            self._update_follow_visibility(False)

    def _update_follow_visibility(self, show: bool) -> None:
        if show:
            if not self.isVisible():
                self.show()
                self.raise_()
                self._apply_drag_state()
        else:
            if self.isVisible():
                self.hide()
        if self._last_visibility_state != show:
            _CLIENT_LOGGER.debug("Overlay visibility set to %s; %s", "visible" if show else "hidden", self.format_scale_debug())
            self._last_visibility_state = show

    def _move_to_screen(self, rect: QRect) -> None:
        window = self.windowHandle()
        if window is None:
            return
        screen = self._screen_for_rect(rect)
        if screen is not None and window.screen() is not screen:
            _CLIENT_LOGGER.debug(
                "Moving overlay to screen %s; %s",
                self._describe_screen(screen),
                self.format_scale_debug(),
            )
            window.setScreen(screen)
            self._last_screen_name = self._describe_screen(screen)
        elif screen is not None:
            self._last_screen_name = self._describe_screen(screen)

    def _screen_for_rect(self, rect: QRect):
        screens = QGuiApplication.screens()
        if not screens:
            return None
        best_screen = None
        best_area = 0
        for screen in screens:
            area = rect.intersected(screen.geometry())
            intersection_area = area.width() * area.height()
            if intersection_area > best_area:
                best_area = intersection_area
                best_screen = screen
        if best_screen is not None:
            return best_screen
        primary = QGuiApplication.primaryScreen()
        return primary or screens[0]

    def _screen_for_native_rect(self, rect: QRect) -> Optional[QScreen]:
        screens = QGuiApplication.screens()
        if not screens:
            return None
        best_screen: Optional[QScreen] = None
        best_area = 0
        for screen in screens:
            try:
                native_geometry = screen.nativeGeometry()
            except AttributeError:
                native_geometry = screen.geometry()
            area = rect.intersected(native_geometry)
            intersection_area = max(area.width(), 0) * max(area.height(), 0)
            if intersection_area > best_area:
                best_area = intersection_area
                best_screen = screen
        if best_screen is not None:
            return best_screen
        return QGuiApplication.primaryScreen()

    def _screen_info_for_native_rect(self, rect: Tuple[int, int, int, int]) -> Optional[ScreenInfo]:
        native_rect = QRect(*rect)
        screen = self._screen_for_native_rect(native_rect)
        if screen is None:
            return None
        try:
            native_geometry = screen.nativeGeometry()
        except AttributeError:
            native_geometry = screen.geometry()
        logical_geometry = screen.geometry()
        device_ratio = 1.0
        screen_name = screen.name() or screen.manufacturer() or "unknown"
        try:
            device_ratio = float(screen.devicePixelRatio())
        except (AttributeError, RuntimeError, TypeError, ValueError) as exc:
            _CLIENT_LOGGER.debug("devicePixelRatio unavailable for screen %s; defaulting to 1.0 (%s)", screen_name, exc)
            device_ratio = 1.0
        if device_ratio <= 0.0:
            device_ratio = 1.0
        return ScreenInfo(
            name=screen_name,
            logical_geometry=(
                logical_geometry.x(),
                logical_geometry.y(),
                logical_geometry.width(),
                logical_geometry.height(),
            ),
            native_geometry=(
                native_geometry.x(),
                native_geometry.y(),
                native_geometry.width(),
                native_geometry.height(),
            ),
            device_ratio=device_ratio,
        )

    def _describe_screen(self, screen) -> str:
        if screen is None:
            return "unknown"
        try:
            geometry = screen.geometry()
            return f"{screen.name()} {geometry.width()}x{geometry.height()}@({geometry.x()},{geometry.y()})"
        except Exception:
            return str(screen)

    def _sync_base_dimensions_to_widget(self) -> None:
        width_px, height_px = self._current_physical_size()
        self._base_width = max(int(round(width_px)), 1)
        self._base_height = max(int(round(height_px)), 1)

    def _classify_geometry_override(
        self,
        tracker_tuple: Tuple[int, int, int, int],
        actual_tuple: Tuple[int, int, int, int],
    ) -> str:
        """Identify whether a WM override stems from internal layout constraints."""
        try:
            min_hint = self.minimumSizeHint()
        except Exception:
            min_hint = None
        try:
            size_hint = self.sizeHint()
        except Exception:
            size_hint = None
        return self._compute_geometry_override_classification(tracker_tuple, actual_tuple, min_hint, size_hint)

    @staticmethod
    def _compute_geometry_override_classification(
        tracker_tuple: Tuple[int, int, int, int],
        actual_tuple: Tuple[int, int, int, int],
        min_hint: Optional[QSize],
        size_hint: Optional[QSize],
        *,
        tolerance: int = 2,
    ) -> str:
        tracker_width = tracker_tuple[2]
        tracker_height = tracker_tuple[3]
        actual_width = actual_tuple[2]
        actual_height = actual_tuple[3]
        width_diff = actual_width - tracker_width
        height_diff = actual_height - tracker_height

        if width_diff < 0 or height_diff < 0:
            return "wm_intervention"

        min_width = max(min_hint.width() if isinstance(min_hint, QSize) else 0, 0)
        min_height = max(min_hint.height() if isinstance(min_hint, QSize) else 0, 0)
        size_width = max(size_hint.width() if isinstance(size_hint, QSize) else 0, 0)
        size_height = max(size_hint.height() if isinstance(size_hint, QSize) else 0, 0)

        within_preferred_width = size_width <= 0 or actual_width <= size_width + tolerance
        within_preferred_height = size_height <= 0 or actual_height <= size_height + tolerance

        width_constrained = (
            width_diff > 0
            and min_width > 0
            and actual_width >= (min_width - tolerance)
            and within_preferred_width
        )
        height_constrained = (
            height_diff > 0
            and min_height > 0
            and actual_height >= (min_height - tolerance)
            and within_preferred_height
        )

        if width_constrained or height_constrained:
            return "layout"
        return "wm_intervention"

    # Legacy overlay handling ---------------------------------------------

    def _update_auto_legacy_scale(self, width: int, height: int) -> None:
        mapper = self._compute_legacy_mapper()
        try:
            ratio = self.devicePixelRatioF()
        except Exception:
            ratio = 1.0
        if ratio <= 0.0:
            ratio = 1.0
        state = ViewportState(width=float(max(width, 1)), height=float(max(height, 1)), device_ratio=ratio)
        scale_x, scale_y = legacy_scale_components(mapper, state)
        transform = mapper.transform
        diagonal_scale = math.sqrt((scale_x * scale_x + scale_y * scale_y) / 2.0)
        self._font_scale_diag = diagonal_scale
        self._update_message_font()
        current = (
            round(scale_x, 4),
            round(scale_y, 4),
            round(diagonal_scale, 4),
            round(transform.scale, 4),
            round(transform.scaled_size[0], 1),
            round(transform.scaled_size[1], 1),
            round(mapper.offset_x, 1),
            round(mapper.offset_y, 1),
            transform.mode.value,
            transform.overflow_x,
            transform.overflow_y,
        )
        if self._last_logged_scale != current:
            width_px, height_px = self._current_physical_size()
            _CLIENT_LOGGER.debug(
                (
                    "Overlay scaling updated: window=%dx%d px mode=%s base_scale=%.4f "
                    "scale_x=%.3f scale_y=%.3f diag=%.2f scaled=%.1fx%.1f "
                    "offset=(%.1f,%.1f) overflow_x=%d overflow_y=%d message_pt=%.1f"
                ),
                int(round(width_px)),
                int(round(height_px)),
                transform.mode.value,
                transform.scale,
                scale_x,
                scale_y,
                diagonal_scale,
                transform.scaled_size[0],
                transform.scaled_size[1],
                mapper.offset_x,
                mapper.offset_y,
                1 if transform.overflow_x else 0,
                1 if transform.overflow_y else 0,
                self._debug_message_point_size,
            )
            self._last_logged_scale = current

    def _extract_plugin_name(self, payload: Mapping[str, Any]) -> Optional[str]:
        for key in ("plugin", "plugin_name", "source_plugin"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                return value
        meta = payload.get("meta")
        if isinstance(meta, Mapping):
            for key in ("plugin", "plugin_name", "source_plugin"):
                value = meta.get(key)
                if isinstance(value, str) and value:
                    return value
        raw = payload.get("raw")
        if isinstance(raw, Mapping):
            for key in ("plugin", "plugin_name", "source_plugin"):
                value = raw.get(key)
                if isinstance(value, str) and value:
                    return value
        override_manager = getattr(self, "_override_manager", None)
        if override_manager is not None:
            inferred = override_manager.infer_plugin_name(payload)
            if inferred:
                return inferred
        return None

    def _should_trace_payload(self, plugin: Optional[str], message_id: str) -> bool:
        cfg = self._debug_config
        if not cfg.trace_enabled:
            return False
        if cfg.trace_payload_ids:
            if not message_id:
                return False
            if not any(message_id.startswith(prefix) for prefix in cfg.trace_payload_ids):
                return False
        return True

    @staticmethod
    def _format_trace_points(points: Any) -> List[Tuple[Any, Any]]:
        formatted: List[Tuple[Any, Any]] = []
        if isinstance(points, list):
            for entry in points:
                if isinstance(entry, Mapping):
                    formatted.append((entry.get("x"), entry.get("y")))
                elif isinstance(entry, (tuple, list)) and len(entry) >= 2:
                    formatted.append((entry[0], entry[1]))
        return formatted

    def _log_legacy_trace(
        self,
        plugin: Optional[str],
        message_id: str,
        stage: str,
        info: Mapping[str, Any],
    ) -> None:
        if not self._should_trace_payload(plugin, message_id):
            return
        serialisable: Dict[str, Any] = {}
        for key, value in info.items():
            if key in {"points", "scaled_points"}:
                serialisable[key] = self._format_trace_points(value)
            else:
                serialisable[key] = value
        _CLIENT_LOGGER.debug(
            "trace plugin=%s id=%s stage=%s info=%s",
            plugin or "unknown",
            message_id,
            stage,
            serialisable,
        )

    def _trace_legacy_store_event(self, stage: str, item: LegacyItem) -> None:
        details: Dict[str, Any] = {"kind": item.kind}
        if item.kind == "vector":
            details["points"] = item.data.get("points")
        self._log_legacy_trace(item.plugin, item.item_id, stage, details)

    def _handle_legacy(self, payload: Dict[str, Any]) -> None:
        plugin_name = self._extract_plugin_name(payload)
        message_id = str(payload.get("id") or "")
        self._override_manager.apply(payload)
        inferred = self._override_manager.infer_plugin_name(payload)
        if inferred:
            payload["plugin"] = inferred
            plugin_name = inferred
        else:
            plugin_name = self._extract_plugin_name(payload)
        trace_enabled = self._should_trace_payload(plugin_name, message_id)
        if trace_enabled and str(payload.get("shape") or "").lower() == "vect":
            self._log_legacy_trace(plugin_name, message_id, "post_override", {"points": payload.get("vector")})
        trace_fn: Optional[TraceCallback] = None
        if trace_enabled:
            def trace_fn(stage: str, _payload: Mapping[str, Any], extra: Mapping[str, Any]) -> None:
                self._log_legacy_trace(plugin_name, message_id, stage, extra)

        if self._payload_model.ingest(payload, trace_fn=trace_fn):
            if self._cycle_payload_enabled:
                self._sync_cycle_items()
            self._mark_legacy_cache_dirty()
            self.update()

    def _purge_legacy(self) -> None:
        now = time.monotonic()
        if self._payload_model.purge_expired(now):
            if self._cycle_payload_enabled:
                self._sync_cycle_items()
            self._mark_legacy_cache_dirty()
            self.update()
        if not len(self._payload_model):
            self._group_log_pending_base.clear()
            self._group_log_pending_transform.clear()
            self._group_log_next_allowed.clear()
            self._logged_group_bounds.clear()
            self._logged_group_transforms.clear()

    def _paint_legacy(self, painter: QPainter) -> None:
        mapper = self._compute_legacy_mapper()
        state = self._viewport_state()
        context = RenderContext(
            width=max(self.width(), 0),
            height=max(self.height(), 0),
            mapper=mapper,
            dev_mode=self._dev_mode_enabled,
            debug_bounds=self._debug_config.group_bounds_outline,
            debug_vertices=self._debug_config.payload_vertex_markers,
            settings=RenderSettings(
                font_family=self._font_family,
                font_fallbacks=self._font_fallbacks,
                preset_point_size=lambda label, s=state, m=mapper: self._legacy_preset_point_size(label, s, m),
            ),
            grouping=self._grouping_adapter,
        )
        snapshot = PayloadSnapshot(items_count=len(list(self._payload_model.store.items())))
        self._render_pipeline.paint(painter, context, snapshot)
        payload_results = getattr(self._render_pipeline, "_last_payload_results", None)
        if payload_results:
            latest_base_payload = payload_results.get("latest_base_payload") or {}
            transform_candidates = payload_results.get("transform_candidates") or {}
            translations = payload_results.get("translations") or {}
            report_overlay_bounds = payload_results.get("report_overlay_bounds") or {}
            transform_by_group = payload_results.get("transform_by_group") or {}
            overlay_bounds_for_draw = payload_results.get("overlay_bounds_for_draw") or {}
            overlay_bounds_base = payload_results.get("overlay_bounds_base") or {}
            commands = payload_results.get("commands") or []
            trace_helper = self._group_trace_helper(report_overlay_bounds, commands)
            trace_helper()
            # Preserve existing behavior for log buffers/trace helper.
            self._apply_group_logging_payloads(
                latest_base_payload,
                transform_candidates,
                translations,
                report_overlay_bounds,
            )
            anchor_translations = payload_results.get("anchor_translation_by_group") or {}
            # Preserve debug helpers/logging behavior.
            self._maybe_collect_debug_helpers(
                commands,
                overlay_bounds_for_draw,
                overlay_bounds_base,
                transform_by_group,
                translations,
                report_overlay_bounds,
                mapper,
            )
            # Paint commands and collect offscreen/debug helpers.
            self._render_commands(
                painter,
                commands,
                anchor_translations,
                translations,
                overlay_bounds_for_draw,
                overlay_bounds_base,
                report_overlay_bounds,
                transform_by_group,
                mapper,
            )

    def _apply_group_logging_payloads(
        self,
        latest_base_payload: Mapping[Tuple[str, Optional[str]], Mapping[str, Any]],
        transform_candidates: Mapping[Tuple[str, Optional[str]], Tuple[str, Optional[str]]],
        translations: Mapping[Tuple[str, Optional[str]], Tuple[int, int]],
        report_overlay_bounds: Mapping[Tuple[str, Optional[str]], _OverlayBounds],
    ) -> None:
        """Apply group logging/cache updates using payload data returned by the render pipeline."""
        payload_results = getattr(self._render_pipeline, "_last_payload_results", {}) or {}
        cache_base_payloads = payload_results.get("cache_base_payloads") or {}
        cache_transform_payloads = payload_results.get("cache_transform_payloads") or {}
        active_group_keys: Set[Tuple[str, Optional[str]]] = payload_results.get("active_group_keys") or set()
        now_monotonic = self._monotonic_now() if hasattr(self, "_monotonic_now") else time.monotonic()

        for key, payload in latest_base_payload.items():
            bounds_tuple = payload.get("bounds_tuple")
            pending_payload = self._group_log_pending_base.get(key)
            pending_tuple = pending_payload.get("bounds_tuple") if pending_payload else None
            last_logged = self._logged_group_bounds.get(key)
            should_schedule = pending_payload is not None or last_logged != bounds_tuple
            if should_schedule:
                if pending_payload is None or pending_tuple != bounds_tuple:
                    self._group_log_pending_base[key] = dict(payload)
                    delay_target = (
                        now_monotonic
                        if self._payload_log_delay <= 0.0
                        else (now_monotonic or 0.0) + self._payload_log_delay
                    )
                    self._group_log_next_allowed[key] = delay_target
            else:
                self._group_log_pending_base.pop(key, None)
                self._group_log_next_allowed.pop(key, None)
            if not payload.get("has_transformed"):
                self._group_log_pending_transform.pop(key, None)

        for key, _labels in transform_candidates.items():
            report_bounds = report_overlay_bounds.get(key)
            if report_bounds is None or not report_bounds.is_valid():
                self._group_log_pending_transform.pop(key, None)
                continue
            transform_payload = cache_transform_payloads.get(key)
            if transform_payload is None:
                continue
            transform_tuple = (
                report_bounds.min_x,
                report_bounds.min_y,
                report_bounds.max_x,
                report_bounds.max_y,
            )
            pending_payload = self._group_log_pending_transform.get(key)
            pending_tuple = pending_payload.get("bounds_tuple") if pending_payload else None
            last_logged = self._logged_group_transforms.get(key)
            should_schedule = pending_payload is not None or last_logged != transform_tuple
            if not should_schedule:
                self._group_log_pending_transform.pop(key, None)
                continue
            if pending_payload is None or pending_tuple != transform_tuple:
                self._group_log_pending_transform[key] = {
                    **transform_payload,
                    "bounds_tuple": transform_tuple,
                }
                if key not in self._group_log_pending_base:
                    base_snapshot = latest_base_payload.get(key)
                    if base_snapshot is not None:
                        self._group_log_pending_base[key] = dict(base_snapshot)
                delay_target = (
                    now_monotonic
                    if self._payload_log_delay <= 0.0
                    else (now_monotonic or 0.0) + self._payload_log_delay
                )
                self._group_log_next_allowed[key] = delay_target

        self._update_group_cache_from_payloads(cache_base_payloads, cache_transform_payloads)
        self._flush_group_log_entries(active_group_keys)

    def _maybe_collect_debug_helpers(
        self,
        commands: Sequence[Any],
        overlay_bounds_for_draw: Mapping[Tuple[str, Optional[str]], _OverlayBounds],
        overlay_bounds_base: Mapping[Tuple[str, Optional[str]], _OverlayBounds],
        transform_by_group: Mapping[Tuple[str, Optional[str]], Optional[GroupTransform]],
        translations: Mapping[Tuple[str, Optional[str]], Tuple[int, int]],
        report_overlay_bounds: Mapping[Tuple[str, Optional[str]], _OverlayBounds],
        mapper: LegacyMapper,
    ) -> None:
        collect_debug_helpers = self._dev_mode_enabled and self._debug_config.group_bounds_outline
        if collect_debug_helpers:
            final_bounds_map = overlay_bounds_for_draw if overlay_bounds_for_draw else overlay_bounds_base
            self._debug_group_bounds_final = self._clone_overlay_bounds_map(final_bounds_map)
            self._debug_group_state = self._build_group_debug_state(
                self._debug_group_bounds_final,
                transform_by_group,
                translations,
                canonical_bounds=report_overlay_bounds,
            )
        else:
            self._debug_group_bounds_final = {}
            self._debug_group_state = {}

    def _render_commands(
        self,
        painter: QPainter,
        commands: Sequence[Any],
        anchor_translation_by_group: Mapping[Tuple[str, Optional[str]], Tuple[float, float]],
        translations: Mapping[Tuple[str, Optional[str]], Tuple[int, int]],
        overlay_bounds_for_draw: Mapping[Tuple[str, Optional[str]], _OverlayBounds],
        overlay_bounds_base: Mapping[Tuple[str, Optional[str]], _OverlayBounds],
        report_overlay_bounds: Mapping[Tuple[str, Optional[str]], _OverlayBounds],
        transform_by_group: Mapping[Tuple[str, Optional[str]], Optional[GroupTransform]],
        mapper: LegacyMapper,
    ) -> None:
        collect_debug_helpers = self._dev_mode_enabled and self._debug_config.group_bounds_outline
        window_width = max(self.width(), 0)
        window_height = max(self.height(), 0)
        draw_vertex_markers = self._dev_mode_enabled and self._debug_config.payload_vertex_markers
        vertex_points: List[Tuple[int, int]] = []
        for command in commands:
            key_tuple = command.group_key.as_tuple()
            translation_x, translation_y = anchor_translation_by_group.get(key_tuple, (0.0, 0.0))
            nudge_x, nudge_y = translations.get(key_tuple, (0, 0))
            justification_dx = getattr(command, "justification_dx", 0.0)
            payload_offset_x = translation_x + justification_dx + nudge_x
            payload_offset_y = translation_y + nudge_y
            self._log_offscreen_payload(command, payload_offset_x, payload_offset_y, window_width, window_height)
            command.paint(self, painter, payload_offset_x, payload_offset_y)
            if draw_vertex_markers and command.bounds:
                left, top, right, bottom = command.bounds
                group_corners = [
                    (left, top),
                    (right, top),
                    (left, bottom),
                    (right, bottom),
                ]
                trace_vertices = self._should_trace_payload(
                    getattr(command.legacy_item, "plugin", None),
                    command.legacy_item.item_id,
                )
                for px, py in group_corners:
                    adjusted_x = int(round(float(px) + payload_offset_x))
                    adjusted_y = int(round(float(py) + payload_offset_y))
                    vertex_points.append((adjusted_x, adjusted_y))
                    if trace_vertices:
                        self._log_legacy_trace(
                            command.legacy_item.plugin,
                            command.legacy_item.item_id,
                            "debug:payload_vertex",
                            {
                                "pixel_x": adjusted_x,
                                "pixel_y": adjusted_y,
                                "payload_kind": getattr(command.legacy_item, "kind", "unknown"),
                            },
                        )
        if draw_vertex_markers and vertex_points:
            self._draw_payload_vertex_markers(painter, vertex_points)
        if collect_debug_helpers:
            self._draw_group_debug_helpers(painter, mapper)

    def _build_legacy_commands_for_pass(
        self,
        mapper: LegacyMapper,
        overlay_bounds_hint: Optional[Dict[Tuple[str, Optional[str]], _OverlayBounds]],
        collect_only: bool = False,
    ) -> Tuple[
        List[_LegacyPaintCommand],
        Dict[Tuple[str, Optional[str]], _ScreenBounds],
        Dict[Tuple[str, Optional[str]], _OverlayBounds],
        Dict[Tuple[str, Optional[str]], Tuple[float, float]],
        Dict[Tuple[str, Optional[str]], Optional[GroupTransform]],
    ]:
        commands: List[_LegacyPaintCommand] = []
        bounds_by_group: Dict[Tuple[str, Optional[str]], _ScreenBounds] = {}
        overlay_bounds_by_group: Dict[Tuple[str, Optional[str]], _OverlayBounds] = {}
        effective_anchor_by_group: Dict[Tuple[str, Optional[str]], Tuple[float, float]] = {}
        transform_by_group: Dict[Tuple[str, Optional[str]], Optional[GroupTransform]] = {}
        for item_id, legacy_item in self._payload_model.store.items():
            group_key = self._group_coordinator.resolve_group_key(
                item_id,
                legacy_item.plugin,
                self._override_manager,
            )
            group_transform = self._grouping_helper.get_transform(group_key)
            transform_by_group[group_key.as_tuple()] = group_transform
            has_explicit_offset = False
            if group_transform is not None:
                dx = getattr(group_transform, "dx", 0.0)
                dy = getattr(group_transform, "dy", 0.0)
                has_explicit_offset = bool(dx) or bool(dy)
            overlay_hint = None
            if overlay_bounds_hint and not has_explicit_offset:
                overlay_hint = overlay_bounds_hint.get(group_key.as_tuple())
            if legacy_item.kind == "message":
                command = self._build_message_command(
                    legacy_item,
                    mapper,
                    group_key,
                    group_transform,
                    overlay_hint,
                    collect_only=collect_only,
                )
            elif legacy_item.kind == "rect":
                command = self._build_rect_command(
                    legacy_item,
                    mapper,
                    group_key,
                    group_transform,
                    overlay_hint,
                    collect_only=collect_only,
                )
            elif legacy_item.kind == "vector":
                command = self._build_vector_command(
                    legacy_item,
                    mapper,
                    group_key,
                    group_transform,
                    overlay_hint,
                    collect_only=collect_only,
                )
            else:
                command = None
            if command is None:
                continue
            if not collect_only:
                commands.append(command)
                if command.bounds:
                    bounds = bounds_by_group.setdefault(command.group_key.as_tuple(), _ScreenBounds())
                    bounds.include_rect(*command.bounds)
                if command.effective_anchor is not None:
                    effective_anchor_by_group[command.group_key.as_tuple()] = command.effective_anchor
            if command.overlay_bounds:
                overlay_bounds = overlay_bounds_by_group.setdefault(command.group_key.as_tuple(), _OverlayBounds())
                overlay_bounds.include_rect(*command.overlay_bounds)
            if collect_only:
                continue
        return commands, bounds_by_group, overlay_bounds_by_group, effective_anchor_by_group, transform_by_group

    def _prepare_anchor_translations(
        self,
        mapper: LegacyMapper,
        bounds_by_group: Mapping[Tuple[str, Optional[str]], _ScreenBounds],
        overlay_bounds_by_group: Mapping[Tuple[str, Optional[str]], _OverlayBounds],
        effective_anchor_by_group: Mapping[Tuple[str, Optional[str]], Tuple[float, float]],
        transform_by_group: Mapping[Tuple[str, Optional[str]], Optional[GroupTransform]],
    ) -> Tuple[Dict[Tuple[str, Optional[str]], Tuple[float, float]], Dict[Tuple[str, Optional[str]], _ScreenBounds]]:
        cloned_bounds: Dict[Tuple[str, Optional[str]], _ScreenBounds] = {}
        for key, bounds in bounds_by_group.items():
            if bounds is None or not bounds.is_valid():
                continue
            clone = _ScreenBounds()
            clone.min_x = bounds.min_x
            clone.max_x = bounds.max_x
            clone.min_y = bounds.min_y
            clone.max_y = bounds.max_y
            cloned_bounds[key] = clone
        translations: Dict[Tuple[str, Optional[str]], Tuple[float, float]] = {}
        base_scale = mapper.transform.scale
        if not math.isfinite(base_scale) or math.isclose(base_scale, 0.0, rel_tol=1e-9, abs_tol=1e-9):
            base_scale = 1.0
        for key in bounds_by_group:
            translation_overlay_x: Optional[float]
            translation_overlay_y: Optional[float]
            bounds = overlay_bounds_by_group.get(key)
            token = None
            transform = transform_by_group.get(key)
            if transform is not None:
                token = getattr(transform, "anchor_token", None)
            translation_overlay_x = translation_overlay_y = None
            if bounds is not None and bounds.is_valid() and token:
                user_anchor = self._anchor_from_overlay_bounds(bounds, token)
                if user_anchor is not None:
                    translation_overlay_x = bounds.min_x - user_anchor[0]
                    translation_overlay_y = bounds.min_y - user_anchor[1]
            if translation_overlay_x is None or translation_overlay_y is None:
                continue
            if not (math.isfinite(translation_overlay_x) and math.isfinite(translation_overlay_y)):
                continue
            translation_px_x = translation_overlay_x * base_scale
            translation_px_y = translation_overlay_y * base_scale
            translations[key] = (translation_px_x, translation_px_y)
            clone = cloned_bounds.get(key)
            if clone is not None:
                clone.translate(translation_px_x, translation_px_y)
        return translations, cloned_bounds

    def _apply_payload_justification(
        self,
        commands: Sequence[_LegacyPaintCommand],
        transform_by_group: Mapping[Tuple[str, Optional[str]], Optional[GroupTransform]],
        anchor_translation_by_group: Mapping[Tuple[str, Optional[str]], Tuple[float, float]],
        translated_bounds_by_group: Dict[Tuple[str, Optional[str]], _ScreenBounds],
        overlay_bounds_by_group: Dict[Tuple[str, Optional[str]], _OverlayBounds],
        base_overlay_bounds: Mapping[Tuple[str, Optional[str]], _OverlayBounds],
        base_scale: float,
    ) -> Dict[Tuple[str, Optional[str]], _ScreenBounds]:
        command_contexts: List[CommandContext] = []
        for command in commands:
            command.justification_dx = 0.0
            bounds = command.bounds
            if not bounds:
                continue
            key = command.group_key.as_tuple()
            transform = transform_by_group.get(key)
            justification = (getattr(transform, "payload_justification", "left") or "left").strip().lower()
            suffix = command.group_key.suffix
            plugin = getattr(command.legacy_item, "plugin", None)
            item_id = command.legacy_item.item_id
            command_contexts.append(
                CommandContext(
                    identifier=id(command),
                    key=key,
                    bounds=(float(bounds[0]), float(bounds[1]), float(bounds[2]), float(bounds[3])),
                    raw_min_x=command.raw_min_x,
                    right_just_multiplier=getattr(command, "right_just_multiplier", 0),
                    justification=justification,
                    suffix=suffix,
                    plugin=plugin,
                    item_id=item_id,
                )
            )

        def _trace(plugin: Optional[str], item_id: str, stage: str, details: Dict[str, float]) -> None:
            self._log_legacy_trace(plugin, item_id, stage, details)

        base_bounds_map: Dict[Tuple[str, Optional[str]], Tuple[float, float, float, float]] = {}
        for key, bounds in base_overlay_bounds.items():
            if bounds is None or not bounds.is_valid():
                continue
            base_bounds_map[key] = (bounds.min_x, bounds.min_y, bounds.max_x, bounds.max_y)
        overlay_bounds_map: Dict[Tuple[str, Optional[str]], Tuple[float, float, float, float]] = {}
        for key, bounds in overlay_bounds_by_group.items():
            if bounds is None or not bounds.is_valid():
                continue
            overlay_bounds_map[key] = (bounds.min_x, bounds.min_y, bounds.max_x, bounds.max_y)
        baseline_bounds = build_baseline_bounds(base_bounds_map, overlay_bounds_map)

        offset_map = compute_justification_offsets(
            command_contexts,
            transform_by_group,
            baseline_bounds,
            base_scale,
            trace_fn=_trace,
        )
        if not offset_map:
            return translated_bounds_by_group

        updated_bounds: Dict[Tuple[str, Optional[str]], _ScreenBounds] = {}
        for command in commands:
            bounds = command.bounds
            if not bounds:
                continue
            key = command.group_key.as_tuple()
            command.justification_dx = offset_map.get(id(command), 0.0)
            translation_x, translation_y = anchor_translation_by_group.get(key, (0.0, 0.0))
            offset_x = translation_x + command.justification_dx
            offset_y = translation_y
            clone = updated_bounds.setdefault(key, _ScreenBounds())
            clone.include_rect(
                float(bounds[0]) + offset_x,
                float(bounds[1]) + offset_y,
                float(bounds[2]) + offset_x,
                float(bounds[3]) + offset_y,
            )
        for key, original in translated_bounds_by_group.items():
            if key in updated_bounds:
                continue
            clone = _ScreenBounds()
            clone.min_x = original.min_x
            clone.max_x = original.max_x
            clone.min_y = original.min_y
            clone.max_y = original.max_y
            updated_bounds[key] = clone
        return updated_bounds

    def _rebuild_translated_bounds(
        self,
        commands: Sequence[_LegacyPaintCommand],
        anchor_translation_by_group: Mapping[Tuple[str, Optional[str]], Tuple[float, float]],
        baseline_bounds: Mapping[Tuple[str, Optional[str]], _ScreenBounds],
    ) -> Dict[Tuple[str, Optional[str]], _ScreenBounds]:
        updated: Dict[Tuple[str, Optional[str]], _ScreenBounds] = {}
        for command in commands:
            bounds = command.bounds
            if not bounds:
                continue
            key = command.group_key.as_tuple()
            translation_x, translation_y = anchor_translation_by_group.get(key, (0.0, 0.0))
            justification_dx = getattr(command, "justification_dx", 0.0)
            offset_x = translation_x
            offset_y = translation_y
            if justification_dx:
                offset_x += justification_dx
            clone = updated.setdefault(key, _ScreenBounds())
            clone.include_rect(
                float(bounds[0]) + offset_x,
                float(bounds[1]) + offset_y,
                float(bounds[2]) + offset_x,
                float(bounds[3]) + offset_y,
            )
        for key, original in baseline_bounds.items():
            if key in updated:
                continue
            clone = _ScreenBounds()
            clone.min_x = original.min_x
            clone.max_x = original.max_x
            clone.min_y = original.min_y
            clone.max_y = original.max_y
            updated[key] = clone
        return updated

    @staticmethod
    def _anchor_from_overlay_bounds(bounds: _OverlayBounds, token: Optional[str]) -> Optional[Tuple[float, float]]:
        if bounds is None or not bounds.is_valid():
            return None
        token = (token or "nw").strip().lower()
        min_x = bounds.min_x
        max_x = bounds.max_x
        min_y = bounds.min_y
        max_y = bounds.max_y
        mid_x = (min_x + max_x) / 2.0
        mid_y = (min_y + max_y) / 2.0
        if token in {"nw"}:
            return min_x, min_y
        if token in {"ne"}:
            return max_x, min_y
        if token in {"left", "west"}:
            return min_x, mid_y
        if token in {"right", "east"}:
            return max_x, mid_y
        if token in {"sw"}:
            return min_x, max_y
        if token in {"se"}:
            return max_x, max_y
        if token == "top":
            return mid_x, min_y
        if token == "bottom":
            return mid_x, max_y
        if token == "center":
            return mid_x, mid_y
        # fallback to base (nw)
        return min_x, min_y

    @staticmethod
    def _right_justification_delta(
        transform: Optional[GroupTransform],
        payload_min_x: Optional[float],
    ) -> float:
        if transform is None or payload_min_x is None:
            return 0.0
        justification = (getattr(transform, "payload_justification", "left") or "left").strip().lower()
        if justification != "right":
            return 0.0
        reference = getattr(transform, "bounds_min_x", None)
        try:
            reference_value = float(reference)
            payload_value = float(payload_min_x)
        except (TypeError, ValueError):
            return 0.0
        if not (math.isfinite(reference_value) and math.isfinite(payload_value)):
            return 0.0
        delta = payload_value - reference_value
        if math.isclose(delta, 0.0, rel_tol=1e-9, abs_tol=1e-9):
            return 0.0
        return delta

    def _legacy_preset_point_size(self, preset: str, state: ViewportState, mapper: LegacyMapper) -> float:
        """Return the scaled font size for a legacy preset relative to normal."""
        return util_legacy_preset_point_size(
            preset,
            state,
            mapper,
            self._font_scale_diag,
            self._font_min_point,
            self._font_max_point,
        )

    def _measure_text(self, text: str, point_size: float, font_family: Optional[str] = None) -> Tuple[int, int, int]:
        if self._text_measurer is not None:
            measured = self._text_measurer(text, point_size, font_family or self._font_family)
            return measured.width, measured.ascent, measured.descent
        metrics_font = QFont(font_family or self._font_family)
        self._apply_font_fallbacks(metrics_font)
        metrics_font.setPointSizeF(point_size)
        metrics_font.setWeight(QFont.Weight.Normal)
        metrics = QFontMetrics(metrics_font)
        return metrics.horizontalAdvance(text), metrics.ascent(), metrics.descent()

    def set_text_measurer(self, measurer: Optional[Callable[[str, float, str], _MeasuredText]]) -> None:
        self._text_measurer = measurer

    def _build_message_command(
        self,
        legacy_item: LegacyItem,
        mapper: LegacyMapper,
        group_key: GroupKey,
        group_transform: Optional[GroupTransform],
        overlay_bounds_hint: Optional[_OverlayBounds],
        collect_only: bool = False,
    ) -> Optional[_MessagePaintCommand]:
        item = legacy_item.data
        item_id = legacy_item.item_id
        plugin_name = legacy_item.plugin
        trace_enabled = self._should_trace_payload(plugin_name, item_id)
        color = QColor(str(item.get("color", "white")))
        size = str(item.get("size", "normal")).lower()
        state = self._viewport_state()
        scaled_point_size = self._legacy_preset_point_size(size, state, mapper)
        offset_x, offset_y = self._group_offsets(group_transform)
        group_ctx = build_group_context(
            mapper,
            state,
            group_transform,
            overlay_bounds_hint,
            offset_x,
            offset_y,
            group_anchor_point=self._group_anchor_point,
            group_base_point=self._group_base_point,
        )
        fill = group_ctx.fill
        transform_context = group_ctx.transform_context
        scale = group_ctx.scale
        base_offset_x = group_ctx.base_offset_x
        base_offset_y = group_ctx.base_offset_y
        selected_anchor = group_ctx.selected_anchor
        base_anchor_point = group_ctx.base_anchor_point
        anchor_for_transform = group_ctx.anchor_for_transform
        base_translation_dx = group_ctx.base_translation_dx
        base_translation_dy = group_ctx.base_translation_dy
        transform_meta = item.get("__mo_transform__")
        self._debug_legacy_point_size = scaled_point_size
        raw_left = float(item.get("x", 0))
        raw_top = float(item.get("y", 0))
        (
            adjusted_left,
            adjusted_top,
            base_left_logical,
            base_top_logical,
            effective_anchor,
            translation_dx,
            translation_dy,
        ) = self._compute_message_transform(
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
            trace_enabled,
            collect_only,
        )
        text = str(item.get("text", ""))
        text_width, ascent, descent = self._measure_text(text, scaled_point_size, self._font_family)
        x = int(round(fill.screen_x(adjusted_left)))
        payload_point_y = int(round(fill.screen_y(adjusted_top)))
        baseline = int(round(payload_point_y + ascent))
        center_x = x + text_width // 2
        top = baseline - ascent
        bottom = baseline + descent
        center_y = int(round((top + bottom) / 2.0))
        bounds = (x, top, x + text_width, bottom)
        overlay_bounds: Optional[Tuple[float, float, float, float]] = None
        base_overlay_bounds: Optional[Tuple[float, float, float, float]] = None
        if scale > 0.0:
            overlay_left = (bounds[0] - base_offset_x) / scale
            overlay_top = (bounds[1] - base_offset_y) / scale
            overlay_right = (bounds[2] - base_offset_x) / scale
            overlay_bottom = (bounds[3] - base_offset_y) / scale
            overlay_bounds = (overlay_left, overlay_top, overlay_right, overlay_bottom)
            base_x = int(round(fill.screen_x(base_left_logical)))
            base_base_y = int(round(fill.screen_y(base_top_logical)))
            base_baseline = int(round(base_base_y + ascent))
            base_top = base_baseline - ascent
            base_bottom = base_baseline + descent
            base_bounds = (base_x, base_top, base_x + text_width, base_bottom)
            base_overlay_left = (base_bounds[0] - base_offset_x) / scale
            base_overlay_top = (base_bounds[1] - base_offset_y) / scale
            base_overlay_right = (base_bounds[2] - base_offset_x) / scale
            base_overlay_bottom = (base_bounds[3] - base_offset_y) / scale
            base_overlay_bounds = (
                base_overlay_left,
                base_overlay_top,
                base_overlay_right,
                base_overlay_bottom,
            )
        if trace_enabled and not collect_only:
            self._log_legacy_trace(
                plugin_name,
                item_id,
                "paint:message_output",
                {
                    "adjusted_x": adjusted_left,
                    "adjusted_y": adjusted_top,
                    "pixel_x": x,
                    "baseline": baseline,
                    "text_width": text_width,
                    "font_size": scaled_point_size,
                    "mode": mapper.transform.mode.value,
                },
            )
        trace_fn = None
        if trace_enabled and not collect_only:
            def trace_fn(stage: str, details: Mapping[str, Any]) -> None:
                self._log_legacy_trace(plugin_name, item_id, stage, details)
        command = _MessagePaintCommand(
            group_key=group_key,
            group_transform=group_transform,
            legacy_item=legacy_item,
            bounds=bounds,
            overlay_bounds=overlay_bounds,
            effective_anchor=effective_anchor,
            debug_log=None,
            text=text,
            color=color,
            point_size=scaled_point_size,
            x=x,
            baseline=baseline,
            text_width=text_width,
            ascent=ascent,
            descent=descent,
            cycle_anchor=(center_x, center_y),
            trace_fn=trace_fn,
            base_overlay_bounds=base_overlay_bounds,
            debug_vertices=[(x, payload_point_y)],
            raw_min_x=raw_left,
            right_just_multiplier=2,
        )
        return command

    def _build_rect_command(
        self,
        legacy_item: LegacyItem,
        mapper: LegacyMapper,
        group_key: GroupKey,
        group_transform: Optional[GroupTransform],
        overlay_bounds_hint: Optional[_OverlayBounds],
        collect_only: bool = False,
    ) -> Optional[_RectPaintCommand]:
        item = legacy_item.data
        item_id = legacy_item.item_id
        plugin_name = legacy_item.plugin
        border_spec = str(item.get("color", "white"))
        fill_spec = str(item.get("fill", "#00000000"))

        if not border_spec or border_spec.lower() == "none":
            pen = QPen(Qt.PenStyle.NoPen)
        else:
            border_color = QColor(border_spec)
            if not border_color.isValid():
                border_color = QColor("white")
            pen = QPen(border_color)
            pen.setWidth(self._line_width("legacy_rect"))

        if not fill_spec or fill_spec.lower() == "none":
            brush = QBrush(Qt.BrushStyle.NoBrush)
        else:
            fill_color = QColor(fill_spec)
            if not fill_color.isValid():
                fill_color = QColor("#00000000")
            brush = QBrush(fill_color)

        state = self._viewport_state()
        offset_x, offset_y = self._group_offsets(group_transform)
        group_ctx = build_group_context(
            mapper,
            state,
            group_transform,
            overlay_bounds_hint,
            offset_x,
            offset_y,
            group_anchor_point=self._group_anchor_point,
            group_base_point=self._group_base_point,
        )
        fill = group_ctx.fill
        transform_context = group_ctx.transform_context
        scale = group_ctx.scale
        selected_anchor = group_ctx.selected_anchor
        base_anchor_point = group_ctx.base_anchor_point
        anchor_for_transform = group_ctx.anchor_for_transform
        base_translation_dx = group_ctx.base_translation_dx
        base_translation_dy = group_ctx.base_translation_dy
        transform_meta = item.get("__mo_transform__")
        trace_enabled = self._should_trace_payload(plugin_name, item_id)
        raw_x = float(item.get("x", 0))
        raw_y = float(item.get("y", 0))
        raw_w = float(item.get("w", 0))
        raw_h = float(item.get("h", 0))
        transformed_overlay, base_overlay_points, reference_overlay_bounds, effective_anchor = self._compute_rect_transform(
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
            trace_enabled,
            collect_only,
        )
        xs_overlay = [pt[0] for pt in transformed_overlay]
        ys_overlay = [pt[1] for pt in transformed_overlay]
        min_x_overlay = min(xs_overlay)
        max_x_overlay = max(xs_overlay)
        min_y_overlay = min(ys_overlay)
        max_y_overlay = max(ys_overlay)
        x = int(round(fill.screen_x(min_x_overlay)))
        y = int(round(fill.screen_y(min_y_overlay)))
        w = max(1, int(round(max(0.0, max_x_overlay - min_x_overlay) * scale)))
        h = max(1, int(round(max(0.0, max_y_overlay - min_y_overlay) * scale)))
        center_x = x + w // 2
        center_y = y + h // 2
        bounds = (x, y, x + w, y + h)
        overlay_bounds = (min_x_overlay, min_y_overlay, max_x_overlay, max_y_overlay)
        base_overlay_bounds: Optional[Tuple[float, float, float, float]] = None
        if base_overlay_points:
            base_xs = [pt[0] for pt in base_overlay_points]
            base_ys = [pt[1] for pt in base_overlay_points]
            base_min_x = min(base_xs)
            base_max_x = max(base_xs)
            base_min_y = min(base_ys)
            base_max_y = max(base_ys)
            base_overlay_bounds = (base_min_x, base_min_y, base_max_x, base_max_y)
        command = _RectPaintCommand(
            group_key=group_key,
            group_transform=group_transform,
            legacy_item=legacy_item,
            bounds=bounds,
            overlay_bounds=overlay_bounds,
            effective_anchor=effective_anchor,
            debug_log=None,
            pen=pen,
            brush=brush,
            x=x,
            y=y,
            width=w,
            height=h,
            cycle_anchor=(center_x, center_y),
            base_overlay_bounds=base_overlay_bounds,
            reference_overlay_bounds=reference_overlay_bounds,
            debug_vertices=[
                (x, y),
                (x + w, y),
                (x, y + h),
                (x + w, y + h),
            ],
            raw_min_x=raw_x,
            right_just_multiplier=2,
        )
        if trace_enabled and not collect_only:
            self._log_legacy_trace(
                plugin_name,
                item_id,
                "paint:rect_output",
                {
                    "adjusted_x": min_x_overlay,
                    "adjusted_y": min_y_overlay,
                    "adjusted_w": max_x_overlay - min_x_overlay,
                    "adjusted_h": max_y_overlay - min_y_overlay,
                    "pixel_x": x,
                    "pixel_y": y,
                    "pixel_w": w,
                    "pixel_h": h,
                    "mode": mapper.transform.mode.value,
                },
            )
        return command

    def _build_vector_command(
        self,
        legacy_item: LegacyItem,
        mapper: LegacyMapper,
        group_key: GroupKey,
        group_transform: Optional[GroupTransform],
        overlay_bounds_hint: Optional[_OverlayBounds],
        collect_only: bool = False,
    ) -> Optional[_VectorPaintCommand]:
        item_id = legacy_item.item_id
        item = legacy_item.data
        plugin_name = legacy_item.plugin
        trace_enabled = self._should_trace_payload(plugin_name, item_id)
        state = self._viewport_state()
        offset_x, offset_y = self._group_offsets(group_transform)
        group_ctx = build_group_context(
            mapper,
            state,
            group_transform,
            overlay_bounds_hint,
            offset_x,
            offset_y,
            group_anchor_point=self._group_anchor_point,
            group_base_point=self._group_base_point,
        )
        fill = group_ctx.fill
        transform_context = group_ctx.transform_context
        scale = group_ctx.scale
        selected_anchor = group_ctx.selected_anchor
        base_anchor_point = group_ctx.base_anchor_point
        anchor_for_transform = group_ctx.anchor_for_transform
        base_translation_dx = group_ctx.base_translation_dx
        base_translation_dy = group_ctx.base_translation_dy
        raw_points = item.get("points") or []
        transform_meta = item.get("__mo_transform__")
        (
            vector_payload,
            screen_points,
            overlay_bounds,
            base_overlay_bounds,
            effective_anchor,
            raw_min_x,
            trace_fn,
        ) = self._compute_vector_transform(
            plugin_name,
            item_id,
            fill,
            transform_context,
            transform_meta,
            mapper,
            group_transform,
            item,
            raw_points,
            offset_x,
            offset_y,
            selected_anchor,
            base_anchor_point,
            anchor_for_transform,
            base_translation_dx,
            base_translation_dy,
            trace_enabled,
            collect_only,
        )
        if vector_payload is None:
            return None
        bounds: Optional[Tuple[int, int, int, int]]
        cycle_anchor: Optional[Tuple[int, int]]
        if screen_points:
            xs = [pt[0] for pt in screen_points]
            ys = [pt[1] for pt in screen_points]
            bounds = (min(xs), min(ys), max(xs), max(ys))
            cycle_anchor = (
                int(round((min(xs) + max(xs)) / 2.0)),
                int(round((min(ys) + max(ys)) / 2.0)),
            )
        else:
            bounds = None
            cycle_anchor = None
        command = _VectorPaintCommand(
            group_key=group_key,
            group_transform=group_transform,
            legacy_item=legacy_item,
            bounds=bounds,
            overlay_bounds=overlay_bounds,
            effective_anchor=effective_anchor,
            debug_log=None,
            vector_payload=vector_payload,
            scale=scale,
            base_offset_x=fill.base_offset_x,
            base_offset_y=fill.base_offset_y,
            trace_fn=trace_fn,
            cycle_anchor=cycle_anchor,
            base_overlay_bounds=base_overlay_bounds,
            debug_vertices=tuple(screen_points),
            raw_min_x=raw_min_x,
            right_just_multiplier=2 if raw_min_x is not None else 0,
        )
        return command

    def _compute_group_nudges(
        self,
        bounds_by_group: Mapping[Tuple[str, Optional[str]], _ScreenBounds],
    ) -> Dict[Tuple[str, Optional[str]], Tuple[int, int]]:
        return self._group_coordinator.compute_group_nudges(
            bounds_by_group,
            self.width(),
            self.height(),
            self._payload_nudge_enabled,
            self._payload_nudge_gutter,
        )

    def _collect_base_overlay_bounds(
        self,
        commands: Sequence[_LegacyPaintCommand],
    ) -> Dict[Tuple[str, Optional[str]], _OverlayBounds]:
        bounds_map: Dict[Tuple[str, Optional[str]], _OverlayBounds] = {}
        if not commands:
            return bounds_map
        for command in commands:
            if not command.base_overlay_bounds:
                continue
            bounds = bounds_map.setdefault(command.group_key.as_tuple(), _OverlayBounds())
            bounds.include_rect(*command.base_overlay_bounds)
        return bounds_map

    def _build_group_debug_state(
        self,
        final_bounds: Mapping[Tuple[str, Optional[str]], _OverlayBounds],
        transform_by_group: Mapping[Tuple[str, Optional[str]], Optional[GroupTransform]],
        translations: Mapping[Tuple[str, Optional[str]], Tuple[int, int]],
        canonical_bounds: Optional[Mapping[Tuple[str, Optional[str]], _OverlayBounds]] = None,
    ) -> Dict[Tuple[str, Optional[str]], _GroupDebugState]:
        state: Dict[Tuple[str, Optional[str]], _GroupDebugState] = {}
        for key, bounds in final_bounds.items():
            if bounds is None or not bounds.is_valid():
                continue
            transform = transform_by_group.get(key)
            use_transformed = self._has_user_group_transform(transform)
            anchor_token = (getattr(transform, "anchor_token", "nw") or "nw").strip().lower()
            justification = (getattr(transform, "payload_justification", "left") or "left").strip().lower()
            anchor_point = self._anchor_from_overlay_bounds(bounds, anchor_token)
            if anchor_point is None:
                anchor_point = (bounds.min_x, bounds.min_y)
            anchor_logical = anchor_point
            if canonical_bounds is not None:
                logical_bounds = canonical_bounds.get(key)
                if logical_bounds is not None and logical_bounds.is_valid():
                    logical_anchor = self._anchor_from_overlay_bounds(logical_bounds, anchor_token)
                    if logical_anchor is not None:
                        anchor_logical = logical_anchor
            nudged = bool(translations.get(key))
            state[key] = _GroupDebugState(
                anchor_token=anchor_token or "nw",
                justification=justification or "left",
                use_transformed=use_transformed,
                anchor_point=anchor_point,
                anchor_logical=anchor_logical,
                nudged=nudged,
            )
        return state

    def _has_user_group_transform(self, transform: Optional[GroupTransform]) -> bool:
        if transform is None:
            return False
        anchor = (getattr(transform, "anchor_token", "nw") or "nw").strip().lower()
        justification = (getattr(transform, "payload_justification", "left") or "left").strip().lower()
        if anchor and anchor != "nw":
            return True
        if justification and justification not in {"", "left"}:
            return True
        return False

    def _group_trace_helper(
        self,
        bounds_map: Mapping[Tuple[str, Optional[str]], _OverlayBounds],
        commands: Sequence[_LegacyPaintCommand],
    ) -> Callable[[], None]:
        def _emit() -> None:
            for key, bounds in bounds_map.items():
                if bounds is None or not bounds.is_valid():
                    continue
                sample_command = next((cmd for cmd in commands if cmd.group_key.as_tuple() == key), None)
                if sample_command is None:
                    continue
                legacy_item = sample_command.legacy_item
                if not self._should_trace_payload(legacy_item.plugin, legacy_item.item_id):
                    continue
                self._log_legacy_trace(
                    legacy_item.plugin,
                    legacy_item.item_id,
                    "group:aggregate_bounds",
                    {
                        "group_key": key,
                        "trans_min_x": bounds.min_x,
                        "trans_max_x": bounds.max_x,
                        "trans_min_y": bounds.min_y,
                        "trans_max_y": bounds.max_y,
                    },
                )

        return _emit

    def _update_group_cache_from_payloads(
        self,
        base_payloads: Mapping[Tuple[str, Optional[str]], Mapping[str, Any]],
        transform_payloads: Mapping[Tuple[str, Optional[str]], Mapping[str, Any]],
    ) -> None:
        self._group_coordinator.update_cache_from_payloads(
            base_payloads=base_payloads,
            transform_payloads=transform_payloads,
        )

    def _draw_payload_vertex_markers(self, painter: QPainter, points: Sequence[Tuple[int, int]]) -> None:
        if not points:
            return
        painter.save()
        pen = QPen(QColor("#ff3333"))
        pen.setWidth(max(1, self._line_width("vector_marker")))
        painter.setPen(pen)
        span = 3
        for x, y in points:
            painter.drawLine(x - span, y - span, x + span, y + span)
            painter.drawLine(x - span, y + span, x + span, y - span)
        painter.restore()

    def _draw_group_debug_helpers(self, painter: QPainter, mapper: LegacyMapper) -> None:
        if not self._debug_group_state:
            return
        painter.save()
        outline_pen = QPen(QColor("#ffa500"))
        outline_pen.setWidth(self._line_width("group_outline"))
        outline_pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(outline_pen)
        text_pen = QPen(QColor("#ffffff"))
        font = QFont(self._font_family)
        self._apply_font_fallbacks(font)
        font.setWeight(QFont.Weight.Normal)
        font.setPointSizeF(max(font.pointSizeF(), 9.0))
        painter.setFont(font)
        for key, debug_state in self._debug_group_state.items():
            if self._debug_group_filter and key != self._debug_group_filter:
                continue
            bounds = self._debug_group_bounds_final.get(key)
            if bounds is None or not bounds.is_valid():
                continue
            rect = self._overlay_bounds_to_rect(bounds, mapper)
            painter.setPen(outline_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(rect)
            anchor_point = debug_state.anchor_point
            if anchor_point is None:
                continue
            anchor_pixel = self._overlay_point_to_screen(anchor_point, mapper)
            painter.setBrush(QBrush(QColor("#ffffff")))
            painter.drawEllipse(QPoint(anchor_pixel[0], anchor_pixel[1]), 5, 5)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(text_pen)
            anchor_label_point = debug_state.anchor_logical or anchor_point
            label = f"{debug_state.anchor_token.upper()} ({anchor_label_point[0]:.1f}, {anchor_label_point[1]:.1f})"
            if debug_state.nudged:
                label += " nudged"
            metrics = painter.fontMetrics()
            label_pos = self._anchor_label_position(
                debug_state.anchor_token,
                anchor_pixel,
                metrics.horizontalAdvance(label),
                metrics.ascent(),
                metrics.descent(),
                max(self.width(), 0),
                max(self.height(), 0),
            )
            painter.drawText(label_pos[0], label_pos[1], label)
            painter.setPen(outline_pen)
        painter.restore()

    def _flush_group_log_entries(self, active_keys: Set[Tuple[str, Optional[str]]]) -> None:
        now = time.monotonic()
        for key in list(self._group_log_pending_base.keys()):
            next_allowed = self._group_log_next_allowed.get(key, now)
            is_active = key in active_keys
            should_flush = (not is_active) or now >= next_allowed
            if not should_flush:
                continue
            payload = self._group_log_pending_base.pop(key, None)
            self._group_log_next_allowed.pop(key, None)
            if payload:
                bounds_tuple = payload.pop("bounds_tuple", None)
                if bounds_tuple != self._logged_group_bounds.get(key):
                    self._emit_group_base_log(payload)
                    if bounds_tuple is not None:
                        self._logged_group_bounds[key] = bounds_tuple
            transform_payload = self._group_log_pending_transform.pop(key, None)
            if transform_payload:
                transform_tuple = transform_payload.pop("bounds_tuple", None)
                if transform_tuple != self._logged_group_transforms.get(key):
                    self._emit_group_transform_log(transform_payload)
                    if transform_tuple is not None:
                        self._logged_group_transforms[key] = transform_tuple
            if not is_active:
                self._logged_group_bounds.pop(key, None)
                self._logged_group_transforms.pop(key, None)

    def _emit_group_base_log(self, payload: Mapping[str, Any]) -> None:
        log_parts = [
            "group-base-values",
            f"plugin={payload.get('plugin', '')}",
            f"idPrefix_group={payload.get('suffix', '')}",
            f"base_min_x={float(payload.get('min_x', 0.0)):.1f}",
            f"base_min_y={float(payload.get('min_y', 0.0)):.1f}",
            f"base_width={float(payload.get('width', 0.0)):.1f}",
            f"base_height={float(payload.get('height', 0.0)):.1f}",
            f"base_max_x={float(payload.get('max_x', 0.0)):.1f}",
            f"base_max_y={float(payload.get('max_y', 0.0)):.1f}",
            f"has_transformed={bool(payload.get('has_transformed', False))}",
            f"offset_x={float(payload.get('offset_x', 0.0)):.1f}",
            f"offset_y={float(payload.get('offset_y', 0.0)):.1f}",
        ]
        _CLIENT_LOGGER.debug(" ".join(log_parts))

    def _emit_group_transform_log(self, payload: Mapping[str, Any]) -> None:
        log_parts = [
            "group-transformed-values",
            f"plugin={payload.get('plugin', '')}",
            f"idPrefix_group={payload.get('suffix', '')}",
            f"trans_min_x={float(payload.get('min_x', 0.0)):.1f}",
            f"trans_min_y={float(payload.get('min_y', 0.0)):.1f}",
            f"trans_width={float(payload.get('width', 0.0)):.1f}",
            f"trans_height={float(payload.get('height', 0.0)):.1f}",
            f"trans_max_x={float(payload.get('max_x', 0.0)):.1f}",
            f"trans_max_y={float(payload.get('max_y', 0.0)):.1f}",
            f"anchor={payload.get('anchor', 'nw')}",
            f"justification={payload.get('justification', 'left')}",
            f"nudge_dx={payload.get('nudge_dx', 0)}",
            f"nudge_dy={payload.get('nudge_dy', 0)}",
            f"nudged={payload.get('nudged', False)}",
            f"offset_dx={float(payload.get('offset_dx', 0.0)):.1f}",
            f"offset_dy={float(payload.get('offset_dy', 0.0)):.1f}",
        ]
        _CLIENT_LOGGER.debug(" ".join(log_parts))

    def _overlay_bounds_to_rect(self, bounds: _OverlayBounds, mapper: LegacyMapper) -> QRect:
        scale = mapper.transform.scale
        if not math.isfinite(scale) or math.isclose(scale, 0.0, rel_tol=1e-9, abs_tol=1e-9):
            scale = 1.0
        width = max(1, int(round((bounds.max_x - bounds.min_x) * scale)))
        height = max(1, int(round((bounds.max_y - bounds.min_y) * scale)))
        x = int(round(bounds.min_x * scale + mapper.offset_x))
        y = int(round(bounds.min_y * scale + mapper.offset_y))
        return QRect(x, y, width, height)

    def _overlay_point_to_screen(self, point: Tuple[float, float], mapper: LegacyMapper) -> Tuple[int, int]:
        scale = mapper.transform.scale
        if not math.isfinite(scale) or math.isclose(scale, 0.0, rel_tol=1e-9, abs_tol=1e-9):
            scale = 1.0
        x = int(round(point[0] * scale + mapper.offset_x))
        y = int(round(point[1] * scale + mapper.offset_y))
        return x, y

    @staticmethod
    def _anchor_label_position(
        anchor_token: str,
        anchor_px: Tuple[int, int],
        label_width: int,
        ascent: int,
        descent: int,
        canvas_width: int,
        canvas_height: int,
    ) -> Tuple[int, int]:
        token = (anchor_token or "nw").lower()
        x, y = anchor_px
        if "w" in token or token in {"left"}:
            draw_x = x - label_width - 6
        elif "e" in token or token in {"right"}:
            draw_x = x + 6
        else:
            draw_x = x - label_width // 2
        if "n" in token or token in {"top"}:
            draw_y = y - 6
        elif "s" in token or token in {"bottom"}:
            draw_y = y + ascent + 6
        else:
            draw_y = y + ascent // 2
        margin = 8
        if canvas_width > 0:
            min_x = margin
            max_x = max(margin, canvas_width - margin - label_width)
            draw_x = min(max(draw_x, min_x), max_x)
        if canvas_height > 0:
            top = draw_y - ascent
            bottom = draw_y + descent
            min_top = margin
            max_bottom = max(margin, canvas_height - margin)
            if top < min_top:
                shift = min_top - top
                draw_y += shift
                bottom += shift
            if bottom > max_bottom:
                shift = bottom - max_bottom
                draw_y -= shift
        return draw_x, draw_y

    @staticmethod
    def _clone_overlay_bounds_map(
        overlay_bounds_by_group: Mapping[Tuple[str, Optional[str]], _OverlayBounds],
    ) -> Dict[Tuple[str, Optional[str]], _OverlayBounds]:
        cloned: Dict[Tuple[str, Optional[str]], _OverlayBounds] = {}
        for key, bounds in overlay_bounds_by_group.items():
            clone = _OverlayBounds()
            clone.min_x = bounds.min_x
            clone.max_x = bounds.max_x
            clone.min_y = bounds.min_y
            clone.max_y = bounds.max_y
            cloned[key] = clone
        return cloned

    def _apply_anchor_translations_to_overlay_bounds(
        self,
        overlay_bounds_by_group: Dict[Tuple[str, Optional[str]], _OverlayBounds],
        anchor_translations: Mapping[Tuple[str, Optional[str]], Tuple[float, float]],
        base_scale: float,
    ) -> Dict[Tuple[str, Optional[str]], _OverlayBounds]:
        if not anchor_translations:
            return overlay_bounds_by_group
        if not math.isfinite(base_scale) or math.isclose(base_scale, 0.0, rel_tol=1e-9, abs_tol=1e-9):
            base_scale = 1.0
        for key, (dx_px, dy_px) in anchor_translations.items():
            bounds = overlay_bounds_by_group.get(key)
            if bounds is None or not bounds.is_valid():
                continue
            bounds.translate(dx_px / base_scale, dy_px / base_scale)
        return overlay_bounds_by_group

    def _apply_group_nudges_to_overlay_bounds(
        self,
        overlay_bounds_by_group: Dict[Tuple[str, Optional[str]], _OverlayBounds],
        translations: Mapping[Tuple[str, Optional[str]], Tuple[int, int]],
        base_scale: float,
    ) -> Dict[Tuple[str, Optional[str]], _OverlayBounds]:
        if not translations:
            return overlay_bounds_by_group
        if not math.isfinite(base_scale) or math.isclose(base_scale, 0.0, rel_tol=1e-9, abs_tol=1e-9):
            base_scale = 1.0
        for key, (dx_px, dy_px) in translations.items():
            bounds = overlay_bounds_by_group.get(key)
            if bounds is None:
                continue
            bounds.translate(dx_px / base_scale, dy_px / base_scale)
        return overlay_bounds_by_group


    def _log_offscreen_payload(
        self,
        command: _LegacyPaintCommand,
        offset_x: float,
        offset_y: float,
        window_width: int,
        window_height: int,
    ) -> None:
        bounds = command.bounds
        payload_id = command.legacy_item.item_id or ""
        if not bounds or not payload_id:
            if payload_id:
                self._offscreen_payloads.discard(payload_id)
            return
        left = float(bounds[0]) + float(offset_x)
        top = float(bounds[1]) + float(offset_y)
        right = float(bounds[2]) + float(offset_x)
        bottom = float(bounds[3]) + float(offset_y)
        offscreen = (
            right < 0.0
            or bottom < 0.0
            or left >= float(window_width)
            or top >= float(window_height)
        )
        if offscreen:
            if payload_id not in self._offscreen_payloads:
                plugin_name = command.legacy_item.plugin or "unknown"
                self._offscreen_payloads.add(payload_id)
                _CLIENT_LOGGER.warning(
                    "Payload '%s' from plugin '%s' rendered completely outside the overlay window "
                    "(bounds=(%.1f, %.1f)-(%.1f, %.1f), window=%dx%d)",
                    payload_id,
                    plugin_name,
                    left,
                    top,
                    right,
                    bottom,
                    window_width,
                    window_height,
                )
        else:
            self._offscreen_payloads.discard(payload_id)

    def _paint_debug_overlay(self, painter: QPainter) -> None:
        self._debug_overlay_view.paint_debug_overlay(
            painter,
            show_debug_overlay=self._show_debug_overlay,
            frame_geometry=self.frameGeometry(),
            width_px=self._current_physical_size()[0],
            height_px=self._current_physical_size()[1],
            mapper=self._compute_legacy_mapper(),
            viewport_state=self._viewport_state(),
            font_scale_diag=self._font_scale_diag,
            font_min_point=self._font_min_point,
            font_max_point=self._font_max_point,
            debug_message_pt=self._debug_message_point_size,
            debug_status_pt=self._debug_status_point_size,
            debug_legacy_pt=self._debug_legacy_point_size,
            aspect_ratio_label_fn=self._aspect_ratio_label,
            last_screen_name=self._last_screen_name,
            describe_screen_fn=self._describe_screen,
            active_screen=self.windowHandle().screen() if self.windowHandle() else None,
            last_follow_state=self._last_follow_state,
            follow_controller=self._follow_controller,
            last_raw_window_log=self._last_raw_window_log,
            title_bar_enabled=self._title_bar_enabled,
            title_bar_height=self._title_bar_height,
            last_title_bar_offset=self._last_title_bar_offset,
            debug_overlay_corner=self._debug_overlay_corner,
            legacy_preset_point_size_fn=self._legacy_preset_point_size,
        )

    def _paint_overlay_outline(self, painter: QPainter) -> None:
        self._debug_overlay_view.paint_overlay_outline(
            painter,
            debug_outline=self._debug_config.overlay_outline,
            mapper=self._compute_legacy_mapper(),
            window_width=float(self.width()),
            window_height=float(self.height()),
        )

    def _apply_legacy_scale(self) -> None:
        self.update()

    def _apply_window_dimensions(self, *, force: bool = False) -> None:
        return

    def _line_width(self, key: str) -> int:
        return util_line_width(self._line_widths, _LINE_WIDTH_DEFAULTS, key)

def resolve_port_file(args_port: Optional[str]) -> Path:
    if args_port:
        return Path(args_port).expanduser().resolve()
    env_override = os.getenv("EDMC_OVERLAY_PORT_FILE")
    if env_override:
        return Path(env_override).expanduser().resolve()
    return (Path(__file__).resolve().parent.parent / "port.json").resolve()

def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="EDMC Modern Overlay client")
    parser.add_argument("--port-file", help="Path to port.json emitted by the plugin")
    args = parser.parse_args(argv)

    port_file = resolve_port_file(args.port_file)
    settings_path = (CLIENT_DIR.parent / "overlay_settings.json").resolve()
    initial_settings = load_initial_settings(settings_path)
    debug_config_path = (CLIENT_DIR.parent / "debug.json").resolve()
    debug_config = load_debug_config(debug_config_path)
    if not DEBUG_CONFIG_ENABLED:
        _CLIENT_LOGGER.debug(
            "debug.json ignored (release mode). Export %s=1 or use a -dev version to enable trace toggles.",
            DEV_MODE_ENV_VAR,
        )
    helper = DeveloperHelperController(_CLIENT_LOGGER, CLIENT_DIR, initial_settings)
    if debug_config.overlay_logs_to_keep is not None:
        helper.set_log_retention(debug_config.overlay_logs_to_keep)

    _CLIENT_LOGGER.info("Starting overlay client (pid=%s)", os.getpid())
    _CLIENT_LOGGER.debug("Resolved port file path to %s", port_file)
    _CLIENT_LOGGER.debug(
        "Loaded initial settings from %s: retention=%d force_render=%s force_xwayland=%s",
        settings_path,
        initial_settings.client_log_retention,
        initial_settings.force_render,
        initial_settings.force_xwayland,
    )
    if debug_config.trace_enabled:
        payload_filter = ",".join(debug_config.trace_payload_ids) if debug_config.trace_payload_ids else "*"
        _CLIENT_LOGGER.debug("Debug tracing enabled (payload_ids=%s)", payload_filter)

    app = QApplication(sys.argv)
    data_client = OverlayDataClient(port_file)
    window = OverlayWindow(initial_settings, debug_config)
    window.set_data_client(data_client)
    helper.apply_initial_window_state(window, initial_settings)
    tracker = create_elite_window_tracker(_CLIENT_LOGGER, monitor_provider=window.monitor_snapshots)
    if tracker is not None:
        window.set_window_tracker(tracker)
    else:
        _CLIENT_LOGGER.info("Window tracker unavailable; overlay will remain stationary")
    _CLIENT_LOGGER.debug(
        "Overlay window created; size=%dx%d; %s",
        window.width(),
        window.height(),
        window.format_scale_debug(),
    )

    def _handle_payload(payload: Dict[str, Any]) -> None:
        event = payload.get("event")
        if event == "OverlayConfig":
            helper.apply_config(window, payload)
            return
        if event == "LegacyOverlay":
            helper.handle_legacy_payload(window, payload)
            return
        if event == "OverlayCycle":
            action = payload.get("action")
            if isinstance(action, str):
                window.handle_cycle_action(action)
            return
        message_text = payload.get("message")
        ttl: Optional[float] = None
        if event == "TestMessage" and payload.get("message"):
            message_text = payload["message"]
            ttl = 10.0
        if message_text is not None:
            window.display_message(str(message_text), ttl=ttl)

    data_client.message_received.connect(_handle_payload)
    data_client.status_changed.connect(window.set_status_text)

    window.show()
    data_client.start()

    exit_code = app.exec()
    data_client.stop()
    _CLIENT_LOGGER.info("Overlay client exiting with code %s", exit_code)
    return int(exit_code)


OverlayClient = OverlayWindow

if __name__ == "__main__":
    raise SystemExit(main())
