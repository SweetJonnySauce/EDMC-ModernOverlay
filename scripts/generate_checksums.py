#!/usr/bin/env python3
"""Generate a SHA256 manifest for release validation.

The manifest is consumed by install_linux.sh to verify the extracted release
and the installed plugin tree. It hashes files under EDMCModernOverlay/ by
default and writes a checksums.txt compatible with `sha256sum -c`.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import pathlib
import sys
from typing import Iterable


DEFAULT_MANIFEST = "checksums.txt"
DEFAULT_TARGET_DIR = "EDMCModernOverlay"

DEFAULT_EXCLUDE_SUBSTRINGS = {"overlay_client/.venv"}


def hash_file(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def should_skip(
    relative_path: pathlib.Path,
    exclude_dirs: set[str],
    exclude_root_dirs: set[str],
    exclude_files: set[str],
    exclude_patterns: list[str],
    exclude_substrings: set[str],
) -> bool:
    if relative_path.name in exclude_files:
        return True

    parts = relative_path.parts
    if parts:
        first = parts[0]
        if first in exclude_root_dirs:
            return True

    for part in parts:
        if part in exclude_dirs:
            return True

    name = relative_path.name
    for pattern in exclude_patterns:
        if fnmatch.fnmatch(name, pattern):
            return True

    rel_str = relative_path.as_posix()
    for needle in exclude_substrings:
        if needle in rel_str:
            return True
    return False


def load_excludes(manifest_path: pathlib.Path) -> dict:
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    return {
        "directories": set(data.get("directories", [])),
        "root_directories": set(data.get("root_directories", [])),
        "files": set(data.get("files", [])) | {DEFAULT_MANIFEST, ".DS_Store"},
        "patterns": list(data.get("patterns", [])),
        "substrings": set(data.get("substrings", [])) | DEFAULT_EXCLUDE_SUBSTRINGS,
    }


def build_manifest(root: pathlib.Path, target_dir: pathlib.Path, excludes: dict) -> Iterable[str]:
    exclude_dirs = excludes["directories"]
    exclude_root_dirs = excludes["root_directories"]
    exclude_files = excludes["files"]
    exclude_patterns = excludes["patterns"]
    exclude_substrings = excludes["substrings"]

    for path in sorted(target_dir.rglob("*")):
        if not path.is_file():
            continue
        relative_path = path.relative_to(root)
        if should_skip(
            relative_path,
            exclude_dirs,
            exclude_root_dirs,
            exclude_files,
            exclude_patterns,
            exclude_substrings,
        ):
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
    parser.add_argument(
        "--excludes",
        type=pathlib.Path,
        default=pathlib.Path(__file__).resolve().parent / "release_excludes.json",
        help="Path to JSON manifest listing files/directories/patterns to exclude from hashing.",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Verify an existing manifest instead of generating a new one.",
    )
    parser.add_argument(
        "--manifest",
        type=pathlib.Path,
        default=None,
        help=f"Path to an existing manifest to verify (default: <root>/{DEFAULT_MANIFEST}).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.root.resolve()
    manifest_path = (args.manifest or root / DEFAULT_MANIFEST).resolve()

    if args.verify:
        if not manifest_path.is_file():
            print(f"Manifest '{manifest_path}' not found; cannot verify.", file=sys.stderr)
            return 1
        try:
            manifest_lines = manifest_path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            print(f"Failed to read manifest '{manifest_path}': {exc}", file=sys.stderr)
            return 1

        expected = {}
        ok = True
        for line in manifest_lines:
            line = line.strip()
            if not line:
                continue
            if "  " not in line:
                print(f"Skipping malformed manifest line: {line}", file=sys.stderr)
                ok = False
                continue
            digest, rel = line.split("  ", 1)
            expected[pathlib.Path(rel)] = digest

        mismatches = []
        missing = []
        extras = []

        for rel_path, digest in expected.items():
            candidate = root / rel_path
            if not candidate.is_file():
                missing.append(rel_path.as_posix())
                ok = False
                continue
            actual = hash_file(candidate)
            if actual != digest:
                mismatches.append((rel_path.as_posix(), digest, actual))
                ok = False

        for extra in root.rglob("*"):
            if not extra.is_file():
                continue
            rel_extra = extra.relative_to(root)
            if rel_extra not in expected and DEFAULT_MANIFEST not in rel_extra.parts:
                extras.append(rel_extra.as_posix())

        if not ok or missing or mismatches or extras:
            if missing:
                print("Missing files:", file=sys.stderr)
                for item in missing[:10]:
                    print(f"  {item}", file=sys.stderr)
                if len(missing) > 10:
                    print(f"  ... and {len(missing) - 10} more", file=sys.stderr)
            if mismatches:
                print("Hash mismatches:", file=sys.stderr)
                for rel, exp, act in mismatches[:10]:
                    print(f"  {rel}: expected {exp}, got {act}", file=sys.stderr)
                if len(mismatches) > 10:
                    print(f"  ... and {len(mismatches) - 10} more", file=sys.stderr)
            if extras:
                print("Extra files not in manifest:", file=sys.stderr)
                for item in extras[:10]:
                    print(f"  {item}", file=sys.stderr)
                if len(extras) > 10:
                    print(f"  ... and {len(extras) - 10} more", file=sys.stderr)
            return 1

        print(f"Manifest verified against root '{root}'.")
        return 0

    target_dir = args.target_dir or root / DEFAULT_TARGET_DIR
    target_dir = target_dir.resolve()
    if not target_dir.exists() or not target_dir.is_dir():
        print(f"Target directory '{target_dir}' not found. Pass --target-dir to override.", file=sys.stderr)
        return 1

    output_path = args.output or root / DEFAULT_MANIFEST

    excludes_path = args.excludes.resolve()
    if not excludes_path.is_file():
        print(f"Exclude manifest '{excludes_path}' not found.", file=sys.stderr)
        return 1
    excludes = load_excludes(excludes_path)

    lines = list(build_manifest(root, target_dir, excludes))
    if not lines:
        print(f"No files hashed under '{target_dir}'. Check exclusions.", file=sys.stderr)
        return 1

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {len(lines)} checksums to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
