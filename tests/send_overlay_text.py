#!/usr/bin/env python3
"""Send a LegacyOverlay text payload through ModernOverlay from the command line."""
from __future__ import annotations

import argparse
import json
import shutil
import socket
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, Optional

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SETTINGS_PATH = PLUGIN_ROOT / "overlay_settings.json"
DEBUG_CONFIG_PATH = PLUGIN_ROOT / "debug.json"
PORT_PATH = PLUGIN_ROOT / "port.json"
DEFAULT_MESSAGE = "Hello from send_overlay_text.py"


def _print_step(message: str) -> None:
    print(f"[overlay-cli] {message}")


def _fail(message: str, *, code: int = 1) -> None:
    print(f"[overlay-cli] ERROR: {message}", file=sys.stderr)
    raise SystemExit(code)


def _load_json(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        _fail(f"Required file missing: {path}")
    except json.JSONDecodeError as exc:
        _fail(f"Failed to parse {path}: {exc}")


def _settings_payload_logging() -> Optional[bool]:
    try:
        config = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except json.JSONDecodeError:
        return None
    flag = config.get("log_payloads")
    if isinstance(flag, bool):
        return flag
    if flag is not None:
        return bool(flag)
    return None


def _legacy_debug_payload_logging() -> bool:
    try:
        config = json.loads(DEBUG_CONFIG_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return False
    except json.JSONDecodeError:
        return False
    section = config.get("payload_logging")
    if isinstance(section, dict):
        flag = section.get("overlay_payload_log_enabled")
        if isinstance(flag, bool):
            return flag
        if flag is not None:
            return bool(flag)
        exclude_flag = section.get("enabled")
        if isinstance(exclude_flag, bool):
            return exclude_flag
    legacy_flag = config.get("log_payloads")
    if isinstance(legacy_flag, bool):
        return legacy_flag
    if legacy_flag is not None:
        return bool(legacy_flag)
    return False


def _is_payload_logging_enabled() -> bool:
    pref_flag = _settings_payload_logging()
    if pref_flag is not None:
        return pref_flag
    return _legacy_debug_payload_logging()


def _warn_payload_logging() -> None:
    if _is_payload_logging_enabled():
        _print_step("Detected overlay payload logging enabled (overlay-payloads.log).")
    else:
        _print_step(
            "WARNING: overlay payload logging is disabled. Enable \"Log incoming payloads\" in the Modern Overlay"
            " preferences (Settings > Plugins > Modern Overlay) to mirror payloads to overlay-payloads.log."
        )


def _ensure_overlay_client_running() -> None:
    pgrep = shutil.which("pgrep")
    if pgrep is None:
        _print_step("pgrep not available; skipping process check for overlay client.")
        return
    patterns = [
        "overlay_client.py",  # direct script invocation
        "overlay_client.overlay_client",  # module invocation
    ]
    for pattern in patterns:
        result = subprocess.run([pgrep, "-f", pattern], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if result.returncode == 0:
            _print_step(f"Overlay client process detected (pattern: {pattern}).")
            return
    _fail(
        "Could not find the overlay client process. Ensure the ModernOverlay window is running before sending messages."
    )


def _compose_payload(text: str, x: int, y: int, ttl: int) -> Dict[str, Any]:
    identifier = datetime.now(UTC).strftime("cli-%Y%m%dT%H%M%S%f")
    return {
        "cli": "legacy_overlay",
        "payload": {
            "event": "LegacyOverlay",
            "type": "message",
            "id": identifier,
            "text": text,
            "color": "#ffffff",
            "x": x,
            "y": y,
            "ttl": ttl,
            "size": "normal",
        },
    }


def _send_payload(port: int, payload: Dict[str, Any], *, timeout: float = 5.0) -> Dict[str, Any]:
    message = json.dumps(payload, ensure_ascii=False)
    _print_step(f"Connecting to ModernOverlay broadcaster on 127.0.0.1:{port} …")
    with socket.create_connection(("127.0.0.1", port), timeout=timeout) as sock:
        sock.settimeout(timeout)
        writer = sock.makefile("w", encoding="utf-8", newline="\n")
        reader = sock.makefile("r", encoding="utf-8")
        writer.write(message)
        writer.write("\n")
        writer.flush()
        _print_step("Payload dispatched; awaiting acknowledgement …")
        for _ in range(10):
            ack_line = reader.readline()
            if not ack_line:
                _fail("No acknowledgement received from ModernOverlay (connection closed).")
            try:
                response = json.loads(ack_line)
            except json.JSONDecodeError:
                continue
            if isinstance(response, dict) and "status" in response:
                return response
            _print_step("Received broadcast payload before acknowledgement; waiting for status …")
        _fail("Did not receive a CLI acknowledgement after multiple attempts.")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Send a LegacyOverlay message via ModernOverlay.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("text", nargs="?", default=DEFAULT_MESSAGE, help="Message text to display on the overlay")
    parser.add_argument("--x", type=int, default=120, help="Overlay X coordinate (virtual pixels)")
    parser.add_argument("--y", type=int, default=160, help="Overlay Y coordinate (virtual pixels)")
    parser.add_argument("--ttl", type=int, default=8, help="Time-to-live in seconds")
    args = parser.parse_args(argv)

    _print_step(f"Using plugin root: {PLUGIN_ROOT}")
    _load_json(SETTINGS_PATH)
    _warn_payload_logging()

    _ensure_overlay_client_running()

    port_data = _load_json(PORT_PATH)
    port = port_data.get("port")
    if not isinstance(port, int) or port <= 0:
        _fail(f"port.json does not contain a valid port: {port_data!r}")
    _print_step(f"ModernOverlay broadcaster port resolved to {port}.")

    payload = _compose_payload(args.text, args.x, args.y, args.ttl)
    _print_step(f"Prepared LegacyOverlay payload id={payload['payload']['id']}.")

    response = _send_payload(port, payload)
    status = response.get("status")
    if status == "ok":
        _print_step("ModernOverlay acknowledged the payload. The message should now appear on the HUD and in the log.")
    else:
        message = response.get("error") or response
        _fail(f"ModernOverlay reported an error: {message}")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:
        print(
            "[overlay-cli] ERROR: Unexpected failure while sending the overlay message.",
            file=sys.stderr,
        )
        print(f"[overlay-cli] DETAILS: {exc}", file=sys.stderr)
        print(
            "[overlay-cli] usage: PYTHONPATH=. python3 tests/send_overlay_text.py [message] [--x X] [--y Y] [--ttl TTL]",
            file=sys.stderr,
        )
        raise SystemExit(1)
