"""Primary entry point for the EDMC Modern Overlay plugin."""
from __future__ import annotations

import importlib
import json
import logging
import os
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional, Set

if __package__:
    from .version import __version__ as MODERN_OVERLAY_VERSION
    from .overlay_plugin.overlay_watchdog import OverlayWatchdog
    from .overlay_plugin.overlay_socket_server import WebSocketBroadcaster
    from .overlay_plugin.preferences import Preferences, PreferencesPanel
    from .overlay_plugin.overlay_api import (
        register_publisher,
        send_overlay_message,
        unregister_publisher,
    )
else:  # pragma: no cover - EDMC loads as top-level module
    from version import __version__ as MODERN_OVERLAY_VERSION
    from overlay_plugin.overlay_watchdog import OverlayWatchdog
    from overlay_plugin.overlay_socket_server import WebSocketBroadcaster
    from overlay_plugin.preferences import Preferences, PreferencesPanel
    from overlay_plugin.overlay_api import (
        register_publisher,
        send_overlay_message,
        unregister_publisher,
    )

PLUGIN_NAME = "EDMC-ModernOverlay"
PLUGIN_VERSION = MODERN_OVERLAY_VERSION
LOGGER_NAME = "EDMC.ModernOverlay"
LOG_TAG = "EDMC-ModernOverlay"


EDMC_DEFAULT_LOG_LEVEL = logging.INFO
_LEVEL_NAME_MAP = {
    "CRITICAL": logging.CRITICAL,
    "FATAL": logging.CRITICAL,
    "ERROR": logging.ERROR,
    "WARN": logging.WARNING,
    "WARNING": logging.WARNING,
    "INFO": logging.INFO,
    "DEBUG": logging.DEBUG,
    "TRACE": logging.DEBUG,
}


def _load_edmc_config_module() -> Optional[Any]:
    try:
        return importlib.import_module("config")
    except Exception:
        return None


def _resolve_edmc_logger() -> Tuple[Optional[logging.Logger], Optional[Callable[[str], None]]]:
    module = _load_edmc_config_module()
    if module is None:
        return None, None
    logger_obj = getattr(module, "logger", None)
    config_obj = getattr(module, "config", None)
    legacy_log = getattr(config_obj, "log", None) if config_obj is not None else None
    return logger_obj if isinstance(logger_obj, logging.Logger) else None, legacy_log if callable(legacy_log) else None


def _resolve_edmc_log_level() -> int:
    def _coerce_level(raw: Any) -> Optional[int]:
        if raw is None:
            return None
        if isinstance(raw, int):
            return raw
        if isinstance(raw, str):
            token = raw.strip().upper()
            if token.isdigit():
                try:
                    return int(token)
                except ValueError:
                    return None
            return _LEVEL_NAME_MAP.get(token)
        return None

    module = _load_edmc_config_module()
    candidates: list[int] = []
    if module is not None:
        config_obj = getattr(module, "config", None)
        if config_obj is not None:
            for attr in ("log_level", "loglevel", "logLevel"):
                coerced = _coerce_level(getattr(config_obj, attr, None))
                if coerced is not None:
                    candidates.append(coerced)
                    break
            getter = getattr(config_obj, "get", None)
            if callable(getter):
                try:
                    coerced = _coerce_level(getter("loglevel"))
                    if coerced is not None:
                        candidates.append(coerced)
                except Exception:
                    pass
        logger_obj = getattr(module, "logger", None)
        if isinstance(logger_obj, logging.Logger):
            try:
                coerced = _coerce_level(logger_obj.getEffectiveLevel())
                if coerced is not None:
                    candidates.append(coerced)
            except Exception:
                pass
    root = logging.getLogger()
    candidates.append(root.getEffectiveLevel())
    candidates.append(EDMC_DEFAULT_LOG_LEVEL)

    for level in candidates:
        if isinstance(level, int) and level != logging.NOTSET:
            return level
    return EDMC_DEFAULT_LOG_LEVEL


def _ensure_plugin_logger_level() -> int:
    level = _resolve_edmc_log_level()
    logging.getLogger(LOGGER_NAME).setLevel(level)
    return level


class _EDMCLogHandler(logging.Handler):
    """Logging bridge that always respects EDMC's configured log level."""

    def emit(self, record: logging.LogRecord) -> None:
        target_level = _resolve_edmc_log_level()
        plugin_logger = logging.getLogger(LOGGER_NAME)
        if plugin_logger.level != target_level:
            plugin_logger.setLevel(target_level)
        if record.levelno < target_level:
            return
        message = self.format(record)
        edmc_logger, legacy_log = _resolve_edmc_logger()
        if edmc_logger is not None:
            try:
                if edmc_logger.isEnabledFor(record.levelno):
                    edmc_logger.log(record.levelno, message)
                    return
            except Exception:
                pass
        if legacy_log is not None:
            try:
                legacy_log(message)
                return
            except Exception:
                pass
        root_logger = logging.getLogger()
        if root_logger.isEnabledFor(record.levelno):
            root_logger.log(record.levelno, message)


def _configure_logger() -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    _ensure_plugin_logger_level()
    if not any(getattr(handler, "_edmc_handler", False) for handler in logger.handlers):
        handler = _EDMCLogHandler()
        handler._edmc_handler = True  # type: ignore[attr-defined]
        formatter = logging.Formatter(f"[%(asctime)s] [{LOG_TAG}] %(message)s", "%H:%M:%S")
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
        self._legacy_conflict = False
        self._capture_active = False
        self._state: Dict[str, Any] = {
            "cmdr": "",
            "system": "",
            "station": "",
            "docked": False,
        }
        self._preferences = preferences
        self._last_config: Dict[str, Any] = {}
        self._config_timers: Set[threading.Timer] = set()
        self._config_timer_lock = threading.Lock()
        self._enforce_force_xwayland(persist=True, update_watchdog=False, emit_config=False)

    # Lifecycle ------------------------------------------------------------

    def start(self) -> str:
        with self._lock:
            if self._running:
                return PLUGIN_NAME
            _ensure_plugin_logger_level()
            if self._legacy_overlay_active():
                self._legacy_conflict = True
                self._delete_port_file()
                LOGGER.error("Legacy edmcoverlay overlay detected; Modern Overlay will remain inactive.")
                return PLUGIN_NAME
            server_started = self.broadcaster.start()
            if not server_started:
                _log("Overlay broadcast server failed to start; running in degraded mode.")
                self._running = False
                self._delete_port_file()
            else:
                self._write_port_file()
                if not self._start_watchdog():
                    self._running = False
                    self.broadcaster.stop()
                    self._delete_port_file()
                    _log("Overlay client launch aborted; Modern Overlay plugin remains inactive.")
                else:
                    self._running = True
        if not self._running:
            return PLUGIN_NAME

        register_publisher(self._publish_external)
        self._send_overlay_config(rebroadcast=True)
        _log("Plugin started")
        return PLUGIN_NAME

    def stop(self) -> None:
        with self._lock:
            if not self._running:
                return
            self._running = False
        unregister_publisher()
        _log("Plugin stopping")
        self._cancel_config_timers()
        if self.watchdog:
            if self.watchdog.stop():
                LOGGER.debug("Overlay watchdog stopped and client terminated cleanly")
            else:
                LOGGER.warning("Overlay watchdog stop reported incomplete shutdown")
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
        self._publish_payload(payload)

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
        data = {
            "port": self.broadcaster.port,
            "version": PLUGIN_VERSION,
        }
        target.write_text(json.dumps(data, indent=2), encoding="utf-8")
        _log(f"Wrote port.json with port {self.broadcaster.port} (plugin version {PLUGIN_VERSION})")

    def _delete_port_file(self) -> None:
        try:
            (self.plugin_dir / "port.json").unlink()
        except FileNotFoundError:
            pass

    def _start_watchdog(self) -> bool:
        overlay_script = self._locate_overlay_client()
        if not overlay_script:
            _log("Overlay client not found; watchdog disabled")
            return False
        python_executable = self._locate_overlay_python()
        if python_executable is None:
            _log(
                "Overlay client environment not found. Create overlay-client/.venv (or set EDMC_OVERLAY_PYTHON) and restart EDMC-ModernOverlay."
            )
            LOGGER.error(
                "Overlay launch aborted: no overlay Python interpreter available under overlay-client/.venv or EDMC_OVERLAY_PYTHON."
            )
            return False
        command = [str(python_executable), str(overlay_script)]
        LOGGER.debug(
            "Attempting to start overlay client via watchdog: command=%s cwd=%s",
            command,
            overlay_script.parent,
        )
        launch_env = self._build_overlay_environment()
        platform_context = self._platform_context_payload()
        LOGGER.debug(
            "Overlay launch context: session=%s compositor=%s force_xwayland=%s qt_platform=%s",
            platform_context.get("session_type"),
            platform_context.get("compositor"),
            platform_context.get("force_xwayland"),
            launch_env.get("QT_QPA_PLATFORM"),
        )
        self.watchdog = OverlayWatchdog(
            command,
            overlay_script.parent,
            log=_log,
            debug_log=LOGGER.debug,
            capture_output=self._capture_enabled(),
            env=launch_env,
        )
        self._update_capture_state(self._capture_enabled())
        self.watchdog.start()
        return True

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
        return bool(self._preferences.capture_output and _resolve_edmc_log_level() <= logging.DEBUG)

    def _update_capture_state(self, enabled: bool) -> None:
        if enabled and not self._capture_active:
            LOGGER.debug("EDMC DEBUG mode detected; piping overlay stdout/stderr to EDMC log.")
        self._capture_active = enabled

    def _desired_force_xwayland(self) -> bool:
        return (os.environ.get("XDG_SESSION_TYPE") or "").lower() == "wayland"

    def _sync_force_xwayland_ui(self) -> None:
        # UI toggle removed; keep method for legacy callers.
        return

    def _enforce_force_xwayland(
        self,
        *,
        persist: bool,
        update_watchdog: bool,
        emit_config: bool,
    ) -> bool:
        desired = self._desired_force_xwayland()
        current = bool(self._preferences.force_xwayland)
        if current == desired:
            self._sync_force_xwayland_ui()
            return False
        self._preferences.force_xwayland = desired
        if persist:
            try:
                self._preferences.save()
            except Exception as exc:
                LOGGER.warning("Failed to save preferences while enforcing XWayland setting: %s", exc)
        if desired:
            LOGGER.info("Detected Wayland session; forcing overlay client to run via XWayland.")
        else:
            LOGGER.info("Detected non-Wayland session; disabling XWayland override.")
        if update_watchdog and self.watchdog:
            try:
                self.watchdog.set_environment(self._build_overlay_environment())
            except Exception as exc:
                LOGGER.warning("Failed to apply updated overlay environment: %s", exc)
            else:
                _log("Overlay XWayland preference updated; restart overlay to apply.")
        self._sync_force_xwayland_ui()
        if emit_config:
            self._send_overlay_config()
        return True

    def on_preferences_updated(self) -> None:
        self._enforce_force_xwayland(persist=True, update_watchdog=True, emit_config=False)
        LOGGER.debug(
            "Applying updated preferences: capture_output=%s show_connection_status=%s log_payloads=%s "
            "client_log_retention=%d gridlines_enabled=%s gridline_spacing=%d overlay_opacity=%.2f "
            "force_render=%s force_xwayland=%s debug_overlay=%s font_min=%.1f font_max=%.1f",
            self._preferences.capture_output,
            self._preferences.show_connection_status,
            self._preferences.log_payloads,
            self._preferences.client_log_retention,
            self._preferences.gridlines_enabled,
            self._preferences.gridline_spacing,
            self._preferences.overlay_opacity,
            self._preferences.force_render,
            self._preferences.force_xwayland,
            self._preferences.show_debug_overlay,
            self._preferences.min_font_point,
            self._preferences.max_font_point,
        )
        if self.watchdog:
            self.watchdog.set_capture_output(self._capture_enabled())
        self._update_capture_state(self._capture_enabled())
        self._send_overlay_config()

    def send_test_message(self, message: str, x: Optional[int] = None, y: Optional[int] = None) -> None:
        text = message.strip()
        if not text:
            raise ValueError("Message is empty")
        if not self._running:
            raise RuntimeError("Overlay is not running")
        payload: Dict[str, Any]
        if x is None and y is None:
            payload = {
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "event": "TestMessage",
                "message": text,
            }
        else:
            if x is None or y is None:
                raise ValueError("Both X and Y coordinates are required when specifying a position")
            try:
                x_val = max(0, int(x))
                y_val = max(0, int(y))
            except (TypeError, ValueError):
                raise ValueError("Coordinates must be integers") from None
            payload = {
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "event": "LegacyOverlay",
                "type": "message",
                "id": f"test-{datetime.utcnow().strftime('%H%M%S%f')}",
                "text": text,
                "color": "#ffffff",
                "x": x_val,
                "y": y_val,
                "ttl": 5,
                "size": "normal",
            }
        if not send_overlay_message(payload):
            raise RuntimeError("Failed to send test message via overlay API")
        if payload.get("event") == "LegacyOverlay":
            LOGGER.debug(
                "Sent positioned test overlay message: text=%s x=%s y=%s ttl=%s size=%s",
                text,
                payload["x"],
                payload["y"],
                payload["ttl"],
                payload["size"],
            )
        else:
            LOGGER.debug("Sent test message to overlay via API: %s", text)

    def preview_overlay_opacity(self, value: float) -> None:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            numeric = 0.0
        self._preferences.overlay_opacity = max(0.0, min(1.0, numeric))
        self._send_overlay_config()

    def set_show_status_preference(self, value: bool) -> None:
        self._preferences.show_connection_status = bool(value)
        self._preferences.save()
        self._send_overlay_config()

    def set_status_bandwidth_preference(self, value: bool) -> None:
        self._preferences.show_ed_bandwidth = bool(value)
        self._preferences.save()
        self._send_overlay_config()

    def set_status_fps_preference(self, value: bool) -> None:
        self._preferences.show_ed_fps = bool(value)
        self._preferences.save()
        self._send_overlay_config()

    def set_log_payload_preference(self, value: bool) -> None:
        self._preferences.log_payloads = bool(value)
        LOGGER.debug("Overlay payload logging %s", "enabled" if self._preferences.log_payloads else "disabled")
        self._send_overlay_config()

    def set_gridlines_enabled_preference(self, value: bool) -> None:
        self._preferences.gridlines_enabled = bool(value)
        LOGGER.debug("Overlay gridlines %s", "enabled" if self._preferences.gridlines_enabled else "disabled")
        self._send_overlay_config()

    def set_gridline_spacing_preference(self, value: int) -> None:
        try:
            spacing = int(value)
        except (TypeError, ValueError):
            spacing = self._preferences.gridline_spacing
        spacing = max(10, spacing)
        self._preferences.gridline_spacing = spacing
        LOGGER.debug("Overlay gridline spacing set to %d px", spacing)
        self._send_overlay_config()

    def set_force_render_preference(self, value: bool) -> None:
        self._preferences.force_render = bool(value)
        LOGGER.debug(
            "Overlay force-render %s",
            "enabled" if self._preferences.force_render else "disabled",
        )
        self._send_overlay_config()

    def set_debug_overlay_preference(self, value: bool) -> None:
        self._preferences.show_debug_overlay = bool(value)
        LOGGER.debug("Overlay debug overlay %s", "enabled" if self._preferences.show_debug_overlay else "disabled")
        self._send_overlay_config()

    def set_min_font_preference(self, value: float) -> None:
        try:
            minimum = float(value)
        except (TypeError, ValueError):
            minimum = self._preferences.min_font_point
        minimum = max(1.0, min(minimum, 48.0))
        if minimum != self._preferences.min_font_point:
            if minimum > self._preferences.max_font_point:
                self._preferences.max_font_point = minimum
            self._preferences.min_font_point = minimum
            LOGGER.debug("Overlay minimum font point set to %.1f", minimum)
            self._send_overlay_config()

    def set_max_font_preference(self, value: float) -> None:
        try:
            maximum = float(value)
        except (TypeError, ValueError):
            maximum = self._preferences.max_font_point
        maximum = max(self._preferences.min_font_point, min(maximum, 72.0))
        if maximum != self._preferences.max_font_point:
            self._preferences.max_font_point = maximum
            LOGGER.debug("Overlay maximum font point set to %.1f", maximum)
            self._send_overlay_config()

    def set_force_xwayland_preference(self, value: bool) -> None:
        desired = self._desired_force_xwayland()
        if bool(value) != desired:
            LOGGER.debug(
                "Ignoring manual XWayland toggle request (%s); environment requires %s",
                value,
                "XWayland" if desired else "native",
            )
        self._enforce_force_xwayland(persist=True, update_watchdog=True, emit_config=True)

    def _publish_external(self, payload: Mapping[str, Any]) -> bool:
        if not self._running:
            return False
        original_payload = dict(payload)
        message = dict(original_payload)
        message.setdefault("cmdr", self._state.get("cmdr", ""))
        message.setdefault("system", self._state.get("system", ""))
        message.setdefault("station", self._state.get("station", ""))
        message.setdefault("docked", self._state.get("docked", False))
        message.setdefault("raw", original_payload)
        self._publish_payload(message)
        return True

    def _send_overlay_config(self, rebroadcast: bool = False) -> None:
        payload = {
            "event": "OverlayConfig",
            "opacity": float(self._preferences.overlay_opacity),
            "enable_drag": bool(self._preferences.overlay_opacity > 0.5),
            "show_status": bool(self._preferences.show_connection_status),
            "status_bottom_margin": int(self._preferences.status_bottom_margin()),
            "client_log_retention": int(self._preferences.client_log_retention),
            "gridlines_enabled": bool(self._preferences.gridlines_enabled),
            "gridline_spacing": int(self._preferences.gridline_spacing),
            "force_render": bool(self._preferences.force_render),
            "show_debug_overlay": bool(self._preferences.show_debug_overlay),
            "min_font_point": float(self._preferences.min_font_point),
            "max_font_point": float(self._preferences.max_font_point),
            "platform_context": self._platform_context_payload(),
        }
        self._last_config = dict(payload)
        self._publish_payload(payload)
        LOGGER.debug(
            "Published overlay config: opacity=%s show_status=%s status_bottom_margin=%s client_log_retention=%d gridlines_enabled=%s "
            "gridline_spacing=%d force_render=%s debug_overlay=%s font_min=%.1f font_max=%.1f platform_context=%s",
            payload["opacity"],
            payload["show_status"],
            payload["status_bottom_margin"],
            payload["client_log_retention"],
            payload["gridlines_enabled"],
            payload["gridline_spacing"],
            payload["force_render"],
            payload["show_debug_overlay"],
            payload["min_font_point"],
            payload["max_font_point"],
            payload["platform_context"],
        )
        if rebroadcast:
            self._schedule_config_rebroadcasts()

    def _publish_payload(self, payload: Mapping[str, Any]) -> None:
        self._log_payload(payload)
        self.broadcaster.publish(dict(payload))

    def _log_payload(self, payload: Mapping[str, Any]) -> None:
        if not self._preferences.log_payloads:
            return
        event: Optional[str] = None
        if isinstance(payload, Mapping):
            raw_event = payload.get("event")
            if isinstance(raw_event, str) and raw_event:
                event = raw_event
        try:
            serialised = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        except (TypeError, ValueError):
            serialised = repr(payload)
        if event:
            LOGGER.info("Overlay payload [%s]: %s", event, serialised)
        else:
            LOGGER.info("Overlay payload: %s", serialised)

    def _locate_overlay_python(self) -> Optional[Path]:
        env_override = os.getenv("EDMC_OVERLAY_PYTHON")
        if env_override:
            override_path = Path(env_override).expanduser()
            if override_path.exists():
                LOGGER.debug("Using overlay Python from EDMC_OVERLAY_PYTHON=%s", override_path)
                return override_path
            LOGGER.debug("Overlay Python override %s not found, falling back", override_path)

        venv_candidates = []
        plugin_root = self.plugin_dir
        overlay_client_root = plugin_root / "overlay-client"
        venv_candidates.append(
            overlay_client_root
            / ".venv"
            / ("Scripts" if os.name == "nt" else "bin")
            / ("python.exe" if os.name == "nt" else "python")
        )

        for candidate in venv_candidates:
            if candidate.exists():
                LOGGER.debug("Using overlay client Python interpreter at %s", candidate)
                return candidate

        return None

    def _detect_wayland_compositor(self) -> str:
        session = (os.environ.get("XDG_SESSION_TYPE") or "").lower()
        if session != "wayland":
            return "none"
        env = os.environ
        current_desktop = (env.get("XDG_CURRENT_DESKTOP") or "").upper()
        if env.get("SWAYSOCK"):
            return "sway"
        if env.get("HYPRLAND_INSTANCE_SIGNATURE"):
            return "hyprland"
        if "KDE" in current_desktop or env.get("KDE_FULL_SESSION"):
            return "kwin"
        if "GNOME" in current_desktop or env.get("GNOME_SHELL_SESSION_MODE"):
            return "gnome-shell"
        if "COSMIC" in current_desktop:
            return "cosmic"
        if env.get("WAYLAND_DISPLAY", "").startswith("wayland-"):
            return "unknown"
        return "unknown"

    def _build_overlay_environment(self) -> Dict[str, str]:
        env = dict(os.environ)
        session = (env.get("XDG_SESSION_TYPE") or "").lower()
        compositor = self._detect_wayland_compositor()
        force_xwayland = bool(self._preferences.force_xwayland)
        env["EDMC_OVERLAY_SESSION_TYPE"] = session or "unknown"
        env["EDMC_OVERLAY_COMPOSITOR"] = compositor
        env["EDMC_OVERLAY_FORCE_XWAYLAND"] = "1" if force_xwayland else "0"
        if sys.platform.startswith("linux"):
            if session == "wayland" and not force_xwayland:
                env.setdefault("QT_QPA_PLATFORM", "wayland")
                env.setdefault("QT_WAYLAND_DISABLE_WINDOWDECORATION", "1")
                env.setdefault("QT_WAYLAND_LAYER_SHELL", "1")
            else:
                env["QT_QPA_PLATFORM"] = env.get("QT_QPA_PLATFORM", "xcb")
                env.setdefault("QT_WAYLAND_DISABLE_WINDOWDECORATION", "1")
        return env

    def _platform_context_payload(self) -> Dict[str, Any]:
        session = (os.environ.get("XDG_SESSION_TYPE") or "").lower()
        return {
            "session_type": session or "unknown",
            "compositor": self._detect_wayland_compositor(),
            "force_xwayland": bool(self._preferences.force_xwayland),
        }

    def _legacy_overlay_active(self) -> bool:
        try:
            legacy_module = importlib.import_module("edmcoverlay")
        except ModuleNotFoundError:
            return False
        except Exception as exc:
            LOGGER.debug("Error importing legacy edmcoverlay module: %s", exc)
            return False

        module_file = getattr(legacy_module, "__file__", None)
        if module_file:
            try:
                module_path = Path(module_file).resolve()
                if module_path.is_relative_to(self.plugin_dir.resolve()):
                    return False
            except Exception:
                pass

        overlay_cls = getattr(legacy_module, "Overlay", None)
        if overlay_cls is None:
            return False

        try:
            overlay = overlay_cls()
            try:
                overlay.connect()
            except Exception:
                pass
            overlay.send_message(
                "modern-overlay-conflict",
                "EDMC Modern Overlay detected the legacy overlay. Using legacy overlay instead.",
                "#ffa500",
                100,
                100,
                ttl=5,
                size="normal",
            )
        except Exception as exc:
            LOGGER.debug("Legacy edmcoverlay overlay not responding: %s", exc)
            return False

        return True

    def _schedule_config_rebroadcasts(self, count: int = 5, interval: float = 1.0) -> None:
        if count <= 0 or interval <= 0:
            return

        self._cancel_config_timers()

        def _schedule(delay: float) -> None:
            timer_ref: Optional[threading.Timer] = None

            def _callback() -> None:
                try:
                    self._rebroadcast_last_config()
                finally:
                    if timer_ref is not None:
                        with self._config_timer_lock:
                            self._config_timers.discard(timer_ref)

            timer_ref = threading.Timer(delay, _callback)
            timer_ref.daemon = True
            with self._config_timer_lock:
                self._config_timers.add(timer_ref)
            timer_ref.start()

        for index in range(count):
            delay = interval * (index + 1)
            _schedule(delay)

    def _rebroadcast_last_config(self) -> None:
        if not self._running:
            return
        if not self._last_config:
            return
        self._publish_payload(dict(self._last_config))

    def _cancel_config_timers(self) -> None:
        with self._config_timer_lock:
            timers = list(self._config_timers)
            self._config_timers.clear()
        for timer in timers:
            try:
                timer.cancel()
            except Exception:
                pass


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
    global _prefs_panel, _plugin, _preferences
    if _plugin:
        try:
            _plugin.stop()
        finally:
            _plugin = None
    _prefs_panel = None
    _preferences = None


def plugin_app(parent) -> Optional[Any]:  # pragma: no cover - EDMC Tk frame hook
    return None


def plugin_prefs(parent, cmdr: str, is_beta: bool):  # pragma: no cover - optional settings pane
    LOGGER.debug("plugin_prefs invoked: parent=%r cmdr=%r is_beta=%s", parent, cmdr, is_beta)
    if _preferences is None:
        LOGGER.debug("Preferences not initialised; returning no UI")
        return None
    send_callback = _plugin.send_test_message if _plugin else None
    opacity_callback = _plugin.preview_overlay_opacity if _plugin else None
    try:
        status_callback = _plugin.set_show_status_preference if _plugin else None
        status_bandwidth_callback = _plugin.set_status_bandwidth_preference if _plugin else None
        status_fps_callback = _plugin.set_status_fps_preference if _plugin else None
        log_callback = _plugin.set_log_payload_preference if _plugin else None
        gridlines_enabled_callback = _plugin.set_gridlines_enabled_preference if _plugin else None
        gridline_spacing_callback = _plugin.set_gridline_spacing_preference if _plugin else None
        force_render_callback = _plugin.set_force_render_preference if _plugin else None
        debug_overlay_callback = _plugin.set_debug_overlay_preference if _plugin else None
        font_min_callback = _plugin.set_min_font_preference if _plugin else None
        font_max_callback = _plugin.set_max_font_preference if _plugin else None
        panel = PreferencesPanel(
            parent,
            _preferences,
            send_callback,
            opacity_callback,
            status_callback,
            status_bandwidth_callback,
            status_fps_callback,
            log_callback,
            gridlines_enabled_callback,
            gridline_spacing_callback,
            force_render_callback,
            debug_overlay_callback,
            font_min_callback,
            font_max_callback,
        )
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
        if _preferences:
            LOGGER.debug(
                "Preferences saved: capture_output=%s show_connection_status=%s log_payloads=%s "
                "client_log_retention=%d gridlines_enabled=%s gridline_spacing=%d "
                "force_render=%s force_xwayland=%s debug_overlay=%s font_min=%.1f font_max=%.1f",
                _preferences.capture_output,
                _preferences.show_connection_status,
                _preferences.log_payloads,
                _preferences.client_log_retention,
                _preferences.gridlines_enabled,
                _preferences.gridline_spacing,
                _preferences.force_render,
                _preferences.force_xwayland,
                _preferences.show_debug_overlay,
                _preferences.min_font_point,
                _preferences.max_font_point,
            )
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
