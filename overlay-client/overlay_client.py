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
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

from PyQt6.QtCore import Qt, pyqtSignal, QObject, QTimer, QPoint, QRect, QSize
from PyQt6.QtGui import (
    QColor,
    QFont,
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
    from version import __version__ as MODERN_OVERLAY_VERSION
except Exception:  # pragma: no cover - fallback when module unavailable
    MODERN_OVERLAY_VERSION = "unknown"

from client_config import InitialClientSettings, load_initial_settings  # type: ignore  # noqa: E402
from developer_helpers import DeveloperHelperController  # type: ignore  # noqa: E402
from platform_integration import MonitorSnapshot, PlatformContext, PlatformController  # type: ignore  # noqa: E402
from window_tracking import WindowState, WindowTracker, create_elite_window_tracker  # type: ignore  # noqa: E402
from legacy_store import LegacyItem, LegacyItemStore  # type: ignore  # noqa: E402
from legacy_processor import TraceCallback, process_legacy_payload  # type: ignore  # noqa: E402
from vector_renderer import render_vector, VectorPainterAdapter  # type: ignore  # noqa: E402
from plugin_overrides import PluginOverrideManager  # type: ignore  # noqa: E402
from debug_config import DebugConfig, load_debug_config  # type: ignore  # noqa: E402

_LOGGER_NAME = "EDMC.ModernOverlay.Client"
_CLIENT_LOGGER = logging.getLogger(_LOGGER_NAME)
_CLIENT_LOGGER.setLevel(logging.DEBUG)
_CLIENT_LOGGER.propagate = False

DEFAULT_WINDOW_BASE_WIDTH = 1280
DEFAULT_WINDOW_BASE_HEIGHT = 720

def _initial_platform_context(initial: InitialClientSettings) -> PlatformContext:
    force_env = os.environ.get("EDMC_OVERLAY_FORCE_XWAYLAND") == "1"
    session = os.environ.get("EDMC_OVERLAY_SESSION_TYPE") or os.environ.get("XDG_SESSION_TYPE") or ""
    compositor = os.environ.get("EDMC_OVERLAY_COMPOSITOR") or ""
    return PlatformContext(
        session_type=session,
        compositor=compositor,
        force_xwayland=bool(initial.force_xwayland or force_env),
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
            connection_message = f"{connection_prefix} - Connected to 127.0.0.1:{port}"
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
        self._show_payload_ids: bool = bool(getattr(initial, "show_payload_ids", False))
        self._status_bottom_margin = self._coerce_non_negative(getattr(initial, "status_bottom_margin", 20), default=20)
        self._debug_overlay_corner: str = self._normalise_debug_corner(getattr(initial, "debug_overlay_corner", "NW"))
        self._font_scale_diag = 1.0
        min_font = getattr(initial, "min_font_point", 6.0)
        max_font = getattr(initial, "max_font_point", 24.0)
        self._font_min_point = max(1.0, min(float(min_font), 48.0))
        self._font_max_point = max(self._font_min_point, min(float(max_font), 72.0))
        self._override_manager = PluginOverrideManager(
            ROOT_DIR / "plugin_overrides.json",
            _CLIENT_LOGGER,
            debug_config=self._debug_config,
        )
        layout = QVBoxLayout()
        layout.addWidget(self.message_label, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        layout.addStretch(1)
        layout.setContentsMargins(20, 20, 20, 40)
        self._apply_drag_state()
        self.setLayout(layout)

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

    def _legacy_scale_components(self, *, use_physical: bool = True) -> Tuple[float, float]:
        width = max(self.width(), 1)
        height = max(self.height(), 1)
        scale_x = width / float(DEFAULT_WINDOW_BASE_WIDTH)
        scale_y = height / float(DEFAULT_WINDOW_BASE_HEIGHT)
        if use_physical:
            ratio = self.devicePixelRatioF()
            if ratio <= 0.0:
                ratio = 1.0
            scale_x *= ratio
            scale_y *= ratio
        return max(scale_x, 0.01), max(scale_y, 0.01)

    def _legacy_scale(self, *, use_physical: bool = True) -> Tuple[float, float]:
        return self._legacy_scale_components(use_physical=use_physical)

    def _scaled_point_size(
        self,
        base_point: float,
        clamp_min: Optional[float] = None,
        clamp_max: Optional[float] = None,
    ) -> float:
        if clamp_min is None:
            clamp_min = self._font_min_point
        if clamp_max is None:
            clamp_max = self._font_max_point
        diagonal_scale = self._font_scale_diag
        if diagonal_scale <= 0.0:
            scale_x, scale_y = self._legacy_scale()
            diagonal_scale = math.sqrt((scale_x * scale_x + scale_y * scale_y) / 2.0)
        return max(clamp_min, min(clamp_max, base_point * diagonal_scale))

    def _update_message_font(self) -> None:
        target_point = self._scaled_point_size(self._base_message_point_size)
        if not math.isclose(target_point, self._debug_message_point_size, rel_tol=1e-3):
            font = self.message_label.font()
            font.setPointSizeF(target_point)
            self.message_label.setFont(font)
            self._debug_message_point_size = target_point
            self._publish_metrics()

    def _publish_metrics(self) -> None:
        client = self._data_client
        if client is None:
            return
        width_px, height_px = self._current_physical_size()
        scale_x, scale_y = self._legacy_scale()
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
            },
            "device_pixel_ratio": float(self.devicePixelRatioF()),
        }
        client.send_cli_payload(payload)

    def format_scale_debug(self) -> str:
        width_px, height_px = self._current_physical_size()
        scale_x, scale_y = self._legacy_scale()
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
            grid_pen.setWidth(1)
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

    def set_show_payload_ids(self, enabled: bool) -> None:
        flag = bool(enabled)
        if flag == self._show_payload_ids:
            return
        self._show_payload_ids = flag
        _CLIENT_LOGGER.debug("Payload ID labels %s", "enabled" if flag else "disabled")
        self.update()

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
            self.update()

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
        new_context = PlatformContext(session_type=session, compositor=compositor, force_xwayland=force_flag)
        if new_context == self._platform_context:
            return
        self._platform_context = new_context
        self._platform_controller.update_context(new_context)
        self._platform_controller.prepare_window(self.windowHandle())
        self._platform_controller.apply_click_through(True)
        self._restore_drag_interactivity()
        _CLIENT_LOGGER.debug(
            "Platform context updated: session=%s compositor=%s force_xwayland=%s",
            new_context.session_type or "unknown",
            new_context.compositor or "unknown",
            new_context.force_xwayland,
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
    ) -> Tuple[int, int, int, int]:
        if not self._title_bar_enabled or self._title_bar_height <= 0:
            return geometry
        x, y, width, height = geometry
        if height <= 1:
            return geometry
        scaled_offset = float(self._title_bar_height) * max(scale_y, 0.0)
        offset = min(int(round(scaled_offset)), max(0, height - 1))
        if offset <= 0:
            return geometry
        adjusted_height = max(1, height - offset)
        return (x, y + offset, width, adjusted_height)

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
        desired_tuple = self._apply_title_bar_offset(tracker_qt_tuple, scale_y=scale_y)
        desired_tuple = self._apply_aspect_guard(desired_tuple)

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

    def _apply_aspect_guard(self, geometry: Tuple[int, int, int, int]) -> Tuple[int, int, int, int]:
        x, y, width, height = geometry
        if width <= 0 or height <= 0:
            return geometry
        base_ratio = DEFAULT_WINDOW_BASE_WIDTH / float(DEFAULT_WINDOW_BASE_HEIGHT)
        current_ratio = width / float(height)
        ratio_delta = abs(current_ratio - base_ratio) / base_ratio
        if ratio_delta >= 0.12:
            return geometry
        expected_height = int(round(width * DEFAULT_WINDOW_BASE_HEIGHT / float(DEFAULT_WINDOW_BASE_WIDTH)))
        tolerance = max(2, int(round(expected_height * 0.01)))
        if height > expected_height + tolerance:
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

        min_width = max(
            min_hint.width() if isinstance(min_hint, QSize) else 0,
            size_hint.width() if isinstance(size_hint, QSize) else 0,
        )
        min_height = max(
            min_hint.height() if isinstance(min_hint, QSize) else 0,
            size_hint.height() if isinstance(size_hint, QSize) else 0,
        )

        width_constrained = width_diff > 0 and min_width > 0 and actual_width >= (min_width - tolerance)
        height_constrained = height_diff > 0 and min_height > 0 and actual_height >= (min_height - tolerance)

        if width_constrained or height_constrained:
            return "layout"
        return "wm_intervention"

    # Legacy overlay handling ---------------------------------------------

    def _update_auto_legacy_scale(self, width: int, height: int) -> None:
        scale_x, scale_y = self._legacy_scale(use_physical=True)
        diagonal_scale = math.sqrt((scale_x * scale_x + scale_y * scale_y) / 2.0)
        self._font_scale_diag = diagonal_scale
        self._update_message_font()
        current = (round(scale_x, 4), round(scale_y, 4), round(diagonal_scale, 4))
        if self._last_logged_scale != current:
            width_px, height_px = self._current_physical_size()
            _CLIENT_LOGGER.debug(
                "Overlay scaling updated: window=%dx%d px scale_x=%.3f scale_y=%.3f diag=%.2f message_pt=%.1f",
                int(round(width_px)),
                int(round(height_px)),
                scale_x,
                scale_y,
                diagonal_scale,
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
        return None

    def _should_trace_payload(self, plugin: Optional[str], message_id: str) -> bool:
        cfg = self._debug_config
        if not cfg.trace_enabled:
            return False
        if cfg.trace_plugin:
            if not plugin or cfg.trace_plugin != plugin:
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
        trace_enabled = self._should_trace_payload(plugin_name, message_id)
        self._override_manager.apply(payload)
        if trace_enabled and str(payload.get("shape") or "").lower() == "vect":
            self._log_legacy_trace(plugin_name, message_id, "post_override", {"points": payload.get("vector")})
        trace_fn: Optional[TraceCallback] = None
        if trace_enabled:
            def trace_fn(stage: str, _payload: Mapping[str, Any], extra: Mapping[str, Any]) -> None:
                self._log_legacy_trace(plugin_name, message_id, stage, extra)

        if process_legacy_payload(self._legacy_items, payload, trace_fn=trace_fn):
            self.update()

    def _purge_legacy(self) -> None:
        now = time.monotonic()
        if self._legacy_items.purge_expired(now):
            self.update()

    def _paint_legacy(self, painter: QPainter) -> None:
        for item_id, item in self._legacy_items.items():
            if item.kind == "message":
                self._paint_legacy_message(painter, item_id, item.data)
            elif item.kind == "rect":
                self._paint_legacy_rect(painter, item_id, item.data)
            elif item.kind == "vector":
                self._paint_legacy_vector(painter, item)

    def _legacy_coordinate_scale_factors(self) -> Tuple[float, float]:
        return self._legacy_scale(use_physical=False)

    def _legacy_aspect_factor(self) -> float:
        scale_x, scale_y = self._legacy_coordinate_scale_factors()
        if scale_x <= 0.0:
            return 1.0
        return scale_y / scale_x

    def _legacy_preset_point_size(self, preset: str) -> float:
        """Return the scaled font size for a legacy preset relative to normal."""
        normal_point = self._scaled_point_size(10.0)
        offsets = {
            "small": -2.0,
            "normal": 0.0,
            "large": 2.0,
            "huge": 4.0,
        }
        target = normal_point + offsets.get(preset.lower(), 0.0)
        return max(1.0, target)

    def _draw_item_id(self, painter: QPainter, item_id: str, top_left_x: int, top_left_y: int) -> None:
        if not self._show_payload_ids:
            return
        label = str(item_id)
        if not label:
            return
        painter.save()
        font = QFont(self._font_family)
        font.setPointSizeF(max(4.0, self._legacy_preset_point_size("small")))
        font.setWeight(QFont.Weight.Normal)
        painter.setFont(font)
        painter.setPen(QColor(190, 220, 255, 220))
        metrics = painter.fontMetrics()
        x = max(0, int(round(top_left_x)))
        text_width = metrics.horizontalAdvance(label)
        if x + text_width > self.width():
            x = max(0, self.width() - text_width)
        baseline = int(round(top_left_y - 2))
        baseline = max(metrics.ascent(), baseline)
        baseline = min(self.height() - 1, baseline)
        painter.drawText(x, baseline, label)
        painter.restore()

    def _paint_legacy_message(self, painter: QPainter, item_id: str, item: Dict[str, Any]) -> None:
        color = QColor(str(item.get("color", "white")))
        size = str(item.get("size", "normal")).lower()
        scaled_point_size = self._legacy_preset_point_size(size)
        scale_x, scale_y = self._legacy_coordinate_scale_factors()
        font = QFont(self._font_family)
        font.setPointSizeF(scaled_point_size)
        font.setWeight(QFont.Weight.Normal)
        painter.setPen(color)
        self._debug_legacy_point_size = scaled_point_size
        painter.setFont(font)
        raw_left = float(item.get("x", 0))
        raw_top = float(item.get("y", 0))
        text = str(item.get("text", ""))
        x = int(round(raw_left * scale_x))
        metrics = painter.fontMetrics()
        text_width = metrics.horizontalAdvance(text)
        margin = 12
        max_x = self.width() - text_width - margin
        min_x = margin
        if max_x < min_x:
            max_x = min_x
        available_width = max(1, self.width() - (2 * margin))
        if text_width > available_width:
            shrink_ratio = available_width / float(text_width)
            adjusted_point = max(4.0, scaled_point_size * shrink_ratio)
            if adjusted_point < font.pointSizeF() - 0.1:
                font.setPointSizeF(adjusted_point)
                painter.setFont(font)
                metrics = painter.fontMetrics()
                text_width = metrics.horizontalAdvance(text)
                max_x = self.width() - text_width - margin
                if max_x < min_x:
                    max_x = min_x
                self._debug_legacy_point_size = adjusted_point
        if x < min_x:
            x = min_x
        elif x > max_x:
            x = max_x
        baseline = int(round(raw_top * scale_y + metrics.ascent()))
        painter.drawText(x, baseline, text)

        if self._show_payload_ids:
            top_left_y = baseline - metrics.ascent()
            self._draw_item_id(painter, item_id, x, int(round(top_left_y)))

    def _paint_legacy_rect(self, painter: QPainter, item_id: str, item: Dict[str, Any]) -> None:
        border_spec = str(item.get("color", "white"))
        fill_spec = str(item.get("fill", "#00000000"))

        pen: QPen
        if not border_spec or border_spec.lower() == "none":
            pen = QPen(Qt.PenStyle.NoPen)
        else:
            border_color = QColor(border_spec)
            if not border_color.isValid():
                border_color = QColor("white")
            pen = QPen(border_color)
            pen.setWidth(2)

        if not fill_spec or fill_spec.lower() == "none":
            brush = QBrush(Qt.BrushStyle.NoBrush)
        else:
            fill_color = QColor(fill_spec)
            if not fill_color.isValid():
                fill_color = QColor("#00000000")
            brush = QBrush(fill_color)

        painter.setPen(pen)
        painter.setBrush(brush)
        scale_x, scale_y = self._legacy_coordinate_scale_factors()
        aspect_factor = self._legacy_aspect_factor()
        raw_x = float(item.get("x", 0))
        raw_y = float(item.get("y", 0))
        raw_w = float(item.get("w", 0))
        raw_h = float(item.get("h", 0))
        if not math.isclose(aspect_factor, 1.0, rel_tol=1e-3):
            center_x = raw_x + raw_w / 2.0
            raw_w *= aspect_factor
            raw_x = center_x - raw_w / 2.0
        x = int(round(raw_x * scale_x))
        y = int(round(raw_y * scale_y))
        w = max(1, int(round(max(raw_w, 0.0) * scale_x)))
        h = max(1, int(round(max(raw_h, 0.0) * scale_y)))
        painter.drawRect(
            x,
            y,
            w,
            h,
        )

        if self._show_payload_ids:
            self._draw_item_id(painter, item_id, x, y)

    def _paint_legacy_vector(self, painter: QPainter, legacy_item: LegacyItem) -> None:
        item_id = legacy_item.item_id
        item = legacy_item.data
        plugin_name = legacy_item.plugin
        trace_enabled = self._should_trace_payload(plugin_name, item_id)
        adapter = _QtVectorPainterAdapter(self, painter)
        scale_x, scale_y = self._legacy_coordinate_scale_factors()
        aspect_factor = self._legacy_aspect_factor()
        if trace_enabled:
            self._log_legacy_trace(
                plugin_name,
                item_id,
                "paint:scale_factors",
                {"scale_x": scale_x, "scale_y": scale_y, "aspect": aspect_factor},
            )
            self._log_legacy_trace(
                plugin_name,
                item_id,
                "paint:raw_points",
                {"points": item.get("points")},
            )
        vector_payload = item
        transform_meta = vector_payload.get("__mo_transform__") if isinstance(vector_payload, Mapping) else None
        pivot_override: Optional[float] = None
        if isinstance(transform_meta, Mapping):
            pivot_info = transform_meta.get("pivot")
            if isinstance(pivot_info, Mapping):
                try:
                    pivot_override = float(pivot_info.get("x"))
                except (TypeError, ValueError):
                    pivot_override = None
        if not math.isclose(aspect_factor, 1.0, rel_tol=1e-3):
            points = item.get("points", [])
            adjusted_points = []
            xs = []
            for point in points:
                if not isinstance(point, Mapping):
                    continue
                try:
                    x_val = float(point.get("x", 0.0))
                except (TypeError, ValueError):
                    continue
                xs.append(x_val)
            if xs:
                if pivot_override is not None:
                    center_x = pivot_override
                else:
                    center_x = (min(xs) + max(xs)) / 2.0
                for point in points:
                    if not isinstance(point, Mapping):
                        continue
                    try:
                        x_val = float(point.get("x", 0.0))
                        y_val = float(point.get("y", 0.0))
                    except (TypeError, ValueError):
                        continue
                    adjusted_point = dict(point)
                    adjusted_point["x"] = center_x + (x_val - center_x) * aspect_factor
                    adjusted_point["y"] = y_val
                    adjusted_points.append(adjusted_point)
            if adjusted_points:
                vector_payload = dict(item)
                vector_payload["points"] = adjusted_points
                if trace_enabled:
                    self._log_legacy_trace(
                        plugin_name,
                        item_id,
                        "paint:aspect_adjusted_points",
                        {"points": adjusted_points},
                    )
        if trace_enabled and pivot_override is not None:
            self._log_legacy_trace(
                plugin_name,
                item_id,
                "paint:anchor",
                {"pivot_x": pivot_override},
            )
        trace_fn = None
        if trace_enabled:
            def trace_fn(stage: str, details: Mapping[str, Any]) -> None:
                self._log_legacy_trace(plugin_name, item_id, stage, details)

        render_vector(adapter, vector_payload, scale_x, scale_y, trace=trace_fn)

        if self._show_payload_ids:
            points = vector_payload.get("points", [])
            scaled_points: List[Tuple[int, int]] = []
            for point in points:
                if not isinstance(point, Mapping):
                    continue
                try:
                    raw_x = float(point.get("x", 0.0))
                    raw_y = float(point.get("y", 0.0))
                except (TypeError, ValueError):
                    continue
                scaled_points.append(
                    (
                        int(round(raw_x * scale_x)),
                        int(round(raw_y * scale_y)),
                    )
                )
            if scaled_points:
                min_x = min(pt[0] for pt in scaled_points)
                min_y = min(pt[1] for pt in scaled_points)
                self._draw_item_id(painter, item_id, min_x, min_y)

    def _paint_debug_overlay(self, painter: QPainter) -> None:
        if not self._show_debug_overlay:
            return
        frame = self.frameGeometry()
        scale_x, scale_y = self._legacy_coordinate_scale_factors()
        diagonal_scale = self._font_scale_diag
        if diagonal_scale <= 0.0:
            diagonal_scale = math.sqrt((scale_x * scale_x + scale_y * scale_y) / 2.0)
        width_px, height_px = self._current_physical_size()
        size_labels = [("S", "small"), ("N", "normal"), ("L", "large"), ("H", "huge")]
        legacy_sizes_str = " ".join(
            "{}={:.1f}".format(label, self._legacy_preset_point_size(name))
            for label, name in size_labels
        )
        monitor_desc = self._last_screen_name or self._describe_screen(self.windowHandle().screen() if self.windowHandle() else None)
        monitor_lines = [
            "Monitor:",
            f"  active={monitor_desc or 'unknown'}",
        ]
        if self._last_follow_state is not None:
            monitor_lines.append(
                "  tracker=({},{}) {}x{}".format(
                    self._last_follow_state.x,
                    self._last_follow_state.y,
                    self._last_follow_state.width,
                    self._last_follow_state.height,
                )
            )
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

        overlay_lines = [
            "Overlay:",
            "  widget={}x{}".format(self.width(), self.height()),
            "  frame={}x{} phys={}x{}".format(
                frame.width(),
                frame.height(),
                int(round(width_px)),
                int(round(height_px)),
            ),
        ]
        if self._last_raw_window_log is not None:
            raw_x, raw_y, raw_w, raw_h = self._last_raw_window_log
            overlay_lines.append("  raw=({},{}) {}x{}".format(raw_x, raw_y, raw_w, raw_h))

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

        info_lines = monitor_lines + [""] + overlay_lines + [""] + font_lines
        painter.save()
        debug_font = QFont(self._font_family, 10)
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


class _QtVectorPainterAdapter(VectorPainterAdapter):
    def __init__(self, window: "OverlayWindow", painter: QPainter) -> None:
        self._window = window
        self._painter = painter

    def set_pen(self, color: str, *, width: int = 2) -> None:
        q_color = QColor(color)
        if not q_color.isValid():
            q_color = QColor("white")
        pen = QPen(q_color)
        pen.setWidth(width)
        self._painter.setPen(pen)
        self._painter.setBrush(Qt.BrushStyle.NoBrush)

    def draw_line(self, x1: int, y1: int, x2: int, y2: int) -> None:
        self._painter.drawLine(x1, y1, x2, y2)

    def draw_circle_marker(self, x: int, y: int, radius: int, color: str) -> None:
        q_color = QColor(color)
        if not q_color.isValid():
            q_color = QColor("white")
        pen = QPen(q_color)
        pen.setWidth(2)
        self._painter.setPen(pen)
        self._painter.setBrush(QBrush(q_color))
        self._painter.drawEllipse(QPoint(x, y), radius, radius)

    def draw_cross_marker(self, x: int, y: int, size: int, color: str) -> None:
        self.set_pen(color, width=2)
        self._painter.drawLine(x - size, y - size, x + size, y + size)
        self._painter.drawLine(x - size, y + size, x + size, y - size)

    def draw_text(self, x: int, y: int, text: str, color: str) -> None:
        q_color = QColor(color)
        if not q_color.isValid():
            q_color = QColor("white")
        pen = QPen(q_color)
        self._painter.setPen(pen)
        font = QFont(self._window._font_family)
        font.setPointSizeF(self._window._legacy_preset_point_size("small"))
        font.setWeight(QFont.Weight.Normal)
        self._painter.setFont(font)
        self._painter.drawText(x, y, text)

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
    helper = DeveloperHelperController(_CLIENT_LOGGER, CLIENT_DIR, initial_settings)

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
        _CLIENT_LOGGER.debug(
            "Debug tracing enabled for plugin=%s payload_ids=%s",
            debug_config.trace_plugin or "*",
            ",".join(debug_config.trace_payload_ids) if debug_config.trace_payload_ids else "*",
        )

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

if __name__ == "__main__":
    raise SystemExit(main())
