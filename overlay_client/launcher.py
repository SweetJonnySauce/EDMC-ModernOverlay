from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

import json
import logging

from PyQt6.QtWidgets import QApplication

from overlay_client.client_config import InitialClientSettings, load_initial_settings
from overlay_client.data_client import OverlayDataClient
from overlay_client.debug_config import DEBUG_CONFIG_ENABLED, load_dev_settings, load_troubleshooting_config
from overlay_client.developer_helpers import DeveloperHelperController
from overlay_client.overlay_client import CLIENT_DIR, DEV_MODE_ENV_VAR, OverlayWindow, _CLIENT_LOGGER, apply_log_level_hint
from overlay_client.window_tracking import create_elite_window_tracker


def resolve_port_file(args_port: Optional[str]) -> Path:
    if args_port:
        return Path(args_port).expanduser().resolve()
    env_override = os.getenv("EDMC_OVERLAY_PORT_FILE")
    if env_override:
        return Path(env_override).expanduser().resolve()
    return (Path(__file__).resolve().parent.parent / "port.json").resolve()


def _diagnostics_enabled(initial: InitialClientSettings) -> bool:
    if DEBUG_CONFIG_ENABLED:
        return True
    level = initial.edmc_log_level
    if level is None:
        return False
    try:
        numeric = int(level)
    except (TypeError, ValueError):
        return False
    return numeric <= logging.DEBUG


def resolve_log_level_hint(port_file: Path) -> tuple[Optional[int], Optional[str], str]:
    def _clean_name(value: Any) -> Optional[str]:
        if value is None:
            return None
        try:
            text = str(value).strip()
        except Exception:
            return None
        return text or None

    def _coerce_level(value: Any, name: Any) -> tuple[Optional[int], Optional[str]]:
        numeric = None
        try:
            numeric = int(value) if value is not None else None
        except (TypeError, ValueError):
            numeric = None
        level_name = _clean_name(name)
        if numeric is None and level_name:
            attr = getattr(logging, level_name.upper(), None)
            if isinstance(attr, int):
                numeric = int(attr)
        if level_name is None and numeric is not None:
            level_name = logging.getLevelName(numeric)
        return numeric, level_name

    try:
        raw_data = json.loads(port_file.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        raw_data = None

    if isinstance(raw_data, dict):
        payload = raw_data.get("log_level")
        if isinstance(payload, dict):
            level_value, level_name = _coerce_level(payload.get("value"), payload.get("name"))
            if level_value is not None or level_name:
                if level_name is None and level_value is not None:
                    level_name = logging.getLevelName(level_value)
                return level_value, level_name, "port.json"

    env_level, env_name = _coerce_level(os.getenv("EDMC_OVERLAY_LOG_LEVEL"), os.getenv("EDMC_OVERLAY_LOG_LEVEL_NAME"))
    if env_level is not None or env_name:
        return env_level, env_name, "env"

    return None, None, "default"


def _record_log_level_hint(initial: InitialClientSettings, port_file: Path) -> None:
    if initial is None:
        return
    level_value, level_name, source = resolve_log_level_hint(port_file)
    if level_value is not None or level_name:
        initial.edmc_log_level = level_value
        initial.edmc_log_level_name = level_name
        initial.edmc_log_level_source = source
        _CLIENT_LOGGER.info(
            "EDMC log level hint: value=%s name=%s (source=%s)",
            level_value,
            level_name or "unknown",
            source,
        )
    else:
        _CLIENT_LOGGER.debug("EDMC log level hint unavailable; assuming INFO.")


def _build_payload_handler(helper: DeveloperHelperController, window: OverlayWindow):
    def _handle_payload(payload: Dict[str, Any]) -> None:
        event = payload.get("event")
        if event == "OverlayConfig":
            helper.apply_config(window, payload)
            return
        if event == "OverlayControllerActiveGroup":
            window.set_active_controller_group(payload.get("plugin"), payload.get("label"), payload.get("anchor"), payload.get("edit_nonce"))
            return
        if event == "OverlayOverrideReload":
            window.handle_override_reload(payload)
            return
        if event == "OverlayOverridesPayload":
            window.apply_override_payload(payload)
            return
        if event == "OverlayGroupCacheReset":
            window.reset_group_cache()
            return
        if event == "LegacyOverlay":
            payload_id = str(payload.get("id") or "").strip().lower()
            if payload_id in {"overlay-controller-status", "edmcmodernoverlay-controller-status"}:
                window.handle_controller_active_signal()
            helper.handle_legacy_payload(window, payload)
            return
        if event == "OverlayCycle":
            action = payload.get("action")
            if isinstance(action, str):
                window.handle_cycle_action(action)
            return
        message_text = payload.get("message")
        ttl: Optional[float] = None
        if event == "TestMessage" and payload.get("message"):
            message_text = payload["message"]
            ttl = 10.0
        if message_text is not None:
            window.display_message(str(message_text), ttl=ttl)

    return _handle_payload


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="EDMC Modern Overlay client")
    parser.add_argument("--port-file", help="Path to port.json emitted by the plugin")
    args = parser.parse_args(argv)

    port_file = resolve_port_file(args.port_file)
    settings_path = (CLIENT_DIR.parent / "overlay_settings.json").resolve()
    initial_settings = load_initial_settings(settings_path)
    _record_log_level_hint(initial_settings, port_file)
    apply_log_level_hint(initial_settings.edmc_log_level, source=initial_settings.edmc_log_level_source)
    diagnostics_enabled = _diagnostics_enabled(initial_settings)
    if not diagnostics_enabled and initial_settings.show_debug_overlay:
        _CLIENT_LOGGER.debug(
            "Debug overlay metrics disabled (EDMC log level is %s; enable DEBUG to restore).",
            initial_settings.edmc_log_level_name or initial_settings.edmc_log_level or "INFO",
        )
        initial_settings.show_debug_overlay = False
    debug_config_path = (CLIENT_DIR.parent / "debug.json").resolve()
    troubleshooting_config = load_troubleshooting_config(debug_config_path, enabled=diagnostics_enabled)
    dev_settings_path = (CLIENT_DIR.parent / "dev_settings.json").resolve()
    dev_settings = load_dev_settings(dev_settings_path)
    if not diagnostics_enabled:
        _CLIENT_LOGGER.debug(
            "debug.json ignored (diagnostics disabled; set EDMC log level to DEBUG to enable troubleshooting capture toggles)."
        )
    if not DEBUG_CONFIG_ENABLED:
        _CLIENT_LOGGER.debug(
            "dev_settings.json ignored (release mode). Export %s=1 or use a -dev version to enable dev helpers.",
            DEV_MODE_ENV_VAR,
        )
    helper = DeveloperHelperController(_CLIENT_LOGGER, CLIENT_DIR, initial_settings)
    if troubleshooting_config.overlay_logs_to_keep is not None:
        helper.set_log_retention(troubleshooting_config.overlay_logs_to_keep)

    _CLIENT_LOGGER.info("Starting overlay client (pid=%s)", os.getpid())
    _CLIENT_LOGGER.debug("Resolved port file path to %s", port_file)
    _CLIENT_LOGGER.debug(
        "Loaded initial settings from %s: retention=%d force_render=%s force_xwayland=%s",
        settings_path,
        initial_settings.client_log_retention,
        initial_settings.force_render,
        initial_settings.force_xwayland,
    )
    if dev_settings.trace_enabled:
        payload_filter = ",".join(dev_settings.trace_payload_ids) if dev_settings.trace_payload_ids else "*"
        _CLIENT_LOGGER.debug("Debug tracing enabled (payload_ids=%s)", payload_filter)

    app = QApplication(sys.argv)
    data_client = OverlayDataClient(port_file)
    window = OverlayWindow(initial_settings, dev_settings)
    window.set_data_client(data_client)
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

    data_client.message_received.connect(_build_payload_handler(helper, window))
    data_client.status_changed.connect(window.set_status_text)

    window.show()
    data_client.start()

    exit_code = app.exec()
    data_client.stop()
    _CLIENT_LOGGER.info("Overlay client exiting with code %s", exit_code)
    return int(exit_code)
