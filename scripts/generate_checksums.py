#!/usr/bin/env python3
"""Generate a SHA256 manifest for release validation.

The manifest is consumed by install_linux.sh to verify the extracted release
and the installed plugin tree. It hashes files under EDMCModernOverlay/ by
default and writes a checksums.txt compatible with `sha256sum -c`.
"""

from __future__ import annotations

import argparse
import hashlib
import pathlib
import sys
from typing import Iterable


DEFAULT_MANIFEST = "checksums.txt"
DEFAULT_TARGET_DIR = "EDMCModernOverlay"

EXCLUDE_DIR_NAMES = {
    ".git",
    ".github",
    ".mypy_cache",
    ".pytest_cache",
    "__pycache__",
    ".idea",
    ".vscode",
    ".venv",
    "logs",
}

EXCLUDE_FILE_NAMES = {
    DEFAULT_MANIFEST,
    ".DS_Store",
}

EXCLUDE_SUBSTRINGS = {
    "overlay_client/.venv",
}


def hash_file(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def should_skip(relative_path: pathlib.Path) -> bool:
    if relative_path.name in EXCLUDE_FILE_NAMES:
        return True
    for part in relative_path.parts:
        if part in EXCLUDE_DIR_NAMES:
            return True
    rel_str = relative_path.as_posix()
    for needle in EXCLUDE_SUBSTRINGS:
        if needle in rel_str:
            return True
    return False


def build_manifest(root: pathlib.Path, target_dir: pathlib.Path) -> Iterable[str]:
    for path in sorted(target_dir.rglob("*")):
        if not path.is_file():
            continue
        relative_path = path.relative_to(root)
        if should_skip(relative_path):
            continue
        yield f"{hash_file(path)}  {relative_path.as_posix()}"


def parse_args() -> argparse.Namespace:
    default_root = pathlib.Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description="Generate SHA256 manifest for release assets.")
    parser.add_argument(
        "--root",
        type=pathlib.Path,
        default=default_root,
        help="Release root containing EDMCModernOverlay/ (default: repository root).",
    )
    parser.add_argument(
        "--target-dir",
        type=pathlib.Path,
        default=None,
        help="Directory to hash relative to root (default: EDMCModernOverlay under root).",
    )
    parser.add_argument(
        "--output",
        type=pathlib.Path,
        default=None,
        help=f"Manifest output path (default: <root>/{DEFAULT_MANIFEST}).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.root.resolve()
    target_dir = args.target_dir or root / DEFAULT_TARGET_DIR
    target_dir = target_dir.resolve()
    if not target_dir.exists() or not target_dir.is_dir():
        print(f"Target directory '{target_dir}' not found. Pass --target-dir to override.", file=sys.stderr)
        return 1

    output_path = args.output or root / DEFAULT_MANIFEST
    lines = list(build_manifest(root, target_dir))
    if not lines:
        print(f"No files hashed under '{target_dir}'. Check exclusions.", file=sys.stderr)
        return 1

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {len(lines)} checksums to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
