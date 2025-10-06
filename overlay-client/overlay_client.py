"""Standalone PyQt6 overlay client for EDMC Modern Overlay."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import threading
from pathlib import Path
from typing import Any, Dict, Optional

from PyQt6.QtCore import Qt, pyqtSignal, QObject
from PyQt6.QtGui import QColor, QFont, QPainter
from PyQt6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget


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
        self.data_client = data_client
        self._status = "Initialising"
        self._state: Dict[str, Any] = {
            "cmdr": "---",
            "system": "---",
            "station": "---",
            "docked": False,
        }

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )

        font = QFont("Segoe UI", 18)
        self.cmdr_label = QLabel("CMDR: ---")
        self.system_label = QLabel("System: ---")
        self.station_label = QLabel("Station: ---")
        self.status_label = QLabel(self._status)
        for label in (self.cmdr_label, self.system_label, self.station_label, self.status_label):
            label.setFont(font)
            label.setStyleSheet("color: white;")

        layout = QVBoxLayout()
        layout.addWidget(self.cmdr_label)
        layout.addWidget(self.system_label)
        layout.addWidget(self.station_label)
        layout.addWidget(self.status_label)
        layout.setContentsMargins(20, 20, 20, 20)
        self.setLayout(layout)

        # Connect signals
        self.data_client.message_received.connect(self._on_message)
        self.data_client.status_changed.connect(self._on_status)

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        self._enable_click_through()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor(0, 0, 0, 96))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(self.rect(), 12, 12)
        painter.end()
        super().paintEvent(event)

    # Signal handlers ------------------------------------------------------

    def _on_message(self, payload: Dict[str, Any]) -> None:
        self._state.update(
            {
                "cmdr": payload.get("cmdr", self._state["cmdr"]),
                "system": payload.get("system", self._state["system"]),
                "station": payload.get("station", self._state["station"]),
                "docked": payload.get("docked", self._state["docked"]),
            }
        )
        docked_text = "Docked" if self._state.get("docked") else "In flight"
        self.cmdr_label.setText(f"CMDR: {self._state['cmdr']}")
        self.system_label.setText(f"System: {self._state['system']}")
        self.station_label.setText(f"Station: {self._state['station']} ({docked_text})")

    def _on_status(self, status: str) -> None:
        self._status = status
        self.status_label.setText(status)

    # Platform integration -------------------------------------------------

    def _enable_click_through(self) -> None:
        if not sys.platform.startswith("win"):
            return
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


def resolve_port_file(args_port: Optional[str]) -> Path:
    if args_port:
        return Path(args_port).expanduser().resolve()
    env_override = os.getenv("EDMC_OVERLAY_PORT_FILE")
    if env_override:
        return Path(env_override).expanduser().resolve()
    return (Path(__file__).resolve().parent.parent / "plugin" / "port.json").resolve()


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="EDMC Modern Overlay client")
    parser.add_argument("--port-file", help="Path to port.json emitted by the plugin")
    args = parser.parse_args(argv)

    port_file = resolve_port_file(args.port_file)
    app = QApplication(sys.argv)
    data_client = OverlayDataClient(port_file)
    window = OverlayWindow(data_client)
    window.resize(400, 200)
    window.show()
    data_client.start()

    exit_code = app.exec()
    data_client.stop()
    return int(exit_code)


if __name__ == "__main__":
    raise SystemExit(main())
