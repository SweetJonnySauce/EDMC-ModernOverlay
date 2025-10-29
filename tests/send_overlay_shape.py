#!/usr/bin/env python3
"""Send a LegacyOverlay vector (shape) payload through ModernOverlay from the command line."""
from __future__ import annotations

import argparse
import json
import shutil
import socket
import subprocess
import sys
from datetime import UTC, datetime
from math import cos, radians, sin
from pathlib import Path
from typing import Any, Dict

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SETTINGS_PATH = PLUGIN_ROOT / "overlay_settings.json"
PORT_PATH = PLUGIN_ROOT / "port.json"


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


def _ensure_log_payload_enabled(settings: Dict[str, Any]) -> None:
    if not bool(settings.get("log_payloads", False)):
        _print_step(
            "WARNING: log_payloads=false. Overlay payloads will not be mirrored to the EDMC log."
            " Enable 'Send overlay payloads to the EDMC log' in the preferences to see log entries."
        )
    else:
        _print_step("Detected log_payloads=true (log mirroring enabled).")


def _ensure_overlay_client_running() -> None:
    pgrep = shutil.which("pgrep")
    if pgrep is None:
        _print_step("pgrep not available; skipping process check for overlay client.")
        return
    result = subprocess.run([pgrep, "-f", "overlay_client.py"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if result.returncode != 0:
        _fail(
            "Could not find the overlay client process. Ensure the ModernOverlay window is running before sending messages."
        )
    _print_step("Overlay client process detected (overlay_client.py).")


def _arrow_points(x: int, y: int, length: int, angle_deg: float) -> list[Dict[str, Any]]:
    angle = radians(angle_deg)
    end_x = x + int(length * cos(angle))
    end_y = y + int(length * sin(angle))
    head_angle_left = radians(angle_deg + 150)
    head_angle_right = radians(angle_deg - 150)
    head_length = max(15, length // 5)
    left_x = end_x + int(head_length * cos(head_angle_left))
    left_y = end_y + int(head_length * sin(head_angle_left))
    right_x = end_x + int(head_length * cos(head_angle_right))
    right_y = end_y + int(head_length * sin(head_angle_right))
    return [
        {"x": x, "y": y, "color": "#00ffff", "marker": "circle", "text": "Start"},
        {"x": end_x, "y": end_y, "color": "#00ffff"},
        {"x": left_x, "y": left_y, "color": "#ffaa00", "marker": "cross"},
        {"x": end_x, "y": end_y, "color": "#00ffff"},
        {"x": right_x, "y": right_y, "color": "#ffaa00", "marker": "cross"},
    ]


def _compose_payload(x: int, y: int, length: int, angle: float, ttl: int) -> Dict[str, Any]:
    identifier = datetime.now(UTC).strftime("cli-shape-%Y%m%dT%H%M%S%f")
    vector = _arrow_points(x, y, length, angle)
    return {
        "cli": "legacy_overlay",
        "payload": {
            "event": "LegacyOverlay",
            "type": "shape",
            "shape": "vect",
            "id": identifier,
            "color": "#00ffff",
            "ttl": ttl,
            "vector": vector,
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
        description="Send a LegacyOverlay vector (shape) via ModernOverlay.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--x", type=int, default=400, help="Start X coordinate (virtual pixels)")
    parser.add_argument("--y", type=int, default=200, help="Start Y coordinate (virtual pixels)")
    parser.add_argument("--length", type=int, default=180, help="Arrow length in virtual pixels")
    parser.add_argument("--angle", type=float, default=0.0, help="Arrow angle in degrees (0=right, 90=down)")
    parser.add_argument("--ttl", type=int, default=10, help="Time-to-live in seconds")
    args = parser.parse_args(argv)

    if args.length <= 0:
        _fail("Arrow length must be positive")
    if args.ttl <= 0:
        _fail("TTL must be positive")

    _print_step(f"Using plugin root: {PLUGIN_ROOT}")
    settings = _load_json(SETTINGS_PATH)
    _ensure_log_payload_enabled(settings)

    _ensure_overlay_client_running()

    port_data = _load_json(PORT_PATH)
    port = port_data.get("port")
    if not isinstance(port, int) or port <= 0:
        _fail(f"port.json does not contain a valid port: {port_data!r}")
    _print_step(f"ModernOverlay broadcaster port resolved to {port}.")

    payload = _compose_payload(args.x, args.y, args.length, args.angle, args.ttl)
    _print_step(f"Prepared LegacyOverlay shape payload id={payload['payload']['id']}.")

    # Add CLI helper info so the developer overlay helper can report diagnostics
    payload.setdefault("meta", {})
    payload["meta"]["source"] = "send_overlay_shape"
    payload["meta"]["description"] = "Developer-initiated vector payload"

    response = _send_payload(port, payload)
    if response.get("status") == "ok":
        _print_step(
            "ModernOverlay acknowledged the payload. The shape payload should now be logged (rendering pending)."
        )
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
            "[overlay-cli] ERROR: Unexpected failure while sending the overlay shape payload.",
            file=sys.stderr,
        )
        print(f"[overlay-cli] DETAILS: {exc}", file=sys.stderr)
        print(
            "[overlay-cli] usage: PYTHONPATH=. python3 tests/send_overlay_shape.py [--x X] [--y Y] [--length L] [--angle A] [--ttl TTL]",
            file=sys.stderr,
        )
        raise SystemExit(1)
