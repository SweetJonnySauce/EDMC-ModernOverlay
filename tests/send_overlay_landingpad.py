#!/usr/bin/env python3
"""Send a LandingPad-style overlay composed of vect payloads."""
from __future__ import annotations

import argparse
import json
import shutil
import socket
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SETTINGS_PATH = PLUGIN_ROOT / "overlay_settings.json"
PORT_PATH = PLUGIN_ROOT / "port.json"


def _print_step(message: str) -> None:
    print(f"[overlay-cli] {message}")


def _fail(message: str, *, code: int = 1) -> None:
    print(f"[overlay-cli] ERROR: {message}", file=sys.stderr)
    raise SystemExit(code)


# ---------------------------------------------------------------------------
# Landing pad shape data captured from the live plugin

def _points(coords: Iterable[Tuple[int, int]]) -> List[Dict[str, int]]:
    return [{"x": int(x), "y": int(y)} for x, y in coords]


BASE_VECTOR_SHAPES: List[Dict[str, Any]] = [
    {
        "id": "shell-0",
        "shape": "vect",
        "color": "#ffffff",
        "vector": _points(
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
    },
    {
        "id": "shell-1",
        "shape": "vect",
        "color": "#ffffff",
        "vector": _points(
            [
                (106, 474),
                (98, 446),
                (84, 430),
                (67, 430),
                (53, 446),
                (45, 474),
                (45, 506),
                (53, 534),
                (67, 550),
                (84, 550),
                (98, 534),
                (106, 506),
                (106, 474),
            ]
        ),
    },
    {
        "id": "shell-2",
        "shape": "vect",
        "color": "#ffffff",
        "vector": _points(
            [
                (98, 478),
                (92, 458),
                (82, 446),
                (70, 446),
                (59, 458),
                (53, 478),
                (53, 502),
                (59, 522),
                (70, 534),
                (82, 534),
                (92, 522),
                (98, 502),
                (98, 478),
            ]
        ),
    },
    {
        "id": "shell-3",
        "shape": "vect",
        "color": "#ffffff",
        "vector": _points(
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
    },
    {
        "id": "line-0",
        "shape": "vect",
        "color": "#ffffff",
        "vector": _points([(124, 464), (88, 484)]),
    },
    {
        "id": "line-1",
        "shape": "vect",
        "color": "#ffffff",
        "vector": _points([(111, 419), (85, 472)]),
    },
    {
        "id": "line-2",
        "shape": "vect",
        "color": "#ffffff",
        "vector": _points([(89, 393), (79, 466)]),
    },
    {
        "id": "line-3",
        "shape": "vect",
        "color": "#ffffff",
        "vector": _points([(62, 393), (73, 466)]),
    },
    {
        "id": "line-4",
        "shape": "vect",
        "color": "#ffffff",
        "vector": _points([(40, 419), (66, 472)]),
    },
    {
        "id": "line-5",
        "shape": "vect",
        "color": "#ffffff",
        "vector": _points([(27, 464), (63, 484)]),
    },
    {
        "id": "line-6",
        "shape": "vect",
        "color": "#ffffff",
        "vector": _points([(27, 516), (63, 496)]),
    },
    {
        "id": "line-7",
        "shape": "vect",
        "color": "#ffffff",
        "vector": _points([(40, 561), (66, 508)]),
    },
    {
        "id": "line-8",
        "shape": "vect",
        "color": "#ffffff",
        "vector": _points([(62, 587), (73, 514)]),
    },
    {
        "id": "line-9",
        "shape": "vect",
        "color": "#ffffff",
        "vector": _points([(89, 587), (79, 514)]),
    },
    {
        "id": "line-10",
        "shape": "vect",
        "color": "#ffffff",
        "vector": _points([(111, 561), (85, 508)]),
    },
    {
        "id": "line-11",
        "shape": "vect",
        "color": "#ffffff",
        "vector": _points([(124, 516), (88, 496)]),
    },
    {
        "id": "toaster-right-0",
        "shape": "vect",
        "color": "green",
        "vector": _points(
            [
                (76, 465),
                (112, 465),
                (114, 469),
                (125, 469),
                (126, 471),
                (126, 509),
                (125, 511),
                (114, 511),
                (112, 515),
                (76, 515),
            ]
        ),
    },
    {
        "id": "toaster-left-0",
        "shape": "vect",
        "color": "red",
        "vector": _points(
            [
                (76, 465),
                (39, 465),
                (37, 469),
                (26, 469),
                (25, 471),
                (25, 509),
                (26, 511),
                (37, 511),
                (39, 515),
                (76, 515),
            ]
        ),
    },
    {
        "id": "toaster-right-1",
        "shape": "vect",
        "color": "green",
        "vector": _points(
            [
                (76, 464),
                (112, 464),
                (114, 468),
                (125, 468),
                (125, 470),
                (125, 510),
                (125, 512),
                (114, 512),
                (112, 516),
                (76, 516),
            ]
        ),
    },
    {
        "id": "toaster-left-1",
        "shape": "vect",
        "color": "red",
        "vector": _points(
            [
                (76, 464),
                (39, 464),
                (37, 468),
                (26, 468),
                (26, 470),
                (26, 510),
                (26, 512),
                (37, 512),
                (39, 516),
                (76, 516),
            ]
        ),
    },
]

BASE_RECT_SHAPES: List[Dict[str, Any]] = [
    {
        "id": "pad-19-0",
        "shape": "rect",
        "color": "yellow",
        "fill": "yellow",
        "x": 60,
        "y": 469,
        "w": 2,
        "h": 9,
    },
    {
        "id": "pad-19-1",
        "shape": "rect",
        "color": "yellow",
        "fill": "yellow",
        "x": 59,
        "y": 470,
        "w": 4,
        "h": 7,
    },
    {
        "id": "pad-19-2",
        "shape": "rect",
        "color": "yellow",
        "fill": "yellow",
        "x": 59,
        "y": 472,
        "w": 5,
        "h": 3,
    },
]

BASE_SHAPES: List[Dict[str, Any]] = BASE_VECTOR_SHAPES + BASE_RECT_SHAPES


def _compute_base_metrics() -> Tuple[float, float, float]:
    xs: List[float] = []
    ys: List[float] = []
    for shape in BASE_SHAPES:
        if shape["shape"] == "vect":
            for point in shape["vector"]:
                xs.append(point["x"])
                ys.append(point["y"])
        else:
            xs.extend([shape["x"], shape["x"] + shape["w"]])
            ys.extend([shape["y"], shape["y"] + shape["h"]])
    if not xs or not ys:
        raise RuntimeError("No base landing pad shapes defined.")
    center_x = (min(xs) + max(xs)) / 2.0
    center_y = (min(ys) + max(ys)) / 2.0
    half_width = max(abs(x - center_x) for x in xs)
    half_height = max(abs(y - center_y) for y in ys)
    base_radius = max(half_width, half_height)
    return center_x, center_y, base_radius


BASE_CENTER_X, BASE_CENTER_Y, BASE_RADIUS = _compute_base_metrics()


# ---------------------------------------------------------------------------

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


def _transform_shape(
    shape: Dict[str, Any],
    center_x: float,
    center_y: float,
    scale: float,
    ttl: int,
    suffix: str,
) -> Dict[str, Any]:
    new_shape: Dict[str, Any] = {
        "type": "shape",
        "shape": shape["shape"],
        "id": f"{shape['id']}-{suffix}",
        "color": shape.get("color", "#ffffff"),
        "ttl": ttl,
    }

    if shape["shape"] == "vect":
        transformed_points: List[Dict[str, int]] = []
        for point in shape["vector"]:
            new_x = center_x + (point["x"] - BASE_CENTER_X) * scale
            new_y = center_y + (point["y"] - BASE_CENTER_Y) * scale
            transformed_points.append({"x": int(round(new_x)), "y": int(round(new_y))})
        new_shape["vector"] = transformed_points
    else:
        raw_x = float(shape["x"])
        raw_y = float(shape["y"])
        raw_w = float(shape["w"])
        raw_h = float(shape["h"])
        center_px = raw_x + raw_w / 2.0
        center_py = raw_y + raw_h / 2.0
        transformed_cx = center_x + (center_px - BASE_CENTER_X) * scale
        transformed_cy = center_y + (center_py - BASE_CENTER_Y) * scale
        new_w = max(1, int(round(raw_w * scale)))
        new_h = max(1, int(round(raw_h * scale)))
        new_shape["x"] = int(round(transformed_cx - new_w / 2.0))
        new_shape["y"] = int(round(transformed_cy - new_h / 2.0))
        new_shape["w"] = new_w
        new_shape["h"] = new_h
        if shape.get("fill") is not None:
            new_shape["fill"] = shape["fill"]

    return new_shape


def _compose_payloads(cx: int, cy: int, radius: int, ttl: int) -> List[Dict[str, Any]]:
    timestamp = datetime.now(UTC).strftime("cli-landingpad-%Y%m%dT%H%M%S%f")
    payloads: List[Dict[str, Any]] = []
    scale = radius / BASE_RADIUS

    for base_shape in BASE_SHAPES:
        transformed = _transform_shape(base_shape, cx, cy, scale, ttl, timestamp)
        payloads.append(
            {
                "cli": "legacy_overlay",
                "payload": {
                    "event": "LegacyOverlay",
                    **transformed,
                },
                "meta": {
                    "source": "send_overlay_landingpad",
                    "description": f"LandingPad element {base_shape['id']}",
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
    parser.add_argument(
        "--radius",
        type=int,
        default=160,
        help=f"Target radius for scaling relative to the captured asset (base radius ≈ {int(round(BASE_RADIUS))})",
    )
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
