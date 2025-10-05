"""Standalone PyQt6 overlay that connects to the EDMC Modern Overlay plugin."""
from __future__ import annotations

import asyncio
import html
import json
import sys
import threading
import time
from pathlib import Path
from typing import Dict, Optional

from PyQt6 import QtCore, QtGui, QtWidgets

try:
    import websockets
except ImportError as exc:
    raise SystemExit("websockets package is required. Install overlay-client/requirements.txt") from exc

PORT_JSON_NAME = "port.json"
DEFAULT_PORT = 8765
RECONNECT_DELAY_SECONDS = 3


def locate_port_file() -> Path:
    """Return the expected port.json path relative to the overlay script."""
    script_dir = Path(__file__).resolve().parent
    candidate = script_dir.parent / "plugin" / PORT_JSON_NAME
    return candidate


class OverlayWindow(QtWidgets.QWidget):
    message_changed = QtCore.pyqtSignal(dict)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("EDMC Modern Overlay")
        self.setWindowFlags(
            QtCore.Qt.WindowType.FramelessWindowHint
            | QtCore.Qt.WindowType.WindowStaysOnTopHint
            | QtCore.Qt.WindowType.Tool
        )
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_NoSystemBackground, True)

        self._layout = QtWidgets.QVBoxLayout(self)
        self._layout.setContentsMargins(24, 24, 24, 24)
        self._layout.setSpacing(6)

        self._title = QtWidgets.QLabel("EDMC Modern Overlay")
        font = QtGui.QFont("Segoe UI", 16, QtGui.QFont.Weight.Bold)
        self._title.setFont(font)
        self._title.setStyleSheet("color: #FFFFFF;")

        self._body = QtWidgets.QLabel("Waiting for EDMC…")
        self._body.setFont(QtGui.QFont("Segoe UI", 13))
        self._body.setStyleSheet("color: #FFFFFF;")
        self._body.setWordWrap(True)

        self._layout.addWidget(self._title)
        self._layout.addWidget(self._body)

        self.message_changed.connect(self._render_message)
        self.resize(420, 140)
        self._apply_click_through()

    # ------------------------------------------------------------------
    def _apply_click_through(self) -> None:
        if sys.platform.startswith("win"):
            try:
                import ctypes

                hwnd = self.winId().__int__()
                GWL_EXSTYLE = -20
                WS_EX_LAYERED = 0x00080000
                WS_EX_TRANSPARENT = 0x00000020
                user32 = ctypes.windll.user32
                style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
                user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_LAYERED | WS_EX_TRANSPARENT)
                ctypes.windll.user32.SetLayeredWindowAttributes(hwnd, 0, 255, 0x2)
            except Exception:
                pass

    # ------------------------------------------------------------------
    @QtCore.pyqtSlot(dict)
    def _render_message(self, payload: Dict[str, str]) -> None:
        event = payload.get("event") or "Unknown"
        ts = payload.get("timestamp") or time.strftime("%H:%M:%S")
        self._title.setText(f"{event} @ {ts}")
        raw = payload.get("raw") or {}
        pretty = json.dumps(raw, indent=2)
        self._body.setText(f"<pre style='color:#FFFFFF;'>{html.escape(pretty)}</pre>")


class WebSocketWorker(QtCore.QObject):
    message_received = QtCore.pyqtSignal(dict)
    connection_state = QtCore.pyqtSignal(bool)

    def __init__(self, port_file: Path) -> None:
        super().__init__()
        self._port_file = port_file
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="Overlay-WebSocket", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        self._thread = None

    # ------------------------------------------------------------------
    def _run(self) -> None:
        asyncio.run(self._run_async())

    async def _run_async(self) -> None:
        while not self._stop.is_set():
            uri = self._build_uri()
            if uri is None:
                self.connection_state.emit(False)
                await asyncio.sleep(RECONNECT_DELAY_SECONDS)
                continue
            try:
                async with websockets.connect(uri) as ws:
                    self.connection_state.emit(True)
                    async for message in ws:
                        try:
                            payload = json.loads(message)
                        except json.JSONDecodeError:
                            continue
                        self.message_received.emit(payload)
            except Exception:
                self.connection_state.emit(False)
                await asyncio.sleep(RECONNECT_DELAY_SECONDS)

    def _build_uri(self) -> Optional[str]:
        port = DEFAULT_PORT
        try:
            data = json.loads(self._port_file.read_text(encoding="utf-8"))
            port = int(data.get("port", port))
        except FileNotFoundError:
            return None
        except Exception:
            return None
        return f"ws://127.0.0.1:{port}"


class OverlayController(QtCore.QObject):
    def __init__(self, app: QtWidgets.QApplication) -> None:
        super().__init__()
        self.app = app
        self.window = OverlayWindow()
        port_file = locate_port_file()
        self.worker = WebSocketWorker(port_file)
        self.worker.message_received.connect(self.window.message_changed)
        self.worker.connection_state.connect(self._on_connection_state)
        self.window.show()
        self.worker.start()

    @QtCore.pyqtSlot(bool)
    def _on_connection_state(self, connected: bool) -> None:
        if connected:
            self.window._body.setText("Connected to EDMC…")
        else:
            self.window._body.setText("Waiting for EDMC…")

    def shutdown(self) -> None:
        self.worker.stop()


def main() -> None:
    app = QtWidgets.QApplication(sys.argv)
    controller = OverlayController(app)

    def on_exit() -> None:
        controller.shutdown()

    app.aboutToQuit.connect(on_exit)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
