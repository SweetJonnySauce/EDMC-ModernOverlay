#!/usr/bin/env python3
"""Run payload sweeps across multiple resolutions for Modern Overlay."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TESTS_DIR = PROJECT_ROOT / "tests"
CONFIG_PATH = TESTS_DIR / "test_resolution.json"
PORT_PATH = PROJECT_ROOT / "port.json"

MOCK_WINDOW_PATH = TESTS_DIR / "mock_elite_window.py"
SEND_FROM_LOG_PATH = TESTS_DIR / "send_overlay_from_log.py"

DEFAULT_TITLE = "Elite - Dangerous (Stub)"


class DriverError(RuntimeError):
    """Raised when the resolution test driver encounters a fatal issue."""


def _log(message: str) -> None:
    print(f"[resolution-tests] {message}")


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise DriverError(f"Required file missing: {path}") from exc
    except json.JSONDecodeError as exc:
        raise DriverError(f"Failed to parse JSON file {path}: {exc}") from exc


def _ensure_overlay_running() -> None:
    pgrep = shutil.which("pgrep")
    if not pgrep:
        _log("pgrep not found; skipping overlay client process check.")
        return
    result = subprocess.run(
        [pgrep, "-f", "overlay_client.py"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if result.returncode != 0:
        raise DriverError("Could not find overlay_client.py process. Launch the overlay before running tests.")
    _log("Overlay client process detected.")


def _resolve_port() -> int:
    data = _read_json(PORT_PATH)
    port = data.get("port")
    if not isinstance(port, int) or port <= 0:
        raise DriverError(f"port.json does not contain a valid port number: {data!r}")
    return port


def _wait_for_overlay_ready(port: int, *, timeout: float = 180.0, poll_interval: float = 1.0) -> None:
    """Wait until the overlay broadcaster accepts TCP connections."""
    deadline = time.monotonic() + timeout
    attempt = 0
    _log(f"Waiting for ModernOverlay broadcaster on 127.0.0.1:{port} …")
    while True:
        attempt += 1
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=5.0):
                _log(f"Overlay broadcaster reachable (attempt {attempt}).")
                return
        except OSError as exc:
            now = time.monotonic()
            if now >= deadline:
                raise DriverError(
                    f"Timed out after {timeout:.0f}s waiting for ModernOverlay broadcaster on port {port}: {exc}"
                ) from exc
            time.sleep(min(poll_interval, max(0.1, deadline - now)))


def _launch_mock_window(
    width: int,
    height: int,
    *,
    label_file: Path,
    title: str = DEFAULT_TITLE,
    crosshair_x: Optional[float] = None,
    crosshair_y: Optional[float] = None,
) -> subprocess.Popen[Any]:
    env = dict(os.environ)
    env["MOCK_ELITE_WIDTH"] = str(width)
    env["MOCK_ELITE_HEIGHT"] = str(height)
    command = [
        sys.executable,
        str(MOCK_WINDOW_PATH),
        "--title",
        title,
        "--size",
        f"{width}x{height}",
        "--label-file",
        str(label_file),
    ]
    if crosshair_x is not None:
        command.extend(["--crosshair-x", str(crosshair_x)])
    if crosshair_y is not None:
        command.extend(["--crosshair-y", str(crosshair_y)])
    _log(f"Launching mock Elite window at {width}x{height} …")
    return subprocess.Popen(command, cwd=PROJECT_ROOT, env=env)


def _terminate_process(process: Optional[subprocess.Popen[Any]]) -> None:
    if process is None:
        return
    if process.poll() is not None:
        return
    _log("Stopping mock window …")
    try:
        process.terminate()
    except Exception:
        pass
    try:
        process.wait(timeout=3.0)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=1.0)


def _write_label(path: Path, text: str) -> None:
    try:
        path.write_text(text.strip() + "\n", encoding="utf-8")
    except OSError as exc:
        _log(f"Warning: unable to update payload label file {path}: {exc}")


def _replay_payload(log_source: str, ttl: float, *, port: int) -> None:
    ttl_value = max(1, int(round(ttl)))
    command = [
        sys.executable,
        str(SEND_FROM_LOG_PATH),
        "--logfile",
        log_source,
        "--ttl",
        str(ttl_value),
        "--max-payloads",
        "0",
    ]
    _log(f"Sending payload from {log_source} (ttl={ttl_value}) …")
    completed = subprocess.run(command, cwd=PROJECT_ROOT, env=dict(os.environ, MODERN_OVERLAY_PORT=str(port)))
    if completed.returncode != 0:
        raise DriverError(f"Failed to send payload from {log_source} (exit code {completed.returncode}).")


def _coerce_float(value: Any, default: float, minimum: float = 0.0) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        numeric = default
    if numeric < minimum:
        numeric = minimum
    return numeric


def _load_plan(path: Path) -> tuple[Dict[str, float], List[Dict[str, int]], List[Dict[str, Any]]]:
    data = _read_json(path)
    settings_raw = data.get("settings", {})
    if not isinstance(settings_raw, Mapping):
        settings_raw = {}

    window_wait = _coerce_float(settings_raw.get("window_wait_seconds"), default=1.0, minimum=0.0)
    between_wait = _coerce_float(settings_raw.get("wait_between_payload_tests"), default=1.0, minimum=0.0)
    after_wait = _coerce_float(settings_raw.get("after_resolution_wait_seconds"), default=1.0, minimum=0.0)
    fallback_ttl = _coerce_float(settings_raw.get("payload_ttl_seconds"), default=5.0, minimum=0.1)
    wait_to_finish = _coerce_float(settings_raw.get("wait_to_finish_seconds"), default=1.0, minimum=0.0)
    crosshair_x = settings_raw.get("crosshair_x_percent")
    crosshair_y = settings_raw.get("crosshair_y_percent")
    try:
        crosshair_x_value = float(crosshair_x) if crosshair_x is not None else None
    except (TypeError, ValueError):
        crosshair_x_value = None
    try:
        crosshair_y_value = float(crosshair_y) if crosshair_y is not None else None
    except (TypeError, ValueError):
        crosshair_y_value = None

    settings = {
        "window_wait_seconds": window_wait,
        "wait_between_payload_tests": between_wait,
        "after_resolution_wait_seconds": after_wait,
        "payload_ttl_seconds": fallback_ttl,
        "crosshair_x_percent": crosshair_x_value,
        "crosshair_y_percent": crosshair_y_value,
        "wait_to_finish_seconds": wait_to_finish,
    }

    resolutions_raw = data.get("resolutions")
    if not isinstance(resolutions_raw, Iterable):
        raise DriverError("'resolutions' must be a list in test_resolution.json")
    resolutions: List[Dict[str, int]] = []
    for entry in resolutions_raw:
        if not isinstance(entry, Mapping):
            raise DriverError(f"Invalid resolution entry: {entry!r}")
        width = entry.get("width")
        height = entry.get("height")
        try:
            width_int = int(width)
            height_int = int(height)
        except (TypeError, ValueError) as exc:
            raise DriverError(f"Resolution values must be integers: {entry!r}") from exc
        if width_int <= 0 or height_int <= 0:
            raise DriverError(f"Resolution values must be positive: {entry!r}")
        resolutions.append({"width": width_int, "height": height_int})
    if not resolutions:
        raise DriverError("No resolutions found in configuration.")

    payloads_raw = data.get("payloads")
    if not isinstance(payloads_raw, Iterable):
        raise DriverError("'payloads' must be a list in test_resolution.json")
    payloads: List[Dict[str, Any]] = []
    for entry in payloads_raw:
        if not isinstance(entry, Mapping):
            raise DriverError(f"Invalid payload entry: {entry!r}")
        name = str(entry.get("name") or "").strip()
        source = str(entry.get("source") or "").strip()
        if not name or not source:
            raise DriverError(f"Payload entries must include 'name' and 'source': {entry!r}")
        ttl = entry.get("ttl")
        ttl_value = _coerce_float(ttl, default=fallback_ttl, minimum=0.1) if ttl is not None else fallback_ttl
        payloads.append({"name": name, "source": source, "ttl": ttl_value})
    if not payloads:
        raise DriverError("No payloads defined in configuration.")

    return settings, resolutions, payloads


def run_tests(config_path: Path, *, wait_override: Optional[float] = None) -> None:
    _log(f"Loading configuration from {config_path} …")
    settings, resolutions, payloads = _load_plan(config_path)

    window_wait = settings["window_wait_seconds"]
    between_wait = settings["wait_between_payload_tests"]
    after_wait = settings["after_resolution_wait_seconds"]
    crosshair_x = settings.get("crosshair_x_percent")
    crosshair_y = settings.get("crosshair_y_percent")
    wait_to_finish = settings.get("wait_to_finish_seconds", 1.0)
    if wait_override is not None:
        wait_to_finish = max(wait_override, 0.0)

    _ensure_overlay_running()
    port = _resolve_port()
    _log(f"ModernOverlay broadcaster port: {port}")
    _wait_for_overlay_ready(port)

    label_file_handle = tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8")
    label_file_path = Path(label_file_handle.name)
    label_file_handle.close()

    mock_process: Optional[subprocess.Popen[Any]] = None
    try:
        for index, res in enumerate(resolutions, start=1):
            width = res["width"]
            height = res["height"]
            _log(f"--- Resolution {index}/{len(resolutions)}: {width}x{height} ---")
            _terminate_process(mock_process)
            _write_label(label_file_path, "")
            mock_process = _launch_mock_window(
                width,
                height,
                label_file=label_file_path,
                crosshair_x=crosshair_x,
                crosshair_y=crosshair_y,
            )
            time.sleep(window_wait)

            for payload in payloads:
                name = payload["name"]
                source = payload["source"]
                ttl = payload["ttl"]
                _log(f"Payload '{name}' (ttl={ttl}) from {source}")
                _write_label(label_file_path, name)
                _replay_payload(source, ttl, port=port)
                time.sleep(between_wait)

            _write_label(label_file_path, "")
            time.sleep(after_wait)

        if wait_to_finish > 0.0:
            _log(f"Waiting {wait_to_finish:.1f}s before closing mock window …")
            time.sleep(wait_to_finish)
        _log("Resolution payload sweep completed successfully.")
    finally:
        _terminate_process(mock_process)
        try:
            label_file_path.unlink(missing_ok=True)  # type: ignore[arg-type]
        except Exception:
            pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run payload sweeps across resolutions for Modern Overlay.")
    parser.add_argument(
        "--config",
        type=Path,
        default=CONFIG_PATH,
        help="Path to the resolution configuration file (default: %(default)s)",
    )
    parser.add_argument(
        "--wait-to-finish",
        type=float,
        default=None,
        metavar="SECONDS",
        help="Override wait time before closing the mock window at the end (default from config, fallback 1s)",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        run_tests(args.config.resolve(), wait_override=args.wait_to_finish)
    except DriverError as exc:
        _log(f"ERROR: {exc}")
        return 1
    except KeyboardInterrupt:
        _log("Interrupted by user.")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
