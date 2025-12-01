"""Standalone PyQt6 overlay client for EDMC Modern Overlay."""
from __future__ import annotations

# ruff: noqa: E402

import json
import logging
import math
import os
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple, Set

CLIENT_DIR = Path(__file__).resolve().parent
ROOT_DIR = CLIENT_DIR.parent

from PyQt6.QtCore import Qt, QTimer, QPoint, QRect, QSize
from PyQt6.QtGui import (
    QColor,
    QFont,
    QPainter,
    QPen,
    QCursor,
    QPixmap,
    QGuiApplication,
    QScreen,
    QWindow,
)
from PyQt6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

from overlay_client.follow_controller import FollowController  # type: ignore
from overlay_client.payload_model import PayloadModel  # type: ignore
from overlay_client.render_pipeline import LegacyRenderPipeline  # type: ignore
from overlay_client.grouping_adapter import GroupingAdapter  # type: ignore

try:  # pragma: no cover - defensive fallback when running standalone
    from version import __version__ as MODERN_OVERLAY_VERSION, DEV_MODE_ENV_VAR
except Exception:  # pragma: no cover - fallback when module unavailable
    MODERN_OVERLAY_VERSION = "unknown"
    DEV_MODE_ENV_VAR = "MODERN_OVERLAY_DEV_MODE"

from overlay_client.data_client import OverlayDataClient  # type: ignore  # noqa: E402
from overlay_client.client_config import InitialClientSettings  # type: ignore  # noqa: E402
from overlay_client.platform_integration import MonitorSnapshot, PlatformContext, PlatformController  # type: ignore  # noqa: E402
from overlay_client.window_tracking import WindowState, WindowTracker  # type: ignore  # noqa: E402
from overlay_client.legacy_store import LegacyItem  # type: ignore  # noqa: E402
from overlay_client.plugin_overrides import PluginOverrideManager  # type: ignore  # noqa: E402
from overlay_client.debug_config import DEBUG_CONFIG_ENABLED, DebugConfig  # type: ignore  # noqa: E402
from overlay_client.group_transform import GroupTransform  # type: ignore  # noqa: E402
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
from overlay_client.status_presenter import StatusPresenter  # type: ignore  # noqa: E402
from overlay_client.window_controller import WindowController  # type: ignore  # noqa: E402
from overlay_client.interaction_controller import InteractionController  # type: ignore  # noqa: E402
from overlay_client.visibility_helper import VisibilityHelper  # type: ignore  # noqa: E402
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
    _GroupDebugState,
    _MeasuredText,
    _OverlayBounds,
)

_LOGGER_NAME = "EDMC.ModernOverlay.Client"
_CLIENT_LOGGER = logging.getLogger(_LOGGER_NAME)
_CLIENT_LOGGER.setLevel(logging.DEBUG if DEBUG_CONFIG_ENABLED else logging.INFO)
_CLIENT_LOGGER.propagate = False
# Opt-in propagation flag for environments/tests that want client logs upstream.
if os.environ.get("EDMC_OVERLAY_PROPAGATE_LOGS", "").lower() in {"1", "true", "yes", "on"}:
    _CLIENT_LOGGER.propagate = True


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

class OverlayWindow(QWidget, RenderSurfaceMixin):
    """Transparent overlay that renders CMDR and location info."""

    _resolve_font_family = _resolve_font_family
    _resolve_emoji_font_families = _resolve_emoji_font_families
    _apply_font_fallbacks = _apply_font_fallbacks

    _WM_OVERRIDE_TTL = 1.25  # seconds
    _REPAINT_DEBOUNCE_MS = 33  # coalesce ingest/purge repaint storms
    _TEXT_CACHE_MAX = 512
    _TEXT_BLOCK_CACHE_MAX = 256

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
        self._visibility_helper = VisibilityHelper(log_fn=_CLIENT_LOGGER.debug)
        self._interaction_controller = InteractionController(
            is_wayland_fn=self._is_wayland,
            log_fn=_CLIENT_LOGGER.debug,
            prepare_window_fn=lambda window: self._platform_controller.prepare_window(window),
            apply_click_through_fn=lambda transparent: self._platform_controller.apply_click_through(transparent),
            set_transient_parent_fn=lambda parent: self.windowHandle().setTransientParent(parent) if self.windowHandle() else None,
            clear_transient_parent_ids_fn=self._clear_transient_parent_ids,
            window_handle_fn=lambda: self.windowHandle(),
            set_widget_attribute_fn=lambda attr, enabled: self.setAttribute(attr, enabled),
            set_window_flag_fn=lambda flag, enabled: self.setWindowFlag(flag, enabled),
            ensure_visible_fn=lambda: self.show() if not self.isVisible() else None,
            raise_fn=lambda: self.raise_() if self.isVisible() else None,
            set_children_attr_fn=lambda transparent: self._set_children_click_through(transparent),
            transparent_input_supported=self._transparent_input_supported,
            set_window_transparent_input_fn=lambda transparent: self.windowHandle().setFlag(Qt.WindowType.WindowTransparentForInput, transparent) if self.windowHandle() else None,
        )
        self._status_presenter = StatusPresenter(
            send_payload_fn=self.handle_legacy_payload,
            platform_label_fn=lambda: self._platform_controller.platform_label(),
            base_height=DEFAULT_WINDOW_BASE_HEIGHT,
            log_fn=_CLIENT_LOGGER.debug,
        )
        self._status_presenter.set_status_bottom_margin(
            self._coerce_non_negative(getattr(initial, "status_bottom_margin", 20), default=20),
            coerce_fn=lambda value, default: self._coerce_non_negative(value, default=default),
        )
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
        self._line_width_defaults: Dict[str, int] = _LINE_WIDTH_DEFAULTS
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
        self._repaint_metrics: Dict[str, Any] = {
            "enabled": dev_mode_active or DEBUG_CONFIG_ENABLED,
            "counts": {"total": 0, "ingest": 0, "purge": 0},
            "last_ts": None,
            "burst_current": 0,
            "burst_max": 0,
        }
        self._repaint_debounce_enabled: bool = True
        if debug_config.repaint_debounce_enabled is not None:
            self._repaint_debounce_enabled = bool(debug_config.repaint_debounce_enabled)
        self._repaint_debounce_log: bool = bool(getattr(debug_config, "log_repaint_debounce", False))
        self._repaint_log_last: Optional[Dict[str, Any]] = None
        self._repaint_timer = QTimer(self)
        self._repaint_timer.setSingleShot(True)
        self._repaint_timer.setInterval(self._REPAINT_DEBOUNCE_MS)
        self._repaint_timer.timeout.connect(self._trigger_debounced_repaint)
        self._paint_log_timer = QTimer(self)
        self._paint_log_timer.setInterval(5000)
        self._paint_log_timer.timeout.connect(self._emit_paint_stats)
        if self._repaint_debounce_log:
            self._paint_log_timer.start()
        self._paint_stats = {"paint_count": 0}
        self._paint_log_state = {"last_ingest": 0, "last_purge": 0, "last_total": 0}
        self._measure_stats = {"calls": 0}
        self._text_cache: Dict[Tuple[str, float, str], Tuple[int, int, int]] = {}
        self._text_block_cache: Dict[Tuple[str, float, str, Tuple[str, ...], float, int], Tuple[int, int]] = {}
        self._text_cache_generation = 0
        self._text_cache_context: Optional[Tuple[str, Tuple[str, ...], float]] = None
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
        stats = getattr(self, "_paint_stats", None)
        if isinstance(stats, dict):
            stats["paint_count"] = stats.get("paint_count", 0) + 1
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
            self._interaction_controller.handle_force_render_enter()
            self._update_follow_visibility(True)
            if sys.platform.startswith("linux"):
                self._interaction_controller.restore_drag_interactivity(
                    self._drag_enabled,
                    self._drag_active,
                    self.format_scale_debug,
                )
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
            font_family=self._font_family,
            window_width=float(self.width()),
            window_height=float(self.height()),
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
        self._status_presenter.set_status_text(status)
        self._status_raw = self._status_presenter.status_raw
        self._status = self._status_presenter.status

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
        self._status_presenter.set_show_status(show)
        self._show_status = self._status_presenter.show_status

    def set_status_bottom_margin(self, margin: Optional[int]) -> None:
        self._status_presenter.set_status_bottom_margin(
            margin if margin is not None else self._status_presenter.status_bottom_margin,
            coerce_fn=lambda value, default: self._coerce_non_negative(value, default=default),
        )
        self._status_bottom_margin = self._status_presenter.status_bottom_margin

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

    def _record_repaint_event(self, reason: str) -> None:
        metrics = self._repaint_metrics
        if not metrics.get("enabled"):
            return
        counts = metrics.setdefault("counts", {})
        counts["total"] = counts.get("total", 0) + 1
        counts[reason] = counts.get(reason, 0) + 1
        now = time.monotonic()
        last_ts_raw = metrics.get("last_ts")
        last_ts = float(last_ts_raw) if last_ts_raw is not None else None
        if last_ts is None or now - last_ts > 0.1:
            burst = 1
        else:
            burst = int(metrics.get("burst_current", 0)) + 1
        metrics["burst_current"] = burst
        metrics["last_ts"] = now
        if burst > metrics.get("burst_max", 0):
            metrics["burst_max"] = burst
            _CLIENT_LOGGER.debug(
                "Repaint burst updated (%s): current=%d max=%d interval=%.3fs totals=%s",
                reason,
                burst,
                metrics["burst_max"],
                (now - last_ts) if last_ts is not None else 0.0,
                counts,
            )

    def _request_repaint(self, reason: str, *, immediate: bool = False) -> None:
        self._record_repaint_event(reason)
        debounce_enabled = bool(getattr(self, "_repaint_debounce_enabled", True))
        timer = getattr(self, "_repaint_timer", None)
        effective_immediate = immediate or not debounce_enabled or timer is None
        if self._repaint_debounce_log:
            should_log = effective_immediate or timer is None or not timer.isActive()
            if should_log:
                path_label = "immediate" if effective_immediate else "debounced"
                now = time.monotonic()
                last = self._repaint_log_last or {}
                if (
                    last.get("reason") != reason
                    or last.get("path") != path_label
                    or now - float(last.get("ts", 0.0)) > 1.0
                ):
                    _CLIENT_LOGGER.debug(
                        "Repaint request: reason=%s path=%s debounce_enabled=%s timer_active=%s",
                        reason,
                        path_label,
                        debounce_enabled,
                        timer.isActive() if timer is not None else False,
                    )
                    self._repaint_log_last = {"reason": reason, "path": path_label, "ts": now}
        if effective_immediate:
            if timer is not None and timer.isActive():
                timer.stop()
            self.update()
            return
        if not timer.isActive():
            timer.start()

    def _trigger_debounced_repaint(self) -> None:
        self.update()

    @staticmethod
    def _should_bypass_debounce(payload: Mapping[str, Any]) -> bool:
        """Allow immediate repaint for fast animations/short-lived payloads."""

        if payload.get("animate"):
            return True
        ttl_raw = payload.get("ttl")
        try:
            ttl_value = float(ttl_raw)
        except (TypeError, ValueError):
            return False
        return 0.0 < ttl_value <= 1.0

    def _emit_paint_stats(self) -> None:
        if not self._repaint_debounce_log:
            return
        counts = getattr(self, "_repaint_metrics", {}).get("counts", {})
        stats = getattr(self, "_paint_stats", {})
        paint_count = stats.get("paint_count", 0) if isinstance(stats, dict) else 0
        stats["paint_count"] = 0
        last_state = getattr(self, "_paint_log_state", {}) or {}
        ingest_total = counts.get("ingest", 0) if isinstance(counts, dict) else 0
        purge_total = counts.get("purge", 0) if isinstance(counts, dict) else 0
        total_total = counts.get("total", 0) if isinstance(counts, dict) else 0
        ingest_delta = ingest_total - int(last_state.get("last_ingest", 0))
        purge_delta = purge_total - int(last_state.get("last_purge", 0))
        total_delta = total_total - int(last_state.get("last_total", 0))
        self._paint_log_state = {
            "last_ingest": ingest_total,
            "last_purge": purge_total,
            "last_total": total_total,
        }
        _CLIENT_LOGGER.debug(
            "Repaint stats: paints=%d ingest_delta=%d purge_delta=%d total_delta=%d ingest_total=%s purge_total=%s total=%s",
            paint_count,
            ingest_delta,
            purge_delta,
            total_delta,
            ingest_total,
            purge_total,
            total_total,
        )
        measure_stats = getattr(self, "_measure_stats", {})
        if isinstance(measure_stats, dict) and measure_stats.get("calls"):
            _CLIENT_LOGGER.debug(
                "Text measure stats: calls=%d hits=%d misses=%d resets=%d (window=5s)",
                measure_stats.get("calls", 0),
                measure_stats.get("cache_hit", 0),
                measure_stats.get("cache_miss", 0),
                measure_stats.get("cache_reset", 0),
            )
            measure_stats["calls"] = 0
            measure_stats["cache_hit"] = 0
            measure_stats["cache_miss"] = 0
            measure_stats["cache_reset"] = 0

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
        self._interaction_controller.reapply_current(reason="platform_context_update")
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
        self._interaction_controller.set_click_through(not self._drag_enabled, force=True, reason="apply_drag_state")
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
        self._interaction_controller.set_click_through(transparent, force=True, reason="external_set_click_through")

    def _restore_drag_interactivity(self) -> None:
        self._interaction_controller.restore_drag_interactivity(self._drag_enabled, self._drag_active, self.format_scale_debug)

    def _set_children_click_through(self, transparent: bool) -> None:
        for child_name in ("message_label",):
            child = getattr(self, child_name, None)
            if child is not None:
                try:
                    child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, transparent)
                except (AttributeError, RuntimeError, TypeError, ValueError) as exc:
                    _CLIENT_LOGGER.debug("Failed to set click-through on child %s: %s", child_name, exc)
                except Exception as exc:  # pragma: no cover - unexpected Qt errors
                    _CLIENT_LOGGER.warning("Unexpected error setting click-through on child %s: %s", child_name, exc)

    def _clear_transient_parent_ids(self) -> None:
        self._transient_parent_window = None
        self._transient_parent_id = None

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
            except (AttributeError, RuntimeError, TypeError, ValueError) as exc:
                _CLIENT_LOGGER.debug("Failed to read devicePixelRatio, defaulting to 0.0: %s", exc)
                window_dpr = 0.0
            except Exception as exc:  # pragma: no cover - unexpected Qt errors
                _CLIENT_LOGGER.warning("Unexpected devicePixelRatio failure, defaulting to 0.0: %s", exc)
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
                    except (AttributeError, RuntimeError, TypeError, ValueError) as exc:
                        _CLIENT_LOGGER.debug("Failed to clear transient parent on Wayland: %s", exc)
                    except Exception as exc:  # pragma: no cover - unexpected Qt errors
                        _CLIENT_LOGGER.warning("Unexpected error clearing transient parent on Wayland: %s", exc)
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
        new_state = self._visibility_helper.update_visibility(
            show,
            is_visible_fn=lambda: self.isVisible(),
            show_fn=lambda: self.show(),
            hide_fn=lambda: self.hide(),
            raise_fn=lambda: self.raise_(),
            apply_drag_state_fn=self._apply_drag_state,
            format_scale_debug_fn=self.format_scale_debug,
        )
        # keep compatibility for any consumers expecting cached state
        self._last_visibility_state = new_state

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
        except (AttributeError, RuntimeError, TypeError, ValueError) as exc:
            _CLIENT_LOGGER.debug("Failed to describe screen %r: %s", screen, exc)
            return str(screen)
        except Exception as exc:  # pragma: no cover - unexpected Qt errors
            _CLIENT_LOGGER.warning("Unexpected error describing screen %r: %s", screen, exc)
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
