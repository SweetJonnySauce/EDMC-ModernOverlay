"""Standalone PyQt6 overlay client for EDMC Modern Overlay."""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
import os
import queue
import sys
import threading
import time
from datetime import UTC, datetime
from fractions import Fraction
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple, Set

from PyQt6.QtCore import Qt, pyqtSignal, QObject, QTimer, QPoint, QRect, QSize
from PyQt6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QPainter,
    QPen,
    QBrush,
    QCursor,
    QFontDatabase,
    QGuiApplication,
    QScreen,
    QWindow,
)
from PyQt6.QtWidgets import QApplication, QLabel, QSizePolicy, QVBoxLayout, QWidget


CLIENT_DIR = Path(__file__).resolve().parent
if str(CLIENT_DIR) not in sys.path:
    sys.path.insert(0, str(CLIENT_DIR))

ROOT_DIR = CLIENT_DIR.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

try:  # pragma: no cover - defensive fallback when running standalone
    from version import __version__ as MODERN_OVERLAY_VERSION, DEV_MODE_ENV_VAR
except Exception:  # pragma: no cover - fallback when module unavailable
    MODERN_OVERLAY_VERSION = "unknown"
    DEV_MODE_ENV_VAR = "MODERN_OVERLAY_DEV_MODE"

from client_config import InitialClientSettings, load_initial_settings  # type: ignore  # noqa: E402
from developer_helpers import DeveloperHelperController  # type: ignore  # noqa: E402
from platform_integration import MonitorSnapshot, PlatformContext, PlatformController  # type: ignore  # noqa: E402
from window_tracking import WindowState, WindowTracker, create_elite_window_tracker  # type: ignore  # noqa: E402
from legacy_store import LegacyItem, LegacyItemStore  # type: ignore  # noqa: E402
from legacy_processor import TraceCallback, process_legacy_payload  # type: ignore  # noqa: E402
from vector_renderer import render_vector, VectorPainterAdapter  # type: ignore  # noqa: E402
from plugin_overrides import PluginOverrideManager  # type: ignore  # noqa: E402
from debug_config import DEBUG_CONFIG_ENABLED, DebugConfig, load_debug_config  # type: ignore  # noqa: E402
from group_transform import GroupTransform, GroupKey  # type: ignore  # noqa: E402
from font_utils import apply_font_fallbacks  # type: ignore  # noqa: E402
from viewport_helper import (
    BASE_HEIGHT,
    BASE_WIDTH,
    ScaleMode,
    ViewportTransform,
    compute_viewport_transform,
)  # type: ignore  # noqa: E402
from grouping_helper import FillGroupingHelper  # type: ignore  # noqa: E402
from group_transform import GroupBounds  # type: ignore  # noqa: E402
from payload_transform import (
    accumulate_group_bounds,
    build_payload_transform_context,
    PayloadTransformContext,
    remap_axis_value,
    remap_point,
    remap_rect_points,
    remap_vector_points,
    transform_components,
)  # type: ignore  # noqa: E402
from viewport_transform import (  # type: ignore  # noqa: E402
    FillViewport,
    LegacyMapper,
    ViewportState,
    build_viewport,
    compute_proportional_translation,
    inverse_group_axis,
    map_anchor_axis,
    legacy_scale_components,
    scaled_point_size as viewport_scaled_point_size,
)

_LOGGER_NAME = "EDMC.ModernOverlay.Client"
_CLIENT_LOGGER = logging.getLogger(_LOGGER_NAME)
_CLIENT_LOGGER.setLevel(logging.DEBUG)
_CLIENT_LOGGER.propagate = False

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
class _LegacyPaintCommand:
    group_key: GroupKey
    group_transform: Optional[GroupTransform]
    legacy_item: LegacyItem
    bounds: Optional[Tuple[int, int, int, int]]
    overlay_bounds: Optional[Tuple[float, float, float, float]] = None
    effective_anchor: Optional[Tuple[float, float]] = None
    anchor_offset: Optional[Tuple[float, float]] = None
    debug_log: Optional[str] = None

    def paint(self, window: "OverlayWindow", painter: QPainter, offset_x: int, offset_y: int) -> None:
        raise NotImplementedError


@dataclass
class _MessagePaintCommand(_LegacyPaintCommand):
    text: str = ""
    color: QColor = field(default_factory=lambda: QColor("white"))
    point_size: float = 12.0
    x: int = 0
    baseline: int = 0
    text_width: int = 0
    ascent: int = 0
    descent: int = 0
    cycle_anchor: Optional[Tuple[int, int]] = None
    trace_fn: Optional[Callable[[str, Mapping[str, Any]], None]] = None

    def paint(self, window: "OverlayWindow", painter: QPainter, offset_x: int, offset_y: int) -> None:
        font = QFont(window._font_family)
        window._apply_font_fallbacks(font)
        font.setPointSizeF(self.point_size)
        font.setWeight(QFont.Weight.Normal)
        painter.setFont(font)
        painter.setPen(self.color)
        draw_x = int(round(self.x + offset_x))
        draw_baseline = int(round(self.baseline + offset_y))
        painter.drawText(draw_x, draw_baseline, self.text)
        if self.trace_fn:
            self.trace_fn(
                "render_message:draw",
                {
                    "pixel_x": draw_x,
                    "baseline": draw_baseline,
                    "text_width": self.text_width,
                    "font_size": self.point_size,
                    "color": self.color.name(),
                },
            )
        if self.cycle_anchor:
            anchor_x = int(round(self.cycle_anchor[0] + offset_x))
            anchor_y = int(round(self.cycle_anchor[1] + offset_y))
            window._register_cycle_anchor(self.legacy_item.item_id, anchor_x, anchor_y)


@dataclass
class _RectPaintCommand(_LegacyPaintCommand):
    pen: QPen = field(default_factory=lambda: QPen(Qt.PenStyle.NoPen))
    brush: QBrush = field(default_factory=lambda: QBrush(Qt.BrushStyle.NoBrush))
    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0
    cycle_anchor: Optional[Tuple[int, int]] = None

    def paint(self, window: "OverlayWindow", painter: QPainter, offset_x: int, offset_y: int) -> None:
        painter.setPen(self.pen)
        painter.setBrush(self.brush)
        draw_x = int(round(self.x + offset_x))
        draw_y = int(round(self.y + offset_y))
        painter.drawRect(draw_x, draw_y, self.width, self.height)
        if self.cycle_anchor:
            anchor_x = int(round(self.cycle_anchor[0] + offset_x))
            anchor_y = int(round(self.cycle_anchor[1] + offset_y))
            window._register_cycle_anchor(self.legacy_item.item_id, anchor_x, anchor_y)


@dataclass
class _VectorPaintCommand(_LegacyPaintCommand):
    vector_payload: Mapping[str, Any] = field(default_factory=dict)
    scale: float = 1.0
    base_offset_x: float = 0.0
    base_offset_y: float = 0.0
    trace_fn: Optional[Callable[[str, Mapping[str, Any]], None]] = None
    cycle_anchor: Optional[Tuple[int, int]] = None

    def paint(self, window: "OverlayWindow", painter: QPainter, offset_x: int, offset_y: int) -> None:
        adapter = _QtVectorPainterAdapter(window, painter)
        render_vector(
            adapter,
            self.vector_payload,
            self.scale,
            self.scale,
            offset_x=self.base_offset_x + offset_x,
            offset_y=self.base_offset_y + offset_y,
            trace=self.trace_fn,
        )
        if self.cycle_anchor:
            anchor_x = int(round(self.cycle_anchor[0] + offset_x))
            anchor_y = int(round(self.cycle_anchor[1] + offset_y))
            window._register_cycle_anchor(self.legacy_item.item_id, anchor_x, anchor_y)


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


def _initial_platform_context(initial: InitialClientSettings) -> PlatformContext:
    force_env = os.environ.get("EDMC_OVERLAY_FORCE_XWAYLAND") == "1"
    session = os.environ.get("EDMC_OVERLAY_SESSION_TYPE") or os.environ.get("XDG_SESSION_TYPE") or ""
    compositor = os.environ.get("EDMC_OVERLAY_COMPOSITOR") or ""
    flatpak_flag = os.environ.get("EDMC_OVERLAY_IS_FLATPAK") == "1"
    flatpak_app = os.environ.get("EDMC_OVERLAY_FLATPAK_ID") or ""
    return PlatformContext(
        session_type=session,
        compositor=compositor,
        force_xwayland=bool(initial.force_xwayland or force_env),
        flatpak=flatpak_flag,
        flatpak_app=flatpak_app,
    )

class OverlayDataClient(QObject):
    """Async TCP client that forwards messages to the Qt thread."""

    message_received = pyqtSignal(dict)
    status_changed = pyqtSignal(str)

    def __init__(self, port_file: Path, loop_sleep: float = 1.0) -> None:
        super().__init__()
        self._port_file = port_file
        self._loop_sleep = loop_sleep
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._stop_event = threading.Event()
        self._last_metadata: Dict[str, Any] = {}
        self._outgoing: Optional[asyncio.Queue[Optional[Dict[str, Any]]]] = None
        self._pending: "queue.Queue[Dict[str, Any]]" = queue.Queue(maxsize=32)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._thread_main, name="EDMCOverlay-Client", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(lambda: None)
        if self._thread:
            self._thread.join(timeout=5.0)
        self._loop = None
        self._thread = None
        self._outgoing = None

    def send_cli_payload(self, payload: Mapping[str, Any]) -> bool:
        message = dict(payload)
        loop = self._loop
        queue_ref = self._outgoing
        if loop is not None and queue_ref is not None:
            try:
                loop.call_soon_threadsafe(queue_ref.put_nowait, message)
                return True
            except Exception:
                pass
        try:
            self._pending.put_nowait(message)
        except queue.Full:
            return False
        return True

    # Background thread ----------------------------------------------------

    def _thread_main(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._run())
        finally:
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.close()

    async def _run(self) -> None:
        backoff = 1.0
        while not self._stop_event.is_set():
            metadata = self._read_port()
            if metadata is None:
                self.status_changed.emit("Waiting for port.json…")
                await asyncio.sleep(self._loop_sleep)
                continue
            port = metadata["port"]
            plugin_version = metadata.get("version") or MODERN_OVERLAY_VERSION
            reader = None
            writer = None
            try:
                reader, writer = await asyncio.open_connection("127.0.0.1", port)
            except Exception as exc:
                self.status_changed.emit(f"Connect failed: {exc}")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 1.5, 10.0)
                continue

            script_label = MODERN_OVERLAY_VERSION if MODERN_OVERLAY_VERSION and MODERN_OVERLAY_VERSION != "unknown" else "unknown"
            if script_label != "unknown" and not script_label.lower().startswith("v"):
                script_label = f"v{script_label}"
            connection_prefix = script_label if script_label != "unknown" else "unknown"
            flatpak_suffix = ""
            if metadata.get("flatpak"):
                app_label = metadata.get("flatpak_app")
                flatpak_suffix = f" (Flatpak: {app_label})" if app_label else " (Flatpak)"
            connection_message = f"{connection_prefix} - Connected to 127.0.0.1:{port}{flatpak_suffix}"
            _CLIENT_LOGGER.debug("Status banner updated: %s", connection_message)
            self.status_changed.emit(connection_message)
            backoff = 1.0
            outgoing_queue: asyncio.Queue[Optional[Dict[str, Any]]] = asyncio.Queue()
            self._outgoing = outgoing_queue
            while not self._pending.empty():
                try:
                    pending_payload = self._pending.get_nowait()
                except queue.Empty:
                    break
                try:
                    outgoing_queue.put_nowait(pending_payload)
                except asyncio.QueueFull:
                    break
            sender_task = asyncio.create_task(self._flush_outgoing(writer, outgoing_queue))
            try:
                while not self._stop_event.is_set():
                    line = await reader.readline()
                    if not line:
                        raise ConnectionError("Server closed the connection")
                    try:
                        payload = json.loads(line.decode("utf-8"))
                    except json.JSONDecodeError:
                        continue
                    self.message_received.emit(payload)
            except Exception as exc:
                self.status_changed.emit(f"Disconnected: {exc}")
            finally:
                self._outgoing = None
                try:
                    outgoing_queue.put_nowait(None)
                except Exception:
                    pass
                try:
                    await sender_task
                except Exception:
                    pass
                if writer is not None:
                    try:
                        writer.close()
                        await writer.wait_closed()
                    except Exception:
                        pass
            await asyncio.sleep(backoff)
            backoff = min(backoff * 1.5, 10.0)

    async def _flush_outgoing(
        self,
        writer: asyncio.StreamWriter,
        queue_ref: "asyncio.Queue[Optional[Dict[str, Any]]]",
    ) -> None:
        while not self._stop_event.is_set():
            try:
                payload = await queue_ref.get()
            except Exception:
                break
            if payload is None:
                break
            try:
                serialised = json.dumps(payload, ensure_ascii=False)
            except Exception:
                continue
            try:
                writer.write(serialised.encode("utf-8") + b"\n")
                await writer.drain()
            except Exception:
                break

    def _read_port(self) -> Optional[Dict[str, Any]]:
        try:
            data = json.loads(self._port_file.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except json.JSONDecodeError:
            return None
        port = data.get("port")
        if isinstance(port, int) and port > 0:
            data["port"] = port
            self._last_metadata = data
            return data
        return None

class OverlayWindow(QWidget):
    """Transparent overlay that renders CMDR and location info."""

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
        self._legacy_items = LegacyItemStore()
        setattr(self._legacy_items, "_trace_callback", self._trace_legacy_store_event)
        self._background_opacity: float = 0.0
        self._gridlines_enabled: bool = False
        self._gridline_spacing: int = 120
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
        self._follow_resume_at: float = 0.0
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
        self._wm_authoritative_rect: Optional[Tuple[int, int, int, int]] = None
        self._wm_override_tracker: Optional[Tuple[int, int, int, int]] = None
        self._wm_override_timestamp: float = 0.0
        self._wm_override_reason: Optional[str] = None
        self._wm_override_classification: Optional[str] = None
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
        self._offscreen_payloads: Set[str] = set()

        self._legacy_timer = QTimer(self)
        self._legacy_timer.setInterval(250)
        self._legacy_timer.timeout.connect(self._purge_legacy)
        self._legacy_timer.start()

        self._modifier_timer = QTimer(self)
        self._modifier_timer.setInterval(100)
        self._modifier_timer.timeout.connect(self._poll_modifiers)
        self._modifier_timer.start()

        self._tracking_timer = QTimer(self)
        self._tracking_timer.setInterval(250)
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
        width = max(frame.width(), 1)
        height = max(frame.height(), 1)
        ratio = 1.0
        window = self.windowHandle()
        if window is not None:
            try:
                ratio = window.devicePixelRatio()
            except Exception:
                ratio = 1.0
        if ratio <= 0.0:
            ratio = 1.0
        return width * ratio, height * ratio

    @staticmethod
    def _aspect_ratio_label(width: int, height: int) -> Optional[str]:
        if width <= 0 or height <= 0:
            return None
        ratio = width / float(height)
        known_ratios = (
            ("32:9", 32 / 9),
            ("21:9", 21 / 9),
            ("18:9", 18 / 9),
            ("16:10", 16 / 10),
            ("16:9", 16 / 9),
            ("3:2", 3 / 2),
            ("4:3", 4 / 3),
            ("5:4", 5 / 4),
            ("1:1", 1.0),
        )
        for label, target in known_ratios:
            if target <= 0:
                continue
            if abs(ratio - target) / target < 0.03:  # within ~3%
                return label
        frac = Fraction(width, height).limit_denominator(100)
        return f"{frac.numerator}:{frac.denominator}"

    def _compute_legacy_mapper(self) -> LegacyMapper:
        width = max(float(self.width()), 1.0)
        height = max(float(self.height()), 1.0)
        mode_value = (self._scale_mode or "fit").strip().lower()
        try:
            mode_enum = ScaleMode(mode_value)
        except ValueError:
            mode_enum = ScaleMode.FIT
        transform = compute_viewport_transform(width, height, mode_enum)
        base_scale = max(transform.scale, 0.0)
        scale_x = base_scale
        scale_y = base_scale
        offset_x = transform.offset[0]
        offset_y = transform.offset[1]
        return LegacyMapper(
            scale_x=max(scale_x, 0.0),
            scale_y=max(scale_y, 0.0),
            offset_x=offset_x,
            offset_y=offset_y,
            transform=transform,
        )

    def _viewport_state(self) -> ViewportState:
        width = max(float(self.width()), 1.0)
        height = max(float(self.height()), 1.0)
        try:
            ratio = self.devicePixelRatioF()
        except Exception:
            ratio = 1.0
        if ratio <= 0.0:
            ratio = 1.0
        return ViewportState(width=width, height=height, device_ratio=ratio)

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
        return base_x, base_y

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
        scale = getattr(fill, "scale", 0.0)
        if not math.isfinite(scale) or math.isclose(scale, 0.0, rel_tol=1e-9, abs_tol=1e-9):
            return value_x, value_y
        if math.isclose(scale, 1.0, rel_tol=1e-9, abs_tol=1e-9):
            return value_x, value_y
        anchor_x = anchor[0] if anchor is not None else None
        anchor_y = anchor[1] if anchor is not None else None
        base_x = base_anchor[0] if base_anchor is not None else None
        base_y = base_anchor[1] if base_anchor is not None else None
        adjusted_x = inverse_group_axis(
            value_x,
            scale,
            getattr(fill, "overflow_x", False),
            anchor_x,
            base_x if (base_x is not None and not getattr(fill, "overflow_x", False)) else anchor_x,
        )
        adjusted_y = inverse_group_axis(
            value_y,
            scale,
            getattr(fill, "overflow_y", False),
            anchor_y,
            base_y if (base_y is not None and not getattr(fill, "overflow_y", False)) else anchor_y,
        )
        return adjusted_x, adjusted_y

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
        for item_id, item in list(self._legacy_items.items()):
            self._legacy_items.set(item_id, item)

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
            grid_color = QColor(200, 200, 200, grid_alpha)
            grid_pen = QPen(grid_color)
            grid_pen.setWidth(self._line_width("grid"))
            painter.setPen(grid_pen)
            spacing = self._gridline_spacing
            width = self.width()
            height = self.height()
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
            # Origin label
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
        self._paint_legacy(painter)
        self._paint_overlay_outline(painter)
        self._paint_cycle_overlay(painter)
        if self._show_debug_overlay:
            self._paint_debug_overlay(painter)
        painter.end()
        super().paintEvent(event)

    # Interaction -------------------------------------------------

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
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
        ids = [item_id for item_id, _ in self._legacy_items.items()]
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
        scale_value = fill.scale

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
        if not self._cycle_payload_enabled:
            return
        self._sync_cycle_items()
        if not self._cycle_current_id:
            return
        mapper = self._compute_legacy_mapper()
        anchor = self._cycle_anchor_points.get(self._cycle_current_id)
        plugin_name = "unknown"
        current_item = self._legacy_items.get(self._cycle_current_id)
        if current_item is not None:
            name = current_item.plugin
            if isinstance(name, str) and name:
                plugin_name = name
        group_transform: Optional[GroupTransform] = None
        if current_item is not None:
            group_transform = self._grouping_helper.transform_for_item(current_item.item_id, current_item.plugin)
        plugin_line = f"Plugin name: {plugin_name}"
        if anchor is not None:
            center_line = f"Center: {anchor[0]}, {anchor[1]}"
        else:
            center_line = "Center: -, -"
        data = current_item.data if current_item is not None else {}
        info_lines: List[str] = []
        if current_item is not None:
            if current_item.expiry is None:
                info_lines.append("ttl: ∞")
            else:
                remaining = max(0.0, current_item.expiry - time.monotonic())
                info_lines.append(f"ttl: {remaining:.1f}s")
        updated_iso = data.get("__mo_updated__") if isinstance(data, Mapping) else None
        if isinstance(updated_iso, str):
            try:
                updated_dt = datetime.fromisoformat(updated_iso)
                if updated_dt.tzinfo is None:
                    updated_dt = updated_dt.replace(tzinfo=UTC)
                elapsed = datetime.now(UTC) - updated_dt.astimezone(UTC)
                elapsed_s = max(0.0, elapsed.total_seconds())
                info_lines.append(f"last seen: {elapsed_s:.1f}s ago")
            except Exception:
                info_lines.append(f"last seen: {updated_iso}")
        kind_label = current_item.kind if current_item is not None else None
        if kind_label == "message":
            size_label = str(data.get("size", "unknown"))
            info_lines.append(f"type: message (size={size_label})")
        elif kind_label == "rect":
            w_val = data.get("w")
            h_val = data.get("h")
            if isinstance(w_val, (int, float)) and isinstance(h_val, (int, float)):
                info_lines.append(f"type: rect (w={w_val}, h={h_val})")
            else:
                info_lines.append("type: rect")
        elif kind_label == "vector":
            points_data = data.get("points")
            if isinstance(points_data, list):
                info_lines.append(f"type: vector (points={len(points_data)})")
            else:
                info_lines.append("type: vector")
        elif kind_label:
            info_lines.append(f"type: {kind_label}")

        def _fmt_number(value: Any) -> Optional[str]:
            if isinstance(value, (int, float)):
                return f"{value:g}"
            return None

        transform_meta = data.get("__mo_transform__") if isinstance(data, Mapping) else None
        if isinstance(transform_meta, Mapping):
            original = transform_meta.get("original")
            if isinstance(original, Mapping):
                raw_x_fmt = _fmt_number(original.get("x"))
                raw_y_fmt = _fmt_number(original.get("y"))
                trans_x_fmt = _fmt_number(data.get("x"))
                trans_y_fmt = _fmt_number(data.get("y"))
                if raw_x_fmt is not None and raw_y_fmt is not None and trans_x_fmt is not None and trans_y_fmt is not None:
                    info_lines.append(f"coords: ({raw_x_fmt},{raw_y_fmt}) → ({trans_x_fmt},{trans_y_fmt})")
                raw_w_fmt = _fmt_number(original.get("w"))
                raw_h_fmt = _fmt_number(original.get("h"))
                trans_w_fmt = _fmt_number(data.get("w"))
                trans_h_fmt = _fmt_number(data.get("h"))
                size_parts: List[str] = []
                if raw_w_fmt is not None and trans_w_fmt is not None:
                    size_parts.append(f"w={raw_w_fmt}→{trans_w_fmt}")
                if raw_h_fmt is not None and trans_h_fmt is not None:
                    size_parts.append(f"h={raw_h_fmt}→{trans_h_fmt}")
                if size_parts:
                    info_lines.append("size: " + ", ".join(size_parts))
        transform_lines = self._format_transform_chain(current_item, mapper, group_transform)
        override_lines = self._format_override_lines(current_item)
        painter.save()
        text = self._cycle_current_id
        highlight_color = QColor("#ffb347")
        background = QColor(0, 0, 0, 180)
        font = QFont(self._font_family)
        self._apply_font_fallbacks(font)
        state = self._viewport_state()
        title_point = max(
            20.0,
            viewport_scaled_point_size(
                state,
                18.0,
                self._font_scale_diag,
                self._font_min_point,
                self._font_max_point,
                mapper,
                use_physical=True,
            ),
        )
        font.setPointSizeF(title_point)
        font.setWeight(QFont.Weight.Bold)
        painter.setFont(font)
        metrics = painter.fontMetrics()
        text_width = metrics.horizontalAdvance(text)
        plugin_font = QFont(self._font_family)
        self._apply_font_fallbacks(plugin_font)
        plugin_point = max(12.0, min(title_point - 4.0, title_point * 0.8))
        plugin_font.setPointSizeF(plugin_point)
        plugin_font.setWeight(QFont.Weight.Normal)
        plugin_metrics = QFontMetrics(plugin_font)
        center_x = self.width() // 2
        center_y = self.height() // 2
        padding_x = 12
        padding_y = 8
        line_height_title = metrics.lineSpacing()
        line_height_plugin = plugin_metrics.lineSpacing()
        small_lines = [plugin_line, center_line] + info_lines + transform_lines + override_lines
        small_widths = [plugin_metrics.horizontalAdvance(line) for line in small_lines]
        content_width = max([text_width, *small_widths] if small_widths else [text_width])
        rect_width = content_width + padding_x * 2
        rect_height = line_height_title + len(small_lines) * line_height_plugin + padding_y * 2
        rect_left = center_x - rect_width // 2
        rect_top = center_y - rect_height // 2
        rect_right = rect_left + rect_width
        rect_bottom = rect_top + rect_height
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(background)
        painter.drawRoundedRect(rect_left, rect_top, rect_width, rect_height, 10, 10)
        painter.setPen(highlight_color)
        baseline_top = rect_top + padding_y + metrics.ascent()
        painter.drawText(center_x - text_width // 2, baseline_top, text)
        painter.setFont(plugin_font)
        baseline_line = baseline_top + line_height_title
        for line, width in zip(small_lines, small_widths):
            painter.drawText(center_x - width // 2, baseline_line, line)
            baseline_line += line_height_plugin
        if anchor is not None:
            start_x = center_x
            start_y = center_y
            dx = anchor[0] - center_x
            dy = anchor[1] - center_y
            if dx != 0 or dy != 0:
                candidates: List[float] = []
                if dx > 0:
                    candidates.append((rect_right - center_x) / dx)
                elif dx < 0:
                    candidates.append((rect_left - center_x) / dx)
                if dy > 0:
                    candidates.append((rect_bottom - center_y) / dy)
                elif dy < 0:
                    candidates.append((rect_top - center_y) / dy)
                t_min = min((t for t in candidates if t >= 0.0), default=0.0)
                if t_min > 0.0:
                    start_x = int(round(center_x + dx * t_min))
                    start_y = int(round(center_y + dy * t_min))
                else:
                    start_x = center_x
                    start_y = rect_top + rect_height
            else:
                start_x = center_x
                start_y = rect_top + rect_height
            painter.setPen(QPen(highlight_color, self._line_width("cycle_connector")))
            painter.drawLine(start_x, start_y, anchor[0], anchor[1])
            painter.setBrush(highlight_color)
            painter.drawEllipse(anchor[0] - 4, anchor[1] - 4, 8, 8)
        painter.restore()

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
            "plugin": "EDMC-ModernOverlay",
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
            "plugin": "EDMC-ModernOverlay",
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

    def set_background_opacity(self, opacity: float) -> None:
        try:
            value = float(opacity)
        except (TypeError, ValueError):
            value = 0.0
        value = max(0.0, min(1.0, value))
        if value != self._background_opacity:
            self._background_opacity = value
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
            if self._wm_authoritative_rect is not None:
                self._clear_wm_override(reason="title_bar_compensation_changed")
            _CLIENT_LOGGER.debug(
                "Title bar compensation updated: enabled=%s height=%d",
                self._title_bar_enabled,
                self._title_bar_height,
            )
            self._follow_resume_at = 0.0
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
        if not self._tracking_timer.isActive():
            self._tracking_timer.start()

    def _stop_tracking(self) -> None:
        if self._tracking_timer.isActive():
            self._tracking_timer.stop()

    def _set_wm_override(
        self,
        rect: Tuple[int, int, int, int],
        tracker_tuple: Optional[Tuple[int, int, int, int]],
        reason: str,
        classification: str = "wm_intervention",
    ) -> None:
        self._wm_authoritative_rect = rect
        self._wm_override_tracker = tracker_tuple
        self._wm_override_timestamp = time.monotonic()
        self._wm_override_reason = reason
        self._wm_override_classification = classification
        _CLIENT_LOGGER.debug(
            "Recorded WM authoritative rect (%s, classification=%s): actual=%s tracker=%s; %s",
            reason,
            classification,
            rect,
            tracker_tuple,
            self.format_scale_debug(),
        )

    def _clear_wm_override(self, reason: str) -> None:
        if self._wm_authoritative_rect is None:
            return
        _CLIENT_LOGGER.debug(
            "Clearing WM authoritative rect (%s); %s",
            reason,
            self.format_scale_debug(),
        )
        self._wm_authoritative_rect = None
        self._wm_override_tracker = None
        self._wm_override_timestamp = 0.0
        self._wm_override_reason = None
        self._wm_override_classification = None

    def _suspend_follow(self, delay: float = 0.75) -> None:
        self._follow_resume_at = max(self._follow_resume_at, time.monotonic() + max(0.0, delay))

    def _refresh_follow_geometry(self) -> None:
        if not self._follow_enabled or self._window_tracker is None:
            return
        now = time.monotonic()
        if self._drag_active or self._move_mode:
            self._suspend_follow(0.75)
            _CLIENT_LOGGER.debug("Skipping follow refresh: drag/move active; %s", self.format_scale_debug())
            return
        if now < self._follow_resume_at:
            _CLIENT_LOGGER.debug("Skipping follow refresh: awaiting resume window; %s", self.format_scale_debug())
            return
        try:
            state = self._window_tracker.poll()
        except Exception as exc:  # pragma: no cover - defensive guard
            _CLIENT_LOGGER.debug("Window tracker poll failed: %s; %s", exc, self.format_scale_debug())
            return
        if state is None:
            self._handle_missing_follow_state()
            return
        global_x = state.global_x if state.global_x is not None else state.x
        global_y = state.global_y if state.global_y is not None else state.y
        tracker_key = (state.identifier, global_x, global_y, state.width, state.height)
        if tracker_key != self._last_tracker_state:
            _CLIENT_LOGGER.debug(
                "Tracker state: id=%s global=(%d,%d) size=%dx%d foreground=%s visible=%s; %s",
                state.identifier,
                global_x,
                global_y,
                state.width,
                state.height,
                state.is_foreground,
                state.is_visible,
                self.format_scale_debug(),
            )
            self._last_tracker_state = tracker_key
        self._apply_follow_state(state)

    def _apply_title_bar_offset(
        self,
        geometry: Tuple[int, int, int, int],
        *,
        scale_y: float = 1.0,
    ) -> Tuple[Tuple[int, int, int, int], int]:
        previous_offset = self._last_title_bar_offset
        if not self._title_bar_enabled or self._title_bar_height <= 0:
            self._last_title_bar_offset = 0
            if previous_offset != 0:
                _CLIENT_LOGGER.debug(
                    "Title bar offset updated: enabled=%s height=%d offset=%d scale_y=%.3f",
                    False,
                    self._title_bar_height,
                    0,
                    float(scale_y),
                )
            return geometry, 0
        x, y, width, height = geometry
        if height <= 1:
            self._last_title_bar_offset = 0
            if previous_offset != 0:
                _CLIENT_LOGGER.debug(
                    "Title bar offset updated: enabled=%s height=%d offset=%d scale_y=%.3f",
                    self._title_bar_enabled,
                    self._title_bar_height,
                    0,
                    float(scale_y),
                )
            return geometry, 0
        safe_scale = max(scale_y, 0.0)
        scaled_offset = float(self._title_bar_height) * safe_scale
        offset = min(int(round(scaled_offset)), max(0, height - 1))
        if offset <= 0:
            self._last_title_bar_offset = 0
            if previous_offset != 0:
                _CLIENT_LOGGER.debug(
                    "Title bar offset updated: enabled=%s height=%d offset=%d scale_y=%.3f",
                    self._title_bar_enabled,
                    self._title_bar_height,
                    0,
                    float(scale_y),
                )
            return geometry, 0
        adjusted_height = max(1, height - offset)
        self._last_title_bar_offset = offset
        if offset != previous_offset:
            _CLIENT_LOGGER.debug(
                "Title bar offset updated: enabled=%s height=%d offset=%d scale_y=%.3f",
                self._title_bar_enabled,
                self._title_bar_height,
                offset,
                float(scale_y),
            )
        return (x, y + offset, width, adjusted_height), offset

    def _apply_follow_state(self, state: WindowState) -> None:
        self._lost_window_logged = False

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

        now = time.monotonic()
        target_tuple = desired_tuple
        if self._wm_authoritative_rect is not None:
            tracker_changed = (
                self._wm_override_tracker is not None
                and tracker_qt_tuple != self._wm_override_tracker
            )
            override_expired = (
                self._wm_override_classification not in ("layout", "layout_constraint")
                and (now - self._wm_override_timestamp) >= self._WM_OVERRIDE_TTL
            )
            if tracker_qt_tuple == self._wm_authoritative_rect:
                self._clear_wm_override(reason="tracker realigned with WM")
            elif tracker_changed:
                self._clear_wm_override(reason="tracker changed")
            elif override_expired:
                self._clear_wm_override(reason="override timeout")
            else:
                target_tuple = self._wm_authoritative_rect

        target_rect = QRect(*target_tuple)
        current_rect = self.frameGeometry()
        actual_tuple = (
            current_rect.x(),
            current_rect.y(),
            current_rect.width(),
            current_rect.height(),
        )

        if target_tuple != self._last_geometry_log:
            _CLIENT_LOGGER.debug(
                "Calculated overlay geometry: target=%s; %s",
                target_tuple,
                self.format_scale_debug(),
            )

        needs_geometry_update = actual_tuple != target_tuple

        if needs_geometry_update:
            _CLIENT_LOGGER.debug("Applying geometry via setGeometry: target=%s; %s", target_tuple, self.format_scale_debug())
            self._move_to_screen(target_rect)
            self._last_set_geometry = target_tuple
            self.setGeometry(target_rect)
            self._sync_base_dimensions_to_widget()
            self.raise_()
            current_rect = self.frameGeometry()
            actual_tuple = (
                current_rect.x(),
                current_rect.y(),
                current_rect.width(),
                current_rect.height(),
            )
        else:
            self._last_set_geometry = target_tuple
            self._sync_base_dimensions_to_widget()

        if actual_tuple != target_tuple:
            _CLIENT_LOGGER.debug(
                "Window manager override detected: actual=%s target=%s; %s",
                actual_tuple,
                target_tuple,
                self.format_scale_debug(),
            )
            classification = self._classify_geometry_override(target_tuple, actual_tuple)
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
                    actual_tuple,
                    size_hint,
                    min_hint,
                )
            else:
                _CLIENT_LOGGER.debug(
                    "Adopting WM authoritative geometry: tracker=%s actual=%s (classification=%s)",
                    tracker_qt_tuple,
                    actual_tuple,
                    classification,
                )
            self._set_wm_override(
                actual_tuple,
                tracker_qt_tuple,
                reason="geometry mismatch",
                classification=classification,
            )
            target_tuple = actual_tuple
            target_rect = QRect(*target_tuple)
        elif self._wm_authoritative_rect and tracker_qt_tuple == target_tuple:
            self._clear_wm_override(reason="tracker matched actual")

        self._last_geometry_log = target_tuple
        self._last_follow_state = WindowState(
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

        self._update_auto_legacy_scale(target_tuple[2], target_tuple[3])
        self._ensure_transient_parent(state)
        if (
            sys.platform.startswith("linux")
            and not self._fullscreen_hint_logged
            and state.is_foreground
        ):
            screen = self.windowHandle().screen() if self.windowHandle() else None
            if screen is None:
                screen = QGuiApplication.primaryScreen()
            if screen is not None:
                geometry = screen.geometry()
                if state.width >= geometry.width() and state.height >= geometry.height():
                    _CLIENT_LOGGER.info(
                        "Overlay running in compositor-managed mode; for true fullscreen use borderless windowed in Elite or enable compositor vsync. (%s)",
                        self.format_scale_debug(),
                    )
                    self._fullscreen_hint_logged = True

        should_show = self._force_render or (state.is_visible and state.is_foreground)
        self._update_follow_visibility(should_show)

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

    def _convert_native_rect_to_qt(
        self,
        rect: Tuple[int, int, int, int],
    ) -> Tuple[Tuple[int, int, int, int], Optional[Tuple[str, float, float, float]]]:
        x, y, width, height = rect
        if width <= 0 or height <= 0:
            return rect, None
        native_rect = QRect(x, y, width, height)
        screen = self._screen_for_native_rect(native_rect)
        if screen is None:
            return rect, None
        try:
            native_geometry = screen.nativeGeometry()
        except AttributeError:
            native_geometry = screen.geometry()
        logical_geometry = screen.geometry()
        native_width = native_geometry.width()
        native_height = native_geometry.height()
        device_ratio = 1.0
        try:
            device_ratio = float(screen.devicePixelRatio())
        except Exception:
            device_ratio = 1.0
        if device_ratio <= 0.0:
            device_ratio = 1.0

        scale_x = logical_geometry.width() / native_width if native_width else 1.0
        scale_y = logical_geometry.height() / native_height if native_height else 1.0

        if math.isclose(scale_x, 1.0, abs_tol=1e-4):
            scale_x = 1.0 / device_ratio
        if math.isclose(scale_y, 1.0, abs_tol=1e-4):
            scale_y = 1.0 / device_ratio

        native_origin_x = native_geometry.x()
        native_origin_y = native_geometry.y()
        if math.isclose(native_origin_x, logical_geometry.x(), abs_tol=1e-4):
            native_origin_x = logical_geometry.x() * device_ratio
        if math.isclose(native_origin_y, logical_geometry.y(), abs_tol=1e-4):
            native_origin_y = logical_geometry.y() * device_ratio

        qt_x = logical_geometry.x() + (x - native_origin_x) * scale_x
        qt_y = logical_geometry.y() + (y - native_origin_y) * scale_y
        qt_width = width * scale_x
        qt_height = height * scale_y
        converted = (
            int(round(qt_x)),
            int(round(qt_y)),
            max(1, int(round(qt_width))),
            max(1, int(round(qt_height))),
        )
        screen_name = screen.name() or screen.manufacturer() or "unknown"
        return converted, (screen_name, float(scale_x), float(scale_y), device_ratio)

    def _apply_aspect_guard(
        self,
        geometry: Tuple[int, int, int, int],
        *,
        original_geometry: Optional[Tuple[int, int, int, int]] = None,
        applied_title_offset: int = 0,
    ) -> Tuple[int, int, int, int]:
        x, y, width, height = geometry
        if width <= 0 or height <= 0:
            return geometry
        base_ratio = DEFAULT_WINDOW_BASE_WIDTH / float(DEFAULT_WINDOW_BASE_HEIGHT)
        current_ratio = width / float(height)
        original_ratio = None
        if original_geometry is not None:
            _, _, original_width, original_height = original_geometry
            if original_width > 0 and original_height > 0:
                original_ratio = original_width / float(original_height)
        ratio_for_check = original_ratio if original_ratio is not None else current_ratio
        if abs(ratio_for_check - base_ratio) > 0.04:
            if not self._aspect_guard_skip_logged:
                _CLIENT_LOGGER.debug(
                    "Aspect guard skipped: tracker_ratio=%.3f current_ratio=%.3f base_ratio=%.3f offset=%d",
                    ratio_for_check,
                    current_ratio,
                    base_ratio,
                    int(applied_title_offset),
                )
                self._aspect_guard_skip_logged = True
            return geometry
        self._aspect_guard_skip_logged = False
        expected_height = int(round(width * DEFAULT_WINDOW_BASE_HEIGHT / float(DEFAULT_WINDOW_BASE_WIDTH)))
        tolerance = max(2, int(round(expected_height * 0.01)))
        if height <= expected_height:
            return geometry
        height_delta = height - expected_height
        max_delta = max(6, int(round(width * 0.02)))
        if height_delta > max_delta:
            return geometry
        if height_delta > 0:
            adjusted = (x, y, width, expected_height)
            _CLIENT_LOGGER.debug(
                "Aspect guard trimmed overlay height: width=%d height=%d expected=%d tolerance=%d -> adjusted=%s",
                width,
                height,
                expected_height,
                tolerance,
                adjusted,
            )
            return adjusted
        return geometry

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

        if process_legacy_payload(self._legacy_items, payload, trace_fn=trace_fn):
            if self._cycle_payload_enabled:
                self._sync_cycle_items()
            self.update()

    def _purge_legacy(self) -> None:
        now = time.monotonic()
        if self._legacy_items.purge_expired(now):
            if self._cycle_payload_enabled:
                self._sync_cycle_items()
            self.update()

    def _paint_legacy(self, painter: QPainter) -> None:
        self._cycle_anchor_points = {}
        mapper = self._compute_legacy_mapper()
        if mapper.transform.mode is ScaleMode.FILL:
            self._grouping_helper.prepare(mapper)
        else:
            self._grouping_helper.reset()
        draw_group_bounds = self._debug_config.group_bounds_outline
        overlay_bounds_hint: Optional[Dict[Tuple[str, Optional[str]], _OverlayBounds]] = None
        commands: List[_LegacyPaintCommand] = []
        bounds_by_group: Dict[Tuple[str, Optional[str]], _ScreenBounds] = {}
        overlay_bounds_by_group: Dict[Tuple[str, Optional[str]], _OverlayBounds] = {}
        effective_anchor_by_group: Dict[Tuple[str, Optional[str]], Tuple[float, float]] = {}
        transform_by_group: Dict[Tuple[str, Optional[str]], Optional[GroupTransform]] = {}
        effective_anchor_by_group: Dict[Tuple[str, Optional[str]], Tuple[float, float]] = {}
        anchor_offset_by_group: Dict[Tuple[str, Optional[str]], Tuple[float, float]] = {}
        passes = 2 if self._legacy_items else 1
        for pass_index in range(passes):
            commands, bounds_by_group, overlay_bounds_by_group, effective_anchor_by_group, transform_by_group, anchor_offset_by_group = self._build_legacy_commands_for_pass(
                mapper,
                overlay_bounds_hint,
                collect_only=(pass_index == 0 and passes > 1),
            )
            overlay_bounds_hint = overlay_bounds_by_group
            if not self._legacy_items:
                break

        anchor_translation_by_group, translated_bounds_by_group = self._prepare_anchor_translations(
            mapper,
            bounds_by_group,
            overlay_bounds_by_group,
            effective_anchor_by_group,
            transform_by_group,
            anchor_offset_by_group,
        )
        translations = self._compute_group_nudges(translated_bounds_by_group)
        drawn_groups: Set[Tuple[str, Optional[str]]] = set()
        window_width = max(self.width(), 0)
        window_height = max(self.height(), 0)
        for command in commands:
            key_tuple = command.group_key.as_tuple()
            translation_x, translation_y = anchor_translation_by_group.get(key_tuple, (0.0, 0.0))
            nudge_x, nudge_y = translations.get(key_tuple, (0, 0))
            offset_x = translation_x + nudge_x
            offset_y = translation_y + nudge_y
            self._log_offscreen_payload(command, offset_x, offset_y, window_width, window_height)
            command.paint(self, painter, offset_x, offset_y)
            if draw_group_bounds:
                if command.group_transform is not None:
                    if key_tuple not in drawn_groups:
                        drawn_groups.add(key_tuple)
                        self._draw_group_bounds_outline_with_offset(
                            painter,
                            mapper,
                            command.group_transform,
                            overlay_bounds_by_group.get(key_tuple),
                            effective_anchor_by_group.get(key_tuple),
                            anchor_offset_by_group.get(key_tuple),
                            offset_x,
                            offset_y,
                        )
                else:
                    self._draw_item_bounds_outline_with_offset(
                        painter,
                        mapper,
                        command.legacy_item,
                        offset_x,
                        offset_y,
                    )

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
        Dict[Tuple[str, Optional[str]], Tuple[float, float]],
    ]:
        commands: List[_LegacyPaintCommand] = []
        bounds_by_group: Dict[Tuple[str, Optional[str]], _ScreenBounds] = {}
        overlay_bounds_by_group: Dict[Tuple[str, Optional[str]], _OverlayBounds] = {}
        effective_anchor_by_group: Dict[Tuple[str, Optional[str]], Tuple[float, float]] = {}
        anchor_offset_by_group: Dict[Tuple[str, Optional[str]], Tuple[float, float]] = {}
        transform_by_group: Dict[Tuple[str, Optional[str]], Optional[GroupTransform]] = {}
        for item_id, legacy_item in self._legacy_items.items():
            group_key = self._grouping_helper.group_key_for(item_id, legacy_item.plugin)
            group_transform = self._grouping_helper.get_transform(group_key)
            transform_by_group[group_key.as_tuple()] = group_transform
            overlay_hint = overlay_bounds_hint.get(group_key.as_tuple()) if overlay_bounds_hint else None
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
                if command.anchor_offset is not None:
                    anchor_offset_by_group[command.group_key.as_tuple()] = command.anchor_offset
            if command.overlay_bounds:
                overlay_bounds = overlay_bounds_by_group.setdefault(command.group_key.as_tuple(), _OverlayBounds())
                overlay_bounds.include_rect(*command.overlay_bounds)
            if collect_only:
                continue
        return commands, bounds_by_group, overlay_bounds_by_group, effective_anchor_by_group, transform_by_group, anchor_offset_by_group

    def _prepare_anchor_translations(
        self,
        mapper: LegacyMapper,
        bounds_by_group: Mapping[Tuple[str, Optional[str]], _ScreenBounds],
        overlay_bounds_by_group: Mapping[Tuple[str, Optional[str]], _OverlayBounds],
        effective_anchor_by_group: Mapping[Tuple[str, Optional[str]], Tuple[float, float]],
        transform_by_group: Mapping[Tuple[str, Optional[str]], Optional[GroupTransform]],
        anchor_offset_by_group: Mapping[Tuple[str, Optional[str]], Tuple[float, float]],
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
                delta = anchor_offset_by_group.get(key)
                if delta is None:
                    continue
                translation_overlay_x = -delta[0]
                translation_overlay_y = -delta[1]
            if not (math.isfinite(translation_overlay_x) and math.isfinite(translation_overlay_y)):
                continue
            translation_px_x = translation_overlay_x * base_scale
            translation_px_y = translation_overlay_y * base_scale
            translations[key] = (translation_px_x, translation_px_y)
            clone = cloned_bounds.get(key)
            if clone is not None:
                clone.translate(translation_px_x, translation_px_y)
        return translations, cloned_bounds

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
    def _group_offset_for_transform(transform: Optional[GroupTransform]) -> Tuple[float, float]:
        if transform is None:
            return 0.0, 0.0
        dx = getattr(transform, "dx", 0.0)
        dy = getattr(transform, "dy", 0.0)
        if not isinstance(dx, (int, float)) or not math.isfinite(dx):
            dx = 0.0
        if not isinstance(dy, (int, float)) or not math.isfinite(dy):
            dy = 0.0
        return float(dx), float(dy)

    def _legacy_preset_point_size(self, preset: str, state: ViewportState, mapper: LegacyMapper) -> float:
        """Return the scaled font size for a legacy preset relative to normal."""
        normal_point = viewport_scaled_point_size(
            state,
            10.0,
            self._font_scale_diag,
            self._font_min_point,
            self._font_max_point,
            mapper,
            use_physical=True,
        )
        offsets = {
            "small": -2.0,
            "normal": 0.0,
            "large": 2.0,
            "huge": 4.0,
        }
        target = normal_point + offsets.get(preset.lower(), 0.0)
        return max(1.0, target)

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
        fill = build_viewport(mapper, state, group_transform, BASE_WIDTH, BASE_HEIGHT)
        transform_context = build_payload_transform_context(fill)
        scale = fill.scale
        base_offset_x = fill.base_offset_x
        base_offset_y = fill.base_offset_y
        selected_anchor: Optional[Tuple[float, float]] = None
        base_anchor_point: Optional[Tuple[float, float]] = None
        anchor_for_transform: Optional[Tuple[float, float]] = None
        base_translation_dx = 0.0
        base_translation_dy = 0.0
        effective_anchor: Optional[Tuple[float, float]] = None
        anchor_offset: Optional[Tuple[float, float]] = None
        group_offset_dx, group_offset_dy = self._group_offset_for_transform(group_transform)
        if mapper.transform.mode is ScaleMode.FILL:
            use_overlay_bounds_x = (
                overlay_bounds_hint is not None
                and overlay_bounds_hint.is_valid()
                and not fill.overflow_x
            )
            base_anchor_point = self._group_base_point(
                group_transform,
                transform_context,
                overlay_bounds_hint,
                use_overlay_bounds_x=use_overlay_bounds_x,
            )
            anchor_for_transform = base_anchor_point
            if overlay_bounds_hint is not None and overlay_bounds_hint.is_valid():
                selected_anchor = self._group_anchor_point(
                    group_transform,
                    transform_context,
                    overlay_bounds_hint,
                    use_overlay_bounds_x=use_overlay_bounds_x,
                )
            if group_transform is not None and anchor_for_transform is not None:
                base_translation_dx, base_translation_dy = compute_proportional_translation(
                    fill,
                    group_transform,
                    anchor_for_transform,
                    anchor_norm_override=(group_transform.band_min_x, group_transform.band_min_y),
                )
            base_translation_dx += group_offset_dx
            base_translation_dy += group_offset_dy
        transform_meta = item.get("__mo_transform__")
        self._debug_legacy_point_size = scaled_point_size
        raw_left = float(item.get("x", 0))
        raw_top = float(item.get("y", 0))
        if trace_enabled and not collect_only:
            self._log_legacy_trace(
                plugin_name,
                item_id,
                "paint:message_input",
                {
                    "x": raw_left,
                    "y": raw_top,
                    "scale": scale,
                    "offset_x": base_offset_x,
                    "offset_y": base_offset_y,
                    "mode": mapper.transform.mode.value,
                    "font_size": scaled_point_size,
                },
            )
        adjusted_left, adjusted_top = remap_point(fill, transform_meta, raw_left, raw_top, context=transform_context)
        if mapper.transform.mode is ScaleMode.FILL:
            adjusted_left, adjusted_top = self._apply_inverse_group_scale(
                adjusted_left,
                adjusted_top,
                anchor_for_transform,
                base_anchor_point or anchor_for_transform,
                fill,
            )
            adjusted_left += base_translation_dx
            adjusted_top += base_translation_dy
            if selected_anchor is not None:
                transformed_anchor = self._apply_inverse_group_scale(
                    selected_anchor[0],
                    selected_anchor[1],
                    anchor_for_transform,
                    base_anchor_point or anchor_for_transform,
                    fill,
                )
                effective_anchor = (
                    transformed_anchor[0] + base_translation_dx,
                    transformed_anchor[1] + base_translation_dy,
                )
            if base_anchor_point is not None and selected_anchor is not None:
                anchor_offset = (
                    selected_anchor[0] - base_anchor_point[0],
                    selected_anchor[1] - base_anchor_point[1],
                )
        else:
            base_anchor_effective = base_anchor_point
        text = str(item.get("text", ""))
        metrics_font = QFont(self._font_family)
        self._apply_font_fallbacks(metrics_font)
        metrics_font.setPointSizeF(scaled_point_size)
        metrics_font.setWeight(QFont.Weight.Normal)
        metrics = QFontMetrics(metrics_font)
        text_width = metrics.horizontalAdvance(text)
        x = int(round(fill.screen_x(adjusted_left)))
        baseline = int(round(fill.screen_y(adjusted_top) + metrics.ascent()))
        center_x = x + text_width // 2
        top = baseline - metrics.ascent()
        bottom = baseline + metrics.descent()
        center_y = int(round((top + bottom) / 2.0))
        bounds = (x, top, x + text_width, bottom)
        overlay_bounds: Optional[Tuple[float, float, float, float]] = None
        if scale > 0.0:
            overlay_left = (bounds[0] - base_offset_x) / scale
            overlay_top = (bounds[1] - base_offset_y) / scale
            overlay_right = (bounds[2] - base_offset_x) / scale
            overlay_bottom = (bounds[3] - base_offset_y) / scale
            overlay_bounds = (overlay_left, overlay_top, overlay_right, overlay_bottom)
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
            anchor_offset=anchor_offset,
            debug_log=None,
            text=text,
            color=color,
            point_size=scaled_point_size,
            x=x,
            baseline=baseline,
            text_width=text_width,
            ascent=metrics.ascent(),
            descent=metrics.descent(),
            cycle_anchor=(center_x, center_y),
            trace_fn=trace_fn,
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
        fill = build_viewport(mapper, state, group_transform, BASE_WIDTH, BASE_HEIGHT)
        transform_context = build_payload_transform_context(fill)
        scale = fill.scale
        anchor_point: Optional[Tuple[float, float]] = None
        selected_anchor: Optional[Tuple[float, float]] = None
        base_anchor_point: Optional[Tuple[float, float]] = None
        anchor_for_transform: Optional[Tuple[float, float]] = None
        base_translation_dx = 0.0
        base_translation_dy = 0.0
        effective_anchor: Optional[Tuple[float, float]] = None
        anchor_offset: Optional[Tuple[float, float]] = None
        group_offset_dx, group_offset_dy = self._group_offset_for_transform(group_transform)
        if mapper.transform.mode is ScaleMode.FILL:
            use_overlay_bounds_x = (
                overlay_bounds_hint is not None
                and overlay_bounds_hint.is_valid()
                and not fill.overflow_x
            )
            base_anchor_point = self._group_base_point(
                group_transform,
                transform_context,
                overlay_bounds_hint,
                use_overlay_bounds_x=use_overlay_bounds_x,
            )
            anchor_for_transform = base_anchor_point
            if overlay_bounds_hint is not None and overlay_bounds_hint.is_valid():
                selected_anchor = self._group_anchor_point(
                    group_transform,
                    transform_context,
                    overlay_bounds_hint,
                    use_overlay_bounds_x=use_overlay_bounds_x,
                )
            if group_transform is not None and anchor_for_transform is not None:
                base_translation_dx, base_translation_dy = compute_proportional_translation(
                    fill,
                    group_transform,
                    anchor_for_transform,
                    anchor_norm_override=(group_transform.band_min_x, group_transform.band_min_y),
                )
            base_translation_dx += group_offset_dx
            base_translation_dy += group_offset_dy
        base_offset_x = fill.base_offset_x
        base_offset_y = fill.base_offset_y
        transform_meta = item.get("__mo_transform__")
        trace_enabled = self._should_trace_payload(plugin_name, item_id)
        raw_x = float(item.get("x", 0))
        raw_y = float(item.get("y", 0))
        raw_w = float(item.get("w", 0))
        raw_h = float(item.get("h", 0))
        if trace_enabled and not collect_only:
            self._log_legacy_trace(
                plugin_name,
                item_id,
                "paint:rect_input",
                {
                    "x": raw_x,
                    "y": raw_y,
                    "w": raw_w,
                    "h": raw_h,
                    "scale": scale,
                    "offset_x": base_offset_x,
                    "offset_y": base_offset_y,
                    "mode": mapper.transform.mode.value,
                },
            )
        transformed_overlay = remap_rect_points(fill, transform_meta, raw_x, raw_y, raw_w, raw_h, context=transform_context)
        if mapper.transform.mode is ScaleMode.FILL:
            transformed_overlay = [
                self._apply_inverse_group_scale(px, py, anchor_for_transform, base_anchor_point or anchor_for_transform, fill)
                for px, py in transformed_overlay
            ]
            if base_translation_dx or base_translation_dy:
                transformed_overlay = [
                    (px + base_translation_dx, py + base_translation_dy)
                    for px, py in transformed_overlay
                ]
            if selected_anchor is not None:
                transformed_anchor = self._apply_inverse_group_scale(
                    selected_anchor[0],
                    selected_anchor[1],
                    anchor_for_transform,
                    base_anchor_point or anchor_for_transform,
                    fill,
                )
                effective_anchor = (
                    transformed_anchor[0] + base_translation_dx,
                    transformed_anchor[1] + base_translation_dy,
                )
            if base_anchor_point is not None and selected_anchor is not None:
                anchor_offset = (
                    selected_anchor[0] - base_anchor_point[0],
                    selected_anchor[1] - base_anchor_point[1],
                )
        else:
            base_anchor_effective = base_anchor_point
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
        command = _RectPaintCommand(
            group_key=group_key,
            group_transform=group_transform,
            legacy_item=legacy_item,
            bounds=bounds,
            overlay_bounds=overlay_bounds,
            effective_anchor=effective_anchor,
            anchor_offset=anchor_offset,
            debug_log=None,
            pen=pen,
            brush=brush,
            x=x,
            y=y,
            width=w,
            height=h,
            cycle_anchor=(center_x, center_y),
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
        fill = build_viewport(mapper, state, group_transform, BASE_WIDTH, BASE_HEIGHT)
        transform_context = build_payload_transform_context(fill)
        scale = fill.scale
        selected_anchor: Optional[Tuple[float, float]] = None
        base_anchor_point: Optional[Tuple[float, float]] = None
        anchor_for_transform: Optional[Tuple[float, float]] = None
        base_translation_dx = 0.0
        base_translation_dy = 0.0
        effective_anchor: Optional[Tuple[float, float]] = None
        anchor_offset: Optional[Tuple[float, float]] = None
        group_offset_dx, group_offset_dy = self._group_offset_for_transform(group_transform)
        if mapper.transform.mode is ScaleMode.FILL:
            use_overlay_bounds_x = (
                overlay_bounds_hint is not None
                and overlay_bounds_hint.is_valid()
                and not fill.overflow_x
            )
            selected_anchor = self._group_anchor_point(
                group_transform,
                transform_context,
                overlay_bounds_hint,
                use_overlay_bounds_x=use_overlay_bounds_x,
            )
            base_anchor_point = self._group_base_point(
                group_transform,
                transform_context,
                overlay_bounds_hint,
                use_overlay_bounds_x=use_overlay_bounds_x,
            )
            base_anchor_effective = base_anchor_point
            anchor_for_transform = base_anchor_point or selected_anchor
            if group_transform is not None and anchor_for_transform is not None:
                base_translation_dx, base_translation_dy = compute_proportional_translation(
                    fill,
                    group_transform,
                    anchor_for_transform,
                    anchor_norm_override=(group_transform.band_min_x, group_transform.band_min_y),
                )
            base_translation_dx += group_offset_dx
            base_translation_dy += group_offset_dy
        base_offset_x = fill.base_offset_x
        base_offset_y = fill.base_offset_y
        transform_meta = item.get("__mo_transform__")
        if trace_enabled and not collect_only:
            self._log_legacy_trace(
                plugin_name,
                item_id,
                "paint:scale_factors",
                {
                    "scale": scale,
                    "offset_x": base_offset_x,
                    "offset_y": base_offset_y,
                    "mode": mapper.transform.mode.value,
                },
            )
            self._log_legacy_trace(
                plugin_name,
                item_id,
                "paint:raw_points",
                {"points": item.get("points")},
            )
        raw_points = item.get("points") or []
        transformed_points: List[Mapping[str, Any]] = []
        remapped = remap_vector_points(fill, transform_meta, raw_points, context=transform_context)
        overlay_min_x = float("inf")
        overlay_min_y = float("inf")
        overlay_max_x = float("-inf")
        overlay_max_y = float("-inf")
        for ox, oy, original_point in remapped:
            if mapper.transform.mode is ScaleMode.FILL:
                ox, oy = self._apply_inverse_group_scale(ox, oy, anchor_for_transform, base_anchor_point or anchor_for_transform, fill)
                ox += base_translation_dx
                oy += base_translation_dy
            new_point = dict(original_point)
            new_point["x"] = ox
            new_point["y"] = oy
            if ox < overlay_min_x:
                overlay_min_x = ox
            if ox > overlay_max_x:
                overlay_max_x = ox
            if oy < overlay_min_y:
                overlay_min_y = oy
            if oy > overlay_max_y:
                overlay_max_y = oy
            transformed_points.append(new_point)
        if mapper.transform.mode is ScaleMode.FILL and selected_anchor is not None:
            transformed_anchor = self._apply_inverse_group_scale(
                selected_anchor[0],
                selected_anchor[1],
                anchor_for_transform,
                base_anchor_point or anchor_for_transform,
                fill,
            )
            effective_anchor = (
                transformed_anchor[0] + base_translation_dx,
                transformed_anchor[1] + base_translation_dy,
            )
        if base_anchor_point is not None and selected_anchor is not None:
            anchor_offset = (
                selected_anchor[0] - base_anchor_point[0],
                selected_anchor[1] - base_anchor_point[1],
            )
        if len(transformed_points) < 2:
            return None, None
        vector_payload = {
            "base_color": item.get("base_color"),
            "points": transformed_points,
        }
        trace_fn = None
        if trace_enabled:
            def trace_fn(stage: str, details: Mapping[str, Any]) -> None:
                self._log_legacy_trace(plugin_name, item_id, stage, details)

        px_list: List[int] = []
        py_list: List[int] = []
        for point in vector_payload.get("points", []):
            try:
                mapped_x = float(point.get("x", 0.0)) * scale + base_offset_x
                mapped_y = float(point.get("y", 0.0)) * scale + base_offset_y
            except (TypeError, ValueError):
                continue
            px = int(round(mapped_x))
            py = int(round(mapped_y))
            px_list.append(px)
            py_list.append(py)
        bounds: Optional[Tuple[int, int, int, int]]
        cycle_anchor: Optional[Tuple[int, int]]
        overlay_bounds: Optional[Tuple[float, float, float, float]]
        if px_list and py_list:
            bounds = (min(px_list), min(py_list), max(px_list), max(py_list))
            cycle_anchor = (
                int(round((min(px_list) + max(px_list)) / 2.0)),
                int(round((min(py_list) + max(py_list)) / 2.0)),
            )
            if (
                math.isfinite(overlay_min_x)
                and math.isfinite(overlay_max_x)
                and math.isfinite(overlay_min_y)
                and math.isfinite(overlay_max_y)
                and overlay_min_x <= overlay_max_x
                and overlay_min_y <= overlay_max_y
            ):
                overlay_bounds = (overlay_min_x, overlay_min_y, overlay_max_x, overlay_max_y)
            else:
                overlay_bounds = None
        else:
            bounds = None
            cycle_anchor = None
            overlay_bounds = None
        command = _VectorPaintCommand(
            group_key=group_key,
            group_transform=group_transform,
            legacy_item=legacy_item,
            bounds=bounds,
            overlay_bounds=overlay_bounds,
            effective_anchor=effective_anchor,
            anchor_offset=anchor_offset,
            debug_log=None,
            vector_payload=vector_payload,
            scale=scale,
            base_offset_x=base_offset_x,
            base_offset_y=base_offset_y,
            trace_fn=trace_fn,
            cycle_anchor=cycle_anchor,
        )
        return command

    def _compute_group_nudges(
        self,
        bounds_by_group: Mapping[Tuple[str, Optional[str]], _ScreenBounds],
    ) -> Dict[Tuple[str, Optional[str]], Tuple[int, int]]:
        if not self._payload_nudge_enabled or not bounds_by_group:
            return {}
        width = max(self.width(), 1)
        height = max(self.height(), 1)
        gutter = max(0, int(self._payload_nudge_gutter))
        translations: Dict[Tuple[str, Optional[str]], Tuple[int, int]] = {}
        for key, bounds in bounds_by_group.items():
            if not bounds.is_valid():
                continue
            dx = self._compute_axis_nudge(bounds.min_x, bounds.max_x, width, gutter)
            dy = self._compute_axis_nudge(bounds.min_y, bounds.max_y, height, gutter)
            if dx or dy:
                translations[key] = (dx, dy)
        return translations

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

    @staticmethod
    def _compute_axis_nudge(min_coord: float, max_coord: float, window_span: int, gutter: int) -> int:
        if window_span <= 0:
            return 0
        if not (math.isfinite(min_coord) and math.isfinite(max_coord)):
            return 0
        span = max(0.0, max_coord - min_coord)
        if span <= 0.0:
            return 0
        left_overflow = min_coord < 0.0
        right_overflow = max_coord > window_span
        if not (left_overflow or right_overflow):
            return 0
        dx = 0.0
        current_min = min_coord
        current_max = max_coord
        if left_overflow:
            shift = -current_min
            dx += shift
            current_min += shift
            current_max += shift
        if current_max > window_span:
            shift = current_max - window_span
            dx -= shift
            current_min -= shift
            current_max -= shift
        effective_gutter = min(max(0.0, float(gutter)), max(window_span - span, 0.0))
        if effective_gutter > 0.0:
            if left_overflow:
                extra = min(effective_gutter, max(0.0, window_span - current_max))
                dx += extra
                current_min += extra
                current_max += extra
            if right_overflow:
                extra = min(effective_gutter, max(0.0, current_min))
                dx -= extra
                current_min -= extra
                current_max -= extra
        return int(round(dx))

    def _draw_group_bounds_outline_with_offset(
        self,
        painter: QPainter,
        mapper: LegacyMapper,
        transform: GroupTransform,
        overlay_bounds: Optional[_OverlayBounds],
        explicit_anchor: Optional[Tuple[float, float]],
        anchor_offset: Optional[Tuple[float, float]],
        offset_x: int,
        offset_y: int,
    ) -> None:
        if offset_x or offset_y:
            anchor_visual_offset = (float(offset_x), float(offset_y))
            painter.save()
            painter.translate(offset_x, offset_y)
            self._draw_group_bounds_outline(
                painter,
                mapper,
                transform,
                overlay_bounds,
                explicit_anchor,
                anchor_offset,
                anchor_visual_offset=anchor_visual_offset,
            )
            painter.restore()
            return
        self._draw_group_bounds_outline(painter, mapper, transform, overlay_bounds, explicit_anchor, anchor_offset)

    def _draw_item_bounds_outline_with_offset(
        self,
        painter: QPainter,
        mapper: LegacyMapper,
        legacy_item: LegacyItem,
        offset_x: int,
        offset_y: int,
    ) -> None:
        if offset_x or offset_y:
            painter.save()
            painter.translate(offset_x, offset_y)
            self._draw_item_bounds_outline(painter, mapper, legacy_item)
            painter.restore()
            return
        self._draw_item_bounds_outline(painter, mapper, legacy_item)

    def _draw_group_bounds_outline(
        self,
        painter: QPainter,
        mapper: LegacyMapper,
        transform: GroupTransform,
        overlay_bounds: Optional[_OverlayBounds],
        explicit_anchor: Optional[Tuple[float, float]] = None,
        anchor_offset: Optional[Tuple[float, float]] = None,
        anchor_visual_offset: Optional[Tuple[float, float]] = None,
    ) -> None:
        state = self._viewport_state()
        fill = build_viewport(mapper, state, transform, BASE_WIDTH, BASE_HEIGHT)
        transform_context = build_payload_transform_context(fill)
        use_actual_bounds = overlay_bounds is not None and overlay_bounds.is_valid()
        anchor_point: Optional[Tuple[float, float]] = None
        bounds_anchor_override: Optional[Tuple[float, float]] = None
        if use_actual_bounds:
            min_x = overlay_bounds.min_x
            max_x = overlay_bounds.max_x
            min_y = overlay_bounds.min_y
            max_y = overlay_bounds.max_y
            base_anchor_point = (min_x, min_y)
            base_anchor_overlay: Optional[Tuple[float, float]] = base_anchor_point
        else:
            min_x = transform.bounds_min_x
            max_x = transform.bounds_max_x
            min_y = transform.bounds_min_y
            max_y = transform.bounds_max_y
            base_anchor_point = self._group_base_point(transform, transform_context)
            base_anchor_overlay: Optional[Tuple[float, float]] = base_anchor_point
        if not all(math.isfinite(value) for value in (min_x, max_x, min_y, max_y)):
            return
        base_translation_dx = 0.0
        base_translation_dy = 0.0
        if mapper.transform.mode is ScaleMode.FILL:
            if use_actual_bounds:
                bounds_anchor_override = self._map_anchor_to_overlay_bounds(transform, overlay_bounds) or None
            else:
                anchor_point = self._group_anchor_point(transform, transform_context)
                min_x, min_y = self._apply_inverse_group_scale(min_x, min_y, anchor_point, base_anchor_point, fill)
                max_x, max_y = self._apply_inverse_group_scale(max_x, max_y, anchor_point, base_anchor_point, fill)
                if base_anchor_overlay is not None:
                    base_anchor_overlay = self._apply_inverse_group_scale(
                        base_anchor_overlay[0],
                        base_anchor_overlay[1],
                        anchor_point,
                        base_anchor_point,
                        fill,
                    )
                if base_anchor_point is not None:
                    base_translation_dx, base_translation_dy = compute_proportional_translation(
                        fill,
                        transform,
                        base_anchor_point,
                        anchor_norm_override=(transform.band_min_x, transform.band_min_y),
                    )
                    min_x += base_translation_dx
                    max_x += base_translation_dx
                    min_y += base_translation_dy
                    max_y += base_translation_dy
                    if base_anchor_overlay is not None:
                        base_anchor_overlay = (
                            base_anchor_overlay[0] + base_translation_dx,
                            base_anchor_overlay[1] + base_translation_dy,
                        )
        elif use_actual_bounds:
            bounds_anchor_override = self._map_anchor_to_overlay_bounds(transform, overlay_bounds) or None
        left_px = fill.screen_x(min_x)
        right_px = fill.screen_x(max_x)
        top_px = fill.screen_y(min_y)
        bottom_px = fill.screen_y(max_y)
        if not all(math.isfinite(value) for value in (left_px, right_px, top_px, bottom_px)):
            return
        rect_left = int(round(min(left_px, right_px)))
        rect_top = int(round(min(top_px, bottom_px)))
        rect_width = int(round(abs(right_px - left_px)))
        rect_height = int(round(abs(bottom_px - top_px)))
        if rect_width <= 0 or rect_height <= 0:
            return

        painter.save()
        pen = QPen(QColor(255, 221, 0))
        pen.setWidth(self._line_width("group_outline"))
        pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(rect_left, rect_top, rect_width, rect_height)
        base_anchor_qt: Optional[QPoint] = None
        if base_anchor_overlay is not None:
            base_px = fill.screen_x(base_anchor_overlay[0])
            base_py = fill.screen_y(base_anchor_overlay[1])
            if math.isfinite(base_px) and math.isfinite(base_py):
                base_anchor_qt = QPoint(int(round(base_px)), int(round(base_py)))
        display_overlay = base_anchor_overlay if base_anchor_overlay is not None else None
        if explicit_anchor is not None:
            anchor_overlay_x, anchor_overlay_y = explicit_anchor
        elif display_overlay is not None:
            anchor_overlay_x, anchor_overlay_y = display_overlay
        else:
            anchor_overlay = bounds_anchor_override or anchor_point
            if anchor_overlay is None:
                anchor_overlay_x = transform.band_anchor_x * BASE_WIDTH
                anchor_overlay_y = transform.band_anchor_y * BASE_HEIGHT
                anchor_overlay_x = remap_axis_value(anchor_overlay_x, transform_context.axis_x)
                anchor_overlay_y = remap_axis_value(anchor_overlay_y, transform_context.axis_y)
            else:
                anchor_overlay_x, anchor_overlay_y = anchor_overlay
                if mapper.transform.mode is ScaleMode.FILL:
                    anchor_overlay_x, anchor_overlay_y = self._apply_inverse_group_scale(
                        anchor_overlay_x,
                        anchor_overlay_y,
                        anchor_point,
                        base_anchor_point,
                        fill,
                    )
                    anchor_overlay_x += base_translation_dx
                    anchor_overlay_y += base_translation_dy
        anchor_token = getattr(transform, "anchor_token", "") or ""
        anchor_point_qt: Optional[QPoint] = None
        display_anchor_qt: Optional[QPoint] = base_anchor_qt
        anchor_visual_dx = float(anchor_visual_offset[0]) if anchor_visual_offset else 0.0
        anchor_visual_dy = float(anchor_visual_offset[1]) if anchor_visual_offset else 0.0
        anchor_visual_applied = bool(anchor_visual_dx or anchor_visual_dy)
        if anchor_visual_applied:
            painter.save()
            painter.translate(-anchor_visual_dx, -anchor_visual_dy)
        try:
            if (
                math.isfinite(anchor_overlay_x)
                and math.isfinite(anchor_overlay_y)
            ):
                anchor_px = fill.screen_x(anchor_overlay_x)
                anchor_py = fill.screen_y(anchor_overlay_y)
                if not fill.overflow_x:
                    width = rect_width
                    if anchor_token in {"top", "center", "bottom"}:
                        anchor_px = rect_left + width / 2.0
                    elif anchor_token in {"left", "west", "nw", "sw"}:
                        anchor_px = rect_left
                    elif anchor_token in {"right", "east", "ne", "se"}:
                        anchor_px = rect_left + width
                if math.isfinite(anchor_px) and math.isfinite(anchor_py):
                    anchor_point_qt = QPoint(int(round(anchor_px)), int(round(anchor_py)))
            if display_anchor_qt is None and display_overlay is not None:
                disp_x, disp_y = display_overlay
                if math.isfinite(disp_x) and math.isfinite(disp_y):
                    disp_px = fill.screen_x(disp_x)
                    disp_py = fill.screen_y(disp_y)
                    if math.isfinite(disp_px) and math.isfinite(disp_py):
                        display_anchor_qt = QPoint(int(round(disp_px)), int(round(disp_py)))
            if display_anchor_qt is not None:
                dot_radius = max(4, self._line_width("group_outline") * 2)
                painter.setBrush(QColor(255, 255, 255))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawEllipse(display_anchor_qt, dot_radius, dot_radius)
                painter.setPen(QColor(255, 255, 255))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                label_overlay = display_overlay
                if label_overlay is None:
                    label_overlay = (anchor_overlay_x, anchor_overlay_y) if (
                        math.isfinite(anchor_overlay_x) and math.isfinite(anchor_overlay_y)
                    ) else None
                if label_overlay is not None:
                    text = "({:.1f}, {:.1f})".format(label_overlay[0], label_overlay[1])
                else:
                    text = "(n/a)"
                if anchor_offset is not None:
                    text += " Δ=({:.1f}, {:.1f})".format(anchor_offset[0], anchor_offset[1])
                metrics = painter.fontMetrics()
                text_rect = metrics.boundingRect(text)
                offset_x = dot_radius + 6
                offset_y = -dot_radius - 6
                label_x = display_anchor_qt.x() + offset_x
                label_y = display_anchor_qt.y() + offset_y
                if label_x + text_rect.width() > fill.visible_width:
                    label_x = display_anchor_qt.x() - offset_x - text_rect.width()
                if label_y - text_rect.height() < 0:
                    label_y = display_anchor_qt.y() + offset_y + text_rect.height()
                painter.drawText(label_x, label_y, text)
            # no longer draw extra base anchor markers; the anchor dot already reflects the base anchor
        finally:
            if anchor_visual_applied:
                painter.restore()
        painter.restore()

    def _draw_item_bounds_outline(
        self,
        painter: QPainter,
        mapper: LegacyMapper,
        legacy_item: LegacyItem,
    ) -> None:
        state = self._viewport_state()
        fill = build_viewport(mapper, state, None, BASE_WIDTH, BASE_HEIGHT)
        scale = fill.scale
        if not math.isfinite(scale) or math.isclose(scale, 0.0, rel_tol=1e-9, abs_tol=1e-9):
            return

        def preset_point_size(label: str) -> float:
            return self._legacy_preset_point_size(label, state, mapper)

        bounds = GroupBounds()
        accumulate_group_bounds(
            bounds,
            legacy_item,
            mapper.transform.scale,
            self._font_family,
            preset_point_size,
            font_fallbacks=self._font_fallbacks,
        )
        if not bounds.is_valid():
            return

        left_overlay = fill.axis_x.remap(bounds.min_x, 0.0, 1.0, 0.0)
        right_overlay = fill.axis_x.remap(bounds.max_x, 0.0, 1.0, 0.0)
        top_overlay = fill.axis_y.remap(bounds.min_y, 0.0, 1.0, 0.0)
        bottom_overlay = fill.axis_y.remap(bounds.max_y, 0.0, 1.0, 0.0)

        left_px = left_overlay * scale + fill.base_offset_x
        right_px = right_overlay * scale + fill.base_offset_x
        top_px = top_overlay * scale + fill.base_offset_y
        bottom_px = bottom_overlay * scale + fill.base_offset_y

        if not all(math.isfinite(value) for value in (left_px, right_px, top_px, bottom_px)):
            return

        rect_left = int(round(min(left_px, right_px)))
        rect_top = int(round(min(top_px, bottom_px)))
        rect_width = int(round(abs(right_px - left_px)))
        rect_height = int(round(abs(bottom_px - top_px)))
        if rect_width <= 0 or rect_height <= 0:
            return

        painter.save()
        pen = QPen(QColor(255, 221, 0))
        pen.setWidth(self._line_width("group_outline"))
        pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(rect_left, rect_top, rect_width, rect_height)
        painter.restore()

    def _paint_debug_overlay(self, painter: QPainter) -> None:
        if not self._show_debug_overlay:
            return
        frame = self.frameGeometry()
        mapper = self._compute_legacy_mapper()
        state = self._viewport_state()
        scale_x, scale_y = legacy_scale_components(mapper, state)
        diagonal_scale = self._font_scale_diag
        if diagonal_scale <= 0.0:
            diagonal_scale = math.sqrt((scale_x * scale_x + scale_y * scale_y) / 2.0)
        width_px, height_px = self._current_physical_size()
        size_labels = [("S", "small"), ("N", "normal"), ("L", "large"), ("H", "huge")]
        legacy_sizes_str = " ".join(
            "{}={:.1f}".format(label, self._legacy_preset_point_size(name, state, mapper))
            for label, name in size_labels
        )
        active_screen = self.windowHandle().screen() if self.windowHandle() else None
        monitor_desc = self._last_screen_name or self._describe_screen(active_screen)
        active_ratio = None
        if active_screen is not None:
            try:
                geo = active_screen.geometry()
                active_ratio = self._aspect_ratio_label(geo.width(), geo.height())
            except Exception:
                active_ratio = None
        active_line = f"  active={monitor_desc or 'unknown'}"
        if active_ratio:
            active_line += f" ({active_ratio})"
        monitor_lines = ["Monitor:", active_line]
        if self._last_follow_state is not None:
            tracker_ratio = self._aspect_ratio_label(
                max(1, int(self._last_follow_state.width)),
                max(1, int(self._last_follow_state.height)),
            )
            tracker_line = "  tracker=({},{}) {}x{}".format(
                self._last_follow_state.x,
                self._last_follow_state.y,
                self._last_follow_state.width,
                self._last_follow_state.height,
            )
            if tracker_ratio:
                tracker_line += f" ({tracker_ratio})"
            monitor_lines.append(tracker_line)
        if self._wm_authoritative_rect is not None and self._wm_override_classification is not None:
            rect = self._wm_authoritative_rect
            monitor_lines.append(
                "  wm_rect=({},{}) {}x{} [{}]".format(
                    rect[0],
                    rect[1],
                    rect[2],
                    rect[3],
                    self._wm_override_classification,
                )
            )

        widget_ratio = self._aspect_ratio_label(self.width(), self.height())
        frame_ratio = self._aspect_ratio_label(frame.width(), frame.height())
        phys_ratio = self._aspect_ratio_label(int(round(width_px)), int(round(height_px)))
        overlay_lines = ["Overlay:"]
        widget_line = "  widget={}x{}".format(self.width(), self.height())
        if widget_ratio:
            widget_line += f" ({widget_ratio})"
        overlay_lines.append(widget_line)
        frame_line = "  frame={}x{}".format(frame.width(), frame.height())
        if frame_ratio:
            frame_line += f" ({frame_ratio})"
        overlay_lines.append(frame_line)
        phys_line = "  phys={}x{}".format(int(round(width_px)), int(round(height_px)))
        if phys_ratio:
            phys_line += f" ({phys_ratio})"
        overlay_lines.append(phys_line)
        if self._last_raw_window_log is not None:
            raw_x, raw_y, raw_w, raw_h = self._last_raw_window_log
            raw_ratio = self._aspect_ratio_label(raw_w, raw_h)
            raw_line = "  raw=({},{}) {}x{}".format(raw_x, raw_y, raw_w, raw_h)
            if raw_ratio:
                raw_line += f" ({raw_ratio})"
            overlay_lines.append(raw_line)

        transform = mapper.transform
        scaling_lines = [
            "Scaling:",
            "  mode={} base_scale={:.4f}".format(transform.mode.value, transform.scale),
            "  scaled_canvas={:.1f}x{:.1f} offset=({:.1f},{:.1f})".format(
                transform.scaled_size[0],
                transform.scaled_size[1],
                mapper.offset_x,
                mapper.offset_y,
            ),
            "  overflow_x={} overflow_y={}".format(
                "yes" if transform.overflow_x else "no",
                "yes" if transform.overflow_y else "no",
            ),
        ]

        font_lines = [
            "Fonts:",
            "  scale_x={:.2f} scale_y={:.2f} diag={:.2f}".format(scale_x, scale_y, diagonal_scale),
            "  ui_scale={:.2f}".format(self._font_scale_diag),
            "  bounds={:.1f}-{:.1f}".format(self._font_min_point, self._font_max_point),
            "  message={:.1f} status={:.1f} legacy={:.1f}".format(
                self._debug_message_point_size,
                self._debug_status_point_size,
                self._debug_legacy_point_size,
            ),
            "  legacy presets: {}".format(legacy_sizes_str),
        ]

        settings_lines = [
            "Settings:",
            "  title_bar_compensation={}".format("on" if self._title_bar_enabled else "off"),
            "  title_bar_height={}".format(self._title_bar_height),
            "  applied_offset={}".format(self._last_title_bar_offset),
        ]

        info_lines = (
            monitor_lines
            + [""]
            + overlay_lines
            + [""]
            + scaling_lines
            + [""]
            + font_lines
            + [""]
            + settings_lines
        )
        painter.save()
        debug_font = QFont(self._font_family, 10)
        self._apply_font_fallbacks(debug_font)
        painter.setFont(debug_font)
        metrics = painter.fontMetrics()
        line_height = metrics.height()
        text_width = max(metrics.horizontalAdvance(line) for line in info_lines)
        padding = 6
        panel_width = text_width + padding * 2
        panel_height = line_height * len(info_lines) + padding * 2
        rect = QRect(0, 0, panel_width, panel_height)
        margin = 10
        corner = self._debug_overlay_corner
        if corner in {"NW", "SW"}:
            left = margin
        else:
            left = max(margin, self.width() - panel_width - margin)
        if corner in {"NW", "NE"}:
            top = margin
        else:
            top = max(margin, self.height() - panel_height - margin)
        rect.moveTo(left, top)
        painter.setBrush(QColor(0, 0, 0, 160))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(rect, 6, 6)
        painter.setPen(QColor(220, 220, 220))
        for index, line in enumerate(info_lines):
            painter.drawText(
                rect.left() + padding,
                rect.top() + padding + metrics.ascent() + index * line_height,
                line,
            )
        painter.restore()

    def _paint_overlay_outline(self, painter: QPainter) -> None:
        if not self._debug_config.overlay_outline:
            return
        mapper = self._compute_legacy_mapper()
        transform = mapper.transform
        offset_x, offset_y = transform.offset
        scaled_w, scaled_h = transform.scaled_size
        window_w = float(self.width())
        window_h = float(self.height())
        left = offset_x
        top = offset_y
        right = offset_x + scaled_w
        bottom = offset_y + scaled_h
        overflow_left = left < 0.0
        overflow_right = right > window_w
        overflow_top = top < 0.0
        overflow_bottom = bottom > window_h
        vis_left = max(left, 0.0)
        vis_right = min(right, window_w)
        vis_top = max(top, 0.0)
        vis_bottom = min(bottom, window_h)

        painter.save()
        pen = QPen(QColor(255, 136, 0))
        pen.setWidth(self._line_width("viewport_indicator"))
        pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
        painter.setPen(pen)

        def draw_vertical_line(x_pos: float) -> None:
            if vis_top >= vis_bottom:
                return
            x = int(round(x_pos))
            painter.drawLine(x, int(round(vis_top)), x, int(round(vis_bottom)))

        def draw_horizontal_line(y_pos: float) -> None:
            if vis_left >= vis_right:
                return
            y = int(round(y_pos))
            painter.drawLine(int(round(vis_left)), y, int(round(vis_right)), y)

        arrow_length = 18.0
        arrow_span_min = 60.0
        arrow_count = 3

        arrow_tip_margin = 4.0

        def draw_vertical_arrows(edge_x: float, direction: int) -> None:
            span_start = max(vis_top, 0.0)
            span_end = min(vis_bottom, window_h)
            if span_end <= span_start:
                span_start = 0.0
                span_end = window_h
            span = max(span_end - span_start, arrow_span_min)
            step = span / (arrow_count + 1)
            if direction > 0:
                tip_x = min(edge_x - arrow_tip_margin, window_w - arrow_tip_margin)
                base_x = tip_x - arrow_length
            else:
                tip_x = max(edge_x + arrow_tip_margin, arrow_tip_margin)
                base_x = tip_x + arrow_length
            for i in range(1, arrow_count + 1):
                y = span_start + step * i
                painter.drawLine(int(round(base_x)), int(round(y)), int(round(tip_x)), int(round(y)))
                painter.drawLine(
                    int(round(tip_x)),
                    int(round(y)),
                    int(round(tip_x - direction * arrow_length * 0.45)),
                    int(round(y - arrow_length * 0.4)),
                )
                painter.drawLine(
                    int(round(tip_x)),
                    int(round(y)),
                    int(round(tip_x - direction * arrow_length * 0.45)),
                    int(round(y + arrow_length * 0.4)),
                )

        def draw_horizontal_arrows(edge_y: float, direction: int) -> None:
            span_start = max(vis_left, 0.0)
            span_end = min(vis_right, window_w)
            if span_end <= span_start:
                span_start = 0.0
                span_end = window_w
            span = max(span_end - span_start, arrow_span_min)
            step = span / (arrow_count + 1)
            for i in range(1, arrow_count + 1):
                x = span_start + step * i
                if direction > 0:
                    tip_y = min(edge_y - arrow_tip_margin, window_h - arrow_tip_margin)
                    base_y = tip_y - arrow_length
                else:
                    tip_y = max(edge_y + arrow_tip_margin, arrow_tip_margin)
                    base_y = tip_y + arrow_length
                painter.drawLine(int(round(x)), int(round(base_y)), int(round(x)), int(round(tip_y)))
                painter.drawLine(
                    int(round(x)),
                    int(round(tip_y)),
                    int(round(x - arrow_length * 0.35)),
                    int(round(tip_y - direction * arrow_length * 0.4)),
                )
                painter.drawLine(
                    int(round(x)),
                    int(round(tip_y)),
                    int(round(x + arrow_length * 0.35)),
                    int(round(tip_y - direction * arrow_length * 0.4)),
                )

        if not overflow_left:
            draw_vertical_line(vis_left)
        else:
            draw_vertical_arrows(max(vis_left, 0.0), direction=-1)

        if not overflow_right:
            draw_vertical_line(vis_right)
        else:
            draw_vertical_arrows(min(vis_right, window_w), direction=1)

        if not overflow_top:
            draw_horizontal_line(vis_top)
        else:
            draw_horizontal_arrows(max(vis_top, 0.0), direction=-1)

        if not overflow_bottom:
            draw_horizontal_line(vis_bottom)
        else:
            draw_horizontal_arrows(min(vis_bottom, window_h), direction=1)

        painter.restore()

    def _apply_legacy_scale(self) -> None:
        self.update()

    def _apply_window_dimensions(self, *, force: bool = False) -> None:
        return

    def _resolve_font_family(self) -> str:
        fonts_dir = Path(__file__).resolve().parent / "fonts"
        default_family = "Segoe UI"

        def try_font_file(font_path: Path, label: str) -> Optional[str]:
            if not font_path.exists():
                return None
            try:
                font_id = QFontDatabase.addApplicationFont(str(font_path))
            except Exception as exc:
                _CLIENT_LOGGER.warning("Failed to load %s font from %s: %s", label, font_path, exc)
                return None
            if font_id == -1:
                _CLIENT_LOGGER.warning("%s font file at %s could not be registered; falling back", label, font_path)
                return None
            families = QFontDatabase.applicationFontFamilies(font_id)
            if families:
                family = families[0]
                _CLIENT_LOGGER.debug("Using %s font family '%s' from %s", label, family, font_path)
                return family
            _CLIENT_LOGGER.warning("%s font registered but no families reported; falling back", label)
            return None

        def find_font_case_insensitive(filename: str) -> Optional[Path]:
            if not filename:
                return None
            target = filename.lower()
            if not fonts_dir.exists():
                return None
            for child in fonts_dir.iterdir():
                if child.is_file() and child.name.lower() == target:
                    return child
            return None

        preferred_marker = fonts_dir / "preferred_fonts.txt"
        preferred_files: list[Path] = []
        if preferred_marker.exists():
            try:
                for raw_line in preferred_marker.read_text(encoding="utf-8").splitlines():
                    candidate_name = raw_line.strip()
                    if not candidate_name or candidate_name.startswith(("#", ";")):
                        continue
                    candidate_path = find_font_case_insensitive(candidate_name)
                    if candidate_path:
                        preferred_files.append(candidate_path)
                    else:
                        _CLIENT_LOGGER.warning(
                            "Preferred font '%s' listed in %s but not found", candidate_name, preferred_marker
                        )
            except Exception as exc:
                _CLIENT_LOGGER.warning("Failed to read preferred fonts list at %s: %s", preferred_marker, exc)

        standard_candidates = [
            ("SourceSans3-Regular.ttf", "Source Sans 3"),
            ("Eurocaps.ttf", "Eurocaps"),
        ]

        candidate_paths: list[Tuple[Path, str]] = []
        seen: set[Path] = set()

        def add_candidate(path: Optional[Path], label: str) -> None:
            if not path:
                return
            try:
                resolved = path.resolve()
            except Exception:
                resolved = path
            if resolved in seen:
                return
            seen.add(resolved)
            candidate_paths.append((path, label))

        for preferred_path in preferred_files:
            add_candidate(preferred_path, f"Preferred font '{preferred_path.name}'")

        for filename, label in standard_candidates:
            add_candidate(find_font_case_insensitive(filename), label)

        for path, label in candidate_paths:
            family = try_font_file(path, label)
            if family:
                return family

        installed_candidates = [
            "Source Sans 3",
            "SourceSans3",
            "Source Sans",
            "Source Sans 3 Regular",
            "Eurocaps",
            "Euro Caps",
            "EUROCAPS",
        ]
        try:
            available = set(QFontDatabase.families())
        except Exception as exc:
            _CLIENT_LOGGER.warning("Could not enumerate installed fonts: %s", exc)
            available = set()
        for candidate in installed_candidates:
            if candidate in available:
                _CLIENT_LOGGER.debug("Using installed font family '%s'", candidate)
                return candidate

        _CLIENT_LOGGER.warning("Preferred fonts unavailable; falling back to %s", default_family)
        return default_family

    def _resolve_emoji_font_families(self) -> Tuple[str, ...]:
        fonts_dir = Path(__file__).resolve().parent / "fonts"

        def find_font_case_insensitive(filename: str) -> Optional[Path]:
            if not filename:
                return None
            target = filename.lower()
            if not fonts_dir.exists():
                return None
            for child in fonts_dir.iterdir():
                if child.is_file() and child.name.lower() == target:
                    return child
            return None

        try:
            available_lookup = {name.casefold(): name for name in QFontDatabase.families()}
        except Exception as exc:
            _CLIENT_LOGGER.warning("Could not enumerate installed fonts for emoji fallbacks: %s", exc)
            available_lookup = {}

        fallback_families: list[str] = []
        seen: set[str] = set()
        base_family = (self._font_family or "").strip()
        if base_family:
            seen.add(base_family.casefold())

        def add_family(name: Optional[str]) -> None:
            if not name:
                return
            lowered = name.casefold()
            if lowered in seen:
                return
            seen.add(lowered)
            fallback_families.append(name)

        def register_font_file(path: Optional[Path], label: str) -> None:
            if not path:
                return
            try:
                font_id = QFontDatabase.addApplicationFont(str(path))
            except Exception as exc:
                _CLIENT_LOGGER.warning("Failed to load %s font from %s: %s", label, path, exc)
                return
            if font_id == -1:
                _CLIENT_LOGGER.warning("%s font file at %s could not be registered; skipping", label, path)
                return
            families = QFontDatabase.applicationFontFamilies(font_id)
            if not families:
                _CLIENT_LOGGER.warning("%s font registered but reported no families; skipping", label)
                return
            for family in families:
                available_lookup[family.casefold()] = family
                add_family(family)

        def add_if_available(candidate: str, *, warn: bool = False) -> None:
            resolved = available_lookup.get(candidate.casefold())
            if resolved:
                add_family(resolved)
            elif warn:
                _CLIENT_LOGGER.warning("Emoji fallback '%s' listed in emoji_fallbacks.txt but not installed", candidate)

        fallback_marker = fonts_dir / "emoji_fallbacks.txt"
        if fallback_marker.exists():
            try:
                for raw_line in fallback_marker.read_text(encoding="utf-8").splitlines():
                    candidate = raw_line.strip()
                    if not candidate or candidate.startswith(("#", ";")):
                        continue
                    path = find_font_case_insensitive(candidate)
                    if path:
                        register_font_file(path, f"emoji fallback '{path.name}'")
                    else:
                        add_if_available(candidate, warn=True)
            except Exception as exc:
                _CLIENT_LOGGER.warning("Failed to read emoji fallback list at %s: %s", fallback_marker, exc)

        bundled_candidates = [
            "NotoColorEmoji.ttf",
            "NotoColorEmoji-WindowsCompatible.ttf",
            "NotoColorEmojiCompat.ttf",
            "NotoEmoji-Regular.ttf",
            "TwemojiMozilla.ttf",
        ]
        for filename in bundled_candidates:
            register_font_file(find_font_case_insensitive(filename), f"emoji fallback '{filename}'")

        installed_candidates = [
            "Noto Color Emoji",
            "Noto Emoji",
            "Noto Emoji Black",
            "Segoe UI Emoji",
            "Segoe UI Symbol",
            "Apple Color Emoji",
            "Twemoji Mozilla",
            "JoyPixels",
            "EmojiOne Color",
            "OpenMoji Color",
            "OpenMoji",
        ]
        for candidate in installed_candidates:
            add_if_available(candidate, warn=False)

        if fallback_families:
            _CLIENT_LOGGER.debug("Emoji fallbacks enabled: %s", ", ".join(fallback_families))
        else:
            _CLIENT_LOGGER.debug("No emoji fallback fonts discovered; %s will be used alone", self._font_family)
        return tuple(fallback_families)

    def _line_width(self, key: str) -> int:
        default = _LINE_WIDTH_DEFAULTS.get(key, 1)
        value = self._line_widths.get(key, default)
        try:
            width = int(round(float(value)))
        except (TypeError, ValueError):
            width = default
        return max(0, width)

    def _apply_font_fallbacks(self, font: QFont) -> None:
        apply_font_fallbacks(font, getattr(self, "_font_fallbacks", ()))


class _QtVectorPainterAdapter(VectorPainterAdapter):
    def __init__(self, window: "OverlayWindow", painter: QPainter) -> None:
        self._window = window
        self._painter = painter

    def set_pen(self, color: str, *, width: Optional[int] = None) -> None:
        q_color = QColor(color)
        if not q_color.isValid():
            q_color = QColor("white")
        pen = QPen(q_color)
        pen_width = self._window._line_width("vector_line") if width is None else max(0, int(width))
        pen.setWidth(pen_width)
        self._painter.setPen(pen)
        self._painter.setBrush(Qt.BrushStyle.NoBrush)

    def draw_line(self, x1: int, y1: int, x2: int, y2: int) -> None:
        self._painter.drawLine(x1, y1, x2, y2)

    def draw_circle_marker(self, x: int, y: int, radius: int, color: str) -> None:
        q_color = QColor(color)
        if not q_color.isValid():
            q_color = QColor("white")
        pen = QPen(q_color)
        pen.setWidth(self._window._line_width("vector_marker"))
        self._painter.setPen(pen)
        self._painter.setBrush(QBrush(q_color))
        self._painter.drawEllipse(QPoint(x, y), radius, radius)

    def draw_cross_marker(self, x: int, y: int, size: int, color: str) -> None:
        self.set_pen(color, width=self._window._line_width("vector_cross"))
        self._painter.drawLine(x - size, y - size, x + size, y + size)
        self._painter.drawLine(x - size, y + size, x + size, y - size)

    def draw_text(self, x: int, y: int, text: str, color: str) -> None:
        q_color = QColor(color)
        if not q_color.isValid():
            q_color = QColor("white")
        pen = QPen(q_color)
        self._painter.setPen(pen)
        font = QFont(self._window._font_family)
        self._window._apply_font_fallbacks(font)
        mapper = self._window._compute_legacy_mapper()
        state = self._window._viewport_state()
        font.setPointSizeF(self._window._legacy_preset_point_size("small", state, mapper))
        font.setWeight(QFont.Weight.Normal)
        self._painter.setFont(font)
        metrics = QFontMetrics(font)
        baseline = int(round(y + metrics.ascent()))
        self._painter.drawText(x, baseline, text)

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
