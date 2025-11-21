#!/usr/bin/env python3
"""Replay overlay payloads stored in a logfile through the ModernOverlay CLI."""
from __future__ import annotations

import argparse
import json
import shutil
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SETTINGS_PATH = PLUGIN_ROOT / "overlay_settings.json"
DEBUG_CONFIG_PATH = PLUGIN_ROOT / "debug.json"
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


def _debug_payload_logging() -> bool:
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
        legacy_flag = section.get("enabled")
        if isinstance(legacy_flag, bool):
            return legacy_flag
    legacy_top = config.get("log_payloads")
    if isinstance(legacy_top, bool):
        return legacy_top
    if legacy_top is not None:
        return bool(legacy_top)
    return False


def _is_payload_logging_enabled() -> bool:
    pref_flag = _settings_payload_logging()
    if pref_flag is not None:
        return pref_flag
    return _debug_payload_logging()


def _warn_payload_logging() -> None:
    if _is_payload_logging_enabled():
        _print_step("Detected overlay payload logging enabled (overlay-payloads.log).")
    else:
        _print_step(
            "WARNING: overlay payload logging is disabled. Enable \"Log incoming payloads\" in the Modern Overlay"
            " preferences to mirror payloads to overlay-payloads.log."
        )


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


def _resolve_logfile(path_str: str) -> Path:
    raw_path = Path(path_str)
    candidates: List[Path]
    if raw_path.is_absolute():
        candidates = [raw_path]
    else:
        candidates = [
            Path.cwd() / raw_path,
            PLUGIN_ROOT / raw_path,
        ]
        if not raw_path.parts or raw_path.parts[0] != "tests":
            candidates.append(PLUGIN_ROOT / "tests" / raw_path)
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    _fail(f"Log file not found: {path_str}")


def _extract_json_segment(line: str, line_no: int) -> Optional[Dict[str, Any]]:
    """Return the first JSON object found in a log line."""
    start = line.find("{")
    if start == -1:
        return None
    segment = line[start:]
    try:
        return json.loads(segment)
    except json.JSONDecodeError:
        _print_step(f"Skipping line {line_no}: JSON decode failed.")
        return None


def _extract_payload(
    raw_line: str,
    line_no: int,
    *,
    ttl_override: Optional[int],
) -> Optional[Tuple[str, Dict[str, Any]]]:
    record = _extract_json_segment(raw_line, line_no)
    if record is None:
        return None
    payload_obj = record.get("raw")
    if not isinstance(payload_obj, dict):
        payload_obj = record.get("payload")
    if not isinstance(payload_obj, dict):
        payload_obj = record
    if not isinstance(payload_obj, dict):
        _print_step(f"Skipping line {line_no}: payload object not found.")
        return None
    payload = dict(payload_obj)
    if ttl_override is not None:
        payload["ttl"] = ttl_override
    payload_type = payload.get("type")
    if isinstance(payload_type, str) and payload_type.lower() == "legacy_clear":
        payload_id = payload.get("id")
        _print_step(
            f"Skipping line {line_no}: legacy_clear payload{f' ({payload_id})' if payload_id else ''}."
        )
        return None
    ttl_value = payload.get("ttl")
    if isinstance(ttl_value, (int, float)) and ttl_value <= 0:
        _print_step(f"Skipping line {line_no}: ttl <= 0 ({ttl_value}).")
        return None
    event = payload.get("event")
    if not isinstance(event, str) or not event:
        event_value = record.get("event")
        if isinstance(event_value, str) and event_value:
            event = event_value
        else:
            event = "LegacyOverlay"
        payload.setdefault("event", event)
    return event, payload


def _command_for_event(event: str) -> Optional[str]:
    event_lower = event.lower()
    if not event_lower or event_lower == "legacyoverlay":
        return "legacy_overlay"
    if event_lower == "overlaymetrics":
        return "overlay_metrics"
    if event_lower == "overlayconfig":
        return "overlay_controller"
    return None


def _build_cli_message(
    command: str,
    payload: Dict[str, Any],
    *,
    log_path: Path,
    line_no: int,
) -> Dict[str, Any]:
    if command == "legacy_overlay":
        payload_type = str(payload.get("type") or "message").lower()
        if payload_type == "message":
            text = str(payload.get("text") or "").strip()
            if not text:
                raise ValueError("LegacyOverlay message payload has empty text")
        message: Dict[str, Any] = {
            "cli": "legacy_overlay",
            "payload": payload,
        }
    elif command == "overlay_metrics":
        message = {"cli": "overlay_metrics", **payload}
    elif command in ("overlay_controller", "overlay_config"):
        config_payload = dict(payload)
        config_payload.pop("event", None)
        message = {"cli": "overlay_controller", "config": config_payload}
    else:
        raise ValueError(f"Unsupported CLI command: {command}")
    meta = message.setdefault("meta", {})
    if not isinstance(meta, dict):
        meta = {}
        message["meta"] = meta
    meta.setdefault("source", "replay_overlay_logfile")
    meta.setdefault("logfile", str(log_path))
    meta.setdefault("line", line_no)
    return message


def _iter_cli_messages(log_path: Path, ttl_override: Optional[int]) -> Iterable[Dict[str, Any]]:
    with log_path.open("r", encoding="utf-8") as handle:
        for line_no, raw_line in enumerate(handle, start=1):
            if not raw_line.strip():
                continue
            extracted = _extract_payload(raw_line, line_no, ttl_override=ttl_override)
            if not extracted:
                continue
            event, payload = extracted
            command = _command_for_event(event)
            if not command:
                _print_step(f"Skipping line {line_no}: unsupported event '{event}'.")
                continue
            try:
                yield _build_cli_message(command, payload, log_path=log_path, line_no=line_no)
            except Exception as exc:
                _print_step(f"Skipping line {line_no}: unable to build CLI payload ({exc}).")
                continue


def main(argv: List[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Replay overlay payloads recorded in a logfile by sending them to ModernOverlay.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--logfile",
        required=True,
        help="Path to the logfile whose payloads should be replayed.",
    )
    parser.add_argument(
        "--max-payloads",
        type=int,
        default=0,
        help="Optional cap on the number of payloads to send (0 means no limit).",
    )
    parser.add_argument(
        "--ttl",
        type=int,
        help="Override TTL value applied to LegacyOverlay payloads.",
    )
    args = parser.parse_args(argv)

    log_path = _resolve_logfile(args.logfile)
    if args.max_payloads < 0:
        _fail("--max-payloads must be zero or positive.")

    _print_step(f"Using plugin root: {PLUGIN_ROOT}")
    _print_step(f"Resolved logfile to {log_path}")
    _load_json(SETTINGS_PATH)
    _warn_payload_logging()

    _ensure_overlay_client_running()

    port_data = _load_json(PORT_PATH)
    port = port_data.get("port")
    if not isinstance(port, int) or port <= 0:
        _fail(f"port.json does not contain a valid port: {port_data!r}")
    _print_step(f"ModernOverlay broadcaster port resolved to {port}.")

    ttl_override = args.ttl
    if ttl_override is not None and ttl_override <= 0:
        _fail("--ttl must be positive when provided.")

    messages: List[Dict[str, Any]] = []
    for message in _iter_cli_messages(log_path, ttl_override):
        messages.append(message)
        if args.max_payloads and len(messages) >= args.max_payloads:
            break

    if not messages:
        _fail(f"No replayable payloads found in {log_path}.")

    total = len(messages)
    _print_step(f"Prepared {total} payload(s) for replay.")

    for seq, message in enumerate(messages, start=1):
        meta = message.setdefault("meta", {})
        if isinstance(meta, dict):
            meta.setdefault("sequence", seq)
            meta.setdefault("count", total)
        response = _send_payload(port, message)
        status = response.get("status")
        if status == "ok":
            _print_step(f"Payload {seq}/{total} acknowledged.")
        else:
            error_msg = response.get("error") or response
            _fail(f"ModernOverlay reported an error for payload {seq}: {error_msg}")

    _print_step("All payloads replayed successfully.")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:
        print(
            "[overlay-cli] ERROR: Unexpected failure while replaying overlay payloads from logfile.",
            file=sys.stderr,
        )
        print(f"[overlay-cli] DETAILS: {exc}", file=sys.stderr)
        print(
            "[overlay-cli] usage: PYTHONPATH=. python3 tests/send_overlay_from_log.py --logfile PATH [--max-payloads N] [--ttl SECONDS]",
            file=sys.stderr,
        )
        raise SystemExit(1)
