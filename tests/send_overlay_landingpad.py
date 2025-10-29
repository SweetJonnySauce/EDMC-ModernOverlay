#!/usr/bin/env python3
"""Send a LandingPad-style overlay composed of vect payloads."""
from __future__ import annotations

import argparse
import json
import math
import shutil
import socket
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List

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


def _warn_log_payload(settings: Dict[str, Any]) -> None:
    if not bool(settings.get("log_payloads", False)):
        _print_step(
            "WARNING: log_payloads=false. Overlay payloads will not be mirrored to the EDMC log. "
            "Enable 'Send overlay payloads to the EDMC log' in ModernOverlay preferences to capture them."
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


def _dodecagon_points(cx: float, cy: float, radius: float) -> List[Dict[str, int]]:
    points: List[Dict[str, int]] = []
    for i in range(12):
        angle = math.radians(30 * i)
        x = cx + radius * math.cos(angle)
        y = cy + radius * math.sin(angle)
        points.append({"x": int(round(x)), "y": int(round(y))})
    points.append(points[0])
    return points


def _sector_vectors(cx: float, cy: float, inner_r: float, outer_r: float) -> Iterable[List[Dict[str, int]]]:
    for i in range(12):
        angle = math.radians(30 * i)
        x1 = cx + inner_r * math.cos(angle)
        y1 = cy + inner_r * math.sin(angle)
        x2 = cx + outer_r * math.cos(angle)
        y2 = cy + outer_r * math.sin(angle)
        yield [
            {"x": int(round(x1)), "y": int(round(y1))},
            {"x": int(round(x2)), "y": int(round(y2))},
        ]


def _toaster_vectors(cx: float, cy: float, radius: float) -> Iterable[List[Dict[str, int]]]:
    thickness = radius * 0.15
    height = radius * 0.6
    offsets = [(-thickness, height), (thickness, height)]
    for idx, (dx, h) in enumerate(offsets):
        points = [
            {"x": int(round(cx + dx)), "y": int(round(cy - h)), "color": "red" if idx == 0 else "green"},
            {"x": int(round(cx + dx)), "y": int(round(cy + h))},
        ]
        yield points


def _compose_payloads(cx: int, cy: int, radius: int, ttl: int) -> List[Dict[str, Any]]:
    timestamp = datetime.now(UTC).strftime("cli-landingpad-%Y%m%dT%H%M%S%f")
    payloads: List[Dict[str, Any]] = []

    shell_points = _dodecagon_points(cx, cy, radius)
    payloads.append(
        {
            "cli": "legacy_overlay",
            "payload": {
                "event": "LegacyOverlay",
                "type": "shape",
                "shape": "vect",
                "id": f"shell-{timestamp}",
                "color": "#ffaa00",
                "ttl": ttl,
                "vector": shell_points,
            },
            "meta": {
                "source": "send_overlay_landingpad",
                "description": "LandingPad shell polygon",
            },
        }
    )

    for idx, vector in enumerate(_sector_vectors(cx, cy, radius * 0.25, radius)):
        payloads.append(
            {
                "cli": "legacy_overlay",
                "payload": {
                    "event": "LegacyOverlay",
                    "type": "shape",
                    "shape": "vect",
                    "id": f"sector-{idx}-{timestamp}",
                    "color": "#ffaa00",
                    "ttl": ttl,
                    "vector": vector,
                },
                "meta": {
                    "source": "send_overlay_landingpad",
                    "description": f"LandingPad sector line {idx}",
                },
            }
        )

    for idx, vector in enumerate(_toaster_vectors(cx, cy, radius * 0.8)):
        payloads.append(
            {
                "cli": "legacy_overlay",
                "payload": {
                    "event": "LegacyOverlay",
                    "type": "shape",
                    "shape": "vect",
                    "id": f"toaster-{idx}-{timestamp}",
                    "color": "#00ffff",
                    "ttl": ttl,
                    "vector": vector,
                },
                "meta": {
                    "source": "send_overlay_landingpad",
                    "description": f"LandingPad toaster rail {idx}",
                },
            }
        )

    return payloads


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


def main(argv: List[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Send a LandingPad-style vector overlay via ModernOverlay.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--center-x", type=int, default=400, help="Overlay center X coordinate")
    parser.add_argument("--center-y", type=int, default=240, help="Overlay center Y coordinate")
    parser.add_argument("--radius", type=int, default=160, help="Outer radius for the dodecagon")
    parser.add_argument("--ttl", type=int, default=12, help="Time-to-live in seconds")
    args = parser.parse_args(argv)

    if args.radius <= 0:
        _fail("Radius must be positive")
    if args.ttl <= 0:
        _fail("TTL must be positive")

    _print_step(f"Using plugin root: {PLUGIN_ROOT}")
    settings = _load_json(SETTINGS_PATH)
    _warn_log_payload(settings)

    _ensure_overlay_client_running()

    port_data = _load_json(PORT_PATH)
    port = port_data.get("port")
    if not isinstance(port, int) or port <= 0:
        _fail(f"port.json does not contain a valid port: {port_data!r}")
    _print_step(f"ModernOverlay broadcaster port resolved to {port}.")

    payloads = _compose_payloads(args.center_x, args.center_y, args.radius, args.ttl)
    _print_step(f"Prepared {len(payloads)} vector payloads.")

    for idx, payload in enumerate(payloads, start=1):
        payload.setdefault("meta", {})
        payload["meta"].setdefault("sequence", idx)
        response = _send_payload(port, payload)
        if response.get("status") == "ok":
            _print_step(f"Payload {idx}/{len(payloads)} acknowledged.")
        else:
            message = response.get("error") or response
            _fail(f"ModernOverlay reported an error for payload {idx}: {message}")

    _print_step("All payloads sent successfully. The overlay should now display the LandingPad-style graphics.")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:
        print(
            "[overlay-cli] ERROR: Unexpected failure while sending the LandingPad vector payloads.",
            file=sys.stderr,
        )
        print(f"[overlay-cli] DETAILS: {exc}", file=sys.stderr)
        print(
            "[overlay-cli] usage: PYTHONPATH=. python3 tests/send_overlay_landingpad.py [--center-x X] [--center-y Y] [--radius R] [--ttl TTL]",
            file=sys.stderr,
        )
        raise SystemExit(1)
