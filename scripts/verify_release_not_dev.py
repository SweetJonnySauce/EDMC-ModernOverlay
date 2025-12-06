#!/usr/bin/env python3
"""Ensure release builds do not run with dev-mode settings enabled."""

from __future__ import annotations

import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from version import DEV_MODE_ENV_VAR, __version__, is_dev_build  # noqa: E402


def _env_truthy(value: str | None) -> bool:
    if value is None:
        return False
    token = value.strip().lower()
    if not token:
        return False
    if token in {"0", "false", "no", "off"}:
        return False
    return True


def main() -> int:
    env_value = os.getenv(DEV_MODE_ENV_VAR)
    if _env_truthy(env_value):
        print(
            f"Release build aborted: {DEV_MODE_ENV_VAR}={env_value!r} forces dev mode. "
            "Unset the variable before tagging a release.",
            file=sys.stderr,
        )
        return 1

    if is_dev_build():
        print(
            f"Release build aborted: version '{__version__}' is marked as a dev build. "
            "Update version.py before publishing.",
            file=sys.stderr,
        )
        return 1

    print(f"Release guard passed: version={__version__} dev_mode_env={env_value!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
