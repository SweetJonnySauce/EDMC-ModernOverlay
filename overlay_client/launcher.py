from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from PyQt6.QtWidgets import QApplication

from overlay_client.client_config import load_initial_settings
from overlay_client.data_client import OverlayDataClient
from overlay_client.debug_config import DEBUG_CONFIG_ENABLED, load_debug_config
from overlay_client.developer_helpers import DeveloperHelperController
from overlay_client.overlay_client import CLIENT_DIR, DEV_MODE_ENV_VAR, OverlayWindow, _CLIENT_LOGGER
from overlay_client.window_tracking import create_elite_window_tracker


def resolve_port_file(args_port: Optional[str]) -> Path:
    if args_port:
        return Path(args_port).expanduser().resolve()
    env_override = os.getenv("EDMC_OVERLAY_PORT_FILE")
    if env_override:
        return Path(env_override).expanduser().resolve()
    return (Path(__file__).resolve().parent.parent / "port.json").resolve()


def _build_payload_handler(helper: DeveloperHelperController, window: OverlayWindow):
    def _handle_payload(payload: Dict[str, Any]) -> None:
        event = payload.get("event")
        if event == "OverlayConfig":
            helper.apply_config(window, payload)
            return
        if event == "OverlayControllerActiveGroup":
            window.set_active_controller_group(payload.get("plugin"), payload.get("label"))
            return
        if event == "OverlayOverrideReload":
            window.handle_override_reload(payload)
            return
        if event == "LegacyOverlay":
            payload_id = str(payload.get("id") or "").strip().lower()
            if payload_id == "overlay-controller-status":
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
    debug_config_path = (CLIENT_DIR.parent / "debug.json").resolve()
    debug_config = load_debug_config(debug_config_path)
    if not DEBUG_CONFIG_ENABLED:
        _CLIENT_LOGGER.debug(
            "debug.json ignored (release mode). Export %s=1 or use a -dev version to enable trace toggles.",
            DEV_MODE_ENV_VAR,
        )
    helper = DeveloperHelperController(_CLIENT_LOGGER, CLIENT_DIR, initial_settings)
    if debug_config.overlay_logs_to_keep is not None:
        helper.set_log_retention(debug_config.overlay_logs_to_keep)

    _CLIENT_LOGGER.info("Starting overlay client (pid=%s)", os.getpid())
    _CLIENT_LOGGER.debug("Resolved port file path to %s", port_file)
    _CLIENT_LOGGER.debug(
        "Loaded initial settings from %s: retention=%d force_render=%s force_xwayland=%s",
        settings_path,
        initial_settings.client_log_retention,
        initial_settings.force_render,
        initial_settings.force_xwayland,
    )
    if debug_config.trace_enabled:
        payload_filter = ",".join(debug_config.trace_payload_ids) if debug_config.trace_payload_ids else "*"
        _CLIENT_LOGGER.debug("Debug tracing enabled (payload_ids=%s)", payload_filter)

    app = QApplication(sys.argv)
    data_client = OverlayDataClient(port_file)
    window = OverlayWindow(initial_settings, debug_config)
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
