#!/usr/bin/env python3
"""Validate the plugin's Python against the EDMC-tested baseline."""
from __future__ import annotations

import os
import platform
import sys
from pathlib import Path
from typing import Optional, Tuple


BASE_DIR = Path(__file__).resolve().parents[1]
BASELINE_PATH = BASE_DIR / "docs" / "compliance" / "edmc_python_version.txt"
ALLOW_ENV = "ALLOW_EDMC_PYTHON_MISMATCH"


def _load_expected() -> Tuple[Tuple[int, int, int], Optional[str]]:
    if not BASELINE_PATH.exists():
        raise SystemExit(f"Missing baseline file: {BASELINE_PATH}")
    raw = BASELINE_PATH.read_text(encoding="utf-8").strip()
    if not raw:
        raise SystemExit(f"Baseline file is empty: {BASELINE_PATH}")
    tokens = raw.split()
    version_tokens = tokens[0].strip().split(".")
    try:
        major, minor = int(version_tokens[0]), int(version_tokens[1])
        micro = int(version_tokens[2]) if len(version_tokens) > 2 else 0
    except (IndexError, ValueError) as exc:
        raise SystemExit(f"Unable to parse version in {BASELINE_PATH}: {raw}") from exc
    arch = tokens[1].strip().lower() if len(tokens) > 1 else None
    return (major, minor, micro), arch


def _current_version() -> Tuple[int, int, int]:
    return (sys.version_info.major, sys.version_info.minor, sys.version_info.micro)


def _current_arch() -> str:
    return platform.architecture()[0].lower()


def main() -> None:
    expected_version, expected_arch = _load_expected()
    actual_version = _current_version()
    actual_arch = _current_arch()

    mismatches = []
    if actual_version != expected_version:
        mismatches.append(f"Python version mismatch: expected {expected_version}, found {actual_version}")
    if expected_arch and expected_arch != actual_arch:
        mismatches.append(f"Python arch mismatch: expected {expected_arch}, found {actual_arch}")

    if mismatches:
        message = "; ".join(mismatches)
        if os.environ.get(ALLOW_ENV):
            print(f"[check-edmc-python] WARNING: {message} (override via {ALLOW_ENV})")
            raise SystemExit(0)
        raise SystemExit(f"[check-edmc-python] ERROR: {message} (set {ALLOW_ENV}=1 to bypass)")

    print(f"[check-edmc-python] OK: Python {actual_version} ({actual_arch}) matches baseline in {BASELINE_PATH}")


if __name__ == "__main__":
    main()
