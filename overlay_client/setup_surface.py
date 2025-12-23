"""Setup/baseline surface mixin extracted from overlay_client."""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
import math
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from PyQt6.QtCore import Qt, QTimer, QPoint
from PyQt6.QtGui import QColor, QFont, QPainter, QPen, QPixmap, QGuiApplication
from PyQt6.QtWidgets import QLabel, QVBoxLayout

from group_cache import GroupPlacementCache, resolve_cache_path

from overlay_client.client_config import InitialClientSettings
from overlay_client.controller_mode import ControllerModeProfile, ControllerModeTracker, ModeProfile
from overlay_client.data_client import OverlayDataClient
from overlay_client.debug_config import DEBUG_CONFIG_ENABLED, DebugConfig
from overlay_client.debug_cycle_overlay import CycleOverlayView, DebugOverlayView
from overlay_client.follow_controller import FollowController
from overlay_client.group_coordinator import GroupCoordinator
from overlay_client.grouping_adapter import GroupingAdapter
from overlay_client.grouping_helper import FillGroupingHelper
from overlay_client.platform_context import _initial_platform_context
from overlay_client.platform_integration import PlatformController
from overlay_client.plugin_overrides import PluginOverrideManager
from overlay_client.render_pipeline import LegacyRenderPipeline
from overlay_client.render_surface import _GroupDebugState, _OverlayBounds
from overlay_client.status_presenter import StatusPresenter
from overlay_client.visibility_helper import VisibilityHelper
from overlay_client.interaction_controller import InteractionController
from overlay_client.window_controller import WindowController
from overlay_client.window_tracking import WindowState, WindowTracker
from overlay_client.viewport_helper import BASE_HEIGHT, BASE_WIDTH
from overlay_plugin.groupings_loader import GroupingsLoader

_CLIENT_LOGGER = logging.getLogger("EDMC.ModernOverlay.Client")


class SetupSurfaceMixin:
    """Handles widget/setup plumbing and paint/show glue for the overlay window."""

    def _setup_overlay(
        self,
        initial: InitialClientSettings,
        debug_config: DebugConfig,
        *,
        root_dir,
        load_line_width_config: Callable[[], Dict[str, int]],
        line_width_defaults: Dict[str, int],
        payload_model_factory: Callable[[Callable[[str, Dict[str, Any]], None]], Any],
    ) -> None:
        self._font_family = self._resolve_font_family()
        self._font_fallbacks: Tuple[str, ...] = self._resolve_emoji_font_families()
        self._status_raw = "Initialising"
        self._status = self._status_raw
        self._state: Dict[str, Any] = {
            "message": "",
        }
        self._debug_config = debug_config
        self._last_override_reload_nonce: Optional[str] = None
        self._controller_active_group: Optional[tuple[str, str]] = None
        self._controller_active_anchor: Optional[str] = None
        self._controller_active_nonce: str = ""
        self._controller_active_nonce_ts: float = 0.0
        self._controller_override_ts: float = 0.0
        self._mode_profile_overrides: Dict[str, object] = {}
        if DEBUG_CONFIG_ENABLED:
            # Preserve faster dev-mode cache flush cadence as an explicit override.
            self._mode_profile_overrides["cache_flush_seconds"] = 1.0
        self._mode_profile = ControllerModeProfile(
            active=ModeProfile(
                write_debounce_ms=75,
                offset_write_debounce_ms=75,
                status_poll_ms=750,
                cache_flush_seconds=0.1,
            ),
            inactive=ModeProfile(
                write_debounce_ms=200,
                offset_write_debounce_ms=200,
                status_poll_ms=2500,
                cache_flush_seconds=5.0,
            ),
            logger=_CLIENT_LOGGER.debug,
        )
        self._current_mode_profile = self._mode_profile.resolve("inactive", self._mode_profile_overrides)
        self._payload_model = payload_model_factory(self._trace_legacy_store_event)
        self._background_opacity: float = 0.0
        try:
            payload_opacity = int(getattr(initial, "global_payload_opacity", 100))
        except (TypeError, ValueError):
            payload_opacity = 100
        self._payload_opacity: int = max(0, min(payload_opacity, 100))
        self._gridlines_enabled: bool = False
        self._gridline_spacing: int = 120
        self._grid_pixmap: Optional[QPixmap] = None
        self._grid_pixmap_params: Optional[Tuple[int, int, int, int]] = None
        self._drag_enabled: bool = False
        self._drag_active: bool = False
        self._drag_offset = QPoint()
        self._move_mode: bool = False
        self._cursor_saved: bool = False
        self._saved_cursor = self.cursor()
        self._transparent_input_supported = hasattr(Qt.WindowType, "WindowTransparentForInput")
        self._show_status: bool = False
        self._base_height: int = int(BASE_HEIGHT)
        self._base_width: int = int(BASE_WIDTH)
        self._log_retention: int = max(1, int(initial.client_log_retention))
        self._force_render: bool = bool(getattr(initial, "force_render", False))
        self._physical_clamp_enabled: bool = bool(getattr(initial, "physical_clamp_enabled", False))
        self._physical_clamp_overrides: Dict[str, float] = dict(
            getattr(initial, "physical_clamp_overrides", {}) or {}
        )
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
        self._transient_parent_window = None
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
            base_height=BASE_HEIGHT,
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
        self._line_widths: Dict[str, int] = load_line_width_config()
        self._line_width_defaults: Dict[str, int] = line_width_defaults
        self._payload_nudge_enabled: bool = False
        self._payload_nudge_gutter: int = 30
        self._text_measurer: Optional[Callable[[str, float, str], Any]] = None
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
        self._payload_log_delay_base = self._payload_log_delay
        self._group_log_pending_base: Dict[Tuple[str, Optional[str]], Dict[str, Any]] = {}
        self._group_log_pending_transform: Dict[Tuple[str, Optional[str]], Dict[str, Any]] = {}
        self._group_log_next_allowed: Dict[Tuple[str, Optional[str]], float] = {}
        self._logged_group_bounds: Dict[Tuple[str, Optional[str]], Tuple[float, float, float, float]] = {}
        self._logged_group_transforms: Dict[Tuple[str, Optional[str]], Tuple[float, float, float, float]] = {}
        self._group_cache_generations: Dict[Tuple[str, Optional[str]], str] = {}
        self._cache_write_metadata: Dict[Tuple[str, Optional[str]], Dict[str, Any]] = {}
        self._last_cache_flush_ts: float = 0.0
        self._last_overlay_bounds_for_target: Dict[Tuple[str, Optional[str]], Any] = {}
        self._last_transform_by_group: Dict[Tuple[str, Optional[str]], Any] = {}
        self._controller_mode = ControllerModeTracker(
            timeout_seconds=30.0,
            on_state_change=self._handle_controller_mode_change,
        )
        self._controller_mode_timer = QTimer(self)
        self._controller_mode_timer.setSingleShot(True)
        self._controller_mode.configure_timeout_hooks(
            arm_timeout=lambda seconds: self._controller_mode_timer.start(int(max(0.5, seconds) * 1000)),
            cancel_timeout=lambda: self._controller_mode_timer.stop(),
        )
        self._controller_mode_timer.timeout.connect(self._handle_controller_timeout)
        self._group_cache = GroupPlacementCache(
            resolve_cache_path(root_dir),
            debounce_seconds=self._current_mode_profile.cache_flush_seconds,
            logger=_CLIENT_LOGGER,
        )
        self._controller_active_flush_interval = self._current_mode_profile.cache_flush_seconds
        self._mode_profile.log_profile("inactive", self._current_mode_profile, "initial")
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
        legacy_step = getattr(initial, "legacy_font_step", 2)
        try:
            legacy_step_value = float(legacy_step)
        except (TypeError, ValueError):
            legacy_step_value = 2.0
        self._legacy_font_step = max(0.0, min(legacy_step_value, 10.0))
        user_groupings = os.environ.get("MODERN_OVERLAY_USER_GROUPINGS_PATH", root_dir / "overlay_groupings.user.json")
        self._groupings_loader = GroupingsLoader(
            root_dir / "overlay_groupings.json",
            Path(user_groupings),
        )
        _CLIENT_LOGGER.debug(
            "Groupings loader configured: shipped=%s user=%s",
            self._groupings_loader.paths().get("shipped"),
            self._groupings_loader.paths().get("user"),
        )
        self._override_manager = PluginOverrideManager(
            root_dir / "overlay_groupings.json",
            _CLIENT_LOGGER,
            debug_config=self._debug_config,
            groupings_loader=self._groupings_loader,
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
        self._env_override_debug = self._collect_env_override_debug_info()
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

    @staticmethod
    def _parse_env_override_list(var_name: str) -> List[str]:
        raw = os.environ.get(var_name, "")
        if not raw:
            return []
        return [token for token in raw.split(",") if token.strip()]

    def _collect_env_override_debug_info(self) -> Dict[str, Any]:
        keys_of_interest = (
            "QT_AUTO_SCREEN_SCALE_FACTOR",
            "QT_ENABLE_HIGHDPI_SCALING",
            "QT_SCALE_FACTOR",
            "EDMC_OVERLAY_FORCE_XWAYLAND",
        )
        values: Dict[str, Optional[str]] = {}
        for key in keys_of_interest:
            val = os.environ.get(key)
            values[key] = val if val is not None else None
        return {
            "applied": self._parse_env_override_list("EDMC_OVERLAY_ENV_OVERRIDES_APPLIED"),
            "skipped_env": self._parse_env_override_list("EDMC_OVERLAY_ENV_OVERRIDES_SKIPPED_ENV"),
            "skipped_existing": self._parse_env_override_list("EDMC_OVERLAY_ENV_OVERRIDES_SKIPPED_EXISTING"),
            "values": values,
        }

    def _handle_show_event(self) -> None:
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

    def _handle_controller_mode_change(self, previous: str, current: str) -> None:
        _CLIENT_LOGGER.debug("Controller mode changed: %s -> %s", previous, current)
        self._apply_controller_mode_profile(current, reason="state_change")
        if current != "active":
            self.set_active_controller_group(None, None)

    def _apply_controller_mode_profile(self, mode: str, reason: Optional[str] = None) -> None:
        profile = self._mode_profile.resolve(mode, self._mode_profile_overrides)
        previous = getattr(self, "_current_mode_profile", None)
        self._current_mode_profile = profile
        if previous == profile:
            if reason:
                self._mode_profile.log_profile(mode, profile, f"{reason} (unchanged)")
            self._update_payload_log_delay_for_mode(mode)
            return
        self._mode_profile.log_profile(mode, profile, reason or "apply")
        self._set_group_cache_debounce(profile.cache_flush_seconds)
        self._controller_active_flush_interval = profile.cache_flush_seconds
        self._update_payload_log_delay_for_mode(mode)

    def _set_group_cache_debounce(self, debounce_seconds: float) -> None:
        cache = getattr(self, "_group_cache", None)
        if cache is None:
            return
        try:
            cache.configure_debounce(debounce_seconds)
        except Exception as exc:
            _CLIENT_LOGGER.debug(
                "Failed to update group cache debounce to %.2fs: %s",
                debounce_seconds,
                exc,
                exc_info=exc,
            )

    def _update_payload_log_delay_for_mode(self, mode: str) -> None:
        base_delay = getattr(self, "_payload_log_delay_base", self._payload_log_delay)
        if mode == "active":
            target = min(base_delay, max(0.0, self._controller_active_flush_interval / 2.0))
        else:
            target = base_delay
        if not math.isclose(target, self._payload_log_delay, rel_tol=1e-6, abs_tol=1e-6):
            self._payload_log_delay = target
            _CLIENT_LOGGER.debug("Payload log delay set to %.3fs for controller mode %s", target, mode)

    def handle_controller_active_signal(self) -> None:
        self._controller_mode.mark_active()

    def controller_mode_state(self) -> str:
        return self._controller_mode.state

    def _handle_controller_timeout(self) -> None:
        self._controller_mode.mark_inactive()
        self.set_active_controller_group(None, None)

    def _paint_overlay(self, painter: QPainter) -> None:
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

    def _grid_pixmap_for(self, width: int, height: int, spacing: int, grid_alpha: int) -> Optional[QPixmap]:
        if width <= 0 or height <= 0 or spacing <= 0 or grid_alpha <= 0:
            return None
        line_width = self._line_width("grid")
        params = (width, height, spacing, grid_alpha)
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

        self._grid_pixmap = pixmap
        self._grid_pixmap_params = params
        return pixmap
