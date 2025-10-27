"""Standalone PyQt6 overlay client for EDMC Modern Overlay."""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PyQt6.QtCore import Qt, pyqtSignal, QObject, QTimer, QPoint, QRect
from PyQt6.QtGui import QColor, QFont, QPainter, QPen, QBrush, QCursor, QFontDatabase, QGuiApplication, QWindow
from PyQt6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

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

            connection_message = f"Connected to 127.0.0.1:{port}"
            if plugin_version and plugin_version != "unknown":
                connection_message = f"{connection_message} – v{plugin_version}"
            if sys.platform.startswith("linux"):
                session_type = os.environ.get("XDG_SESSION_TYPE")
                if session_type:
                    connection_message = f"{connection_message} ({session_type})"
            self.status_changed.emit(connection_message)
            backoff = 1.0
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
                if writer is not None:
                    try:
                        writer.close()
                        await writer.wait_closed()
                    except Exception:
                        pass
            await asyncio.sleep(backoff)
            backoff = min(backoff * 1.5, 10.0)

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

    def __init__(self, initial: InitialClientSettings) -> None:
        super().__init__()
        self._font_family = self._resolve_font_family()
        self._status_raw = "Initialising"
        self._status = self._status_raw
        self._state: Dict[str, Any] = {
            "message": "",
        }
        self._legacy_items: Dict[str, Dict[str, Any]] = {}
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
        self._last_follow_state: Optional[WindowState] = None
        self._follow_resume_at: float = 0.0
        self._lost_window_logged: bool = False
        self._last_tracker_state: Optional[Tuple[str, int, int, int, int]] = None
        self._last_geometry_log: Optional[Tuple[int, int, int, int]] = None
        self._last_move_log: Optional[Tuple[int, int]] = None
        self._last_status_log: Optional[Tuple[int, int]] = None
        self._last_screen_name: Optional[str] = None
        self._last_set_geometry: Optional[Tuple[int, int, int, int]] = None
        self._last_visibility_state: Optional[bool] = None
        self._wm_authoritative_rect: Optional[Tuple[int, int, int, int]] = None
        self._wm_override_tracker: Optional[Tuple[int, int, int, int]] = None
        self._wm_override_timestamp: float = 0.0
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

        status_font = QFont(self._font_family, 18)
        status_font.setWeight(QFont.Weight.Normal)
        message_font = QFont(self._font_family, 16)
        message_font.setWeight(QFont.Weight.Normal)
        self.message_label = QLabel("")
        self.message_label.setFont(message_font)
        self.message_label.setStyleSheet("color: #80d0ff; background: transparent;")
        self.message_label.setWordWrap(True)
        self.message_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.message_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.status_label = QLabel(self._status)
        self.status_label.setFont(status_font)
        self.status_label.setStyleSheet("color: white; background: transparent;")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom)
        self.status_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        self._debug_message_point_size = message_font.pointSizeF()
        self._debug_legacy_point_size = 0.0
        self._show_debug_overlay = bool(getattr(initial, "show_debug_overlay", False))

        layout = QVBoxLayout()
        layout.addWidget(self.message_label, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        layout.addStretch(1)
        layout.addWidget(self.status_label, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom)
        # Raise the bottom status label ~10px further by increasing bottom margin
        layout.setContentsMargins(20, 20, 20, 40)
        self._apply_drag_state()
        self.setLayout(layout)
        self.status_label.setVisible(False)

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

    def _legacy_scale(self) -> Tuple[float, float]:
        width_px, height_px = self._current_physical_size()
        scale_x = width_px / float(DEFAULT_WINDOW_BASE_WIDTH)
        scale_y = height_px / float(DEFAULT_WINDOW_BASE_HEIGHT)
        return max(scale_x, 0.01), max(scale_y, 0.01)

    def _update_message_font(self, diagonal_scale: float) -> None:
        base_point = 12.0
        target_point = max(6.0, min(36.0, base_point * diagonal_scale))
        if not math.isclose(target_point, self._debug_message_point_size, rel_tol=1e-3):
            font = self.message_label.font()
            font.setPointSizeF(target_point)
            self.message_label.setFont(font)
            self._debug_message_point_size = target_point

    def format_scale_debug(self) -> str:
        width_px, height_px = self._current_physical_size()
        scale_x, scale_y = self._legacy_scale()
        return "size={:.0f}x{:.0f}px scale_x={:.2f} scale_y={:.2f}".format(width_px, height_px, scale_x, scale_y)

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
                )
            self._last_move_log = current
            self._update_status_position_info()

    # External control -----------------------------------------------------

    @property
    def gridlines_enabled(self) -> bool:
        return self._gridlines_enabled

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
        self._status = status
        self._last_status_log = None
        self._refresh_status_label()
        self._update_status_visibility()

    def set_show_status(self, show: bool) -> None:
        self._show_status = bool(show)
        if not self._show_status:
            self.status_label.clear()
            self._last_status_log = None
        self._refresh_status_label()
        self._update_status_visibility()

    def _refresh_status_label(self) -> None:
        if not self._show_status:
            return
        text = self._compose_status_text()
        if text != self.status_label.text():
            self.status_label.setText(text)

    def _compose_status_text(self) -> str:
        base = (self._status_raw or "").strip()
        augmented = self._augment_connection_status(base)
        self._status = augmented
        frame = self.frameGeometry()
        screen_desc = self._describe_screen(self.windowHandle().screen() if self.windowHandle() else None)
        position = f"x={frame.x()} y={frame.y()}"
        suffix = f"{position} on {screen_desc}"
        if augmented:
            return f"{augmented} ({suffix})"
        return f"Overlay position ({suffix})"

    def _augment_connection_status(self, status: str) -> str:
        base = (status or "").strip()
        if not base.lower().startswith("connected to"):
            return base
        if "scale_y=" in base or "scale_x=" in base:
            return base
        width_px, height_px = self._current_physical_size()
        scale_x, scale_y = self._legacy_scale()
        metrics = f"{int(round(width_px))}x{int(round(height_px))}px scale_x={scale_x:.2f} scale_y={scale_y:.2f}"
        separator = " – " if " – " not in base else " "
        return f"{base}{separator}{metrics}"

    def _update_status_position_info(self) -> None:
        if not self._show_status:
            return
        frame = self.frameGeometry()
        current = (frame.x(), frame.y())
        if current != self._last_status_log:
            screen_desc = self._describe_screen(self.windowHandle().screen() if self.windowHandle() else None)
            _CLIENT_LOGGER.debug(
                "Updating status position info: pos=(%d,%d) monitor=%s; %s",
                frame.x(),
                frame.y(),
                screen_desc,
                self.format_scale_debug(),
            )
            self._last_status_log = current
        self._refresh_status_label()

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

    def _update_status_visibility(self) -> None:
        should_display = bool(self._show_status)
        if self.status_label.isVisible() != should_display:
            _CLIENT_LOGGER.debug("Overlay status label visibility set to %s; %s", should_display, self.format_scale_debug())
        self.status_label.setVisible(should_display)

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
        for child_name in ("message_label", "status_label"):
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
    ) -> None:
        self._wm_authoritative_rect = rect
        self._wm_override_tracker = tracker_tuple
        self._wm_override_timestamp = time.monotonic()
        _CLIENT_LOGGER.debug(
            "Recorded WM authoritative rect (%s): actual=%s tracker=%s; %s",
            reason,
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

    def _apply_follow_state(self, state: WindowState) -> None:
        self._lost_window_logged = False

        tracker_global_x = state.global_x if state.global_x is not None else state.x
        tracker_global_y = state.global_y if state.global_y is not None else state.y
        width = max(1, state.width)
        height = max(1, state.height)
        tracker_target_tuple = (
            tracker_global_x,
            tracker_global_y,
            width,
            height,
        )

        now = time.monotonic()
        target_tuple = tracker_target_tuple
        if self._wm_authoritative_rect is not None:
            tracker_changed = (
                self._wm_override_tracker is not None
                and tracker_target_tuple != self._wm_override_tracker
            )
            override_expired = (now - self._wm_override_timestamp) >= self._WM_OVERRIDE_TTL
            if tracker_target_tuple == self._wm_authoritative_rect:
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
            self._set_wm_override(actual_tuple, tracker_target_tuple, reason="geometry mismatch")
            target_tuple = actual_tuple
            target_rect = QRect(*target_tuple)
        elif self._wm_authoritative_rect and tracker_target_tuple == target_tuple:
            self._clear_wm_override(reason="tracker matched actual")

        final_global_x = target_tuple[0]
        final_global_y = target_tuple[1]

        self._last_geometry_log = target_tuple
        self._last_follow_state = WindowState(
            x=final_global_x,
            y=final_global_y,
            width=state.width,
            height=state.height,
            is_foreground=state.is_foreground,
            is_visible=state.is_visible,
            identifier=state.identifier,
            global_x=final_global_x,
            global_y=final_global_y,
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

    # Legacy overlay handling ---------------------------------------------

    def _update_auto_legacy_scale(self, width: int, height: int) -> None:
        scale_x, scale_y = self._legacy_scale()
        diagonal_scale = math.sqrt((scale_x * scale_x + scale_y * scale_y) / 2.0)
        self._update_message_font(diagonal_scale)
        current = (round(scale_x, 4), round(scale_y, 4), round(diagonal_scale, 4))
        if self._last_logged_scale != current:
            width_px, height_px = self._current_physical_size()
            _CLIENT_LOGGER.debug(
                "Overlay scaling updated: window=%dx%d px scale_x=%.2f scale_y=%.2f diag=%.2f message_pt=%.1f",
                int(round(width_px)),
                int(round(height_px)),
                scale_x,
                scale_y,
                diagonal_scale,
                self._debug_message_point_size,
            )
            self._last_logged_scale = current

    def _handle_legacy(self, payload: Dict[str, Any]) -> None:
        item_type = payload.get("type")
        item_id = payload.get("id")
        if item_type == "clear_all":
            self._legacy_items.clear()
            self.update()
            return
        if not isinstance(item_id, str):
            return

        ttl = max(int(payload.get("ttl", 4)), 0)
        expiry: Optional[float] = None if ttl <= 0 else time.monotonic() + ttl

        if item_type == "message":
            text = payload.get("text", "")
            if not text:
                self._legacy_items.pop(item_id, None)
                self.update()
                return
            item = {
                "kind": "message",
                "text": text,
                "color": payload.get("color", "white"),
                "x": int(payload.get("x", 0)),
                "y": int(payload.get("y", 0)),
                "size": payload.get("size", "normal"),
                "expiry": expiry,
            }
            self._legacy_items[item_id] = item
            self.update()
            return

        if item_type == "shape" and payload.get("shape") == "rect":
            fill = payload.get("fill") or "#00000000"
            item = {
                "kind": "rect",
                "color": payload.get("color", "white"),
                "fill": fill,
                "x": int(payload.get("x", 0)),
                "y": int(payload.get("y", 0)),
                "w": int(payload.get("w", 0)),
                "h": int(payload.get("h", 0)),
                "expiry": expiry,
            }
            self._legacy_items[item_id] = item
            self.update()
            return

        if item_type == "raw":
            return

    def _purge_legacy(self) -> None:
        now = time.monotonic()
        expired = [key for key, item in self._legacy_items.items() if item.get("expiry") is not None and item["expiry"] < now]
        for key in expired:
            self._legacy_items.pop(key, None)
        if expired:
            self.update()

    def _paint_legacy(self, painter: QPainter) -> None:
        for item in self._legacy_items.values():
            kind = item.get("kind")
            if kind == "message":
                self._paint_legacy_message(painter, item)
            elif kind == "rect":
                self._paint_legacy_rect(painter, item)

    def _legacy_coordinate_scale_factors(self) -> Tuple[float, float]:
        return self._legacy_scale()

    def _paint_legacy_message(self, painter: QPainter, item: Dict[str, Any]) -> None:
        color = QColor(str(item.get("color", "white")))
        size = str(item.get("size", "normal")).lower()
        base_sizes = {
            "small": 6.0,
            "normal": 10.0,
            "large": 12.0,
            "huge": 14.0,
        }
        base_point_size = base_sizes.get(size, 10.0)
        scale_x, scale_y = self._legacy_coordinate_scale_factors()
        diagonal_scale = math.sqrt((scale_x * scale_x + scale_y * scale_y) / 2.0)
        scaled_point_size = max(6.0, min(36.0, base_point_size * diagonal_scale))
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
        if x < min_x:
            x = min_x
        elif x > max_x:
            x = max_x
        baseline = int(round(raw_top * scale_y + metrics.ascent()))
        painter.drawText(x, baseline, text)

    def _paint_legacy_rect(self, painter: QPainter, item: Dict[str, Any]) -> None:
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
        x = int(round(float(item.get("x", 0)) * scale_x))
        y = int(round(float(item.get("y", 0)) * scale_y))
        w = int(round(float(item.get("w", 0)) * scale_x))
        h = int(round(float(item.get("h", 0)) * scale_y))
        painter.drawRect(
            x,
            y,
            w,
            h,
        )

    def _paint_debug_overlay(self, painter: QPainter) -> None:
        if not self._show_debug_overlay:
            return
        frame = self.frameGeometry()
        scale_x, scale_y = self._legacy_coordinate_scale_factors()
        diagonal_scale = math.sqrt((scale_x * scale_x + scale_y * scale_y) / 2.0)
        width_px, height_px = self._current_physical_size()
        size_labels = [("S", 6.0), ("N", 10.0), ("L", 12.0), ("H", 14.0)]
        legacy_sizes_str = " ".join(
            "{}={:.1f}".format(label, max(6.0, min(36.0, base * diagonal_scale)))
            for label, base in size_labels
        )
        info_lines = [
            "overlay={}x{}".format(self.width(), self.height()),
            "frame={}x{} phys={}x{}".format(
                frame.width(),
                frame.height(),
                int(round(width_px)),
                int(round(height_px)),
            ),
            "scale_x={:.2f} scale_y={:.2f} diag={:.2f}".format(scale_x, scale_y, diagonal_scale),
            "fonts: message={:.1f} legacy={:.1f}".format(
                self._debug_message_point_size,
                self._debug_legacy_point_size,
            ),
            "legacy sizes: {}".format(legacy_sizes_str),
        ]
        painter.save()
        debug_font = QFont(self._font_family, 10)
        painter.setFont(debug_font)
        metrics = painter.fontMetrics()
        line_height = metrics.height()
        text_width = max(metrics.horizontalAdvance(line) for line in info_lines)
        padding = 6
        rect = QRect(
            4,
            4,
            text_width + padding * 2,
            line_height * len(info_lines) + padding * 2,
        )
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
        self._refresh_status_label()

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

    app = QApplication(sys.argv)
    data_client = OverlayDataClient(port_file)
    window = OverlayWindow(initial_settings)
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
