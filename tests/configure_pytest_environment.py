"""Ensure pytest runs with the correct project environment.

Usage:
    python tests/configure_pytest_environment.py

This script inserts the project root on sys.path so relative imports inside the
plugin resolve correctly, and then dispatches pytest with the arguments you
provide.
"""
from __future__ import annotations

import sys
from pathlib import Path


def main(argv: list[str]) -> int:
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))

    try:
        import pytest  # type: ignore
    except ImportError as exc:  # pragma: no cover
        print("pytest is not installed in this environment.", file=sys.stderr)
        raise SystemExit(1) from exc

    return pytest.main(argv)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
