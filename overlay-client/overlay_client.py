"""Standalone PyQt6 overlay client for EDMC Modern Overlay."""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from PyQt6.QtCore import Qt, pyqtSignal, QObject, QTimer, QPoint, QRect
from PyQt6.QtGui import QColor, QFont, QPainter, QPen, QBrush, QCursor, QFontDatabase, QGuiApplication, QWindow
from PyQt6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget


CLIENT_DIR = Path(__file__).resolve().parent
if str(CLIENT_DIR) not in sys.path:
    sys.path.insert(0, str(CLIENT_DIR))

from client_config import InitialClientSettings, load_initial_settings  # type: ignore  # noqa: E402
from developer_helpers import DeveloperHelperController  # type: ignore  # noqa: E402
from window_tracking import WindowState, WindowTracker, create_elite_window_tracker  # type: ignore  # noqa: E402


_LOGGER_NAME = "EDMC.ModernOverlay.Client"
_CLIENT_LOGGER = logging.getLogger(_LOGGER_NAME)
_CLIENT_LOGGER.setLevel(logging.DEBUG)
_CLIENT_LOGGER.propagate = False


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
            port = self._read_port()
            if port is None:
                self.status_changed.emit("Waiting for port.json…")
                await asyncio.sleep(self._loop_sleep)
                continue
            reader = None
            writer = None
            try:
                reader, writer = await asyncio.open_connection("127.0.0.1", port)
            except Exception as exc:
                self.status_changed.emit(f"Connect failed: {exc}")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 1.5, 10.0)
                continue

            self.status_changed.emit(f"Connected to 127.0.0.1:{port}")
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

    def _read_port(self) -> Optional[int]:
        try:
            data = json.loads(self._port_file.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except json.JSONDecodeError:
            return None
        port = data.get("port")
        if isinstance(port, int) and port > 0:
            return port
        return None


class OverlayWindow(QWidget):
    """Transparent overlay that renders CMDR and location info."""

    def __init__(self, initial: InitialClientSettings) -> None:
        super().__init__()
        self._font_family = self._resolve_font_family()
        self._status = "Initialising"
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
        self._legacy_scale_y: float = 1.0
        self._legacy_scale_x: float = 1.0
        self._base_height: int = 0
        self._base_width: int = 0
        self._log_retention: int = max(1, int(initial.client_log_retention))
        self._requested_base_height: Optional[int] = max(360, int(initial.window_height))
        self._requested_width: Optional[int] = max(640, int(initial.window_width))
        self._follow_enabled: bool = bool(getattr(initial, "follow_elite_window", True))
        self._follow_x_offset: int = max(0, int(getattr(initial, "follow_x_offset", 0)))
        self._follow_y_offset: int = max(0, int(getattr(initial, "follow_y_offset", 0)))
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
        self._transient_parent_id: Optional[str] = None
        self._transient_parent_window: Optional[QWindow] = None

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
        self._apply_drag_state()

        status_font = QFont(self._font_family, 18)
        status_font.setWeight(QFont.Weight.Normal)
        message_font = QFont(self._font_family, 16)
        message_font.setWeight(QFont.Weight.Normal)
        self.message_label = QLabel("")
        self.message_label.setFont(message_font)
        self.message_label.setStyleSheet("color: #80d0ff; background: transparent;")
        self.message_label.setWordWrap(True)
        self.status_label = QLabel(self._status)
        self.status_label.setFont(status_font)
        self.status_label.setStyleSheet("color: white; background: transparent;")

        layout = QVBoxLayout()
        layout.addWidget(self.message_label)
        layout.addWidget(self.status_label)
        layout.setContentsMargins(20, 20, 20, 20)
        self.setLayout(layout)
        self.status_label.setVisible(False)

        _CLIENT_LOGGER.debug(
            "Overlay window initialised; log retention=%d, initial_base_height=%s, initial_width=%s",
            self._log_retention,
            self._requested_base_height,
            self._requested_width,
        )

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        if self._base_height <= 0 or self._base_width <= 0:
            raw_height = self.height()
            raw_width = self.width()
            if self._requested_base_height is not None and self._requested_base_height > 0:
                self._base_height = self._requested_base_height
                base_source = "requested"
            else:
                if raw_height <= 0:
                    raw_height = 1
                self._base_height = raw_height
                base_source = "layout"
            if self._base_width <= 0:
                if self._requested_width is not None and self._requested_width > 0:
                    self._base_width = self._requested_width
                else:
                    if raw_width <= 0:
                        raw_width = 1
                    self._base_width = max(raw_width, 1)
            clamped_scale = max(0.5, min(2.0, self._legacy_scale_y))
            clamped_scale_x = max(0.5, min(2.0, self._legacy_scale_x))
            target_height = max(int(round(self._base_height * clamped_scale)), 1)
            target_width = max(int(round(self._base_width * clamped_scale_x)), 1)
            _CLIENT_LOGGER.debug(
                "Initial window height established: raw_height=%s base_source=%s base_height=%s "
                "legacy_scale_y=%.2f clamped_scale=%.2f target_height=%s base_width=%s legacy_scale_x=%.2f "
                "clamped_scale_x=%.2f target_width=%s",
                raw_height,
                base_source,
                self._base_height,
                self._legacy_scale_y,
                clamped_scale,
                target_height,
                self._base_width,
                self._legacy_scale_x,
                clamped_scale_x,
                target_width,
            )
        self._apply_legacy_scale()
        self._enable_click_through()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        bg_opacity = max(0.0, min(1.0, self._background_opacity))
        if bg_opacity > 0.0:
            alpha = int(255 * bg_opacity)
            painter.setBrush(QColor(0, 0, 0, alpha))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(self.rect(), 12, 12)
            if self._gridlines_enabled and self._gridline_spacing > 0:
                grid_color = QColor(200, 200, 200, alpha)
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
        self._paint_legacy(painter)
        painter.end()
        super().paintEvent(event)

    # Interaction -------------------------------------------------

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
                "Overlay moveEvent: pos=(%d,%d) frame=%s last_set=%s monitor=%s",
                frame.x(),
                frame.y(),
                (frame.x(), frame.y(), frame.width(), frame.height()),
                self._last_set_geometry,
                screen_desc,
            )
            if (
                self._follow_enabled
                and self._last_set_geometry is not None
                and (frame.x(), frame.y(), frame.width(), frame.height()) != self._last_set_geometry
            ):
                self._wm_authoritative_rect = (frame.x(), frame.y(), frame.width(), frame.height())
                _CLIENT_LOGGER.debug(
                    "Recorded WM authoritative rect from moveEvent: %s",
                    self._wm_authoritative_rect,
                )
            self._last_move_log = current
            self._update_status_position_info()

    # External control -----------------------------------------------------

    @property
    def gridlines_enabled(self) -> bool:
        return self._gridlines_enabled

    @property
    def follow_offsets(self) -> Tuple[int, int]:
        return self._follow_x_offset, self._follow_y_offset

    def set_window_tracker(self, tracker: Optional[WindowTracker]) -> None:
        self._window_tracker = tracker
        if tracker and self._follow_enabled:
            self._start_tracking()
            self._refresh_follow_geometry()
        else:
            self._stop_tracking()

    def set_follow_enabled(self, enabled: bool) -> None:
        flag = bool(enabled)
        if flag == self._follow_enabled:
            return
        self._follow_enabled = flag
        if flag:
            self._lost_window_logged = False
            self._suspend_follow(0.5)
            self._start_tracking()
            self._update_follow_visibility(True)
        else:
            self._stop_tracking()
            self._update_follow_visibility(True)
            self._sync_base_dimensions_to_widget()
            self._wm_authoritative_rect = None

    def set_follow_offsets(self, x_offset: int, y_offset: int) -> None:
        try:
            x_val = int(x_offset)
        except (TypeError, ValueError):
            x_val = self._follow_x_offset
        try:
            y_val = int(y_offset)
        except (TypeError, ValueError):
            y_val = self._follow_y_offset
        x_val = max(0, x_val)
        y_val = max(0, y_val)
        if x_val == self._follow_x_offset and y_val == self._follow_y_offset:
            return
        self._follow_x_offset = x_val
        self._follow_y_offset = y_val
        if self._follow_enabled and self._last_follow_state:
            self._apply_follow_state(self._last_follow_state)

    def get_follow_offsets(self) -> Tuple[int, int]:
        return self._follow_x_offset, self._follow_y_offset

    def set_force_render(self, force: bool) -> None:
        flag = bool(force)
        if flag == self._force_render:
            return
        self._force_render = flag
        if flag:
            self._update_follow_visibility(True)
            if self._last_follow_state:
                self._apply_follow_state(self._last_follow_state)
        else:
            if (
                self._follow_enabled
                and self._last_follow_state
                and not self._last_follow_state.is_foreground
            ):
                self._update_follow_visibility(False)

    def display_message(self, message: str) -> None:
        self._state["message"] = message
        self.message_label.setText(message)

    def set_status_text(self, status: str) -> None:
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
        base = (self._status or "").strip()
        frame = self.frameGeometry()
        screen_desc = self._describe_screen(self.windowHandle().screen() if self.windowHandle() else None)
        position = f"x={frame.x()} y={frame.y()}"
        suffix = f"{position} on {screen_desc}"
        if base:
            return f"{base} ({suffix})"
        return f"Overlay position ({suffix})"

    def _update_status_position_info(self) -> None:
        if not self._show_status:
            return
        frame = self.frameGeometry()
        current = (frame.x(), frame.y())
        if current != self._last_status_log:
            screen_desc = self._describe_screen(self.windowHandle().screen() if self.windowHandle() else None)
            _CLIENT_LOGGER.debug("Updating status position info: pos=(%d,%d) monitor=%s", frame.x(), frame.y(), screen_desc)
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
            self._apply_drag_state()

    def set_legacy_scale_y(self, scale: float) -> None:
        try:
            value = float(scale)
        except (TypeError, ValueError):
            value = 1.0
        value = max(0.5, min(2.0, value))
        if value != self._legacy_scale_y:
            self._legacy_scale_y = value
            self._apply_legacy_scale()

    def set_legacy_scale_x(self, scale: float) -> None:
        try:
            value = float(scale)
        except (TypeError, ValueError):
            value = 1.0
        value = max(0.5, min(2.0, value))
        if value != self._legacy_scale_x:
            self._legacy_scale_x = value
            self._apply_legacy_scale()

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
        follow_locked = self._follow_enabled and (self._window_tracker is not None or self._last_follow_state is not None)
        if follow_locked:
            if width is not None:
                try:
                    self._requested_width = max(640, int(width))
                except (TypeError, ValueError):
                    pass
            if height is not None:
                try:
                    self._requested_base_height = max(360, int(height))
                except (TypeError, ValueError):
                    pass
            _CLIENT_LOGGER.debug(
                "Ignoring explicit window size while follow mode is active (requested=%sx%s)",
                self._requested_width,
                self._requested_base_height,
            )
            return

        size_changed = False
        if width is not None:
            try:
                numeric_width = int(width)
            except (TypeError, ValueError):
                numeric_width = self._requested_width or self._base_width or self.width()
            numeric_width = max(640, numeric_width)
            if numeric_width != (self._requested_width or self._base_width):
                size_changed = True
            self._requested_width = numeric_width
            self._base_width = numeric_width
        if height is not None:
            try:
                numeric_height = int(height)
            except (TypeError, ValueError):
                numeric_height = self._requested_base_height or self._base_height or self.height()
            numeric_height = max(360, numeric_height)
            if numeric_height != (self._requested_base_height or self._base_height):
                size_changed = True
            self._requested_base_height = numeric_height
            self._base_height = numeric_height
        if size_changed:
            _CLIENT_LOGGER.debug(
                "Applied window size: width=%s, base_height=%s, scale_y=%.2f, scale_x=%.2f",
                self._requested_width,
                self._base_height,
                self._legacy_scale_y,
                self._legacy_scale_x,
            )
            self._apply_legacy_scale()

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
            _CLIENT_LOGGER.debug("Overlay status label visibility set to %s", should_display)
        self.status_label.setVisible(should_display)

    # Platform integration -------------------------------------------------

    def _enable_click_through(self) -> None:
        if sys.platform.startswith("win"):
            try:
                import ctypes

                user32 = ctypes.windll.user32
                GWL_EXSTYLE = -20
                WS_EX_LAYERED = 0x80000
                WS_EX_TRANSPARENT = 0x20
                hwnd = int(self.winId())
                style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
                user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_LAYERED | WS_EX_TRANSPARENT)
            except Exception:
                pass
        window = self.windowHandle()
        if window and self._transparent_input_supported:
            window.setFlag(Qt.WindowType.WindowTransparentForInput, True)

    def _apply_drag_state(self) -> None:
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
        window = self.windowHandle()
        if window and self._transparent_input_supported:
            window.setFlag(Qt.WindowType.WindowTransparentForInput, transparent)
        if transparent:
            self._enable_click_through()
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setWindowFlag(Qt.WindowType.Tool, True)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.show()

    # Follow mode ----------------------------------------------------------

    def _start_tracking(self) -> None:
        if not self._window_tracker or not self._follow_enabled:
            return
        if not self._tracking_timer.isActive():
            self._tracking_timer.start()

    def _stop_tracking(self) -> None:
        if self._tracking_timer.isActive():
            self._tracking_timer.stop()

    def _suspend_follow(self, delay: float = 0.75) -> None:
        self._follow_resume_at = max(self._follow_resume_at, time.monotonic() + max(0.0, delay))

    def _refresh_follow_geometry(self) -> None:
        if not self._follow_enabled or self._window_tracker is None:
            return
        now = time.monotonic()
        if self._drag_active or self._move_mode:
            self._suspend_follow(0.75)
            _CLIENT_LOGGER.debug("Skipping follow refresh: drag/move active")
            return
        if now < self._follow_resume_at:
            _CLIENT_LOGGER.debug("Skipping follow refresh: awaiting resume window")
            return
        try:
            state = self._window_tracker.poll()
        except Exception as exc:  # pragma: no cover - defensive guard
            _CLIENT_LOGGER.debug("Window tracker poll failed: %s", exc)
            return
        if state is None:
            self._handle_missing_follow_state()
            return
        global_x = state.global_x if state.global_x is not None else state.x
        global_y = state.global_y if state.global_y is not None else state.y
        tracker_key = (state.identifier, global_x, global_y, state.width, state.height)
        if tracker_key != self._last_tracker_state:
            _CLIENT_LOGGER.debug(
                "Tracker state: id=%s global=(%d,%d) size=%dx%d foreground=%s visible=%s",
                state.identifier,
                global_x,
                global_y,
                state.width,
                state.height,
                state.is_foreground,
                state.is_visible,
            )
            self._last_tracker_state = tracker_key
        self._apply_follow_state(state)

    def _apply_follow_state(self, state: WindowState) -> None:
        self._lost_window_logged = False

        tracker_global_x = state.global_x if state.global_x is not None else state.x
        tracker_global_y = state.global_y if state.global_y is not None else state.y
        width = max(1, state.width - 2 * self._follow_x_offset)
        height = max(1, state.height - 2 * self._follow_y_offset)
        tracker_target_tuple = (
            tracker_global_x + self._follow_x_offset,
            tracker_global_y + self._follow_y_offset,
            width,
            height,
        )

        target_tuple = tracker_target_tuple
        if self._wm_authoritative_rect and tracker_target_tuple != self._wm_authoritative_rect:
            target_tuple = self._wm_authoritative_rect
        elif self._wm_authoritative_rect and tracker_target_tuple == self._wm_authoritative_rect:
            _CLIENT_LOGGER.debug("Tracker target realigned with WM authoritative rect; clearing override")
            self._wm_authoritative_rect = None

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
                "Calculated overlay geometry: target=%s offsets=(%d,%d)",
                target_tuple,
                self._follow_x_offset,
                self._follow_y_offset,
            )

        needs_geometry_update = (
            self._wm_authoritative_rect is None
            and actual_tuple != target_tuple
        )

        if needs_geometry_update:
            _CLIENT_LOGGER.debug("Applying geometry via setGeometry: target=%s", target_tuple)
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
                "Window manager override detected: actual=%s target=%s",
                actual_tuple,
                target_tuple,
            )
            self._wm_authoritative_rect = actual_tuple
            target_tuple = actual_tuple
            target_rect = QRect(*target_tuple)
        elif self._wm_authoritative_rect and tracker_target_tuple == target_tuple:
            self._wm_authoritative_rect = None

        final_global_x = target_tuple[0] - self._follow_x_offset
        final_global_y = target_tuple[1] - self._follow_y_offset

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

        self._ensure_transient_parent(state)

        should_show = self._force_render or (state.is_visible and state.is_foreground)
        self._update_follow_visibility(should_show)

    def _ensure_transient_parent(self, state: WindowState) -> None:
        if not sys.platform.startswith("linux"):
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
            _CLIENT_LOGGER.debug("Failed to wrap native window %s: %s", identifier, exc)
            return
        if parent_window is None:
            return
        window_handle.setTransientParent(parent_window)
        self._transient_parent_window = parent_window
        self._transient_parent_id = identifier
        _CLIENT_LOGGER.debug("Set overlay transient parent to Elite window %s", identifier)
    def _handle_missing_follow_state(self) -> None:
        if not self._lost_window_logged:
            _CLIENT_LOGGER.debug("Elite Dangerous window not found; waiting for window to appear")
            self._lost_window_logged = True
        if self._last_follow_state is None:
            if not self._force_render:
                self._update_follow_visibility(False)
            return
        if not self._force_render and not self._last_follow_state.is_foreground:
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
            _CLIENT_LOGGER.debug("Overlay visibility set to %s", "visible" if show else "hidden")
            self._last_visibility_state = show

    def _move_to_screen(self, rect: QRect) -> None:
        window = self.windowHandle()
        if window is None:
            return
        screen = self._screen_for_rect(rect)
        if screen is not None and window.screen() is not screen:
            _CLIENT_LOGGER.debug(
                "Moving overlay to screen %s",
                self._describe_screen(screen),
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
        scale_x = max(0.5, min(2.0, self._legacy_scale_x))
        scale_y = max(0.5, min(2.0, self._legacy_scale_y))
        current_width = max(self.width(), 1)
        current_height = max(self.height(), 1)
        self._base_width = max(int(round(current_width / scale_x)), 1)
        self._base_height = max(int(round(current_height / scale_y)), 1)
        self._requested_width = self._base_width
        self._requested_base_height = self._base_height
        self.setMinimumWidth(current_width)
        self.setMinimumHeight(current_height)

    # Legacy overlay handling ---------------------------------------------

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

    def _paint_legacy_message(self, painter: QPainter, item: Dict[str, Any]) -> None:
        color = QColor(str(item.get("color", "white")))
        size = str(item.get("size", "normal")).lower()
        font = QFont(self._font_family, 18 if size == "large" else 14)
        font.setWeight(QFont.Weight.Normal)
        painter.setPen(color)
        painter.setFont(font)
        x = int(round(item.get("x", 0)))
        raw_top = float(item.get("y", 0))
        scaled_top = raw_top * self._legacy_scale_y
        metrics = painter.fontMetrics()
        baseline = int(round(scaled_top + metrics.ascent()))
        painter.drawText(x, baseline, str(item.get("text", "")))

    def _paint_legacy_rect(self, painter: QPainter, item: Dict[str, Any]) -> None:
        border_color = QColor(str(item.get("color", "white")))
        fill_color = QColor(str(item.get("fill", "#00000000")))
        pen = QPen(border_color)
        pen.setWidth(2)
        painter.setPen(pen)
        painter.setBrush(QBrush(fill_color))
        x = int(round(item.get("x", 0)))
        y = int(round(item.get("y", 0) * self._legacy_scale_y))
        w = int(round(item.get("w", 0) * self._legacy_scale_x))
        h = int(round(item.get("h", 0) * self._legacy_scale_y))
        painter.drawRect(
            x,
            y,
            w,
            h,
        )

    def _apply_legacy_scale(self) -> None:
        if self._base_height <= 0:
            if self._requested_base_height and self._requested_base_height > 0:
                self._base_height = self._requested_base_height
            else:
                self._base_height = max(self.height(), 1)
        if self._base_width <= 0:
            if self._requested_width and self._requested_width > 0:
                self._base_width = self._requested_width
            else:
                self._base_width = max(self.width(), 1)
        scale_y = max(0.5, min(2.0, self._legacy_scale_y))
        scale_x = max(0.5, min(2.0, self._legacy_scale_x))
        if self._follow_enabled and (self._window_tracker is not None or self._last_follow_state is not None):
            self._sync_base_dimensions_to_widget()
            self.update()
            return
        target_height = max(int(round(self._base_height * scale_y)), 1)
        target_width = max(int(round(self._base_width * scale_x)), 1)
        self.setMinimumHeight(target_height)
        self.setMinimumWidth(target_width)
        self.resize(target_width, target_height)
        self.update()

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

        font_candidates = [
            (fonts_dir / "SourceSans3-Regular.ttf", "Source Sans 3"),
            (fonts_dir / "Eurocaps.ttf", "Eurocaps"),
        ]

        for path, label in font_candidates:
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
        "Loaded initial settings from %s: retention=%d width=%d height=%d",
        settings_path,
        initial_settings.client_log_retention,
        initial_settings.window_width,
        initial_settings.window_height,
    )

    app = QApplication(sys.argv)
    data_client = OverlayDataClient(port_file)
    window = OverlayWindow(initial_settings)
    helper.apply_initial_window_state(window, initial_settings)
    window.resize(initial_settings.window_width, initial_settings.window_height)
    if not initial_settings.follow_elite_window:
        # Ensure the overlay starts at the top-left of the primary screen (0,0)
        window.move(0, 0)
    tracker = create_elite_window_tracker(_CLIENT_LOGGER)
    if tracker is not None:
        window.set_window_tracker(tracker)
    else:
        _CLIENT_LOGGER.info("Window tracker unavailable; follow mode disabled")
    _CLIENT_LOGGER.debug(
        "Overlay window created, sized to %dx%d, moved to (0,0)",
        window.width(),
        window.height(),
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
        if event == "TestMessage" and payload.get("message"):
            message_text = payload["message"]
        if message_text is not None:
            window.display_message(str(message_text))

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
