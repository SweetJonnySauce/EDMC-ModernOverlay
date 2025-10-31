#!/usr/bin/env python3
"""Inject captured LandingPad shell payloads into the overlay for tracing."""
from __future__ import annotations

import argparse
import json
import socket
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
PORT_PATH = PLUGIN_ROOT / "port.json"
SETTINGS_PATH = PLUGIN_ROOT / "overlay_settings.json"


def _print_step(message: str) -> None:
    print(f"[overlay-shell-trace] {message}")


def _fail(message: str, *, code: int = 1) -> None:
    print(f"[overlay-shell-trace] ERROR: {message}", file=sys.stderr)
    raise SystemExit(code)


def _load_json(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        _fail(f"Required file missing: {path}")
    except json.JSONDecodeError as exc:
        _fail(f"Failed to parse {path}: {exc}")


def _points(coords: Iterable[Tuple[int, int]]) -> List[Dict[str, int]]:
    return [{"x": int(x), "y": int(y)} for x, y in coords]


SHELL_PAYLOADS: List[Tuple[str, List[Dict[str, int]]]] = [
    (
        "shell-0",
        _points(
            [
                (124, 464),
                (111, 419),
                (89, 393),
                (62, 393),
                (40, 419),
                (27, 464),
                (27, 516),
                (40, 561),
                (62, 587),
                (89, 587),
                (111, 561),
                (124, 516),
                (124, 464),
            ]
        ),
    ),
    (
        "line-2",
        _points(
            [
                (89, 393),
                (79, 466),
            ]
        ),
    ),
    (
        "shell-3",
        _points(
            [
                (88, 484),
                (85, 472),
                (79, 466),
                (73, 466),
                (66, 472),
                (63, 484),
                (63, 496),
                (66, 508),
                (73, 514),
                (79, 514),
                (85, 508),
                (88, 496),
                (88, 484),
            ]
        ),
    ),
]

PAD_RECTANGLES: List[Tuple[str, Dict[str, int]]] = [
    ("pad-19-0", {"x": 60, "y": 469, "w": 2, "h": 9}),
    ("pad-19-1", {"x": 59, "y": 470, "w": 4, "h": 7}),
    ("pad-19-2", {"x": 59, "y": 472, "w": 5, "h": 3}),
]


def _make_vect_payload(shape_id: str, vector: List[Dict[str, int]], ttl: int, station: str, cmdr: str) -> Dict[str, Any]:
    timestamp = datetime.now(UTC).isoformat()
    legacy_raw = {
        "color": "#ffffff",
        "id": shape_id,
        "shape": "vect",
        "ttl": ttl,
        "vector": [dict(point) for point in vector],
    }
    raw_shape = {
        "color": "#ffffff",
        "event": "LegacyOverlay",
        "fill": None,
        "h": 0,
        "id": shape_id,
        "legacy_raw": dict(legacy_raw),
        "plugin": "LandingPad",
        "shape": "vect",
        "timestamp": timestamp,
        "ttl": ttl,
        "type": "shape",
        "vector": [dict(point) for point in vector],
        "w": 0,
        "x": 0,
        "y": 0,
    }

    payload = {
        "cmdr": cmdr,
        "color": "#ffffff",
        "docked": False,
        "event": "LegacyOverlay",
        "fill": None,
        "h": 0,
        "id": shape_id,
        "legacy_raw": legacy_raw,
        "plugin": "LandingPad",
        "raw": raw_shape,
        "shape": "vect",
        "station": station,
        "system": "",
        "timestamp": timestamp,
        "ttl": ttl,
        "type": "shape",
        "vector": [dict(point) for point in vector],
        "w": 0,
        "x": 0,
        "y": 0,
    }
    return payload


def _make_rect_payload(
    shape_id: str,
    rect: Dict[str, int],
    ttl: int,
    station: str,
    cmdr: str,
) -> Dict[str, Any]:
    timestamp = datetime.now(UTC).isoformat()
    legacy_raw = {
        "color": "yellow",
        "fill": "yellow",
        "h": rect["h"],
        "id": shape_id,
        "shape": "rect",
        "ttl": ttl,
        "w": rect["w"],
        "x": rect["x"],
        "y": rect["y"],
    }
    raw_shape = {
        "color": "yellow",
        "event": "LegacyOverlay",
        "fill": "yellow",
        "h": rect["h"],
        "id": shape_id,
        "legacy_raw": dict(legacy_raw),
        "plugin": "LandingPad",
        "shape": "rect",
        "timestamp": timestamp,
        "ttl": ttl,
        "type": "shape",
        "w": rect["w"],
        "x": rect["x"],
        "y": rect["y"],
    }
    payload: Dict[str, Any] = {
        "cmdr": cmdr,
        "color": "yellow",
        "docked": False,
        "event": "LegacyOverlay",
        "fill": "yellow",
        "h": rect["h"],
        "id": shape_id,
        "legacy_raw": legacy_raw,
        "plugin": "LandingPad",
        "raw": raw_shape,
        "shape": "rect",
        "station": station,
        "system": "",
        "timestamp": timestamp,
        "ttl": ttl,
        "type": "shape",
        "w": rect["w"],
        "x": rect["x"],
        "y": rect["y"],
    }
    return payload


def _send_payload(port: int, envelope: Dict[str, Any], *, timeout: float = 5.0) -> Dict[str, Any]:
    message = json.dumps(envelope, ensure_ascii=False)
    _print_step(f"Connecting to overlay broadcaster on 127.0.0.1:{port}")
    with socket.create_connection(("127.0.0.1", port), timeout=timeout) as sock:
        sock.settimeout(timeout)
        writer = sock.makefile("w", encoding="utf-8", newline="\n")
        reader = sock.makefile("r", encoding="utf-8")
        writer.write(message)
        writer.write("\n")
        writer.flush()
        _print_step("Payload dispatched; awaiting acknowledgement …")
        for _ in range(10):
            line = reader.readline()
            if not line:
                _fail("Connection closed before acknowledgement received.")
            try:
                response = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(response, dict) and "status" in response:
                return response
        _fail("Did not receive acknowledgement from overlay broadcaster.")


def main(argv: List[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Send captured LandingPad shell payloads to ModernOverlay for trace analysis.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--ttl", type=int, default=5, help="Time-to-live for the injected payloads.")
    parser.add_argument("--station", default="Debug Station", help="Station name to include in payload metadata.")
    parser.add_argument("--cmdr", default="overlay-trace", help="Commander name to embed in payload metadata.")
    args = parser.parse_args(argv)

    if args.ttl <= 0:
        _fail("TTL must be positive.")

    settings = _load_json(SETTINGS_PATH)
    if not bool(settings.get("log_payloads", False)):
        _print_step(
            "WARNING: overlay_settings.json has log_payloads=false. Overlay logs will not mirror payloads unless enabled."
        )

    port_data = _load_json(PORT_PATH)
    port = port_data.get("port")
    if not isinstance(port, int) or port <= 0:
        _fail(f"port.json does not contain a valid port number: {port_data!r}")

    envelopes: List[Dict[str, Any]] = []
    for shape_id, vector in SHELL_PAYLOADS:
        payload = _make_vect_payload(shape_id, vector, args.ttl, args.station, args.cmdr)
        envelopes.append(
            {
                "cli": "legacy_overlay",
                "payload": payload,
                "meta": {
                    "source": "send_overlay_shell_trace",
                    "plugin": "LandingPad",
                    "sequence": shape_id,
                },
            }
        )

    for shape_id, rect in PAD_RECTANGLES:
        payload = _make_rect_payload(shape_id, rect, args.ttl, args.station, args.cmdr)
        envelopes.append(
            {
                "cli": "legacy_overlay",
                "payload": payload,
                "meta": {
                    "source": "send_overlay_shell_trace",
                    "plugin": "LandingPad",
                    "sequence": shape_id,
                },
            }
        )

    _print_step(f"Prepared {len(envelopes)} payload(s); sending via port {port}.")
    for envelope in envelopes:
        response = _send_payload(port, envelope)
        if response.get("status") == "ok":
            _print_step(f"Payload {envelope['meta']['sequence']} acknowledged.")
        else:
            _print_step(f"Overlay broadcaster returned non-ok response: {response}")


if __name__ == "__main__":
    main()
