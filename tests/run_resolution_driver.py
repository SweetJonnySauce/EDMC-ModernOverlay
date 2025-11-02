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
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TESTS_DIR = PROJECT_ROOT / "tests"
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "test_resolution.json"
PORT_PATH = PROJECT_ROOT / "port.json"

MOCK_WINDOW_PATH = TESTS_DIR / "mock_elite_window.py"
SEND_SHAPE_PATH = TESTS_DIR / "send_overlay_shape.py"
SEND_TEXT_PATH = TESTS_DIR / "send_overlay_text.py"
SEND_FROM_LOG_PATH = TESTS_DIR / "send_overlay_from_log.py"

DEFAULT_LOG_REPLAYS: Dict[str, float] = {
    str(TESTS_DIR / "edr-docking.log"): 2.0,
    str(TESTS_DIR / "landingpad.log"): 2.0,
}
LOG_REPLAY_TTL = 2

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


def _run_overlay_sequences(sequences: Iterable[Mapping[str, Any]]) -> None:
    for entry in sequences:
        if not isinstance(entry, Mapping):
            continue
        command = entry.get("command")
        if not isinstance(command, list):
            continue
        _run_subprocess(command)


def _load_resolutions(path: Path) -> List[Dict[str, Any]]:
    data = _read_json(path)
    raw_list: Iterable[Any]
    if isinstance(data, Mapping) and "resolutions" in data:
        raw_list = data["resolutions"]
    elif isinstance(data, Iterable):
        raw_list = data
    else:
        raise DriverError(f"Unexpected resolution config format in {path}")

    resolutions: List[Dict[str, Any]] = []
    for item in raw_list:
        if not isinstance(item, Mapping):
            raise DriverError(f"Invalid resolution entry: {item!r}")
        width = item.get("width")
        height = item.get("height")
        try:
            width_int = int(width)
            height_int = int(height)
        except (TypeError, ValueError) as exc:
            raise DriverError(f"Resolution values must be integers: {item!r}") from exc
        if width_int <= 0 or height_int <= 0:
            raise DriverError(f"Resolution values must be positive: {item!r}")
        resolutions.append(
            {
                "width": width_int,
                "height": height_int,
            }
        )
    if not resolutions:
        raise DriverError(f"No resolutions found in configuration {path}")
    return resolutions


def run_driver(
    *,
    config_path: Path,
    ttl: float,
    window_delay: float = DEFAULT_WINDOW_DELAY,
    overlay_sequences: Optional[List[Mapping[str, Any]]] = None,
) -> None:
    _log(f"Loading resolution config from {config_path} …")
    resolutions = _load_resolutions(config_path)
    _log(f"Loaded {len(resolutions)} resolutions.")

    if ttl <= 0:
        raise DriverError("TTL must be positive.")

    _ensure_overlay_running()
    port = _resolve_port()
    _log(f"ModernOverlay broadcaster port: {port}")
    mock_process: Optional[subprocess.Popen[Any]] = None
    try:
        for index, case in enumerate(resolutions, start=1):
            width = case["width"]
            height = case["height"]
            _log(f"--- Resolution {index}/{len(resolutions)}: {width}x{height} ---")
            _terminate_process(mock_process)
            mock_process = _launch_mock_window(width, height)
            time.sleep(max(0.1, window_delay))

            time.sleep(1.0)
            if overlay_sequences:
                _run_overlay_sequences(overlay_sequences)
            time.sleep(1.0)

            shape_command = [
                sys.executable,
                str(SEND_SHAPE_PATH),
                "--ttl",
                str(int(LOG_REPLAY_TTL)),
            ]
            text_message = f"Resolution {width}x{height}"
            text_command = [
                sys.executable,
                str(SEND_TEXT_PATH),
                text_message,
                "--ttl",
                str(int(LOG_REPLAY_TTL)),
            ]
            _run_subprocess(shape_command)
            time.sleep(1.0)
            _run_subprocess(text_command)
            time.sleep(5.0)

        _log("Resolution sweep completed successfully.")
    finally:
        _terminate_process(mock_process)


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
        default=5.0,
        help="Master TTL in seconds to apply to overlay payloads and per-resolution hold time (default: %(default)s)",
    )
    parser.add_argument(
        "--window-delay",
        type=float,
        default=DEFAULT_WINDOW_DELAY,
        help="Seconds to wait after spawning the mock window before sending payloads (default: %(default)s)",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    ttl = max(1.0, float(args.ttl))
    window_delay = max(0.1, float(args.window_delay))

    sequences: List[Mapping[str, Any]] = []
    for log_path, _ in DEFAULT_LOG_REPLAYS.items():
        sequences.append(
            {
                "command": [
                    sys.executable,
                    str(SEND_FROM_LOG_PATH),
                    "--logfile",
                    str(log_path),
                    "--ttl",
                    str(int(LOG_REPLAY_TTL)),
                    "--max-payloads",
                    "0",
                ],
            }
        )

    try:
        run_driver(
            config_path=args.config.resolve(),
            ttl=ttl,
            window_delay=window_delay,
            overlay_sequences=sequences,
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
