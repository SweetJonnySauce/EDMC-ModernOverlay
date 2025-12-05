#!/usr/bin/env python3
"""Controller workflow helper for validating cache consistency."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def validate_cache_consistency(cache_payload: Mapping[str, Any], *, tolerance: float = 0.5) -> List[Dict[str, Any]]:
    """Return a list of cache entries whose transformed bounds diverge from stored offsets."""

    issues: List[Dict[str, Any]] = []
    groups = cache_payload.get("groups")
    if not isinstance(groups, Mapping):
        return issues
    for plugin_name, plugin_entry in groups.items():
        if not isinstance(plugin_entry, Mapping):
            continue
        for suffix, entry in plugin_entry.items():
            if not isinstance(entry, Mapping):
                continue
            base = entry.get("base")
            transformed = entry.get("transformed")
            if not isinstance(base, Mapping) or not isinstance(transformed, Mapping):
                continue
            base_min_x = _safe_float(base.get("base_min_x"))
            base_min_y = _safe_float(base.get("base_min_y"))
            base_max_x = _safe_float(base.get("base_max_x"))
            base_max_y = _safe_float(base.get("base_max_y"))
            offset_dx = _safe_float(transformed.get("offset_dx", base.get("offset_x")))
            offset_dy = _safe_float(transformed.get("offset_dy", base.get("offset_y")))
            expected_min_x = base_min_x + offset_dx
            expected_min_y = base_min_y + offset_dy
            expected_max_x = base_max_x + offset_dx
            expected_max_y = base_max_y + offset_dy
            actual_min_x = _safe_float(transformed.get("trans_min_x"))
            actual_min_y = _safe_float(transformed.get("trans_min_y"))
            actual_max_x = _safe_float(transformed.get("trans_max_x"))
            actual_max_y = _safe_float(transformed.get("trans_max_y"))
            deltas = (
                abs(actual_min_x - expected_min_x),
                abs(actual_min_y - expected_min_y),
                abs(actual_max_x - expected_max_x),
                abs(actual_max_y - expected_max_y),
            )
            if any(delta > tolerance for delta in deltas):
                issues.append(
                    {
                        "plugin": plugin_name,
                        "group": suffix,
                        "delta": max(deltas),
                        "expected_bounds": (
                            expected_min_x,
                            expected_min_y,
                            expected_max_x,
                            expected_max_y,
                        ),
                        "actual_bounds": (
                            actual_min_x,
                            actual_min_y,
                            actual_max_x,
                            actual_max_y,
                        ),
                    }
                )
    return issues


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate overlay group cache consistency.")
    parser.add_argument(
        "--cache",
        required=True,
        type=Path,
        help="Path to overlay_group_cache.json",
    )
    parser.add_argument(
        "--tolerance",
        type=float,
        default=0.5,
        help="Allowed delta between expected vs. actual transformed bounds (default: 0.5)",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    payload = _load_json(args.cache)
    issues = validate_cache_consistency(payload, tolerance=float(args.tolerance))
    if issues:
        print("[controller-workflow] Detected inconsistent cache entries:")
        for issue in issues:
            print(f"  {issue['plugin']}::{issue['group']} delta={issue['delta']:.3f}")
        return 1
    print("[controller-workflow] Cache consistency check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
