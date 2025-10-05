"""EDMC Modern Overlay plugin entry point."""
from __future__ import annotations

import json
import queue
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

import asyncio

try:
    import websockets
except ImportError:  # pragma: no cover - dependency managed via requirements.txt
    websockets = None  # type: ignore[assignment]

from .overlay_watchdog import OverlayWatchdog

# --------------------------------------------------------------------------------------
# Logging helpers
# --------------------------------------------------------------------------------------

def _log(message: str) -> None:
    """Send a timestamped line to EDMC's log pane (falls back to print)."""
    timestamp = time.strftime("%H:%M:%S")
    line = f"[{timestamp}] [ModernOverlay] {message}"
    try:
        from config import config  # type: ignore

        config.log(line)
    except Exception:
        print(line)


# --------------------------------------------------------------------------------------
# WebSocket broadcaster
# --------------------------------------------------------------------------------------


@dataclass
class WebSocketBroadcaster:
    """Background asyncio server that broadcasts queued messages to clients."""

    host: str = "127.0.0.1"
    port: int = 0  # 0 => auto assign
    _loop: Optional[asyncio.AbstractEventLoop] = field(default=None, init=False)
    _thread: Optional[threading.Thread] = field(default=None, init=False)
    _ready: threading.Event = field(default_factory=threading.Event, init=False)
    _stop: threading.Event = field(default_factory=threading.Event, init=False)
    _queue: "queue.Queue[str]" = field(default_factory=queue.Queue, init=False)
    _clients: set = field(default_factory=set, init=False)

    def start(self) -> None:
        if websockets is None:
            raise RuntimeError("websockets package not available; install requirements")
        if self._thread and self._thread.is_alive():
            return
        self._ready.clear()
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="ModernOverlay-WebSocket", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=5.0)
        if not self._ready.is_set():
            raise RuntimeError("WebSocket server failed to start")

    def stop(self) -> None:
        self._stop.set()
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(lambda: None)
        if self._thread:
            self._thread.join(timeout=2.0)
        self._loop = None
        self._thread = None
        self._clients.clear()

    def publish(self, payload: Dict[str, Any]) -> None:
        try:
            message = json.dumps(payload)
        except (TypeError, ValueError) as exc:
            _log(f"Failed to serialise payload: {exc}")
            return
        self._queue.put_nowait(message)
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(lambda: None)

    def _run(self) -> None:
        if sys.platform.startswith("win"):
            try:
                from asyncio import WindowsSelectorEventLoopPolicy

                asyncio.set_event_loop_policy(WindowsSelectorEventLoopPolicy())
            except Exception:
                pass
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._server_main())
        finally:
            pending = asyncio.all_tasks(self._loop)
            for task in pending:
                task.cancel()
            try:
                self._loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            except Exception:
                pass
            self._loop.run_until_complete(self._loop.shutdown_asyncgens())
            self._loop.close()

    async def _server_main(self) -> None:
        assert websockets is not None

        async def handler(ws, _path):
            client_id = id(ws)
            self._clients.add(ws)
            _log(f"Client connected ({len(self._clients)} active)")
            try:
                await ws.wait_closed()
            finally:
                self._clients.discard(ws)
                _log(f"Client disconnected ({len(self._clients)} active)")

        async with websockets.serve(handler, self.host, self.port) as server:
            sockets: Iterable[Any] = server.sockets or []
            for sock in sockets:
                self.port = sock.getsockname()[1]
                break
            self._ready.set()
            _log(f"WebSocket server listening on {self.host}:{self.port}")
            while not self._stop.is_set():
                try:
                    message = await self._loop.run_in_executor(None, self._queue.get)
                except Exception:
                    await asyncio.sleep(0.05)
                    continue
                await self._broadcast(message)

    async def _broadcast(self, message: str) -> None:
        if not self._clients:
            return
        dead = []
        for ws in self._clients.copy():
            try:
                await ws.send(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._clients.discard(ws)


# --------------------------------------------------------------------------------------
# Main plugin class
# --------------------------------------------------------------------------------------


class ModernOverlayPlugin:
    def __init__(self, plugin_dir: str) -> None:
        self.plugin_dir = Path(plugin_dir)
        self.broadcaster = WebSocketBroadcaster()
        self.watchdog: Optional[OverlayWatchdog] = None
        self._started = False

    # EDMC hooks ------------------------------------------------------------------
    def start(self) -> str:
        if self._started:
            return PLUGIN_NAME
        self.broadcaster.start()
        self._write_port_file()
        self._start_watchdog()
        self._started = True
        _log("Plugin started")
        return PLUGIN_NAME

    def stop(self) -> None:
        if not self._started:
            return
        _log("Plugin stopping")
        if self.watchdog:
            self.watchdog.stop()
            self.watchdog = None
        self.broadcaster.stop()
        self._delete_port_file()
        self._started = False

    def handle_journal(self, entry: Dict[str, Any]) -> None:
        payload = {
            "timestamp": entry.get("timestamp"),
            "event": entry.get("event"),
            "raw": entry,
        }
        self.broadcaster.publish(payload)

    # Internal helpers ------------------------------------------------------------
    def _write_port_file(self) -> None:
        data = {"port": self.broadcaster.port}
        target = self.plugin_dir / "port.json"
        target.write_text(json.dumps(data, indent=2), encoding="utf-8")
        _log(f"Wrote port.json with port {self.broadcaster.port}")

    def _delete_port_file(self) -> None:
        target = self.plugin_dir / "port.json"
        try:
            target.unlink()
        except FileNotFoundError:
            pass

    def _start_watchdog(self) -> None:
        overlay_script = self.plugin_dir.parent / "overlay-client" / "overlay_client.py"
        if not overlay_script.exists():
            _log("Overlay client script not found; watchdog disabled")
            return
        command = [sys.executable, str(overlay_script)]
        self.watchdog = OverlayWatchdog(command, self.plugin_dir)
        self.watchdog.start()


# --------------------------------------------------------------------------------------
# EDMC plugin hook functions
# --------------------------------------------------------------------------------------

_plugin: Optional[ModernOverlayPlugin] = None


def plugin_start3(plugin_dir: str) -> str:
    global _plugin
    _log(f"Initialising plugin from {plugin_dir}")
    _plugin = ModernOverlayPlugin(plugin_dir)
    return _plugin.start()


def plugin_stop() -> None:
    if _plugin:
        _plugin.stop()


def plugin_app(parent) -> Optional[Any]:  # pragma: no cover - Tk frame created by EDMC
    return None


def plugin_prefs(parent, cmdr: str, is_beta: bool):  # pragma: no cover - preferences frame optional
    return None


def journal_entry(cmdr: str, is_beta: bool, system: str, station: str, entry: Dict[str, Any], state: Dict[str, Any]) -> None:
    if _plugin:
        _plugin.handle_journal(entry)


# Convenience attribute expected by some plugin loaders
name = PLUGIN_NAME
version = PLUGIN_VERSION
cmdr = ""


if __name__ == "__main__":  # pragma: no cover - developer harness
    import argparse

    parser = argparse.ArgumentParser(description="Run ModernOverlay plugin harness")
    parser.add_argument("--plugin-dir", default=str(Path(__file__).resolve().parent), help="Directory to write port.json")
    args = parser.parse_args()

    plugin_start3(args.plugin_dir)
    _log("Harness running; press Ctrl+C to stop")
    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        plugin_stop()
