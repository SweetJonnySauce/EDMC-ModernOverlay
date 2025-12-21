"""Ensure pytest runs with the correct project environment.

Usage:
    python tests/configure_pytest_environment.py

This script inserts the project root on sys.path so relative imports inside the
plugin resolve correctly, and then dispatches pytest with the arguments you
provide.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def _ensure_pyqt6() -> None:
    try:
        import PyQt6  # noqa: F401
        return
    except ImportError:
        pass

    print("PyQt6 is not installed; attempting to install it now.", file=sys.stderr)
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "PyQt6"],
        check=False,
    )
    if result.returncode != 0:
        print("Failed to install PyQt6. Install it manually and retry.", file=sys.stderr)
        raise SystemExit(result.returncode)
    try:
        import PyQt6  # noqa: F401
    except ImportError as exc:  # pragma: no cover
        print("PyQt6 is still unavailable after installation.", file=sys.stderr)
        raise SystemExit(1) from exc


def main(argv: list[str]) -> int:
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))

    try:
        import pytest  # type: ignore
    except ImportError as exc:  # pragma: no cover
        print("pytest is not installed in this environment.", file=sys.stderr)
        raise SystemExit(1) from exc

    _ensure_pyqt6()

    return pytest.main(argv)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
