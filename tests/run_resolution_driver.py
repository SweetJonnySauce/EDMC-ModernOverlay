#!/usr/bin/env python3
"""Automate ModernOverlay validation across multiple mock Elite window sizes."""

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
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TESTS_DIR = PROJECT_ROOT / "tests"
DEFAULT_CONFIG_PATH = TESTS_DIR / "test_resolution.json"
PORT_PATH = PROJECT_ROOT / "port.json"

MOCK_WINDOW_PATH = TESTS_DIR / "mock_elite_window.py"
SEND_FROM_LOG_PATH = TESTS_DIR / "send_overlay_from_log.py"

DEFAULT_TITLE = "Elite - Dangerous (Stub)"
DEFAULT_WINDOW_DELAY = 1.0
ACK_TIMEOUT = 5.0


class DriverError(RuntimeError):
    """Error raised when the resolution driver encounters a fatal condition."""


def _log(message: str) -> None:
    print(f"[resolution-driver] {message}")


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
        raise DriverError("Could not find overlay_client.py process. Launch the overlay before running the driver.")
    _log("Overlay client process detected.")


def _resolve_port() -> int:
    data = _read_json(PORT_PATH)
    port = data.get("port")
    if not isinstance(port, int) or port <= 0:
        raise DriverError(f"port.json does not contain a valid port number: {data!r}")
    return port


def _send_cli_payload(port: int, payload: Mapping[str, Any], *, timeout: float = ACK_TIMEOUT) -> Mapping[str, Any]:
    message = json.dumps(payload, ensure_ascii=False)
    _log(f"Connecting to ModernOverlay broadcaster on 127.0.0.1:{port} …")
    with socket.create_connection(("127.0.0.1", port), timeout=timeout) as sock:
        sock.settimeout(timeout)
        writer = sock.makefile("w", encoding="utf-8", newline="\n")
        reader = sock.makefile("r", encoding="utf-8")
        writer.write(message)
        writer.write("\n")
        writer.flush()
        _log("Payload dispatched; awaiting acknowledgement …")
        for _ in range(12):
            response_line = reader.readline()
            if not response_line:
                raise DriverError("No acknowledgement received from ModernOverlay (connection closed).")
            try:
                response = json.loads(response_line)
            except json.JSONDecodeError:
                continue
            if isinstance(response, Mapping) and "status" in response:
                return response
            _log("Received broadcast payload before acknowledgement; waiting for status …")
    raise DriverError("ModernOverlay did not acknowledge the CLI payload.")

def _run_subprocess(command: Sequence[str], *, env: Optional[Mapping[str, str]] = None) -> None:
    _log(f"Executing: {' '.join(command)}")
    completed = subprocess.run(command, cwd=PROJECT_ROOT, env=dict(os.environ, **env) if env else None, check=False)
    if completed.returncode != 0:
        raise DriverError(f"Command failed with exit code {completed.returncode}: {' '.join(command)}")


def _launch_mock_window(
    width: int,
    height: int,
    *,
    title: str = DEFAULT_TITLE,
    payload_label: str = "",
    label_file: Optional[Path] = None,
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
    ]
    if payload_label:
        command.extend(["--payload-label", payload_label])
    if label_file:
        command.extend(["--label-file", str(label_file)])
    _log(f"Launching mock Elite window at {width}x{height} …")
    process = subprocess.Popen(command, cwd=PROJECT_ROOT, env=env)
    return process


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


def _replay_log_payload(log_source: str, ttl_seconds: float) -> None:
    ttl_seconds = max(0.1, ttl_seconds)
    ttl_override = max(1, int(round(ttl_seconds)))
    command = [
        sys.executable,
        str(SEND_FROM_LOG_PATH),
        "--logfile",
        log_source,
        "--ttl",
        str(ttl_override),
        "--max-payloads",
        "0",
    ]
    _run_subprocess(command)


def _write_payload_label(path: Path, label: str) -> None:
    try:
        path.write_text(label.strip() + "\n", encoding="utf-8")
    except OSError as exc:
        _log(f"Warning: unable to update payload label file {path}: {exc}")


def _prompt_action(payload_name: str, resolution: Tuple[int, int], *, default: str = "continue") -> str:
    prompt = (
        f"[resolution-driver] Finished '{payload_name}' at {resolution[0]}x{resolution[1]}."
        " Press Enter to continue, type 'a' to run all, or 's' to stop: "
    )
    try:
        response = input(prompt).strip().lower()
    except (EOFError, KeyboardInterrupt):
        return "stop"
    if not response:
        return default
    if response in {"s", "stop"}:
        return "stop"
    if response in {"a", "all"}:
        return "all"
    return "continue"


def _coerce_positive_float(value: Any, *, default: float, minimum: float = 0.0) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        numeric = default
    if numeric < minimum:
        numeric = minimum
    return numeric


def _load_test_plan(path: Path) -> Tuple[Dict[str, float], List[Dict[str, int]], List[Dict[str, str]]]:
    data = _read_json(path)
    if not isinstance(data, Mapping):
        raise DriverError(f"Resolution config must be a JSON object: {path}")

    settings_raw = data.get("settings", {})
    if not isinstance(settings_raw, Mapping):
        settings_raw = {}

    window_wait = _coerce_positive_float(settings_raw.get("window_wait_seconds"), default=DEFAULT_WINDOW_DELAY, minimum=0.0)
    after_resolution_wait = _coerce_positive_float(
        settings_raw.get("after_resolution_wait_seconds"),
        default=1.0,
        minimum=0.0,
    )
    payload_ttl = _coerce_positive_float(settings_raw.get("payload_ttl_seconds"), default=5.0, minimum=0.1)

    settings = {
        "window_wait_seconds": window_wait,
        "after_resolution_wait_seconds": after_resolution_wait,
        "payload_ttl_seconds": payload_ttl,
    }

    resolutions_raw = data.get("resolutions")
    if not isinstance(resolutions_raw, Iterable):
        raise DriverError(f"'resolutions' must be a list in {path}")
    resolutions: List[Dict[str, int]] = []
    for res_entry in resolutions_raw:
        if not isinstance(res_entry, Mapping):
            raise DriverError(f"Invalid resolution entry: {res_entry!r}")
        width = res_entry.get("width")
        height = res_entry.get("height")
        try:
            width_int = int(width)
            height_int = int(height)
        except (TypeError, ValueError) as exc:
            raise DriverError(f"Resolution values must be integers: {res_entry!r}") from exc
        if width_int <= 0 or height_int <= 0:
            raise DriverError(f"Resolution values must be positive: {res_entry!r}")
        resolutions.append({"width": width_int, "height": height_int})
    if not resolutions:
        raise DriverError(f"No resolutions found in configuration {path}")

    payloads_raw = data.get("payloads")
    if not isinstance(payloads_raw, Iterable):
        raise DriverError(f"'payloads' must be a list in {path}")
    payloads: List[Dict[str, str]] = []
    for index, payload_entry in enumerate(payloads_raw, start=1):
        if not isinstance(payload_entry, Mapping):
            raise DriverError(f"Invalid payload entry: {payload_entry!r}")
        name_value = payload_entry.get("name")
        name = str(name_value).strip() if isinstance(name_value, str) else ""
        if not name:
            name = f"payload-{index}"
        source_value = payload_entry.get("source")
        if not isinstance(source_value, str) or not source_value.strip():
            raise DriverError(f"Payload '{name}' missing valid source: {payload_entry!r}")
        payloads.append({"name": name, "source": source_value.strip()})
    if not payloads:
        raise DriverError(f"No payloads found in configuration {path}")

    return settings, resolutions, payloads


def run_driver(
    *,
    config_path: Path,
    ttl_override: Optional[float] = None,
    window_delay_override: Optional[float] = None,
) -> None:
    _log(f"Loading resolution config from {config_path} …")
    settings, resolutions, payloads = _load_test_plan(config_path)
    _log(f"Loaded {len(resolutions)} resolution(s) and {len(payloads)} payload set(s).")

    if ttl_override is not None:
        settings["payload_ttl_seconds"] = _coerce_positive_float(ttl_override, default=settings["payload_ttl_seconds"], minimum=0.1)
    if window_delay_override is not None:
        settings["window_wait_seconds"] = _coerce_positive_float(
            window_delay_override,
            default=settings["window_wait_seconds"],
            minimum=0.0,
        )

    payload_ttl = settings["payload_ttl_seconds"]
    window_wait = settings["window_wait_seconds"]
    after_resolution_wait = settings["after_resolution_wait_seconds"]

    _ensure_overlay_running()
    port = _resolve_port()
    _log(f"ModernOverlay broadcaster port: {port}")
    _log(f"Configured waits — window: {window_wait}s, after resolution: {after_resolution_wait}s")
    _log(f"Payload TTL override: {payload_ttl}s")
    label_file_handle = tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8")
    label_file_path = Path(label_file_handle.name)
    label_file_handle.close()
    _write_payload_label(label_file_path, "")
    mock_process: Optional[subprocess.Popen[Any]] = None
    run_all = False
    try:
        for index, case in enumerate(resolutions, start=1):
            width = case["width"]
            height = case["height"]
            _log(f"--- Resolution {index}/{len(resolutions)}: {width}x{height} ---")
            _terminate_process(mock_process)
            _write_payload_label(label_file_path, "")
            mock_process = _launch_mock_window(width, height, payload_label="", label_file=label_file_path)
            time.sleep(max(0.0, window_wait))

            for payload_index, payload_entry in enumerate(payloads, start=1):
                payload_name = payload_entry["name"]
                payload_source = payload_entry["source"]
                _log(f"=== Payload {payload_index}/{len(payloads)} ({payload_name}) at {width}x{height} ===")
                _log(f"Replaying payloads from {payload_source} …")
                _write_payload_label(label_file_path, payload_name)
                _replay_log_payload(payload_source, payload_ttl)
                _write_payload_label(label_file_path, "")
                if not run_all:
                    action = _prompt_action(payload_name, (width, height))
                    if action == "stop":
                        _log("Stopping at user request.")
                        return
                    if action == "all":
                        run_all = True
                time.sleep(max(0.0, after_resolution_wait))

        _log("Resolution sweep completed successfully.")
    finally:
        _terminate_process(mock_process)
        try:
            label_file_path.unlink(missing_ok=True)  # type: ignore[arg-type]
        except Exception:
            pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Drive ModernOverlay through a sequence of mock Elite window resolutions.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help="Path to the resolution list JSON file (default: %(default)s)",
    )
    parser.add_argument(
        "--ttl",
        type=float,
        default=None,
        help="Optional override for payload TTL seconds (otherwise taken from config file).",
    )
    parser.add_argument(
        "--window-delay",
        type=float,
        default=None,
        help="Optional override for initial window wait seconds (otherwise taken from config file).",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        run_driver(
            config_path=args.config.resolve(),
            ttl_override=float(args.ttl) if args.ttl is not None else None,
            window_delay_override=float(args.window_delay) if args.window_delay is not None else None,
        )
    except DriverError as exc:
        _log(f"ERROR: {exc}")
        return 1
    except KeyboardInterrupt:
        _log("Interrupted by user.")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
