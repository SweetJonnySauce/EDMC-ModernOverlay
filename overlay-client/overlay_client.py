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
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Dict, Optional

from PyQt6.QtCore import Qt, pyqtSignal, QObject, QTimer, QPoint
from PyQt6.QtGui import QColor, QFont, QPainter, QPen, QBrush, QCursor, QFontDatabase
from PyQt6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget


_LOGGER_NAME = "EDMC.ModernOverlay.Client"
_LOG_DIR_NAME = "EDMC-ModernOverlay"
_LOG_FILE_NAME = "overlay-client.log"
_MAX_LOG_BYTES = 512 * 1024
_CLIENT_LOGGER = logging.getLogger(_LOGGER_NAME)
_CLIENT_LOGGER.setLevel(logging.DEBUG)
_CLIENT_LOGGER.propagate = False
_CLIENT_LOG_HANDLER: Optional[logging.Handler] = None
_CLIENT_LOG_PATH: Optional[Path] = None
_CURRENT_LOG_RETENTION = 5


def _load_initial_retention(default: int = 5) -> int:
    settings_path = Path(__file__).resolve().parents[1] / "overlay_settings.json"
    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default
    try:
        value = int(data.get("client_log_retention", default))
    except (TypeError, ValueError):
        return default
    return max(1, value)


def _resolve_logs_dir() -> Path:
    current = Path(__file__).resolve()
    candidates = []
    parents = current.parents
    if len(parents) >= 4:
        candidates.append(parents[3] / "logs")
    if len(parents) >= 3:
        candidates.append(parents[2] / "logs")
    candidates.append(Path.cwd() / "logs")
    for base in candidates:
        try:
            target = base / _LOG_DIR_NAME
            target.mkdir(parents=True, exist_ok=True)
            return target
        except Exception:
            continue
    fallback = current.parent / "logs" / _LOG_DIR_NAME
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


def _configure_client_logging(retention: int) -> None:
    global _CLIENT_LOG_HANDLER, _CLIENT_LOG_PATH, _CURRENT_LOG_RETENTION
    retention = max(1, retention)
    logs_dir = _resolve_logs_dir()
    log_path = logs_dir / _LOG_FILE_NAME
    backup_count = max(0, retention - 1)
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S")
    try:
        handler = RotatingFileHandler(
            log_path,
            maxBytes=_MAX_LOG_BYTES,
            backupCount=backup_count,
            encoding="utf-8",
        )
    except Exception as exc:
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        if _CLIENT_LOG_HANDLER is not None:
            _CLIENT_LOGGER.removeHandler(_CLIENT_LOG_HANDLER)
            try:
                _CLIENT_LOG_HANDLER.close()
            except Exception:
                pass
        _CLIENT_LOGGER.addHandler(stream_handler)
        _CLIENT_LOGGER.warning("Failed to initialise file logging at %s: %s", log_path, exc)
        _CLIENT_LOG_HANDLER = stream_handler
        _CLIENT_LOG_PATH = None
        _CURRENT_LOG_RETENTION = retention
        return
    handler.setFormatter(formatter)
    if _CLIENT_LOG_HANDLER is not None:
        _CLIENT_LOGGER.removeHandler(_CLIENT_LOG_HANDLER)
        try:
            _CLIENT_LOG_HANDLER.close()
        except Exception:
            pass
    _CLIENT_LOGGER.addHandler(handler)
    _CLIENT_LOG_HANDLER = handler
    _CLIENT_LOG_PATH = log_path
    _CURRENT_LOG_RETENTION = retention
    _CLIENT_LOGGER.debug(
        "Client logging initialised: path=%s retention=%d max_bytes=%d backup_count=%d",
        log_path,
        retention,
        _MAX_LOG_BYTES,
        backup_count,
    )


def _set_log_retention(retention: int) -> None:
    if retention != _CURRENT_LOG_RETENTION:
        _configure_client_logging(retention)
        _CLIENT_LOGGER.debug("Client log retention updated to %d", retention)


def _get_log_retention() -> int:
    return _CURRENT_LOG_RETENTION


def _log_debug(message: str) -> None:
    _CLIENT_LOGGER.debug(message)


_configure_client_logging(_load_initial_retention())


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

    def __init__(self, data_client: OverlayDataClient) -> None:
        super().__init__()
        self._font_family = self._resolve_font_family()
        self.data_client = data_client
        self._status = "Initialising"
        self._state: Dict[str, Any] = {
            "message": "",
        }
        self._legacy_items: Dict[str, Dict[str, Any]] = {}
        self._background_opacity: float = 0.0
        self._drag_enabled: bool = False
        self._drag_active: bool = False
        self._drag_offset: QPoint = QPoint()
        self._move_mode: bool = False
        self._cursor_saved: bool = False
        self._saved_cursor: QCursor = self.cursor()
        self._transparent_input_supported = hasattr(Qt.WindowType, "WindowTransparentForInput")
        self._show_status: bool = False
        self._legacy_scale_y: float = 1.0
        self._base_height: int = 0
        self._log_retention: int = _get_log_retention()

        self._legacy_timer = QTimer(self)
        self._legacy_timer.setInterval(250)
        self._legacy_timer.timeout.connect(self._purge_legacy)
        self._legacy_timer.start()

        self._modifier_timer = QTimer(self)
        self._modifier_timer.setInterval(100)
        self._modifier_timer.timeout.connect(self._poll_modifiers)
        self._modifier_timer.start()

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
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

        # Connect signals
        self.data_client.message_received.connect(self._on_message)
        self.data_client.status_changed.connect(self._on_status)
        _log_debug(f"Overlay window initialised; log retention={self._log_retention}")

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        if self._base_height <= 0:
            raw_height = self.height()
            min_height = 1
            self._base_height = max(raw_height, min_height)
            clamped_scale = max(0.5, min(2.0, self._legacy_scale_y))
            target_height = max(int(round(self._base_height * clamped_scale)), 1)
            _log_debug(
                "Initial window height established: "
                f"raw_height={raw_height}, min_height={min_height}, base_height={self._base_height}, "
                f"legacy_scale_y={self._legacy_scale_y}, clamped_scale={clamped_scale}, target_height={target_height}"
            )
        self._apply_legacy_scale()
        self._enable_click_through()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self._background_opacity > 0.0:
            alpha = int(255 * max(0.0, min(1.0, self._background_opacity)))
            painter.setBrush(QColor(0, 0, 0, alpha))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(self.rect(), 12, 12)
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
            self.raise_()
            if self._cursor_saved:
                self.setCursor(self._saved_cursor)
                self._cursor_saved = False
            self._apply_drag_state()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    # Signal handlers ------------------------------------------------------

    def _on_message(self, payload: Dict[str, Any]) -> None:
        if payload.get("event") == "LegacyOverlay":
            self._handle_legacy(payload)
            return
        if payload.get("event") == "OverlayConfig":
            opacity = payload.get("opacity")
            try:
                self._background_opacity = max(0.0, min(1.0, float(opacity)))
            except (TypeError, ValueError):
                self._background_opacity = 0.0
            self._drag_enabled = bool(payload.get("enable_drag", False))
            if "legacy_scale_y" in payload:
                try:
                    scale_value = float(payload.get("legacy_scale_y", 1.0))
                except (TypeError, ValueError):
                    scale_value = 1.0
                self._legacy_scale_y = max(0.5, min(2.0, scale_value))
                self._apply_legacy_scale()
            if "client_log_retention" in payload:
                try:
                    new_retention = int(payload.get("client_log_retention", self._log_retention))
                except (TypeError, ValueError):
                    new_retention = self._log_retention
                new_retention = max(1, new_retention)
                if new_retention != self._log_retention:
                    self._log_retention = new_retention
                    _set_log_retention(new_retention)
                    _log_debug(f"Applied client log retention from config: {new_retention}")
            if "show_status" in payload:
                previous = self._show_status
                self._show_status = bool(payload.get("show_status"))
                if self._show_status:
                    if self._status and (not previous or not self.status_label.text()):
                        self.status_label.setText(self._status)
                else:
                    self.status_label.clear()
                self._update_status_visibility()
            self._apply_drag_state()
            self.update()
            return

        message_text = payload.get("message")
        if payload.get("event") == "TestMessage" and payload.get("message"):
            message_text = payload.get("message")
        if message_text is not None:
            self._state["message"] = str(message_text)
        self.message_label.setText(self._state.get("message", ""))

    def _on_status(self, status: str) -> None:
        self._status = status
        if self._show_status:
            self.status_label.setText(status)
        else:
            self.status_label.clear()
        self._update_status_visibility()

    def _update_status_visibility(self) -> None:
        should_display = bool(self._show_status and self._status)
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
        w = int(round(item.get("w", 0)))
        h = int(round(item.get("h", 0) * self._legacy_scale_y))
        painter.drawRect(
            x,
            y,
            w,
            h,
        )

    def _apply_legacy_scale(self) -> None:
        if self._base_height <= 0:
            return
        scale = max(0.5, min(2.0, self._legacy_scale_y))
        target_height = max(int(round(self._base_height * scale)), 1)
        self.setMinimumHeight(target_height)
        self.resize(self.width(), target_height)
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
                print(f"[ModernOverlay] Failed to load {label} font from {font_path}: {exc}")
                return None
            if font_id == -1:
                print(f"[ModernOverlay] {label} font file at {font_path} could not be registered; falling back")
                return None
            families = QFontDatabase.applicationFontFamilies(font_id)
            if families:
                family = families[0]
                print(f"[ModernOverlay] Using {label} font family '{family}' from {font_path}")
                return family
            print(f"[ModernOverlay] {label} font registered but no families reported; falling back")
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
            print(f"[ModernOverlay] Could not enumerate installed fonts: {exc}")
            available = set()
        for candidate in installed_candidates:
            if candidate in available:
                print(f"[ModernOverlay] Using installed font family '{candidate}'")
                return candidate

        print(f"[ModernOverlay] Preferred fonts unavailable; falling back to {default_family}")
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

    _CLIENT_LOGGER.info("Starting overlay client (pid=%s)", os.getpid())

    port_file = resolve_port_file(args.port_file)
    _CLIENT_LOGGER.debug("Resolved port file path to %s", port_file)
    app = QApplication(sys.argv)
    data_client = OverlayDataClient(port_file)
    window = OverlayWindow(data_client)
    _CLIENT_LOGGER.debug("Overlay window created; initial log retention=%d", window._log_retention)
    window.resize(1280, 720)
    window.show()
    data_client.start()

    exit_code = app.exec()
    data_client.stop()
    _CLIENT_LOGGER.info("Overlay client exiting with code %s", exit_code)
    return int(exit_code)


if __name__ == "__main__":
    raise SystemExit(main())
