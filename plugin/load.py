"""Primary entry point for the EDMC Modern Overlay plugin."""
from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

try:  # EDMC loads plugins as top-level modules, so support both contexts.
    from .overlay_watchdog import OverlayWatchdog
    from .websocket_server import WebSocketBroadcaster
except ImportError:  # pragma: no cover - fallback when __package__ is empty
    from overlay_watchdog import OverlayWatchdog
    from websocket_server import WebSocketBroadcaster

PLUGIN_NAME = "Modern Overlay"
PLUGIN_VERSION = "0.1.0"


def _log(message: str) -> None:
    """Log to EDMC's output pane, falling back to stdout when unavailable."""
    timestamp = time.strftime("%H:%M:%S")
    line = f"[{timestamp}] [ModernOverlay] {message}"
    try:
        from config import config  # type: ignore

        config.log(line)
    except Exception:
        print(line)


class _PluginRuntime:
    """Encapsulates plugin state so EDMC globals stay tidy."""

    BROADCAST_EVENTS = {
        "LoadGame",
        "Commander",
        "Location",
        "FSDJump",
        "Docked",
        "Undocked",
        "SupercruiseExit",
        "SupercruiseEntry",
    }

    def __init__(self, plugin_dir: str) -> None:
        self.plugin_dir = Path(plugin_dir)
        self.broadcaster = WebSocketBroadcaster(log=_log)
        self.watchdog: Optional[OverlayWatchdog] = None
        self._lock = threading.Lock()
        self._running = False
        self._state: Dict[str, Any] = {
            "cmdr": "",
            "system": "",
            "station": "",
            "docked": False,
        }

    # Lifecycle ------------------------------------------------------------

    def start(self) -> str:
        with self._lock:
            if self._running:
                return PLUGIN_NAME
            self.broadcaster.start()
            self._write_port_file()
            self._start_watchdog()
            self._running = True
        _log("Plugin started")
        return PLUGIN_NAME

    def stop(self) -> None:
        with self._lock:
            if not self._running:
                return
            self._running = False
        _log("Plugin stopping")
        if self.watchdog:
            self.watchdog.stop()
            self.watchdog = None
        self.broadcaster.stop()
        self._delete_port_file()

    # Journal handling -----------------------------------------------------

    def handle_journal(self, cmdr: str, system: str, station: str, entry: Dict[str, Any]) -> None:
        if not self._running:
            return
        event = entry.get("event")
        if not event:
            return

        self._update_state(cmdr, system, station, entry)
        if event not in self.BROADCAST_EVENTS:
            return

        payload = {
            "timestamp": entry.get("timestamp"),
            "event": event,
            "cmdr": self._state.get("cmdr", cmdr),
            "system": self._state.get("system", system),
            "station": self._state.get("station", station),
            "docked": self._state.get("docked", False),
            "raw": entry,
        }
        self.broadcaster.publish(payload)

    # Helpers --------------------------------------------------------------

    def _update_state(self, cmdr: str, system: str, station: str, entry: Dict[str, Any]) -> None:
        event = entry.get("event")
        commander = entry.get("Commander") or entry.get("cmdr") or cmdr
        if commander:
            self._state["cmdr"] = commander
        if event in {"Location", "FSDJump", "Docked"}:
            self._state["system"] = entry.get("StarSystem") or system or self._state.get("system", "")
        if event == "Docked":
            self._state["docked"] = True
            self._state["station"] = entry.get("StationName") or station or self._state.get("station", "")
        elif event == "Undocked":
            self._state["docked"] = False
            self._state["station"] = ""
        elif station:
            self._state["station"] = station
        if event in {"Location", "FSDJump", "SupercruiseExit"} and entry.get("StationName"):
            self._state["station"] = entry["StationName"]

    def _write_port_file(self) -> None:
        target = self.plugin_dir / "port.json"
        data = {"port": self.broadcaster.port}
        target.write_text(json.dumps(data, indent=2), encoding="utf-8")
        _log(f"Wrote port.json with port {self.broadcaster.port}")

    def _delete_port_file(self) -> None:
        try:
            (self.plugin_dir / "port.json").unlink()
        except FileNotFoundError:
            pass

    def _start_watchdog(self) -> None:
        overlay_script = self.plugin_dir.parent / "overlay-client" / "overlay_client.py"
        if not overlay_script.exists():
            _log("Overlay client not found next to plugin; watchdog disabled")
            return
        command = [sys.executable, str(overlay_script)]
        self.watchdog = OverlayWatchdog(command, overlay_script.parent, log=_log)
        self.watchdog.start()


# EDMC hook functions ------------------------------------------------------

_plugin: Optional[_PluginRuntime] = None


def plugin_start3(plugin_dir: str) -> str:
    _log(f"Initialising Modern Overlay plugin from {plugin_dir}")
    global _plugin
    _plugin = _PluginRuntime(plugin_dir)
    return _plugin.start()


def plugin_stop() -> None:
    if _plugin:
        _plugin.stop()


def plugin_app(parent) -> Optional[Any]:  # pragma: no cover - EDMC Tk frame hook
    return None


def plugin_prefs(parent, cmdr: str, is_beta: bool):  # pragma: no cover - optional settings pane
    return None


def journal_entry(
    cmdr: str,
    is_beta: bool,
    system: str,
    station: str,
    entry: Dict[str, Any],
    state: Dict[str, Any],
) -> None:
    if _plugin:
        _plugin.handle_journal(cmdr, system, station, entry)


# Metadata expected by some plugin loaders
name = PLUGIN_NAME
version = PLUGIN_VERSION
cmdr = ""
