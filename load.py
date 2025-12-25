"""Primary entry point for the EDMC Modern Overlay plugin."""
from __future__ import annotations

import importlib
import json
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Set, Tuple

try:
    from monitor import game_running as _edmc_game_running, is_live_galaxy as _edmc_is_live_galaxy  # type: ignore
except Exception:  # pragma: no cover - running outside EDMC
    _edmc_game_running = None  # type: ignore
    _edmc_is_live_galaxy = None  # type: ignore

if __package__:
    from .version import (
        __version__ as MODERN_OVERLAY_VERSION,
        DEV_MODE_ENV_VAR,
        is_dev_build,
    )
    from .overlay_plugin.lifecycle import LifecycleTracker
    from .overlay_plugin.overlay_watchdog import OverlayWatchdog
    from .overlay_plugin.overlay_socket_server import WebSocketBroadcaster
    from .overlay_plugin.logging_utils import build_rotating_payload_handler
    from .overlay_plugin.runtime_services import start_runtime_services, stop_runtime_services
    from .overlay_plugin.controller_services import (
        controller_launch_sequence,
        launch_controller,
        terminate_controller_process,
    )
    from .overlay_plugin.prefs_services import PrefsWorker
    from .overlay_plugin.config_version_services import (
        cancel_config_timers,
        cancel_version_notice_timers,
        rebroadcast_last_config,
        schedule_config_rebroadcasts,
        schedule_version_notice_rebroadcasts,
    )
    from .overlay_plugin.preferences import (
        CLIENT_LOG_RETENTION_MAX,
        CLIENT_LOG_RETENTION_MIN,
        DEFAULT_CLIENT_LOG_RETENTION,
        Preferences,
        PreferencesPanel,
        STATUS_GUTTER_MAX,
        TroubleshootingPanelState,
        _normalise_launch_command,
    )
    from .overlay_plugin.version_helper import VersionStatus, evaluate_version_status
    from .overlay_plugin.legacy_tcp_server import LegacyOverlayTCPServer
    from .overlay_plugin.overlay_api import (
        register_grouping_store,
        register_publisher,
        send_overlay_message,
        unregister_grouping_store,
        unregister_publisher,
    )
    from .overlay_plugin.journal_commands import build_command_helper
    from .EDMCOverlay.edmcoverlay import normalise_legacy_payload
    from .group_cache import GroupPlacementCache
    from .overlay_client import env_overrides as env_overrides_helper
else:  # pragma: no cover - EDMC loads as top-level module
    from version import __version__ as MODERN_OVERLAY_VERSION, DEV_MODE_ENV_VAR, is_dev_build
    from overlay_plugin.lifecycle import LifecycleTracker
    from overlay_plugin.overlay_watchdog import OverlayWatchdog
    from overlay_plugin.overlay_socket_server import WebSocketBroadcaster
    from overlay_plugin.logging_utils import build_rotating_payload_handler
    from overlay_plugin.runtime_services import start_runtime_services, stop_runtime_services
    from overlay_plugin.controller_services import (
        controller_launch_sequence,
        launch_controller,
        terminate_controller_process,
    )
    from overlay_plugin.prefs_services import PrefsWorker
    from overlay_plugin.config_version_services import (
        cancel_config_timers,
        cancel_version_notice_timers,
        rebroadcast_last_config,
        schedule_config_rebroadcasts,
        schedule_version_notice_rebroadcasts,
    )
    from overlay_plugin.preferences import (
        CLIENT_LOG_RETENTION_MAX,
        CLIENT_LOG_RETENTION_MIN,
        DEFAULT_CLIENT_LOG_RETENTION,
        Preferences,
        PreferencesPanel,
        STATUS_GUTTER_MAX,
        TroubleshootingPanelState,
        _normalise_launch_command,
    )
    from overlay_plugin.version_helper import VersionStatus, evaluate_version_status
    from overlay_plugin.legacy_tcp_server import LegacyOverlayTCPServer
    from overlay_plugin.overlay_api import (
        register_grouping_store,
        register_publisher,
        send_overlay_message,
        unregister_grouping_store,
        unregister_publisher,
    )
    from overlay_plugin.journal_commands import build_command_helper
    from EDMCOverlay.edmcoverlay import normalise_legacy_payload
    from group_cache import GroupPlacementCache
    import overlay_client.env_overrides as env_overrides_helper

PLUGIN_NAME = "EDMCModernOverlay"
PLUGIN_VERSION = MODERN_OVERLAY_VERSION
DEV_BUILD = is_dev_build(MODERN_OVERLAY_VERSION)
LOGGER_NAME = PLUGIN_NAME
LOG_TAG = PLUGIN_NAME

DEFAULT_WINDOW_BASE_WIDTH = 1280
DEFAULT_WINDOW_BASE_HEIGHT = 960

VERSION_UPDATE_NOTICE_TEXT = "A newer version of EDMC Modern Overlay is available"
VERSION_UPDATE_NOTICE_COLOR = "#ff3333"
VERSION_UPDATE_NOTICE_TTL = 10
VERSION_UPDATE_NOTICE_POSITION_X = 20
VERSION_UPDATE_NOTICE_POSITION_Y = 20
VERSION_UPDATE_NOTICE_ID = f"{PLUGIN_NAME}-version-notice"
VERSION_UPDATE_NOTICE_REBROADCASTS = 0
VERSION_UPDATE_NOTICE_REBROADCAST_INTERVAL = 2.0

FONT_PREVIEW_COLOR = "#ff7f00"
FONT_PREVIEW_TTL = 5
FONT_PREVIEW_BASE_X = 60
FONT_PREVIEW_BASE_Y = 120
FONT_PREVIEW_LINE_SPACING = 40

EDMC_DEFAULT_LOG_LEVEL = logging.DEBUG if DEV_BUILD else logging.INFO
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

_DEV_LOG_LEVEL_OVERRIDE_EMITTED = False


def _coerce_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _env_flag(name: str) -> Optional[bool]:
    """Parse a boolean environment flag, returning None when unset/invalid."""
    value = os.environ.get(name)
    if value is None:
        return None
    token = value.strip().lower()
    if token in {"1", "true", "yes", "on"}:
        return True
    if token in {"0", "false", "no", "off"}:
        return False
    return None


def _load_edmc_config_module() -> Optional[Any]:
    try:
        return importlib.import_module("config")
    except Exception:
        return None


def _game_running() -> bool:
    if _edmc_game_running is None:
        return True
    try:
        return bool(_edmc_game_running())
    except Exception:
        return True


def _is_live_galaxy() -> bool:
    if _edmc_is_live_galaxy is None:
        return True
    try:
        return bool(_edmc_is_live_galaxy())
    except Exception:
        return True


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


def _edmc_debug_logging_active() -> bool:
    """Return True when EDMC logging is set to DEBUG or lower."""
    try:
        level = _resolve_edmc_log_level()
    except Exception:
        return False
    return level <= logging.DEBUG

def _dev_override_active() -> bool:
    """Return True when Modern Overlay is running in dev mode."""

    return bool(DEV_BUILD)


def _diagnostic_logging_enabled() -> bool:
    """Return True when logging gates should behave as if EDMC were DEBUG."""

    return _edmc_debug_logging_active() or _dev_override_active()


def _effective_log_level(level: Optional[int] = None) -> int:
    """Return the level Modern Overlay loggers should use."""

    if level is None:
        level = _resolve_edmc_log_level()
    if _dev_override_active() and level > logging.DEBUG:
        return logging.DEBUG
    return level


def _ensure_plugin_logger_level() -> int:
    global _DEV_LOG_LEVEL_OVERRIDE_EMITTED

    edmc_level = _resolve_edmc_log_level()
    effective_level = _effective_log_level(edmc_level)
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(effective_level)
    if (
        _dev_override_active()
        and effective_level < edmc_level
        and not _DEV_LOG_LEVEL_OVERRIDE_EMITTED
    ):
        _DEV_LOG_LEVEL_OVERRIDE_EMITTED = True
        logger.info(
            "Dev mode forcing Modern Overlay logger to DEBUG (EDMC log level is %s)",
            logging.getLevelName(edmc_level),
        )
    return effective_level


class _EDMCLogHandler(logging.Handler):
    """Logging bridge that always respects EDMC's configured log level."""

    def emit(self, record: logging.LogRecord) -> None:
        target_level = _effective_log_level()
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


UTC = getattr(datetime, "UTC", timezone.utc)

LOGGER = _configure_logger()
if DEV_BUILD:
    LOGGER.info(
        "Running Modern Overlay dev build (%s); override via %s=0 to force release behaviour.",
        MODERN_OVERLAY_VERSION,
        DEV_MODE_ENV_VAR,
    )
PAYLOAD_LOGGER_NAME = f"{LOGGER_NAME}.payloads"
PAYLOAD_LOG_FILE_NAME = "overlay-payloads.log"
PAYLOAD_LOG_DIR_NAME = PLUGIN_NAME
PAYLOAD_LOG_MAX_BYTES = 512 * 1024
CONNECTION_LOG_INTERVAL_SECONDS = 5.0

DEFAULT_DEBUG_CONFIG: Dict[str, Any] = {
    "capture_client_stderrout": True,
    "overlay_logs_to_keep": 5,
    "payload_logging": {
        "overlay_payload_log_enabled": True,
        "exclude_plugins": [],
    },
}

DEFAULT_DEV_SETTINGS: Dict[str, Any] = {
    "tracing": {
        "enabled": False,
        "payload_ids": [],
    },
    "overlay_outline": True,
    "group_bounds_outline": True,
    "payload_vertex_markers": False,
    "repaint_debounce_enabled": True,
    "log_repaint_debounce": False,
}

FLATPAK_ENV_FORWARD_KEYS: Tuple[str, ...] = (
    "EDMC_OVERLAY_SESSION_TYPE",
    "EDMC_OVERLAY_COMPOSITOR",
    "EDMC_OVERLAY_FORCE_XWAYLAND",
    "EDMC_OVERLAY_IS_FLATPAK",
    "EDMC_OVERLAY_FLATPAK_ID",
    "QT_QPA_PLATFORM",
    "QT_WAYLAND_DISABLE_WINDOWDECORATION",
    "QT_WAYLAND_LAYER_SHELL",
)


def _log(message: str) -> None:
    """Log to EDMC via the Python logging facade."""
    LOGGER.info(message)


def _log_debug(message: str) -> None:
    """Log debug messages through the EDMC logger."""
    LOGGER.debug(message)


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
        self.broadcaster = WebSocketBroadcaster(
            log=_log,
            log_debug=_log_debug,
            connection_log_interval=CONNECTION_LOG_INTERVAL_SECONDS,
            ingest_callback=self._handle_cli_payload,
        )
        self.watchdog: Optional[OverlayWatchdog] = None
        self._legacy_tcp_server: Optional[LegacyOverlayTCPServer] = None
        self._lock = threading.Lock()
        self._lifecycle = LifecycleTracker(LOGGER)
        self._prefs_lock = threading.Lock()
        self._force_monitor_stop = threading.Event()
        self._force_monitor_thread: Optional[threading.Thread] = None
        self._controller_force_render_override = False
        self._running = False
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
        self._overlay_metrics: Dict[str, Any] = {}
        self._enforce_force_xwayland(persist=True, update_watchdog=False, emit_config=False)
        self._payload_logger = logging.getLogger(PAYLOAD_LOGGER_NAME)
        self._payload_logger.setLevel(logging.DEBUG)
        self._payload_logger.propagate = False
        self._payload_log_handler: Optional[logging.Handler] = None
        self._log_retention_override: Optional[int] = None
        self._plugin_prefix_map: Dict[str, str] = self._load_plugin_prefix_map()
        self._payload_filter_path = self.plugin_dir / "debug.json"
        self._dev_settings_path = self.plugin_dir / "dev_settings.json"
        self._payload_filter_mtime: Optional[float] = None
        self._dev_settings_mtime: Optional[float] = None
        self._payload_filter_excludes: Set[str] = set()
        self._payload_logging_enabled: bool = False
        self._trace_enabled: bool = False
        self._trace_payload_prefixes: Tuple[str, ...] = ()
        self._capture_client_stderrout: bool = False
        self._dev_settings: Dict[str, Any] = deepcopy(DEFAULT_DEV_SETTINGS)
        self._flatpak_context = self._detect_flatpak_context()
        self._flatpak_spawn_warning_emitted = False
        self._flatpak_host_warning_emitted = False
        self._load_payload_debug_config(force=True)
        self._load_dev_settings(force=True)
        if self._payload_log_handler is None:
            self._configure_payload_logger()
        self._version_status: Optional[VersionStatus] = None
        self._version_status_lock = threading.Lock()
        self._version_update_notice_sent = False
        self._version_notice_timer_lock = threading.Lock()
        self._version_notice_timers: Set[threading.Timer] = set()
        self._version_check_thread: Optional[threading.Thread] = None
        self._launch_log_timer: Optional[threading.Timer] = None
        self._launch_log_pending: Optional[Tuple[str, str]] = None
        self._last_launch_info_value: str = ""
        self._last_launch_info_time: float = 0.0
        self._last_launch_log_value: str = ""
        self._last_launch_log_time: float = 0.0
        self._command_helper_prefix: Optional[str] = None
        self._controller_active_group: Optional[Tuple[str, str]] = None
        self._prefs_worker = PrefsWorker(self._lifecycle, LOGGER)
        register_grouping_store(self.plugin_dir / "overlay_groupings.json")
        threading.Thread(
            target=self._evaluate_version_status_once,
            name="ModernOverlayVersionCheck",
            daemon=True,
        ).start()
        launch_cmd = _normalise_launch_command(str(getattr(self._preferences, "controller_launch_command", "!ovr")))
        LOGGER.info("Initialising Overlay Controller journal command helper with launch prefix=%s", launch_cmd)
        self._command_helper = self._build_command_helper(launch_cmd)
        self._command_helper_prefix = launch_cmd
        self._controller_launch_lock = threading.Lock()
        self._controller_launch_thread: Optional[threading.Thread] = None
        self._controller_process: Optional[subprocess.Popen] = None
        self._controller_status_id = f"{PLUGIN_NAME}-controller-status"
        self._controller_pid_path = self.plugin_dir / "overlay_controller.pid"
        self._last_override_reload_nonce: Optional[str] = None
        self._lifecycle.track_handle(self.broadcaster)

    # Lifecycle ------------------------------------------------------------

    @property
    def _tracked_threads(self):
        return self._lifecycle.threads

    @property
    def _tracked_handles(self):
        return self._lifecycle.handles

    def start(self) -> str:
        with self._lock:
            if self._running:
                return PLUGIN_NAME
            _ensure_plugin_logger_level()
            self._running = start_runtime_services(self, LOGGER, _log)
        if not self._running:
            return PLUGIN_NAME

        self._start_prefs_worker()
        self._start_force_render_monitor_if_needed()
        self._start_version_status_check()
        register_publisher(self._publish_external)
        self._start_legacy_tcp_server()
        self._send_overlay_config(rebroadcast=True)
        self._maybe_emit_version_update_notice()
        _log("Plugin started")
        return PLUGIN_NAME

    def stop(self) -> None:
        with self._lock:
            if not self._running:
                self._stop_prefs_worker()
                return
            self._running = False
        unregister_publisher()
        unregister_grouping_store()
        _log("Plugin stopping")
        self._cancel_config_timers()
        self._cancel_version_notice_timers()
        self._stop_legacy_tcp_server()
        stop_runtime_services(self, LOGGER, self._lifecycle.untrack_handle)
        if self._payload_log_handler is not None:
            self._payload_logger.removeHandler(self._payload_log_handler)
            try:
                self._payload_log_handler.close()
            except Exception:
                pass
            self._payload_log_handler = None
        self._force_monitor_stop.set()
        self._terminate_controller_process()
        self._lifecycle.join_thread(self._force_monitor_thread, "ModernOverlayForceMonitor", timeout=2.0)
        self._force_monitor_thread = None
        self._lifecycle.join_thread(self._version_check_thread, "ModernOverlayVersionCheck", timeout=2.0)
        self._version_check_thread = None
        self._stop_prefs_worker()
        self._lifecycle.log_state("after stop")

    # Journal handling -----------------------------------------------------

    def handle_journal(self, cmdr: str, system: str, station: str, entry: Dict[str, Any]) -> None:
        if not self._running:
            return
        # Respect EDMC helpers (PLUGINS.md:113) instead of relying solely on journal-derived state.
        if not _game_running():
            return
        event = entry.get("event")
        if not event:
            return
        if not _is_live_galaxy():
            with self._lock:
                self._state.update({"system": "", "station": "", "docked": False})
            return
        try:
            self._command_helper.handle_entry(entry)
        except Exception as exc:  # pragma: no cover - defensive guard
            LOGGER.debug("Journal command helper failed: %s", exc, exc_info=exc)

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

    def _evaluate_version_status_once(self) -> None:
        try:
            status = evaluate_version_status(PLUGIN_VERSION)
        except Exception as exc:  # pragma: no cover - defensive fallback
            LOGGER.debug("Version check failed: %s", exc, exc_info=exc)
            status = VersionStatus(
                current_version=PLUGIN_VERSION,
                latest_version=None,
                is_outdated=False,
                checked_at=time.time(),
                error=str(exc),
            )
        with self._version_status_lock:
            self._version_status = status
        self._maybe_emit_version_update_notice()

    def get_version_status(self) -> Optional[VersionStatus]:
        with self._version_status_lock:
            return self._version_status

    def _maybe_emit_version_update_notice(self) -> None:
        status = self.get_version_status()
        if status is None:
            return
        if not status.update_available:
            return
        if self._version_update_notice_sent:
            return
        if not self._running:
            return
        if self._send_version_update_notice(status):
            self._schedule_version_notice_rebroadcasts()

    def _build_version_update_notice_payload(self) -> Dict[str, Any]:
        current_time = datetime.now(UTC).isoformat()
        return {
            "timestamp": current_time,
            "event": "LegacyOverlay",
            "type": "message",
            "id": VERSION_UPDATE_NOTICE_ID,
            "text": VERSION_UPDATE_NOTICE_TEXT,
            "color": VERSION_UPDATE_NOTICE_COLOR,
            "x": VERSION_UPDATE_NOTICE_POSITION_X,
            "y": VERSION_UPDATE_NOTICE_POSITION_Y,
            "ttl": VERSION_UPDATE_NOTICE_TTL,
            "size": "normal",
        }

    def _send_version_update_notice(self, status: VersionStatus) -> bool:
        payload = self._build_version_update_notice_payload()
        if send_overlay_message(payload):
            LOGGER.info(
                "Overlay update notice displayed; current=%s latest=%s",
                status.current_version,
                status.latest_version or "unknown",
            )
            self._version_update_notice_sent = True
            return True
        LOGGER.debug("Failed to publish version update notice to overlay")
        return False

    def _schedule_version_notice_rebroadcasts(
        self,
        count: int = VERSION_UPDATE_NOTICE_REBROADCASTS,
        interval: float = VERSION_UPDATE_NOTICE_REBROADCAST_INTERVAL,
    ) -> None:
        schedule_version_notice_rebroadcasts(
            should_rebroadcast=lambda: self._running and self._version_update_notice_sent,
            build_payload=self._build_version_update_notice_payload,
            send_payload=send_overlay_message,
            timers=self._version_notice_timers,
            timer_lock=self._version_notice_timer_lock,
            count=count,
            interval=interval,
            logger=LOGGER,
        )

    def _cancel_version_notice_timers(self) -> None:
        cancel_version_notice_timers(self._version_notice_timers, self._version_notice_timer_lock, LOGGER)

    @staticmethod
    def _build_log_level_payload() -> Dict[str, Any]:
        level = _resolve_edmc_log_level()
        try:
            numeric = int(level)
        except (TypeError, ValueError):
            numeric = logging.INFO
        level_name = logging.getLevelName(numeric)
        return {"value": numeric, "name": str(level_name)}

    def _write_port_file(self) -> None:
        target = self.plugin_dir / "port.json"
        data = {
            "port": self.broadcaster.port,
            "version": PLUGIN_VERSION,
            "log_level": self._build_log_level_payload(),
        }
        if self._flatpak_context.get("is_flatpak"):
            data["flatpak"] = True
            if self._flatpak_context.get("app_id"):
                data["flatpak_app"] = self._flatpak_context["app_id"]
        target.write_text(json.dumps(data, indent=2), encoding="utf-8")
        _log(f"Wrote port.json with port {self.broadcaster.port} (plugin version {PLUGIN_VERSION})")

    def _delete_port_file(self) -> None:
        try:
            (self.plugin_dir / "port.json").unlink()
        except FileNotFoundError:
            pass

    def _configure_payload_logger(self) -> None:
        retention = self._resolve_client_log_retention()
        backup_count = max(0, retention - 1)
        log_dir = self._resolve_payload_logs_dir()
        log_path = log_dir / PAYLOAD_LOG_FILE_NAME
        formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S")
        try:
            handler = build_rotating_payload_handler(
                log_dir,
                PAYLOAD_LOG_FILE_NAME,
                retention=retention,
                max_bytes=PAYLOAD_LOG_MAX_BYTES,
                formatter=formatter,
            )
        except Exception as exc:
            LOGGER.warning("Failed to initialise payload log at %s: %s", log_path, exc)
            return

        if self._payload_log_handler is not None:
            self._payload_logger.removeHandler(self._payload_log_handler)
            try:
                self._payload_log_handler.close()
            except Exception:
                pass

        self._payload_logger.addHandler(handler)
        self._payload_log_handler = handler
        LOGGER.debug(
            "Payload logging initialised: path=%s retention=%d max_bytes=%d backup_count=%d",
            log_path,
            retention,
            PAYLOAD_LOG_MAX_BYTES,
            backup_count,
        )

    def _track_thread(self, thread: threading.Thread) -> None:
        self._lifecycle.track_thread(thread)

    def _untrack_thread(self, thread: Optional[threading.Thread]) -> None:
        self._lifecycle.untrack_thread(thread)

    def _track_handle(self, handle: Any) -> None:
        self._lifecycle.track_handle(handle)

    def _untrack_handle(self, handle: Any) -> None:
        self._lifecycle.untrack_handle(handle)

    def _start_prefs_worker(self) -> None:
        if self._prefs_worker is None:
            self._prefs_worker = PrefsWorker(self._lifecycle, LOGGER)
        self._prefs_worker.start()

    def _stop_prefs_worker(self) -> None:
        worker = self._prefs_worker
        if worker is None:
            return
        if isinstance(worker, PrefsWorker):
            worker.stop()
        else:
            try:
                worker.join(timeout=2.0)  # type: ignore[attr-defined]
            except Exception:
                pass
            self._lifecycle.untrack_thread(getattr(worker, "thread", worker))
        self._prefs_worker = None

    def _submit_pref_task(self, func: Callable[[], Any], *, wait: bool = False, timeout: Optional[float] = 2.0) -> Any:
        if self._prefs_worker is None:
            self._prefs_worker = PrefsWorker(self._lifecycle, LOGGER)
        return self._prefs_worker.submit(func, wait=wait, timeout=timeout)

    def _start_force_render_monitor_if_needed(self) -> None:
        if self._force_monitor_thread and self._force_monitor_thread.is_alive():
            return
        if not self._controller_force_render_override:
            return
        self._force_monitor_stop.clear()

        def _worker() -> None:
            try:
                while not self._force_monitor_stop.wait(timeout=5.0):
                    if not self._controller_force_render_override:
                        return
                    if self._overlay_controller_active():
                        continue
                    with self._prefs_lock:
                        if self._controller_force_render_override:
                            self._controller_force_render_override = False
                            LOGGER.info("Overlay Controller no longer detected; force-render override cleared.")
                            self._send_overlay_config()
                    return
            except Exception as exc:
                LOGGER.debug("Force-render monitor terminated with error: %s", exc, exc_info=exc)

        thread = threading.Thread(target=_worker, name="ModernOverlayForceMonitor", daemon=True)
        self._force_monitor_thread = thread
        self._lifecycle.track_thread(thread)
        thread.start()

    def _start_version_status_check(self) -> None:
        thread = self._version_check_thread
        if thread and thread.is_alive():
            return
        worker = threading.Thread(
            target=self._evaluate_version_status_once,
            name="ModernOverlayVersionCheck",
            daemon=True,
        )
        self._version_check_thread = worker
        self._lifecycle.track_thread(worker)
        worker.start()

    def _resolve_client_log_retention(self) -> int:
        try:
            base_value = int(getattr(self._preferences, "client_log_retention", DEFAULT_CLIENT_LOG_RETENTION))
        except (TypeError, ValueError):
            base_value = DEFAULT_CLIENT_LOG_RETENTION
        base_value = max(CLIENT_LOG_RETENTION_MIN, min(base_value, CLIENT_LOG_RETENTION_MAX))
        override = self._log_retention_override
        return override if override is not None else base_value

    def _resolve_force_render(self) -> bool:
        return bool(getattr(self._preferences, "force_render", False)) or bool(
            getattr(self, "_controller_force_render_override", False)
        )

    def _set_log_retention_override(self, value: Optional[int]) -> bool:
        if value is not None:
            value = max(CLIENT_LOG_RETENTION_MIN, min(int(value), CLIENT_LOG_RETENTION_MAX))
        if self._log_retention_override == value:
            return False
        self._log_retention_override = value
        effective = self._resolve_client_log_retention()
        if value is None:
            LOGGER.debug("Overlay log retention override cleared; using preference value %d", effective)
        else:
            LOGGER.debug("Overlay log retention override set to %d via debug.json", effective)
        return True

    def _on_log_retention_changed(self) -> None:
        self._configure_payload_logger()
        if self._last_config:
            self._last_config["client_log_retention"] = self._resolve_client_log_retention()
            self._rebroadcast_last_config()

    def _resolve_payload_logs_dir(self) -> Path:
        plugin_root = self.plugin_dir.resolve()
        candidates = []
        parents = plugin_root.parents
        if len(parents) >= 2:
            candidates.append(parents[1] / "logs")
        if len(parents) >= 1:
            candidates.append(parents[0] / "logs")
        candidates.append(Path.cwd() / "logs")
        for base in candidates:
            try:
                target = base / PAYLOAD_LOG_DIR_NAME
                target.mkdir(parents=True, exist_ok=True)
                return target
            except OSError:
                continue
        return plugin_root

    def _ensure_default_debug_config(self) -> bool:
        template = DEFAULT_DEBUG_CONFIG
        payload = json.dumps(template, indent=2, sort_keys=True) + "\n"
        try:
            self._payload_filter_path.write_text(payload, encoding="utf-8")
        except OSError as exc:
            LOGGER.warning("Unable to create default debug.json at %s: %s", self._payload_filter_path, exc)
            return False
        LOGGER.info("Created default debug.json at %s to enable developer tracing.", self._payload_filter_path)
        return True

    def _ensure_default_dev_settings(self) -> bool:
        payload = json.dumps(DEFAULT_DEV_SETTINGS, indent=2, sort_keys=True) + "\n"
        try:
            self._dev_settings_path.write_text(payload, encoding="utf-8")
        except OSError as exc:
            LOGGER.warning("Unable to create default dev_settings.json at %s: %s", self._dev_settings_path, exc)
            return False
        LOGGER.info("Created default dev_settings.json at %s for dev-mode helpers.", self._dev_settings_path)
        return True

    def _load_payload_debug_config(self, *, force: bool = False) -> None:
        pref_logging_enabled = bool(getattr(self._preferences, "log_payloads", False)) if self._preferences else False
        stat: Optional[os.stat_result]
        try:
            stat = self._payload_filter_path.stat()
        except FileNotFoundError:
            should_seed = _diagnostic_logging_enabled()
            created = self._ensure_default_debug_config() if should_seed else False
            if created:
                try:
                    stat = self._payload_filter_path.stat()
                except (FileNotFoundError, OSError):
                    stat = None
            else:
                stat = None
            if stat is None:
                retention_cleared = self._set_log_retention_override(None)
                if force or self._payload_filter_excludes or self._payload_logging_enabled:
                    self._payload_filter_excludes = set()
                    self._payload_logging_enabled = pref_logging_enabled
                    self._payload_filter_mtime = None
                    self._apply_capture_override(False)
                if retention_cleared:
                    self._on_log_retention_changed()
                self._load_dev_settings(force=False)
                return
        if stat is None:
            self._payload_filter_excludes = set()
            self._payload_logging_enabled = pref_logging_enabled
            self._payload_filter_mtime = None
            self._apply_capture_override(False)
            retention_cleared = self._set_log_retention_override(None)
            if retention_cleared:
                self._on_log_retention_changed()
            self._load_dev_settings(force=False)
            return
        if not force and self._payload_filter_mtime is not None and stat.st_mtime <= self._payload_filter_mtime:
            self._load_dev_settings(force=False)
            return
        try:
            raw_text = self._payload_filter_path.read_text(encoding="utf-8")
            data = json.loads(raw_text)
        except (OSError, json.JSONDecodeError):
            self._payload_filter_excludes = set()
            self._payload_logging_enabled = pref_logging_enabled
            self._apply_capture_override(False)
            retention_cleared = self._set_log_retention_override(None)
            if retention_cleared:
                self._on_log_retention_changed()
            self._payload_filter_mtime = stat.st_mtime
            self._load_dev_settings(force=False)
            return
        excludes: Set[str] = set()
        updated_defaults = False
        if isinstance(data, Mapping):
            mutable_data = dict(data)
            for key, value in DEFAULT_DEBUG_CONFIG.items():
                if key not in mutable_data:
                    mutable_data[key] = deepcopy(value)
                    updated_defaults = True
            payload_logging_defaults = DEFAULT_DEBUG_CONFIG.get("payload_logging")
            if isinstance(payload_logging_defaults, Mapping):
                payload_section = mutable_data.setdefault("payload_logging", {})
                if isinstance(payload_section, Mapping):
                    payload_section = dict(payload_section)
                    for key, value in payload_logging_defaults.items():
                        if key not in payload_section:
                            payload_section[key] = deepcopy(value)
                            updated_defaults = True
                    mutable_data["payload_logging"] = payload_section
            data = mutable_data
        else:
            data = deepcopy(DEFAULT_DEBUG_CONFIG)
            updated_defaults = True
        needs_write = updated_defaults
        if _dev_override_active():
            if self._migrate_dev_settings_from_debug(data):
                needs_write = True

        logging_override: Optional[bool] = None
        capture_client_stderrout = False
        log_retention_override: Optional[int] = None

        def _coerce_log_retention(value: Any) -> Optional[int]:
            if value is None:
                return None
            try:
                numeric = int(value)
            except (TypeError, ValueError):
                return None
            if numeric <= 0:
                return CLIENT_LOG_RETENTION_MIN
            if numeric > CLIENT_LOG_RETENTION_MAX:
                return CLIENT_LOG_RETENTION_MAX
            return numeric

        logging_section = data.get("payload_logging")
        if isinstance(logging_section, Mapping):
            override = logging_section.get("overlay_payload_log_enabled")
            if override is not None:
                logging_override = bool(override)
            exclude_value = logging_section.get("exclude_plugins")
            if isinstance(exclude_value, (list, tuple, set)):
                excludes = {
                    str(item).strip().lower()
                    for item in exclude_value
                    if isinstance(item, (str, int, float)) and str(item).strip()
                }
        capture_value = data.get("capture_client_stderrout")
        if isinstance(capture_value, bool):
            capture_client_stderrout = capture_value
        elif capture_value is not None:
            capture_client_stderrout = bool(capture_value)
        log_retention_override = _coerce_log_retention(data.get("overlay_logs_to_keep"))

        self._payload_filter_excludes = excludes
        effective_logging = pref_logging_enabled if logging_override is None else logging_override
        self._payload_logging_enabled = effective_logging
        self._apply_capture_override(capture_client_stderrout)
        self._payload_filter_mtime = stat.st_mtime
        retention_changed = self._set_log_retention_override(log_retention_override)
        if retention_changed:
            self._on_log_retention_changed()
        if needs_write:
            try:
                self._payload_filter_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            except Exception:
                LOGGER.debug("Failed to backfill defaults into debug.json", exc_info=True)
        self._load_dev_settings(force=_dev_override_active())

    def _read_debug_config_payload(self) -> Optional[MutableMapping[str, Any]]:
        try:
            raw_text = self._payload_filter_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            if not self._ensure_default_debug_config():
                return None
            try:
                raw_text = self._payload_filter_path.read_text(encoding="utf-8")
            except (FileNotFoundError, OSError) as exc:
                LOGGER.warning("Unable to read debug.json after creating defaults: %s", exc)
                return None
        except OSError as exc:
            LOGGER.warning("Unable to read debug.json at %s: %s", self._payload_filter_path, exc)
            return None
        try:
            data = json.loads(raw_text)
        except (json.JSONDecodeError, TypeError) as exc:
            LOGGER.warning("Invalid debug.json detected; resetting to defaults: %s", exc)
            return deepcopy(DEFAULT_DEBUG_CONFIG)
        if not isinstance(data, MutableMapping):
            return deepcopy(DEFAULT_DEBUG_CONFIG)
        return dict(data)

    def _edit_debug_config(self, mutator: Callable[[MutableMapping[str, Any]], bool]) -> None:
        if not _diagnostic_logging_enabled():
            raise RuntimeError("Set EDMC log level to DEBUG (or enable dev mode) to update debug.json.")
        payload = self._read_debug_config_payload()
        if payload is None:
            raise RuntimeError(f"Unable to load debug.json from {self._payload_filter_path}")
        changed = bool(mutator(payload))
        if not changed:
            return
        try:
            self._payload_filter_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        except OSError as exc:
            raise RuntimeError(f"Failed to update debug.json: {exc}") from exc
        self._load_payload_debug_config(force=True)

    @staticmethod
    def _coerce_payload_id_list(value: Any) -> List[str]:
        if value is None:
            return []
        items: Iterable[Any]
        if isinstance(value, (list, tuple, set)):
            items = value
        else:
            items = (value,)
        cleaned: List[str] = []
        for item in items:
            if isinstance(item, (str, int, float)):
                token = str(item).strip()
                if token:
                    cleaned.append(token)
        return cleaned

    def _migrate_dev_settings_from_debug(self, data: MutableMapping[str, Any]) -> bool:
        dev_payload: Dict[str, Any] = {}
        migrated = False

        tracing_section = data.pop("tracing", None)
        if isinstance(tracing_section, Mapping):
            tracing_payload: Dict[str, Any] = {}
            tracing_payload["enabled"] = bool(tracing_section.get("enabled", False))
            tracing_payload["payload_ids"] = self._coerce_payload_id_list(tracing_section.get("payload_ids"))
            if not tracing_payload["payload_ids"]:
                single = tracing_section.get("payload_id") or tracing_section.get("payload")
                tracing_payload["payload_ids"] = self._coerce_payload_id_list(single)
            dev_payload["tracing"] = tracing_payload
            migrated = True
        legacy_trace_enabled = data.pop("trace_enabled", None)
        legacy_payload_ids = data.pop("payload_ids", None)
        if legacy_trace_enabled is not None or legacy_payload_ids is not None:
            tracing_payload = dev_payload.setdefault("tracing", {})
            if legacy_trace_enabled is not None:
                tracing_payload["enabled"] = bool(legacy_trace_enabled)
            if legacy_payload_ids is not None:
                tracing_payload["payload_ids"] = self._coerce_payload_id_list(legacy_payload_ids)
            migrated = True

        for key in ("overlay_outline", "group_bounds_outline", "payload_vertex_markers", "repaint_debounce_enabled", "log_repaint_debounce"):
            if key in data:
                dev_payload[key] = bool(data.pop(key))
                migrated = True

        if not migrated:
            return False

        if not self._dev_settings_path.exists():
            if not self._ensure_default_dev_settings():
                return False
        try:
            raw = self._dev_settings_path.read_text(encoding="utf-8")
            existing = json.loads(raw)
        except (OSError, json.JSONDecodeError):
            existing = {}
        normalized, _ = self._normalise_dev_settings(existing)

        tracing_override = dev_payload.get("tracing")
        if isinstance(tracing_override, Mapping):
            tracing_block = normalized.setdefault("tracing", {})
            tracing_block["enabled"] = bool(tracing_override.get("enabled", tracing_block.get("enabled", False)))
            payload_ids = tracing_override.get("payload_ids")
            if payload_ids is not None:
                tracing_block["payload_ids"] = self._coerce_payload_id_list(payload_ids)
        for key in ("overlay_outline", "group_bounds_outline", "payload_vertex_markers", "repaint_debounce_enabled", "log_repaint_debounce"):
            if key in dev_payload:
                normalized[key] = bool(dev_payload[key])

        try:
            self._dev_settings_path.write_text(json.dumps(normalized, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        except OSError as exc:
            LOGGER.warning("Failed to migrate dev settings into %s: %s", self._dev_settings_path, exc)
            return False
        LOGGER.info("Migrated legacy dev settings from debug.json into %s", self._dev_settings_path)
        return True

    def _normalise_dev_settings(self, raw: Any) -> Tuple[Dict[str, Any], bool]:
        normalized = deepcopy(DEFAULT_DEV_SETTINGS)
        needs_write = False
        if not isinstance(raw, Mapping):
            return normalized, True
        tracing_section = raw.get("tracing")
        tracing_block = normalized["tracing"]
        if isinstance(tracing_section, Mapping):
            tracing_block["enabled"] = bool(tracing_section.get("enabled", tracing_block.get("enabled", False)))
            payload_ids = tracing_section.get("payload_ids")
            if payload_ids is None:
                payload_ids = tracing_section.get("payload_id") or tracing_section.get("payload")
            tracing_block["payload_ids"] = self._coerce_payload_id_list(payload_ids)
        else:
            needs_write = True
        for key in ("overlay_outline", "group_bounds_outline", "payload_vertex_markers", "repaint_debounce_enabled", "log_repaint_debounce"):
            if key in raw:
                normalized[key] = bool(raw.get(key))
        return normalized, needs_write

    def _load_dev_settings(self, *, force: bool = False) -> None:
        if not _dev_override_active():
            self._dev_settings = deepcopy(DEFAULT_DEV_SETTINGS)
            self._dev_settings_mtime = None
            self._trace_enabled = False
            self._trace_payload_prefixes = ()
            return
        stat: Optional[os.stat_result]
        try:
            stat = self._dev_settings_path.stat()
        except FileNotFoundError:
            created = self._ensure_default_dev_settings()
            if created:
                try:
                    stat = self._dev_settings_path.stat()
                except (FileNotFoundError, OSError):
                    stat = None
            else:
                stat = None
        if stat is None:
            self._dev_settings = deepcopy(DEFAULT_DEV_SETTINGS)
            self._dev_settings_mtime = None
            self._trace_enabled = False
            self._trace_payload_prefixes = ()
            return
        if not force and self._dev_settings_mtime is not None and stat.st_mtime <= self._dev_settings_mtime:
            return
        try:
            raw_text = self._dev_settings_path.read_text(encoding="utf-8")
            raw_data = json.loads(raw_text)
        except (OSError, json.JSONDecodeError):
            raw_data = {}
        normalized, needs_write = self._normalise_dev_settings(raw_data)
        self._dev_settings = normalized
        self._dev_settings_mtime = stat.st_mtime
        if needs_write:
            try:
                self._dev_settings_path.write_text(json.dumps(normalized, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            except Exception:
                LOGGER.debug("Failed to backfill defaults into dev_settings.json", exc_info=True)
        tracing = normalized.get("tracing", {})
        self._trace_enabled = bool(tracing.get("enabled"))
        payload_ids = tracing.get("payload_ids") or []
        cleaned_ids = [str(item).strip() for item in payload_ids if isinstance(item, str) and str(item).strip()]
        self._trace_payload_prefixes = tuple(cleaned_ids)

    def _start_watchdog(self) -> bool:
        overlay_root = self._locate_overlay_client()
        if not overlay_root:
            _log("Overlay client not found; watchdog disabled")
            return False
        launch_env = self._build_overlay_environment()
        python_command = self._locate_overlay_python(launch_env)
        if python_command is None:
            _log(
                "Overlay client environment not found. Create overlay_client/.venv (or set EDMC_OVERLAY_PYTHON) and restart EDMC Modern Overlay."
            )
            LOGGER.error(
                "Overlay launch aborted: no overlay Python interpreter available under overlay_client/.venv or EDMC_OVERLAY_PYTHON."
            )
            return False
        command = [*python_command, "-m", "overlay_client.overlay_client"]
        overlay_cwd = overlay_root.parent
        LOGGER.debug(
            "Attempting to start overlay client via watchdog: command=%s cwd=%s",
            command,
            overlay_cwd,
        )
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
            overlay_cwd,
            log=_log,
            debug_log=LOGGER.debug,
            capture_output=self._capture_enabled(),
            env=launch_env,
        )
        self._update_capture_state(self._capture_enabled())
        self.watchdog.start()
        self._lifecycle.track_handle(self.watchdog)
        return True

    def _locate_overlay_client(self) -> Optional[Path]:
        candidates = [
            self.plugin_dir / "overlay_client",
            self.plugin_dir.parent / "overlay_client",
            Path(__file__).resolve().parent / "overlay_client",
        ]
        for candidate in candidates:
            if candidate.is_dir() and (candidate / "overlay_client.py").exists():
                return candidate
        return None

    def _capture_enabled(self) -> bool:
        return bool(self._capture_client_stderrout and _diagnostic_logging_enabled())

    def _apply_capture_override(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if enabled == self._capture_client_stderrout:
            return
        self._capture_client_stderrout = enabled
        if enabled:
            LOGGER.debug("Overlay stdout/stderr capture override enabled via debug.json.")
            if not _diagnostic_logging_enabled():
                LOGGER.debug(
                    "Overlay stdout/stderr capture override is active, but EDMC logging is not DEBUG; no output will be piped until logging is set to DEBUG or dev mode is enabled."
                )
        else:
            LOGGER.debug("Overlay stdout/stderr capture override disabled via debug.json.")
        if self.watchdog:
            try:
                self.watchdog.set_capture_output(self._capture_enabled())
            except Exception as exc:
                LOGGER.debug("Failed to update overlay capture setting: %s", exc)
        self._update_capture_state(self._capture_enabled())

    def _update_capture_state(self, enabled: bool) -> None:
        edmc_debug = _edmc_debug_logging_active()
        dev_override_only = _dev_override_active() and not edmc_debug
        if enabled and not self._capture_active:
            if dev_override_only:
                LOGGER.info(
                    "Dev mode forcing overlay stdout/stderr capture; EDMC log level is %s.",
                    logging.getLevelName(_resolve_edmc_log_level()),
                )
            else:
                LOGGER.info("EDMC DEBUG mode detected; piping overlay stdout/stderr to EDMC log.")
        elif not enabled and self._capture_active:
            LOGGER.info("Overlay stdout/stderr capture inactive (override or EDMC logging level disabled piping).")
        self._capture_active = enabled

    def _desired_force_xwayland(self) -> Tuple[bool, str]:
        env_override = _env_flag("EDMC_OVERLAY_FORCE_XWAYLAND")
        if env_override is not None:
            return env_override, "environment override"
        return bool(self._preferences.force_xwayland), "user preference"

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
        source = "user preference"
        with self._prefs_lock:
            desired, source = self._desired_force_xwayland()
            current = bool(self._preferences.force_xwayland)
            if current == desired:
                self._sync_force_xwayland_ui()
                return False
            self._preferences.force_xwayland = desired
            # Only persist explicit user choices; env overrides should remain ephemeral.
            if persist and source == "user preference":
                try:
                    self._preferences.save()
                except Exception as exc:
                    LOGGER.warning("Failed to save preferences while enforcing XWayland setting: %s", exc)
        LOGGER.info("force_xwayland set to %s via %s.", desired, source)
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
            "Applying updated preferences: show_connection_status=%s "
            "client_log_retention=%d gridlines_enabled=%s gridline_spacing=%d overlay_opacity=%.2f "
            "force_render=%s force_xwayland=%s debug_overlay=%s cycle_payload_ids=%s font_min=%.1f font_max=%.1f",
            self._preferences.show_connection_status,
            self._resolve_client_log_retention(),
            self._preferences.gridlines_enabled,
            self._preferences.gridline_spacing,
            self._preferences.overlay_opacity,
            self._resolve_force_render(),
            self._preferences.force_xwayland,
            self._preferences.show_debug_overlay,
            self._preferences.cycle_payload_ids,
            self._preferences.min_font_point,
            self._preferences.max_font_point,
        )
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
                "timestamp": datetime.now(UTC).isoformat(),
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
            current_time = datetime.now(UTC)
            payload = {
                "timestamp": current_time.isoformat(),
                "event": "LegacyOverlay",
                "type": "message",
                "id": f"{PLUGIN_NAME}-test-{current_time.strftime('%H%M%S%f')}",
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

    def preview_font_sizes(self) -> None:
        if not self._running:
            raise RuntimeError("Overlay is not running")
        timestamp = datetime.now(UTC).isoformat()
        entries = [
            ("huge", "Huge"),
            ("large", "Large"),
            ("normal", "Normal"),
            ("small", "Small"),
        ]
        for index, (size_label, text_label) in enumerate(entries):
            payload = {
                "timestamp": timestamp,
                "event": "LegacyOverlay",
                "type": "message",
                "id": f"{PLUGIN_NAME}-font-preview-{size_label}-{timestamp}",
                "text": text_label,
                "color": FONT_PREVIEW_COLOR,
                "x": FONT_PREVIEW_BASE_X,
                "y": FONT_PREVIEW_BASE_Y + (index * FONT_PREVIEW_LINE_SPACING),
                "ttl": FONT_PREVIEW_TTL,
                "size": size_label,
            }
            if not send_overlay_message(payload):
                raise RuntimeError("Failed to send font preview to overlay")

    def preview_overlay_opacity(self, value: float) -> None:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            numeric = 0.0
        with self._prefs_lock:
            self._preferences.overlay_opacity = max(0.0, min(1.0, numeric))
        self._send_overlay_config()

    def set_show_status_preference(self, value: bool) -> None:
        with self._prefs_lock:
            self._preferences.show_connection_status = bool(value)
            self._preferences.save()
        self._send_overlay_config()

    def set_launch_command_preference(self, value: str) -> None:
        normalised = _normalise_launch_command(str(value))
        now = time.monotonic()
        if normalised != self._last_launch_info_value or now - self._last_launch_info_time >= 1.0:
            LOGGER.info("Overlay Controller launch command change requested (runtime): raw=%r normalised=%s", value, normalised)
            self._last_launch_info_value = normalised
            self._last_launch_info_time = now
        with self._prefs_lock:
            current = getattr(self._preferences, "controller_launch_command", "!ovr")
            current_helper_prefix = self._command_helper_prefix or current
            changed_pref = normalised != current
            changed_helper = normalised != current_helper_prefix
            if changed_pref:
                self._preferences.controller_launch_command = normalised
                self._preferences.save()
        if not changed_pref and not changed_helper:
            if normalised != self._last_launch_log_value or now - self._last_launch_log_time >= 1.0:
                LOGGER.debug("Launch command unchanged; current=%s (debounced)", current)
                self._last_launch_log_value = normalised
                self._last_launch_log_time = now
            return
        if changed_pref:
            now = time.monotonic()
            if normalised != self._last_launch_info_value or now - self._last_launch_info_time >= 1.0:
                LOGGER.info("Overlay Controller launch command changed (runtime): %s -> %s", current, normalised)
                self._last_launch_info_value = normalised
                self._last_launch_info_time = now
        else:
            LOGGER.debug(
                "Overlay Controller launch command unchanged in prefs; refreshing command helper with prefix=%s",
                normalised,
            )
        self._command_helper = self._build_command_helper(normalised, previous_prefix=current_helper_prefix)
        self._command_helper_prefix = normalised
        LOGGER.info("Overlay Controller launch command preference updated to %s", normalised)

    def set_payload_opacity_preference(self, value: int) -> None:
        try:
            numeric = int(value)
        except (TypeError, ValueError):
            numeric = int(getattr(self._preferences, "global_payload_opacity", 100))
        numeric = max(0, min(numeric, 100))
        with self._prefs_lock:
            if numeric == getattr(self._preferences, "global_payload_opacity", 100):
                return
            self._preferences.global_payload_opacity = numeric
            self._preferences.save()
        self._send_overlay_config()

    def _build_command_helper(self, prefix: str, previous_prefix: Optional[str] = None) -> Any:
        legacy: list[str] = []
        if prefix == "!overlay":
            legacy = ["!overlay"]
        elif previous_prefix and previous_prefix != prefix:
            LOGGER.debug(
                "Removing legacy Overlay Controller launch prefix %s; active prefix now %s",
                previous_prefix,
                prefix,
            )
        helper = build_command_helper(self, LOGGER, command_prefix=prefix, legacy_prefixes=legacy)
        LOGGER.debug(
            "Overlay Controller journal command helper configured: primary=%s legacy=%s",
            prefix,
            ", ".join(legacy) if legacy else "<none>",
        )
        return helper

    def set_debug_overlay_corner_preference(self, value: str) -> None:
        corner = (value or "NW").upper()
        if corner not in {"NW", "NE", "SW", "SE"}:
            corner = "NW"
        with self._prefs_lock:
            self._preferences.debug_overlay_corner = corner
            self._preferences.save()
        self._send_overlay_config()

    def set_status_gutter_preference(self, value: int) -> None:
        try:
            gutter = int(value)
        except (TypeError, ValueError):
            gutter = self._preferences.status_message_gutter
        gutter = max(0, min(gutter, STATUS_GUTTER_MAX))
        with self._prefs_lock:
            if gutter == self._preferences.status_message_gutter:
                return
            self._preferences.status_message_gutter = gutter
            self._preferences.save()
        self._send_overlay_config()

    def set_gridlines_enabled_preference(self, value: bool) -> None:
        with self._prefs_lock:
            self._preferences.gridlines_enabled = bool(value)
            LOGGER.debug("Overlay gridlines %s", "enabled" if self._preferences.gridlines_enabled else "disabled")
            self._preferences.save()
        self._send_overlay_config()

    def set_gridline_spacing_preference(self, value: int) -> None:
        try:
            spacing = int(value)
        except (TypeError, ValueError):
            spacing = self._preferences.gridline_spacing
        spacing = max(10, spacing)
        with self._prefs_lock:
            self._preferences.gridline_spacing = spacing
            LOGGER.debug("Overlay gridline spacing set to %d px", spacing)
            self._preferences.save()
        self._send_overlay_config()

    def set_payload_nudge_preference(self, value: bool) -> None:
        enabled = bool(value)
        with self._prefs_lock:
            self._preferences.nudge_overflow_payloads = enabled
            LOGGER.debug("Payload overflow nudging %s", "enabled" if enabled else "disabled")
            self._preferences.save()
        self._send_overlay_config()

    def set_payload_nudge_gutter_preference(self, value: int) -> None:
        try:
            gutter = int(value)
        except (TypeError, ValueError):
            gutter = self._preferences.payload_nudge_gutter
        gutter = max(0, min(gutter, 500))
        with self._prefs_lock:
            self._preferences.payload_nudge_gutter = gutter
            LOGGER.debug("Payload overflow gutter set to %d px", gutter)
            self._preferences.save()
        self._send_overlay_config()

    def _update_force_render_locked(
        self,
        *,
        force_value: Optional[bool],
    ) -> Tuple[bool, bool, bool]:
        preferences = self._preferences
        previous_force = bool(getattr(preferences, "force_render", False))
        broadcast = False
        dirty = False
        if force_value is not None:
            flag = bool(force_value)
            if flag != previous_force:
                preferences.force_render = flag
                dirty = True
                broadcast = True
        return previous_force, dirty, broadcast

    def set_force_render_preference(self, value: bool) -> None:
        with self._prefs_lock:
            _prev_force, dirty, broadcast = self._update_force_render_locked(force_value=value)
            if not dirty:
                return
            self._preferences.save()
        if broadcast:
            self._send_overlay_config()

    def set_title_bar_compensation_preference(self, enabled: bool, height: int) -> None:
        with self._prefs_lock:
            self._preferences.title_bar_enabled = bool(enabled)
            try:
                numeric_height = int(height)
            except (TypeError, ValueError):
                numeric_height = self._preferences.title_bar_height
            numeric_height = max(0, numeric_height)
            self._preferences.title_bar_height = numeric_height
            LOGGER.debug(
                "Overlay title bar compensation updated: enabled=%s height=%d",
                self._preferences.title_bar_enabled,
                self._preferences.title_bar_height,
            )
            self._preferences.save()
        self._send_overlay_config()

    def set_debug_overlay_preference(self, value: bool) -> None:
        with self._prefs_lock:
            self._preferences.show_debug_overlay = bool(value)
            LOGGER.debug("Overlay debug overlay %s", "enabled" if self._preferences.show_debug_overlay else "disabled")
            self._preferences.save()
        self._send_overlay_config()

    def set_payload_logging_preference(self, value: bool) -> None:
        flag = bool(value)
        with self._prefs_lock:
            self._preferences.log_payloads = flag
            try:
                self._preferences.save()
            except Exception as exc:
                LOGGER.warning("Failed to persist payload logging preference: %s", exc)
        if not _diagnostic_logging_enabled():
            self._payload_logging_enabled = flag
            LOGGER.info("Overlay payload logging %s via preferences", "enabled" if flag else "disabled")
            return

        def mutator(payload: MutableMapping[str, Any]) -> bool:
            section = payload.get("payload_logging")
            if not isinstance(section, MutableMapping):
                section = {}
            normalized = dict(section)
            current = normalized.get("overlay_payload_log_enabled")
            if isinstance(current, bool) and current is flag:
                payload["payload_logging"] = normalized
                return False
            normalized["overlay_payload_log_enabled"] = flag
            payload["payload_logging"] = normalized
            return True

        self._edit_debug_config(mutator)
        LOGGER.info(
            "Overlay payload logging %s via debug.json override",
            "enabled" if flag else "disabled",
        )

    def get_troubleshooting_panel_state(self) -> TroubleshootingPanelState:
        with self._prefs_lock:
            excludes = tuple(sorted(self._payload_filter_excludes))
            retention = self._log_retention_override
            capture = self._capture_client_stderrout
        return TroubleshootingPanelState(
            diagnostics_enabled=_diagnostic_logging_enabled(),
            capture_enabled=capture,
            log_retention_override=retention,
            exclude_plugins=excludes,
        )

    def set_capture_override_preference(self, enabled: bool) -> None:
        flag = bool(enabled)

        def mutator(payload: MutableMapping[str, Any]) -> bool:
            current = payload.get("capture_client_stderrout")
            if isinstance(current, bool) and current is flag:
                return False
            payload["capture_client_stderrout"] = flag
            return True

        self._edit_debug_config(mutator)
        LOGGER.info("Overlay stdout/stderr capture override %s via preferences UI", "enabled" if flag else "disabled")

    def set_log_retention_override_preference(self, value: Optional[int]) -> None:
        if value is not None:
            try:
                numeric = int(value)
            except (TypeError, ValueError):
                numeric = DEFAULT_CLIENT_LOG_RETENTION
            numeric = max(CLIENT_LOG_RETENTION_MIN, min(numeric, CLIENT_LOG_RETENTION_MAX))
        else:
            numeric = None

        def mutator(payload: MutableMapping[str, Any]) -> bool:
            current = payload.get("overlay_logs_to_keep")
            if current == numeric:
                return False
            payload["overlay_logs_to_keep"] = numeric
            return True

        self._edit_debug_config(mutator)
        if numeric is None:
            LOGGER.info("Overlay log retention override cleared via preferences UI")
        else:
            LOGGER.info("Overlay log retention override set to %d via preferences UI", numeric)

    def set_payload_logging_exclusions(self, excludes: Sequence[str]) -> None:
        cleaned: List[str] = []
        seen: Set[str] = set()
        for item in excludes:
            token = str(item).strip().lower()
            if not token or token in seen:
                continue
            cleaned.append(token)
            seen.add(token)

        def mutator(payload: MutableMapping[str, Any]) -> bool:
            section = payload.get("payload_logging")
            if not isinstance(section, MutableMapping):
                section = {}
            normalized = dict(section)
            current = normalized.get("exclude_plugins")
            if isinstance(current, list) and [str(item).strip().lower() for item in current] == cleaned:
                payload["payload_logging"] = normalized
                return False
            normalized["exclude_plugins"] = cleaned
            payload["payload_logging"] = normalized
            return True

        self._edit_debug_config(mutator)
        LOGGER.info("Payload logging exclusions updated via preferences UI: %s", ", ".join(cleaned) or "<none>")

    def set_cycle_payload_preference(self, value: bool) -> None:
        flag = bool(value)
        with self._prefs_lock:
            if flag == self._preferences.cycle_payload_ids:
                return
            self._preferences.cycle_payload_ids = flag
            LOGGER.debug("Payload ID cycling %s", "enabled" if flag else "disabled")
            self._preferences.save()
        self._send_overlay_config()

    def set_cycle_payload_copy_preference(self, value: bool) -> None:
        flag = bool(value)
        with self._prefs_lock:
            if flag == self._preferences.copy_payload_id_on_cycle:
                return
            self._preferences.copy_payload_id_on_cycle = flag
            LOGGER.debug("Copy payload ID on cycle %s", "enabled" if flag else "disabled")
            self._preferences.save()
        self._send_overlay_config()

    def cycle_payload_prev(self) -> None:
        self._cycle_payload_step(-1)

    def cycle_payload_next(self) -> None:
        self._cycle_payload_step(1)

    def launch_overlay_controller(self) -> None:
        launch_controller(self, LOGGER)

    def _controller_python_command(self, overlay_env: Dict[str, str]) -> List[str]:
        override = os.getenv("EDMC_OVERLAY_CONTROLLER_PYTHON")
        if override:
            override_path = Path(override).expanduser()
            if override_path.exists():
                LOGGER.debug("Using controller Python from EDMC_OVERLAY_CONTROLLER_PYTHON=%s", override_path)
                return [str(override_path)]
            LOGGER.debug("EDMC_OVERLAY_CONTROLLER_PYTHON=%s not found; falling back to overlay client interpreter", override_path)

        candidate = self._locate_overlay_python(overlay_env)
        if candidate:
            LOGGER.debug("Using controller Python from overlay client environment: %s", candidate[0])
            return candidate
        raise RuntimeError(
            "No Python interpreter available to launch the Overlay Controller. "
            "Create overlay_client/.venv or set EDMC_OVERLAY_CONTROLLER_PYTHON."
        )

    def _overlay_controller_launch_sequence(self) -> None:
        controller_launch_sequence(self, LOGGER)

    def _controller_countdown(self) -> None:
        LOGGER.debug("Overlay Controller countdown started.")
        for remaining in (3, 2, 1):
            text = f"Overlay Controller opening in {remaining}... back out of comms panel now."
            self._emit_controller_message(text, ttl=1.25)
            time.sleep(1)
        LOGGER.debug("Overlay Controller countdown completed.")

    def _spawn_overlay_controller_process(
        self,
        python_command: List[str],
        launch_env: Dict[str, str],
        capture_output: bool,
    ) -> subprocess.Popen:
        module_name = "overlay_controller.overlay_controller"
        command = [*python_command, "-m", module_name]
        LOGGER.debug("Spawning Overlay Controller via %s", command)
        kwargs: Dict[str, Any] = {"cwd": str(self.plugin_dir), "env": launch_env}
        if os.name == "nt":
            creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            if creation_flags:
                kwargs["creationflags"] = creation_flags
        if capture_output:
            kwargs.update(
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
            )
        process = subprocess.Popen(command, **kwargs)
        LOGGER.debug("Overlay Controller launched via chat command (pid=%s)", getattr(process, "pid", "?"))
        return process

    def _emit_controller_message(self, text: str, ttl: Optional[float] = None, persistent: bool = False) -> None:
        payload = {
            "timestamp": datetime.now(UTC).isoformat(),
            "event": "LegacyOverlay",
            "type": "message",
            "id": self._controller_status_id,
            "text": text,
            "color": "#ff8c00",
            "x": 40,
            "y": 40,
            "size": "normal",
            "ttl": 0 if persistent else max(1.0, float(ttl or 2.0)),
        }
        self._publish_payload(payload)

    def _emit_controller_active_notice(self) -> None:
        pid = self._read_controller_pid_file()
        if pid is None:
            with self._controller_launch_lock:
                handle = self._controller_process
            if handle and handle.poll() is None:
                pid = handle.pid
        if pid is None:
            return
        self._emit_controller_message("Overlay Controller is Active", ttl=0, persistent=True)

    def _clear_controller_message(self) -> None:
        payload = {
            "timestamp": datetime.now(UTC).isoformat(),
            "event": "LegacyOverlay",
            "type": "legacy_clear",
            "id": self._controller_status_id,
            "ttl": 0,
        }
        self._publish_payload(payload)
        self._controller_active_group = None
        try:
            self._publish_payload({"event": "OverlayControllerActiveGroup", "plugin": "", "label": ""})
        except Exception:
            pass

    def _format_controller_output(self, stdout: str, stderr: str) -> str:
        def _format_stream(label: str, text: str) -> str:
            if not text or not text.strip():
                return f"{label}: <empty>"
            cleaned = text.rstrip("\n")
            return f"{label}:\n{cleaned}"

        return "\n".join((_format_stream("stdout", stdout), _format_stream("stderr", stderr)))

    def _read_controller_pid_file(self) -> Optional[int]:
        try:
            raw = self._controller_pid_path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            return None
        except OSError:
            return None
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None

    def _cleanup_controller_pid_file(self) -> None:
        try:
            self._controller_pid_path.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass

    def _terminate_controller_process(self) -> None:
        terminate_controller_process(self, LOGGER)

    def _cycle_payload_step(self, direction: int) -> None:
        if not self._running:
            raise RuntimeError("Overlay is not running")
        if not self._preferences.cycle_payload_ids:
            raise RuntimeError("Payload cycling is disabled")
        action = "prev" if direction < 0 else "next"
        payload = {
            "timestamp": datetime.now(UTC).isoformat(),
            "event": "OverlayCycle",
            "action": action,
        }
        self._publish_payload(payload)

    def restart_overlay_client(self) -> None:
        with self._lock:
            if not self._running:
                raise RuntimeError("Overlay is not running")
            watchdog = self.watchdog
        if watchdog is not None:
            LOGGER.debug("Stopping overlay client for user-requested restart")
            if not watchdog.stop():
                raise RuntimeError("Overlay client did not stop cleanly")
            with self._lock:
                if self.watchdog is watchdog:
                    self.watchdog = None
        if not self._start_watchdog():
            raise RuntimeError("Overlay client failed to start; check overlay logs for details")
        self._send_overlay_config(rebroadcast=True)
        _log("Overlay client restart triggered.")

    def reset_group_cache(self) -> bool:
        cache_path = self.plugin_dir / "overlay_group_cache.json"
        try:
            cache = GroupPlacementCache(cache_path, debounce_seconds=0.1, logger=LOGGER)
            cache.reset()
        except Exception as exc:
            LOGGER.warning("Failed to reset overlay group cache: %s", exc)
            return False
        try:
            self._publish_payload(
                {
                    "event": "OverlayGroupCacheReset",
                    "timestamp": datetime.now(UTC).isoformat(),
                }
            )
        except Exception:
            LOGGER.debug("Failed to notify overlay client about cache reset", exc_info=True)
        return True

    def set_min_font_preference(self, value: float) -> None:
        try:
            minimum = float(value)
        except (TypeError, ValueError):
            minimum = self._preferences.min_font_point
        minimum = max(1.0, min(minimum, 48.0))
        with self._prefs_lock:
            if minimum != self._preferences.min_font_point:
                if minimum > self._preferences.max_font_point:
                    self._preferences.max_font_point = minimum
                self._preferences.min_font_point = minimum
                LOGGER.debug("Overlay minimum font point set to %.1f", minimum)
                self._preferences.save()
                broadcast = True
            else:
                broadcast = False
        if broadcast:
            self._send_overlay_config()

    def set_max_font_preference(self, value: float) -> None:
        try:
            maximum = float(value)
        except (TypeError, ValueError):
            maximum = self._preferences.max_font_point
        maximum = max(self._preferences.min_font_point, min(maximum, 72.0))
        with self._prefs_lock:
            if maximum != self._preferences.max_font_point:
                self._preferences.max_font_point = maximum
                LOGGER.debug("Overlay maximum font point set to %.1f", maximum)
                self._preferences.save()
                broadcast = True
            else:
                broadcast = False
        if broadcast:
            self._send_overlay_config()

    def set_legacy_font_step_preference(self, value: int) -> None:
        try:
            step = int(value)
        except (TypeError, ValueError):
            step = int(getattr(self._preferences, "legacy_font_step", 2))
        step = max(0, min(step, 10))
        with self._prefs_lock:
            if step != getattr(self._preferences, "legacy_font_step", 2):
                self._preferences.legacy_font_step = step
                LOGGER.debug("Overlay legacy font step set to %d", step)
                self._preferences.save()
                broadcast = True
            else:
                broadcast = False
        if broadcast:
            self._send_overlay_config()

    def _publish_external(self, payload: Mapping[str, Any]) -> bool:
        if not self._running:
            return False
        original_payload = dict(payload)
        self._trace_payload_event("ingest:external_raw", original_payload)
        message = dict(original_payload)
        message.setdefault("cmdr", self._state.get("cmdr", ""))
        message.setdefault("system", self._state.get("system", ""))
        message.setdefault("station", self._state.get("station", ""))
        message.setdefault("docked", self._state.get("docked", False))
        message.setdefault("raw", original_payload)
        self._trace_payload_event("publish:prepared", message, {"source": "external"})
        self._publish_payload(message)
        return True

    def _start_legacy_tcp_server(self) -> None:
        if self._legacy_tcp_server is not None:
            return
        server = LegacyOverlayTCPServer(
            host="127.0.0.1",
            port=5010,
            log=_log,
            handler=self._handle_legacy_tcp_payload,
        )
        if server.start():
            self._legacy_tcp_server = server
            self._lifecycle.track_handle(server)
        else:
            self._legacy_tcp_server = None

    def _stop_legacy_tcp_server(self) -> None:
        server = self._legacy_tcp_server
        if not server:
            return
        try:
            server.stop()
        except Exception as exc:
            LOGGER.debug("Legacy overlay compatibility server shutdown error: %s", exc)
        self._legacy_tcp_server = None
        self._lifecycle.untrack_handle(server)

    def _update_overlay_metrics(self, payload: Mapping[str, Any]) -> None:
        width = _coerce_float(payload.get("width"))
        height = _coerce_float(payload.get("height"))
        if width is None or height is None or width <= 0 or height <= 0:
            return
        frame = payload.get("frame")
        scale = payload.get("scale")
        device_pixel_ratio = _coerce_float(payload.get("device_pixel_ratio")) or 1.0
        self._overlay_metrics = {
            "width": width,
            "height": height,
            "frame": dict(frame) if isinstance(frame, Mapping) else {},
            "scale": dict(scale) if isinstance(scale, Mapping) else {},
            "device_pixel_ratio": device_pixel_ratio,
        }
        LOGGER.debug(
            "Overlay metrics updated: width=%.1f height=%.1f scale=%s dpr=%.2f",
            width,
            height,
            self._overlay_metrics.get("scale", {}),
            device_pixel_ratio,
        )


    def _handle_legacy_tcp_payload(self, payload: Mapping[str, Any]) -> bool:
        if not self._running:
            return False
        raw_payload = dict(payload)
        self._trace_payload_event("legacy_tcp:received", raw_payload)
        normalised = normalise_legacy_payload(raw_payload)
        if normalised is None:
            self._trace_payload_event("legacy_tcp:dropped", raw_payload, {"reason": "normalise_failed"})
            LOGGER.debug("Legacy overlay payload dropped (unable to normalise): %s", raw_payload)
            return False
        message: Dict[str, Any] = {
            "event": "LegacyOverlay",
            **normalised,
            "legacy_raw": raw_payload,
        }
        message.setdefault("timestamp", datetime.now(UTC).isoformat())
        self._trace_payload_event(
            "legacy_tcp:normalised",
            message,
            {
                "raw_shape": raw_payload.get("shape"),
                "raw_type": raw_payload.get("type"),
            },
        )
        return self._publish_external(message)

    def _handle_cli_payload(self, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        try:
            if not isinstance(payload, Mapping):
                raise ValueError("Payload must be an object")
            command = payload.get("cli")
            if command in ("overlay_controller", "overlay_config"):
                config_payload = payload.get("config")
                if not isinstance(config_payload, Mapping):
                    raise ValueError("Overlay config payload missing 'config' object")
                applied = False
                if (
                    "title_bar_enabled" in config_payload
                    or "title_bar_compensation" in config_payload
                    or "title_bar_height" in config_payload
                ):
                    enabled_raw = config_payload.get("title_bar_enabled")
                    if enabled_raw is None and "title_bar_compensation" in config_payload:
                        enabled_raw = config_payload.get("title_bar_compensation")
                    if enabled_raw is None:
                        enabled_flag = self._preferences.title_bar_enabled
                    else:
                        enabled_flag = bool(enabled_raw)
                    height_value = config_payload.get("title_bar_height", self._preferences.title_bar_height)
                    self._submit_pref_task(
                        lambda: self.set_title_bar_compensation_preference(enabled_flag, height_value),
                        wait=True,
                    )
                    applied = True
                if not applied:
                    raise ValueError("Overlay config payload did not include any recognised directives")
                return {"status": "ok"}
            if command == "force_render_override":
                preferences = self._preferences
                if preferences is None:
                    raise RuntimeError("Preferences are not initialised; cannot apply force-render override")
                if "force_render" not in payload:
                    raise ValueError("force_render_override payload requires 'force_render'")
                desired_force = bool(payload.get("force_render"))

                def _apply_force_override() -> Tuple[bool, bool]:
                    with self._prefs_lock:
                        previous_override = bool(self._controller_force_render_override)
                        if desired_force == previous_override:
                            return previous_override, False
                        self._controller_force_render_override = desired_force
                        return previous_override, True

                previous_override, broadcast = self._submit_pref_task(
                    _apply_force_override,
                    wait=True,
                )
                if desired_force:
                    self._start_force_render_monitor_if_needed()
                if broadcast:
                    self._send_overlay_config()
                return {
                    "status": "ok",
                    "force_render": self._resolve_force_render(),
                    "previous_force_render": previous_override,
                    "force_render_override": bool(self._controller_force_render_override),
                }
            if command == "legacy_overlay":
                legacy_payload = payload.get("payload")
                if not isinstance(legacy_payload, Mapping):
                    raise ValueError("Legacy overlay payload missing 'payload' object")
                message = dict(legacy_payload)
                message.setdefault("event", "LegacyOverlay")
                message.setdefault("timestamp", datetime.now(UTC).isoformat())
                payload_type = str(message.get("type") or "message").lower()
                if payload_type == "message":
                    raw_text = message.get("text")
                    text = str(raw_text or "").strip()
                    if not text:
                        LOGGER.debug(
                            "Ignoring empty LegacyOverlay message text for payload id=%s",
                            message.get("id"),
                        )
                        text = ""
                    message["type"] = "message"
                    message["text"] = text
                elif payload_type == "shape":
                    shape_name = str(message.get("shape") or "").strip().lower()
                    if not shape_name:
                        raise ValueError("LegacyOverlay shape payload requires 'shape'")
                    message["type"] = "shape"
                    message["shape"] = shape_name
                    if shape_name == "vect":
                        vector = message.get("vector")
                        if not isinstance(vector, list) or len(vector) < 2:
                            raise ValueError("Vector shape payload requires a 'vector' list with at least two points")
                else:
                    raise ValueError(f"Unsupported LegacyOverlay payload type: {payload_type}")
                self._trace_payload_event("cli:legacy_overlay", message)
                self._publish_payload(message)
                return {"status": "ok"}
            if command == "overlay_metrics":
                self._update_overlay_metrics(payload)
                return {"status": "ok"}
            if command == "controller_heartbeat":
                self._emit_controller_active_notice()
                return {"status": "ok"}
            if command == "controller_active_group":
                plugin_name_raw = payload.get("plugin")
                label_raw = payload.get("label")
                plugin_name = str(plugin_name_raw or "").strip()
                label = str(label_raw or "").strip()
                anchor_raw = payload.get("anchor")
                anchor_token = str(anchor_raw or "").strip().lower() if anchor_raw is not None else ""
                edit_nonce = str(payload.get("edit_nonce") or "").strip()
                if plugin_name and label:
                    self._controller_active_group = (plugin_name, label)
                else:
                    self._controller_active_group = None
                message = {
                    "event": "OverlayControllerActiveGroup",
                    "plugin": plugin_name,
                    "label": label,
                    "anchor": anchor_token,
                    "edit_nonce": edit_nonce,
                    "timestamp": datetime.now(UTC).isoformat(),
                }
                self._publish_payload(message)
                return {"status": "ok"}
            if command == "controller_override_reload":
                nonce_raw = payload.get("nonce")
                nonce = str(nonce_raw).strip() if nonce_raw is not None else ""
                if nonce and nonce == getattr(self, "_last_override_reload_nonce", None):
                    LOGGER.debug("Controller override reload ignored (duplicate nonce=%s)", nonce)
                    return {"status": "ok", "duplicate": True}
                self._last_override_reload_nonce = nonce or self._last_override_reload_nonce
                message = {
                    "event": "OverlayOverrideReload",
                    "nonce": nonce,
                    "timestamp": datetime.now(UTC).isoformat(),
                }
                self._publish_payload(message)
                LOGGER.debug("Controller override reload dispatched (nonce=%s)", nonce or "none")
                return {"status": "ok"}
            if command == "controller_overrides_payload":
                overrides = payload.get("overrides")
                nonce_raw = payload.get("nonce")
                nonce = str(nonce_raw).strip() if nonce_raw is not None else ""
                if not isinstance(overrides, Mapping):
                    raise ValueError("Overrides payload must be an object")
                message = {
                    "event": "OverlayOverridesPayload",
                    "overrides": overrides,
                    "nonce": nonce,
                    "timestamp": datetime.now(UTC).isoformat(),
                }
                self._publish_payload(message)
                LOGGER.debug("Controller overrides payload dispatched (nonce=%s)", nonce or "none")
                return {"status": "ok"}
            if command == "test_message":
                text = str(payload.get("message") or "").strip()
                if not text:
                    raise ValueError("Test message text is empty")
                x = payload.get("x")
                y = payload.get("y")
                self.send_test_message(text, x=x, y=y)
                return {"status": "ok"}
            raise ValueError(f"Unsupported CLI command: {command!r}")
        except Exception as exc:
            _log(f"CLI payload rejected: {exc}")
            return {"status": "error", "error": str(exc)}


    def _send_overlay_config(self, rebroadcast: bool = False) -> None:
        self._load_payload_debug_config()
        diagnostics_enabled = _diagnostic_logging_enabled()
        show_debug_overlay = bool(self._preferences.show_debug_overlay and diagnostics_enabled)
        payload = {
            "event": "OverlayConfig",
            "opacity": float(self._preferences.overlay_opacity),
            "global_payload_opacity": int(getattr(self._preferences, "global_payload_opacity", 100)),
            "show_status": bool(self._preferences.show_connection_status),
            "debug_overlay_corner": str(self._preferences.debug_overlay_corner or "NW"),
            "status_bottom_margin": int(self._preferences.status_bottom_margin()),
            "client_log_retention": int(self._resolve_client_log_retention()),
            "gridlines_enabled": bool(self._preferences.gridlines_enabled),
            "gridline_spacing": int(self._preferences.gridline_spacing),
            "force_render": self._resolve_force_render(),
            "title_bar_enabled": bool(self._preferences.title_bar_enabled),
            "title_bar_height": int(self._preferences.title_bar_height),
            "show_debug_overlay": show_debug_overlay,
            "physical_clamp_enabled": bool(getattr(self._preferences, "physical_clamp_enabled", False)),
            "physical_clamp_overrides": dict(getattr(self._preferences, "physical_clamp_overrides", {}) or {}),
            "min_font_point": float(self._preferences.min_font_point),
            "max_font_point": float(self._preferences.max_font_point),
            "legacy_font_step": int(getattr(self._preferences, "legacy_font_step", 2)),
            "cycle_payload_ids": bool(self._preferences.cycle_payload_ids),
            "copy_payload_id_on_cycle": bool(self._preferences.copy_payload_id_on_cycle),
            "scale_mode": str(self._preferences.scale_mode or "fit"),
            "nudge_overflow_payloads": bool(self._preferences.nudge_overflow_payloads),
            "payload_nudge_gutter": int(self._preferences.payload_nudge_gutter),
            "payload_log_delay_seconds": float(getattr(self._preferences, "payload_log_delay_seconds", 0.0)),
            "platform_context": self._platform_context_payload(),
        }
        self._last_config = dict(payload)
        self._publish_payload(payload)
        LOGGER.debug(
            "Published overlay config: opacity=%s global_payload_opacity=%s show_status=%s debug_overlay_corner=%s status_bottom_margin=%s client_log_retention=%d gridlines_enabled=%s "
            "gridline_spacing=%d force_render=%s title_bar_enabled=%s title_bar_height=%d debug_overlay=%s physical_clamp=%s cycle_payload_ids=%s copy_payload_id_on_cycle=%s "
            "nudge_overflow=%s payload_gutter=%d payload_log_delay=%.2f font_min=%.1f font_max=%.1f font_step=%d platform_context=%s clamp_overrides=%s",
            payload["opacity"],
            payload["global_payload_opacity"],
            payload["show_status"],
            payload["debug_overlay_corner"],
            payload["status_bottom_margin"],
            payload["client_log_retention"],
            payload["gridlines_enabled"],
            payload["gridline_spacing"],
            payload["force_render"],
            payload["title_bar_enabled"],
            payload["title_bar_height"],
            payload["show_debug_overlay"],
            payload["physical_clamp_enabled"],
            payload["cycle_payload_ids"],
            payload["copy_payload_id_on_cycle"],
            payload["nudge_overflow_payloads"],
            payload["payload_nudge_gutter"],
            payload["payload_log_delay_seconds"],
            payload["min_font_point"],
            payload["max_font_point"],
            payload["legacy_font_step"],
            payload["platform_context"],
            payload["physical_clamp_overrides"],
        )
        if rebroadcast:
            self._schedule_config_rebroadcasts()

    def _publish_payload(self, payload: Mapping[str, Any]) -> None:
        message = dict(payload)
        self._trace_payload_event("publish:dispatch", message)
        self._log_payload(message)
        self.broadcaster.publish(dict(message))
        self._trace_payload_event("publish:sent", message)

    def _load_plugin_prefix_map(self) -> Dict[str, str]:
        config_path = self.plugin_dir / "overlay_groupings.json"
        try:
            raw_text = config_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return {}
        except OSError:
            return {}
        try:
            data = json.loads(raw_text)
        except json.JSONDecodeError:
            return {}
        if not isinstance(data, Mapping):
            return {}
        prefixes: Dict[str, str] = {}

        def _extend_prefix_map(entries: Iterable[str], plugin_label: str) -> None:
            for entry in entries:
                token = entry.strip()
                if token:
                    prefixes[token] = plugin_label

        def _normalise_prefix_iter(raw: Any) -> Iterable[str]:
            def _extract_value(entry: Any) -> Optional[str]:
                if isinstance(entry, str):
                    token = entry.strip()
                    return token if token else None
                if isinstance(entry, Mapping):
                    raw_value = entry.get("value") or entry.get("prefix")
                    if isinstance(raw_value, str):
                        token = raw_value.strip()
                        return token if token else None
                return None

            if isinstance(raw, (str, Mapping)):
                candidate = _extract_value(raw)
                return [candidate] if candidate else []
            if isinstance(raw, Iterable) and not isinstance(raw, (str, bytes)):
                results: list[str] = []
                for item in raw:
                    value = _extract_value(item)
                    if value:
                        results.append(value)
                return results
            return []

        for plugin_name, config in data.items():
            if not isinstance(plugin_name, str) or not isinstance(config, Mapping):
                continue

            matching = config.get("matchingPrefixes")
            candidates = list(_normalise_prefix_iter(matching))
            if not candidates:
                legacy_match = config.get("__match__")
                if isinstance(legacy_match, Mapping):
                    candidates.extend(_normalise_prefix_iter(legacy_match.get("id_prefixes")))
            if not candidates:
                # Fall back to prefixes declared under groups for legacy files
                groups_block = config.get("idPrefixGroups")
                if isinstance(groups_block, Mapping):
                    for spec in groups_block.values():
                        if isinstance(spec, Mapping):
                            candidates.extend(_normalise_prefix_iter(spec.get("idPrefixes") or spec.get("id_prefixes")))
                legacy_grouping = config.get("grouping")
                if isinstance(legacy_grouping, Mapping):
                    raw_groups = legacy_grouping.get("groups")
                    if isinstance(raw_groups, Mapping):
                        for spec in raw_groups.values():
                            if isinstance(spec, Mapping):
                                candidates.extend(_normalise_prefix_iter(spec.get("id_prefixes")))

            _extend_prefix_map(candidates, plugin_name)

        return prefixes

    def _plugin_name_for_payload(self, payload: Mapping[str, Any]) -> Tuple[Optional[str], Optional[str]]:
        if not isinstance(payload, Mapping):
            return None, None

        def _extract_plugin(mapping: Mapping[str, Any]) -> Optional[str]:
            for key in ("plugin", "plugin_name", "source_plugin"):
                value = mapping.get(key)
                if isinstance(value, str) and value:
                    token = value.strip()
                    if token:
                        return token
            return None

        def _extract_id(mapping: Mapping[str, Any]) -> Optional[str]:
            value = mapping.get("id")
            if isinstance(value, str):
                token = value.strip()
                if token:
                    return token
            return None

        plugin_name = _extract_plugin(payload)
        payload_id = _extract_id(payload)

        if plugin_name:
            return plugin_name, payload_id

        for key in ("meta", "raw", "legacy_raw"):
            nested = payload.get(key)
            if isinstance(nested, Mapping):
                candidate = _extract_plugin(nested)
                if candidate:
                    plugin_name = candidate
                if not payload_id:
                    payload_id = _extract_id(nested)
                if plugin_name:
                    return plugin_name, payload_id

        if payload_id:
            for prefix, mapped_name in self._plugin_prefix_map.items():
                if payload_id.startswith(prefix):
                    return mapped_name, payload_id
            prefix_guess = payload_id.split("-", 1)[0]
            if prefix_guess:
                return prefix_guess, payload_id

        return None, payload_id

    def _should_trace_payload(self, plugin_name: Optional[str], payload_id: Optional[str]) -> bool:
        if not self._trace_enabled:
            return False
        if self._trace_payload_prefixes:
            identifier = payload_id or ""
            if not any(identifier.startswith(prefix) for prefix in self._trace_payload_prefixes):
                return False
        return True

    def _trace_payload_event(
        self,
        stage: str,
        payload: Mapping[str, Any],
        extra: Optional[Mapping[str, Any]] = None,
    ) -> None:
        if not self._trace_enabled:
            return
        plugin_name, payload_id = self._plugin_name_for_payload(payload)
        if not self._should_trace_payload(plugin_name, payload_id):
            return
        info: Dict[str, Any] = {}
        event_name = payload.get("event")
        payload_type = payload.get("type")
        if isinstance(event_name, str) and event_name:
            info["event"] = event_name
        if isinstance(payload_type, str) and payload_type:
            info["type"] = payload_type
        if extra:
            for key, value in extra.items():
                info[key] = value
        LOGGER.debug(
            "trace plugin=%s id=%s stage=%s info=%s",
            plugin_name or "unknown",
            payload_id or "",
            stage,
            info,
        )

    def _log_payload(self, payload: Mapping[str, Any]) -> None:
        event: Optional[str] = None
        if isinstance(payload, Mapping):
            raw_event = payload.get("event")
            if isinstance(raw_event, str) and raw_event:
                event = raw_event
        try:
            serialised = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        except (TypeError, ValueError):
            serialised = repr(payload)
        logger = self._payload_logger if self._payload_log_handler is not None else LOGGER
        self._load_payload_debug_config()
        if not self._payload_logging_enabled or not _diagnostic_logging_enabled():
            return
        plugin_name, payload_id = self._plugin_name_for_payload(payload)
        if self._payload_filter_excludes and plugin_name and plugin_name.lower() in self._payload_filter_excludes:
            return
        log_method = logger.debug
        if event:
            if plugin_name:
                log_method("Overlay payload [%s] plugin=%s: %s", event, plugin_name, serialised)
            else:
                log_method("Overlay payload [%s]: %s", event, serialised)
        else:
            if plugin_name:
                log_method("Overlay payload plugin=%s: %s", plugin_name, serialised)
            else:
                log_method("Overlay payload: %s", serialised)
        legacy_raw = None
        if isinstance(payload, Mapping):
            legacy_raw = payload.get("legacy_raw")
        if legacy_raw is not None:
            try:
                legacy_serialised = json.dumps(legacy_raw, ensure_ascii=False, sort_keys=True)
            except (TypeError, ValueError):
                legacy_serialised = repr(legacy_raw)
            legacy_plugin, _ = self._plugin_name_for_payload(legacy_raw)
            if not legacy_plugin:
                legacy_plugin = plugin_name
            if legacy_plugin:
                log_method("Overlay legacy_raw plugin=%s: %s", legacy_plugin, legacy_serialised)
            else:
                log_method("Overlay legacy_raw: %s", legacy_serialised)

    def _locate_overlay_python(self, overlay_env: Optional[Dict[str, str]] = None) -> Optional[List[str]]:
        env_override = os.getenv("EDMC_OVERLAY_PYTHON")
        if env_override:
            override_path = Path(env_override).expanduser()
            if override_path.exists():
                LOGGER.debug("Using overlay Python from EDMC_OVERLAY_PYTHON=%s", override_path)
                return [str(override_path)]
            LOGGER.debug("Overlay Python override %s not found, falling back", override_path)

        if self._flatpak_context.get("is_flatpak"):
            command = self._flatpak_host_command(overlay_env)
            if command:
                return command

        overlay_client_root = self.plugin_dir / "overlay_client"
        venv_path = (
            overlay_client_root
            / ".venv"
            / ("Scripts" if os.name == "nt" else "bin")
            / ("python.exe" if os.name == "nt" else "python")
        )
        if venv_path.exists():
            LOGGER.debug("Using overlay client Python interpreter at %s", venv_path)
            return [str(venv_path)]

        return None

    def _flatpak_host_command(self, overlay_env: Optional[Dict[str, str]]) -> Optional[List[str]]:
        spawn_path = shutil.which("flatpak-spawn")
        if not spawn_path:
            if not self._flatpak_spawn_warning_emitted:
                LOGGER.warning("Flatpak detected but flatpak-spawn binary not found; cannot launch overlay outside sandbox.")
                self._flatpak_spawn_warning_emitted = True
            return None
        host_python = self._flatpak_host_python_path()
        if host_python is None:
            if not self._flatpak_host_warning_emitted:
                LOGGER.warning(
                    "Flatpak detected but no host Python interpreter found. Ensure overlay_client/.venv exists (or set EDMC_OVERLAY_HOST_PYTHON) with the overlay dependencies."
                )
                self._flatpak_host_warning_emitted = True
            return None
        LOGGER.info("Launching overlay client via flatpak-spawn host interpreter at %s", host_python)
        env_args = self._flatpak_env_arguments(overlay_env)
        return [spawn_path, "--host", *env_args, host_python]

    def _flatpak_python_command(self, overlay_env: Optional[Dict[str, str]]) -> Optional[List[str]]:
        """Compat shim for legacy callers; delegates to _flatpak_host_command."""
        return self._flatpak_host_command(overlay_env)

    def _flatpak_env_arguments(self, overlay_env: Optional[Dict[str, str]]) -> List[str]:
        args: List[str] = []
        if not overlay_env:
            return args
        for key in FLATPAK_ENV_FORWARD_KEYS:
            value = overlay_env.get(key)
            if value in (None, ""):
                continue
            args.append(f"--env={key}={value}")
        return args

    def _flatpak_host_python_path(self) -> Optional[str]:
        env_override = os.getenv("EDMC_OVERLAY_HOST_PYTHON")
        if env_override:
            override_path = Path(env_override).expanduser()
            if override_path.exists():
                return str(override_path)
            LOGGER.debug("EDMC_OVERLAY_HOST_PYTHON=%s does not exist; ignoring override", override_path)
        candidate_dirs: Sequence[Path] = (
            self.plugin_dir / "overlay_client" / ".venv" / "bin",
            self.plugin_dir / "overlay_client" / ".venv" / "Scripts",
        )
        for directory in candidate_dirs:
            for name in ("python3", "python"):
                candidate = directory / name
                if candidate.exists():
                    return str(candidate)
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

    def _detect_flatpak_context(self) -> Dict[str, Any]:
        env = os.environ
        flatpak_id = env.get("FLATPAK_ID") or env.get("container_app")
        is_flatpak = bool(flatpak_id or env.get("container") == "flatpak")
        plugin_path = self.plugin_dir
        try:
            resolved = plugin_path.resolve()
        except Exception:
            resolved = plugin_path
        var_app_root = Path.home() / ".var" / "app"
        try:
            relative = resolved.relative_to(var_app_root)
        except ValueError:
            relative = None
        if relative is not None:
            is_flatpak = True
            if not flatpak_id and relative.parts:
                flatpak_id = relative.parts[0]
        context: Dict[str, object] = {"is_flatpak": is_flatpak}
        if flatpak_id:
            context["app_id"] = flatpak_id
        return context

    def _build_overlay_environment(self) -> Dict[str, str]:
        env = dict(os.environ)
        session = (env.get("XDG_SESSION_TYPE") or "").lower()
        compositor = self._detect_wayland_compositor()
        force_xwayland = bool(self._preferences.force_xwayland)
        log_level_payload = self._build_log_level_payload()
        env["EDMC_OVERLAY_LOG_LEVEL"] = str(log_level_payload.get("value"))
        log_level_name = log_level_payload.get("name") or logging.getLevelName(logging.INFO)
        env["EDMC_OVERLAY_LOG_LEVEL_NAME"] = str(log_level_name)
        env["EDMC_OVERLAY_SESSION_TYPE"] = session or "unknown"
        env["EDMC_OVERLAY_COMPOSITOR"] = compositor
        env["EDMC_OVERLAY_FORCE_XWAYLAND"] = "1" if force_xwayland else "0"
        env["EDMC_OVERLAY_IS_FLATPAK"] = "1" if self._flatpak_context.get("is_flatpak") else "0"
        app_id = self._flatpak_context.get("app_id")
        if app_id:
            env["EDMC_OVERLAY_FLATPAK_ID"] = str(app_id)
        if sys.platform.startswith("linux"):
            if session == "wayland" and not force_xwayland:
                env.setdefault("QT_QPA_PLATFORM", "wayland")
                env.setdefault("QT_WAYLAND_DISABLE_WINDOWDECORATION", "1")
                env.setdefault("QT_WAYLAND_LAYER_SHELL", "1")
            else:
                env["QT_QPA_PLATFORM"] = env.get("QT_QPA_PLATFORM", "xcb")
                env.setdefault("QT_WAYLAND_DISABLE_WINDOWDECORATION", "1")
        try:
            overrides_path = self.plugin_dir / "overlay_client" / "env_overrides.json"
            overrides_payload = env_overrides_helper.load_overrides(overrides_path)
            merge_result = env_overrides_helper.apply_overrides(env, overrides_payload, logger=LOGGER)
            if merge_result.applied:
                applied_pairs = [
                    f"{key}={merge_result.applied_values.get(key, env.get(key, ''))}"
                    for key in merge_result.applied
                ]
                LOGGER.info(
                    "Applied overlay env overrides (%s): %s",
                    overrides_path,
                    ", ".join(applied_pairs),
                )
            if merge_result.skipped_env or merge_result.skipped_existing:
                LOGGER.debug(
                    "Skipped env overrides from %s; env=%s existing=%s",
                    overrides_path,
                    ", ".join(merge_result.skipped_env) if merge_result.skipped_env else "none",
                    ", ".join(merge_result.skipped_existing) if merge_result.skipped_existing else "none",
                )
            if merge_result.applied or merge_result.skipped_env or merge_result.skipped_existing:
                env["EDMC_OVERLAY_ENV_OVERRIDES_APPLIED"] = ",".join(merge_result.applied)
                env["EDMC_OVERLAY_ENV_OVERRIDES_SKIPPED_ENV"] = ",".join(merge_result.skipped_env)
                env["EDMC_OVERLAY_ENV_OVERRIDES_SKIPPED_EXISTING"] = ",".join(merge_result.skipped_existing)
        except Exception as exc:
            LOGGER.debug("Failed to apply env overrides: %s", exc)
        return env

    def _overlay_controller_active(self) -> bool:
        try:
            import psutil  # type: ignore
        except Exception:
            psutil = None  # type: ignore
        if psutil is not None:
            try:
                for proc in psutil.process_iter(["name", "cmdline"]):
                    cmdline = proc.info.get("cmdline") or []
                    for token in cmdline:
                        name = os.path.basename(token)
                        token_l = token.lower()
                        if (
                            name.lower() == "overlay_controller.py"
                            or name.lower().endswith("/overlay_controller.py")
                            or "overlay_controller.overlay_controller" in token_l
                        ):
                            return True
                # Fallback: check process names when cmdline is unavailable.
                for proc in psutil.process_iter(["name"]):
                    name = (proc.info.get("name") or "").lower()
                    if "overlay_controller" in name:
                        return True
            except Exception:
                pass
        try:
            output = subprocess.check_output(["ps", "-eo", "cmd"], text=True, stderr=subprocess.DEVNULL)
        except Exception:
            output = ""
        for line in output.splitlines():
            token = line.strip().lower()
            if "overlay_controller.py" in token or "overlay_controller.overlay_controller" in token:
                return True
        return False

    def _platform_context_payload(self) -> Dict[str, Any]:
        session = (os.environ.get("XDG_SESSION_TYPE") or "").lower()
        context = {
            "session_type": session or "unknown",
            "compositor": self._detect_wayland_compositor(),
            "force_xwayland": bool(self._preferences.force_xwayland),
        }
        if self._flatpak_context.get("is_flatpak"):
            context["flatpak"] = True
            if self._flatpak_context.get("app_id"):
                context["flatpak_app"] = self._flatpak_context["app_id"]
        return context

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
                f"{PLUGIN_NAME}-legacy-overlay-conflict",
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
        schedule_config_rebroadcasts(
            rebroadcast_fn=self._rebroadcast_last_config,
            timers=self._config_timers,
            timer_lock=self._config_timer_lock,
            count=count,
            interval=interval,
            logger=LOGGER,
        )

    def _rebroadcast_last_config(self) -> None:
        rebroadcast_last_config(
            is_running=lambda: self._running,
            last_config_provider=lambda: self._last_config,
            publish_payload=self._publish_payload,
        )

    def _cancel_config_timers(self) -> None:
        cancel_config_timers(self._config_timers, self._config_timer_lock, LOGGER)


# EDMC hook functions ------------------------------------------------------

_plugin: Optional[_PluginRuntime] = None
_preferences: Optional[Preferences] = None
_prefs_panel: Optional[PreferencesPanel] = None


def plugin_start3(plugin_dir: str) -> str:
    """EDMC entrypoint: initialise plugin and start runtime once."""
    _log(f"Initialising Modern Overlay plugin from {plugin_dir}")
    global _plugin, _preferences
    _preferences = Preferences(Path(plugin_dir), dev_mode=DEV_BUILD)
    _plugin = _PluginRuntime(plugin_dir, _preferences)
    return _plugin.start()


def plugin_stop() -> None:
    """EDMC entrypoint: stop plugin safely; idempotent if not running."""
    global _prefs_panel, _plugin, _preferences
    if _plugin:
        try:
            _plugin.stop()
        finally:
            _plugin = None
    _prefs_panel = None
    _preferences = None


def plugin_app(parent) -> Optional[Any]:  # pragma: no cover - EDMC Tk frame hook
    """EDMC entrypoint: build preferences panel for EDMC UI."""
    return None


def plugin_prefs(parent, cmdr: str, is_beta: bool):  # pragma: no cover - optional settings pane
    LOGGER.debug("plugin_prefs invoked: parent=%r cmdr=%r is_beta=%s", parent, cmdr, is_beta)
    if _preferences is None:
        LOGGER.debug("Preferences not initialised; returning no UI")
        return None
    send_callback = _plugin.send_test_message if _plugin else None
    opacity_callback = _plugin.preview_overlay_opacity if _plugin else None
    version_status = _plugin.get_version_status() if _plugin else None
    version_update_available = bool(version_status.update_available) if version_status else False
    diagnostics_state = TroubleshootingPanelState(
        diagnostics_enabled=_diagnostic_logging_enabled(),
        capture_enabled=False,
        log_retention_override=None,
        exclude_plugins=(),
    )
    try:
        status_callback = _plugin.set_show_status_preference if _plugin else None
        status_gutter_callback = _plugin.set_status_gutter_preference if _plugin else None
        debug_corner_callback = _plugin.set_debug_overlay_corner_preference if _plugin else None
        gridlines_enabled_callback = _plugin.set_gridlines_enabled_preference if _plugin else None
        gridline_spacing_callback = _plugin.set_gridline_spacing_preference if _plugin else None
        payload_nudge_callback = _plugin.set_payload_nudge_preference if _plugin else None
        payload_gutter_callback = _plugin.set_payload_nudge_gutter_preference if _plugin else None
        force_render_callback = _plugin.set_force_render_preference if _plugin else None
        title_bar_config_callback = _plugin.set_title_bar_compensation_preference if _plugin else None
        debug_overlay_callback = _plugin.set_debug_overlay_preference if _plugin else None
        payload_logging_callback = _plugin.set_payload_logging_preference if _plugin else None
        font_min_callback = _plugin.set_min_font_preference if _plugin else None
        font_max_callback = _plugin.set_max_font_preference if _plugin else None
        font_step_callback = _plugin.set_legacy_font_step_preference if _plugin else None
        font_preview_callback = _plugin.preview_font_sizes if _plugin else None
        cycle_toggle_callback = _plugin.set_cycle_payload_preference if _plugin else None
        cycle_copy_callback = _plugin.set_cycle_payload_copy_preference if _plugin else None
        cycle_prev_callback = _plugin.cycle_payload_prev if _plugin else None
        cycle_next_callback = _plugin.cycle_payload_next if _plugin else None
        restart_overlay_callback = _plugin.restart_overlay_client if _plugin else None
        launch_command_callback = _plugin.set_launch_command_preference if _plugin else None
        payload_opacity_callback = _plugin.set_payload_opacity_preference if _plugin else None
        reset_group_cache_callback = _plugin.reset_group_cache if _plugin else None
        capture_override_callback = _plugin.set_capture_override_preference if _plugin else None
        log_retention_override_callback = _plugin.set_log_retention_override_preference if _plugin else None
        payload_exclusion_callback = _plugin.set_payload_logging_exclusions if _plugin else None
        if _plugin:
            diagnostics_state = _plugin.get_troubleshooting_panel_state()
        if launch_command_callback:
            LOGGER.debug("Attaching launch command callback with initial value=%s", _preferences.controller_launch_command)
        panel = PreferencesPanel(
            parent,
            _preferences,
            send_callback,
            opacity_callback,
            status_callback,
            status_gutter_callback,
            debug_corner_callback,
            gridlines_enabled_callback,
            gridline_spacing_callback,
            payload_nudge_callback,
            payload_gutter_callback,
            force_render_callback,
            title_bar_config_callback,
            debug_overlay_callback,
            payload_logging_callback,
            font_min_callback,
            font_max_callback,
            font_step_callback,
            font_preview_callback,
            cycle_toggle_callback,
            cycle_copy_callback,
            cycle_prev_callback,
            cycle_next_callback,
            restart_overlay_callback,
            launch_command_callback,
            payload_opacity_callback,
            reset_group_cache_callback=reset_group_cache_callback,
            dev_mode=DEV_BUILD,
            plugin_version=MODERN_OVERLAY_VERSION,
            version_update_available=version_update_available,
            troubleshooting_state=diagnostics_state,
            set_capture_override_callback=capture_override_callback,
            set_log_retention_override_callback=log_retention_override_callback,
            set_payload_exclusion_callback=payload_exclusion_callback,
            payload_logging_initial=_plugin._payload_logging_enabled if _plugin else None,
        )
    except Exception as exc:
        LOGGER.exception("Failed to build preferences panel: %s", exc)
        return None
    global _prefs_panel
    _prefs_panel = panel
    frame = panel.frame
    LOGGER.debug("plugin_prefs returning frame=%r", frame)
    return frame


def get_version_status() -> Optional[VersionStatus]:
    """Expose the cached upstream version status for other integrations."""

    if _plugin is None:
        return None
    return _plugin.get_version_status()


def prefs_changed(cmdr: str, is_beta: bool) -> None:  # pragma: no cover - save hook
    LOGGER.debug("prefs_changed invoked: cmdr=%r is_beta=%s", cmdr, is_beta)
    if _prefs_panel is None:
        LOGGER.debug("No preferences panel to save")
        return
    try:
        _prefs_panel.apply()
        if _preferences:
            LOGGER.debug(
                "Preferences saved: show_connection_status=%s "
                "client_log_retention=%d gridlines_enabled=%s gridline_spacing=%d "
                "force_render=%s title_bar_enabled=%s title_bar_height=%d force_xwayland=%s "
                "debug_overlay=%s cycle_payload_ids=%s copy_payload_id_on_cycle=%s font_min=%.1f font_max=%.1f",
                _preferences.show_connection_status,
                _plugin._resolve_client_log_retention() if _plugin else _preferences.client_log_retention,
                _preferences.gridlines_enabled,
                _preferences.gridline_spacing,
                _plugin._resolve_force_render() if _plugin else bool(getattr(_preferences, "force_render", False)),
                _preferences.title_bar_enabled,
                _preferences.title_bar_height,
                _preferences.force_xwayland,
                _preferences.show_debug_overlay,
                _preferences.cycle_payload_ids,
                _preferences.copy_payload_id_on_cycle,
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
plugin_name = PLUGIN_NAME
version = PLUGIN_VERSION
cmdr = ""
