"""Primary entry point for the EDMC Modern Overlay plugin."""
from __future__ import annotations

import json
import logging
import os
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

if __package__:
    from .overlay_plugin.overlay_watchdog import OverlayWatchdog
    from .overlay_plugin.websocket_server import WebSocketBroadcaster
    from .overlay_plugin.preferences import Preferences, PreferencesPanel
else:  # pragma: no cover - EDMC loads as top-level module
    from overlay_plugin.overlay_watchdog import OverlayWatchdog
    from overlay_plugin.websocket_server import WebSocketBroadcaster
    from overlay_plugin.preferences import Preferences, PreferencesPanel

PLUGIN_NAME = "Modern Overlay"
PLUGIN_VERSION = "0.1.0"
LOGGER_NAME = "EDMC.ModernOverlay"


class _EDMCLogHandler(logging.Handler):
    """Dispatch Python logging records to EDMC's logger when available."""

    def __init__(self) -> None:
        super().__init__()
        self._config_module: Optional[Any] = None

    def emit(self, record: logging.LogRecord) -> None:
        message = self.format(record)
        config_module = self._ensure_config_module()
        if config_module is not None:
            logger_obj = getattr(config_module, "logger", None)
            if logger_obj is not None:
                try:
                    logger_obj.log(record.levelno, message)
                    return
                except Exception:
                    self._config_module = None
            config_instance = getattr(config_module, "config", None)
            log_func = getattr(config_instance, "log", None)
            if callable(log_func):
                try:
                    log_func(message)
                    return
                except Exception:
                    self._config_module = None
        print(message)

    def _ensure_config_module(self) -> Optional[Any]:
        if self._config_module is None:
            try:
                import importlib

                self._config_module = importlib.import_module("config")
            except Exception:
                self._config_module = None
        return self._config_module


def _configure_logger() -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.DEBUG)
    if not any(getattr(handler, "_edmc_handler", False) for handler in logger.handlers):
        handler = _EDMCLogHandler()
        handler._edmc_handler = True  # type: ignore[attr-defined]
        formatter = logging.Formatter("[%(asctime)s] [ModernOverlay] %(message)s", "%H:%M:%S")
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    logger.propagate = False
    return logger


LOGGER = _configure_logger()


def _log(message: str) -> None:
    """Log to EDMC via the Python logging facade."""
    LOGGER.info(message)


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

    def __init__(self, plugin_dir: str, preferences: Preferences) -> None:
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
        self._preferences = preferences

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
        overlay_script = self._locate_overlay_client()
        if not overlay_script:
            _log("Overlay client not found; watchdog disabled")
            return
        python_executable = self._locate_overlay_python()
        command = [str(python_executable), str(overlay_script)]
        LOGGER.debug(
            "Attempting to start overlay client via watchdog: command=%s cwd=%s",
            command,
            overlay_script.parent,
        )
        self.watchdog = OverlayWatchdog(
            command,
            overlay_script.parent,
            log=_log,
            debug_log=LOGGER.debug,
            capture_output=self._capture_enabled(),
        )
        self.watchdog.start()

    def _locate_overlay_client(self) -> Optional[Path]:
        candidates = [
            self.plugin_dir / "overlay-client" / "overlay_client.py",
            self.plugin_dir / "overlay_client.py",
            self.plugin_dir.parent / "overlay-client" / "overlay_client.py",
            Path(__file__).resolve().parent / "overlay-client" / "overlay_client.py",
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return None

    def _capture_enabled(self) -> bool:
        return bool(self._preferences.capture_output and LOGGER.isEnabledFor(logging.DEBUG))

    def on_preferences_updated(self) -> None:
        LOGGER.debug(
            "Applying updated preferences: capture_output=%s",
            self._preferences.capture_output,
        )
        if self.watchdog:
            self.watchdog.set_capture_output(self._capture_enabled())

    def send_test_message(self, message: str) -> None:
        text = message.strip()
        if not text:
            raise ValueError("Message is empty")
        if not self._running:
            raise RuntimeError("Overlay is not running")
        payload = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "event": "TestMessage",
            "message": text,
            "raw": {"message": text},
        }
        self.broadcaster.publish(payload)
        LOGGER.debug("Sent test message to overlay: %s", text)

    def _locate_overlay_python(self) -> Path:
        env_override = os.getenv("EDMC_OVERLAY_PYTHON")
        if env_override:
            override_path = Path(env_override).expanduser()
            if override_path.exists():
                LOGGER.debug("Using overlay Python from EDMC_OVERLAY_PYTHON=%s", override_path)
                return override_path
            LOGGER.debug("Overlay Python override %s not found, falling back", override_path)

        venv_candidates = []
        plugin_root = self.plugin_dir
        venv_candidates.append(plugin_root / ".venv" / ("Scripts" if os.name == "nt" else "bin") / ("python.exe" if os.name == "nt" else "python"))
        venv_candidates.append(plugin_root / "overlay-client" / ".venv" / ("Scripts" if os.name == "nt" else "bin") / ("python.exe" if os.name == "nt" else "python"))

        for candidate in venv_candidates:
            if candidate.exists():
                LOGGER.debug("Using overlay Python interpreter at %s", candidate)
                return candidate

        LOGGER.debug("No dedicated overlay Python found; falling back to sys.executable=%s", sys.executable)
        return Path(sys.executable)


# EDMC hook functions ------------------------------------------------------

_plugin: Optional[_PluginRuntime] = None
_preferences: Optional[Preferences] = None
_prefs_panel: Optional[PreferencesPanel] = None


def plugin_start3(plugin_dir: str) -> str:
    _log(f"Initialising Modern Overlay plugin from {plugin_dir}")
    global _plugin, _preferences
    _preferences = Preferences(Path(plugin_dir))
    _plugin = _PluginRuntime(plugin_dir, _preferences)
    return _plugin.start()


def plugin_stop() -> None:
    global _prefs_panel
    if _plugin:
        _plugin.stop()
    _prefs_panel = None


def plugin_app(parent) -> Optional[Any]:  # pragma: no cover - EDMC Tk frame hook
    return None


def plugin_prefs(parent, cmdr: str, is_beta: bool):  # pragma: no cover - optional settings pane
    LOGGER.debug("plugin_prefs invoked: parent=%r cmdr=%r is_beta=%s", parent, cmdr, is_beta)
    if _preferences is None:
        LOGGER.debug("Preferences not initialised; returning no UI")
        return None
    send_callback = _plugin.send_test_message if _plugin else None
    try:
        panel = PreferencesPanel(parent, _preferences, send_callback)
    except Exception as exc:
        LOGGER.exception("Failed to build preferences panel: %s", exc)
        return None
    global _prefs_panel
    _prefs_panel = panel
    frame = panel.frame
    LOGGER.debug("plugin_prefs returning frame=%r", frame)
    return frame


def plugin_prefs_save(cmdr: str, is_beta: bool) -> None:  # pragma: no cover - save hook
    LOGGER.debug("plugin_prefs_save invoked: cmdr=%r is_beta=%s", cmdr, is_beta)
    if _prefs_panel is None:
        LOGGER.debug("No preferences panel to save")
        return
    try:
        _prefs_panel.apply()
        LOGGER.debug("Preferences saved: capture_output=%s", _preferences.capture_output if _preferences else None)
        if _plugin:
            _plugin.on_preferences_updated()
    except Exception as exc:
        LOGGER.exception("Failed to save preferences: %s", exc)


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
