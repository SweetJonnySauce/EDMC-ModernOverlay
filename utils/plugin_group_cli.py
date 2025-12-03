#!/usr/bin/env python3
"""Utility to exercise Modern Overlay's plugin-group API."""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import os
from pathlib import Path

from overlay_plugin import overlay_api
from overlay_plugin.overlay_api import PluginGroupingError

ANCHORS = ("nw", "ne", "sw", "se", "center", "top", "bottom", "left", "right")


def _default_groupings_path() -> Path:
    env = os.environ.get("MODERN_OVERLAY_GROUPINGS_PATH")
    if env:
        return Path(env).expanduser()
    return Path(__file__).resolve().parents[1] / "overlay_groupings.json"


def _load_preview(path: Path, plugin_group: str) -> str:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return "<file created>"
    except Exception as exc:  # pragma: no cover - CLI diagnostic
        return f"<failed to read preview: {exc}>"
    fragment = data.get(plugin_group)
    if fragment is None:
        return "<entry missing>"
    return json.dumps(fragment, indent=2, ensure_ascii=False)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create or replace Modern Overlay plugin group metadata")
    parser.add_argument("--groupings-path", type=Path, default=_default_groupings_path(), help="Path to overlay_groupings.json")
    parser.add_argument("--plugin-group", required=True, help="Top-level plugin group name")
    parser.add_argument("--matching-prefixes", nargs="*", help="Full replacement list for matchingPrefixes")
    parser.add_argument("--id-prefix-group", help="Nested idPrefixGroup to create/replace")
    parser.add_argument("--id-prefixes", nargs="*", help="Prefixes associated with the idPrefixGroup")
    parser.add_argument("--anchor", choices=ANCHORS, help="Anchor for the idPrefixGroup")
    parser.add_argument("--write", action="store_true", help="Persist the change instead of running a dry-run preview")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv or sys.argv[1:])
    groupings_path = args.groupings_path.expanduser().resolve()

    if not args.write:
        tmp_dir = tempfile.TemporaryDirectory(prefix="mo-groups-")
        tmp_path = Path(tmp_dir.name) / groupings_path.name
        if groupings_path.exists():
            shutil.copy2(groupings_path, tmp_path)
        target_path = tmp_path
    else:
        tmp_dir = None
        target_path = groupings_path

    overlay_api.register_grouping_store(target_path)
    try:
        updated = overlay_api.define_plugin_group(
            plugin_group=args.plugin_group,
            matching_prefixes=args.matching_prefixes,
            id_prefix_group=args.id_prefix_group,
            id_prefixes=args.id_prefixes,
            id_prefix_group_anchor=args.anchor,
        )
    except PluginGroupingError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    finally:
        overlay_api.unregister_grouping_store()

    if not args.write:
        print("Dry-run complete; original file left untouched.")
        print("Preview of plugin entry:")
        print(_load_preview(target_path, args.plugin_group))
        if tmp_dir:
            tmp_dir.cleanup()
    else:
        if updated:
            print(f"Updated {target_path}")
        else:
            print(f"No changes required; {target_path} already up-to-date")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
