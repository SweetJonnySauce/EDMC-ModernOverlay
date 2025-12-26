"""Diff helpers for overlay groupings.

Given shipped defaults and a merged view (shipped + user), compute the minimal
user-layer payload that would reproduce the merged view when overlaid on the
shipped defaults. Pure helpers: no file IO.
"""
from __future__ import annotations

import logging
import json
import os
from pathlib import Path
from typing import Any, Dict, Mapping

from prefix_entries import parse_prefix_entries, serialise_prefix_entries

from overlay_plugin.overlay_api import (
    PluginGroupingError,
    _normalise_anchor,
    _normalise_background_color,
    _normalise_border_width,
    _normalise_justification,
    _normalise_marker_label_position,
    _normalise_offset,
    _normalise_prefixes,
)
from overlay_plugin.groupings_loader import merge_groupings_dicts

LOGGER = logging.getLogger("EDMC.ModernOverlay.GroupingsDiff")


def diff_groupings(shipped: Mapping[str, Any], merged: Mapping[str, Any]) -> Dict[str, Any]:
    """Return overrides-only payload that, when overlaid on shipped, yields merged."""

    shipped_plugins = shipped if isinstance(shipped, Mapping) else {}
    merged_plugins = merged if isinstance(merged, Mapping) else {}

    result: Dict[str, Any] = {}
    plugin_names = sorted(set(shipped_plugins.keys()) | set(merged_plugins.keys()), key=str.casefold)

    for plugin_name in plugin_names:
        shipped_entry_raw = shipped_plugins.get(plugin_name)
        merged_entry_raw = merged_plugins.get(plugin_name)

        # Plugin disabled: present in shipped, absent in merged.
        if merged_entry_raw is None and shipped_entry_raw is not None:
            result[plugin_name] = {"disabled": True}
            continue

        if merged_entry_raw is None:
            continue

        merged_entry = _normalise_plugin_entry(plugin_name, merged_entry_raw)
        shipped_entry = (
            _normalise_plugin_entry(plugin_name, shipped_entry_raw) if shipped_entry_raw is not None else {}
        )

        plugin_diff = _diff_plugin(plugin_name, shipped_entry, merged_entry)
        if plugin_diff:
            result[plugin_name] = plugin_diff

    return _sorted_dict(result)


def is_empty_diff(payload: Mapping[str, Any]) -> bool:
    """Return True when diff payload has no plugins/groups/fields."""

    if not payload:
        return True
    for _, entry in payload.items():
        if isinstance(entry, Mapping) and entry:
            return False
    return True


def shrink_user_groupings(shipped: Mapping[str, Any], user: Mapping[str, Any]) -> Dict[str, Any]:
    """Return minimal user payload by dropping entries identical to shipped."""

    merged = merge_groupings_dicts(shipped, user)
    return diff_groupings(shipped, merged)


def shrink_user_file(
    shipped_path: Path,
    user_path: Path,
    *,
    backup: bool = True,
    logger: logging.Logger | None = None,
) -> bool:
    """Shrink user file against shipped defaults; returns True when a write occurred."""

    logger = logger or LOGGER
    try:
        shipped_raw = json.loads(shipped_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        logger.warning("Shrink skipped: shipped groupings missing at %s", shipped_path)
        return False
    except json.JSONDecodeError as exc:
        logger.warning("Shrink skipped: shipped groupings invalid JSON (%s): %s", shipped_path, exc)
        return False
    except OSError as exc:
        logger.warning("Shrink skipped: unable to read shipped groupings %s: %s", shipped_path, exc)
        return False

    try:
        user_text = user_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return False
    except OSError as exc:
        logger.warning("Shrink skipped: unable to read user groupings %s: %s", user_path, exc)
        return False

    try:
        user_raw = json.loads(user_text) if user_text.strip() else {}
    except json.JSONDecodeError as exc:
        logger.warning("Shrink skipped: user groupings invalid JSON (%s): %s", user_path, exc)
        return False

    try:
        minimized = shrink_user_groupings(shipped_raw, user_raw)
    except Exception as exc:
        logger.warning("Shrink skipped: unable to compute diff for %s: %s", user_path, exc)
        return False

    current_sorted = json.dumps(user_raw if isinstance(user_raw, Mapping) else {}, sort_keys=True)
    minimized_sorted = json.dumps(minimized, sort_keys=True)
    if current_sorted == minimized_sorted:
        return False

    if backup and user_path.exists():
        try:
            backup_path = user_path.with_suffix(user_path.suffix + ".bak")
            backup_path.write_text(user_text, encoding="utf-8")
        except Exception:
            logger.warning("Shrink: failed to write backup for %s; aborting shrink", user_path)
            return False

    try:
        tmp_path = user_path.with_suffix(user_path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(minimized, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp_path, user_path)
    except Exception as exc:
        logger.warning("Shrink: failed to write minimized user groupings to %s: %s", user_path, exc)
        return False

    return True


# Internal helpers -------------------------------------------------------------


def _normalise_plugin_entry(plugin_name: str, entry: Any) -> Dict[str, Any]:
    if not isinstance(entry, Mapping):
        return {}

    normalised: Dict[str, Any] = {}

    if entry.get("disabled") is True:
        normalised["disabled"] = True

    if "matchingPrefixes" in entry:
        normalised["matchingPrefixes"] = list(_normalise_prefixes(entry.get("matchingPrefixes"), "matchingPrefixes"))

    groups_raw = entry.get("idPrefixGroups")
    if isinstance(groups_raw, Mapping):
        groups_norm: Dict[str, Any] = {}
        for group_label, group_entry in groups_raw.items():
            groups_norm[group_label] = _normalise_group_entry(plugin_name, group_label, group_entry)
        normalised["idPrefixGroups"] = _sorted_dict(groups_norm)

    for key, value in entry.items():
        if key in {"disabled", "matchingPrefixes", "idPrefixGroups"}:
            continue
        normalised[key] = value

    return normalised


def _normalise_group_entry(plugin_name: str, group_label: str, entry: Any) -> Dict[str, Any]:
    if not isinstance(entry, Mapping):
        return {}

    normalised: Dict[str, Any] = {}

    if entry.get("disabled") is True:
        normalised["disabled"] = True

    if "idPrefixes" in entry:
        normalised["idPrefixes"] = _normalise_id_prefixes(entry.get("idPrefixes"), plugin_name, group_label)

    if "idPrefixGroupAnchor" in entry:
        normalised["idPrefixGroupAnchor"] = _normalise_anchor(entry.get("idPrefixGroupAnchor"))

    if "payloadJustification" in entry:
        normalised["payloadJustification"] = _normalise_justification(entry.get("payloadJustification"))

    if "markerLabelPosition" in entry:
        normalised["markerLabelPosition"] = _normalise_marker_label_position(entry.get("markerLabelPosition"))

    if "offsetX" in entry:
        normalised["offsetX"] = _normalise_offset(entry.get("offsetX"), "offsetX")

    if "offsetY" in entry:
        normalised["offsetY"] = _normalise_offset(entry.get("offsetY"), "offsetY")

    if "backgroundColor" in entry:
        value = entry.get("backgroundColor")
        if value is None:
            normalised["backgroundColor"] = None
        else:
            normalised["backgroundColor"] = _normalise_background_color(value)

    if "backgroundBorderColor" in entry:
        value = entry.get("backgroundBorderColor")
        if value is None:
            normalised["backgroundBorderColor"] = None
        else:
            normalised["backgroundBorderColor"] = _normalise_background_color(value)

    if "backgroundBorderWidth" in entry:
        value = entry.get("backgroundBorderWidth")
        if value is None:
            normalised["backgroundBorderWidth"] = None
        else:
            normalised["backgroundBorderWidth"] = _normalise_border_width(value, "backgroundBorderWidth")

    for key, value in entry.items():
        if key in {
            "disabled",
            "idPrefixes",
            "idPrefixGroupAnchor",
            "payloadJustification",
            "markerLabelPosition",
            "offsetX",
            "offsetY",
            "backgroundColor",
            "backgroundBorderColor",
            "backgroundBorderWidth",
        }:
            continue
        normalised[key] = value

    return normalised


def _diff_plugin(plugin_name: str, shipped: Mapping[str, Any], merged: Mapping[str, Any]) -> Dict[str, Any]:
    # User-only plugin: return entire merged entry.
    if not shipped:
        return _sorted_dict(merged)

    diff: Dict[str, Any] = {}

    # Plugin-level fields
    for key in ("disabled", "matchingPrefixes"):
        merged_val = merged.get(key)
        shipped_val = shipped.get(key)
        if merged_val != shipped_val and merged_val is not None:
            diff[key] = merged_val

    # Other plugin-level extras
    for key, merged_val in merged.items():
        if key in {"disabled", "matchingPrefixes", "idPrefixGroups"}:
            continue
        shipped_val = shipped.get(key)
        if merged_val != shipped_val:
            diff[key] = merged_val

    # Groups
    merged_groups = merged.get("idPrefixGroups") if isinstance(merged.get("idPrefixGroups"), Mapping) else {}
    shipped_groups = shipped.get("idPrefixGroups") if isinstance(shipped.get("idPrefixGroups"), Mapping) else {}
    groups_diff: Dict[str, Any] = {}

    group_labels = sorted(set(shipped_groups.keys()) | set(merged_groups.keys()), key=str.casefold)
    for label in group_labels:
        merged_group = merged_groups.get(label)
        shipped_group = shipped_groups.get(label)

        if merged_group is None and shipped_group is not None:
            groups_diff[label] = {"disabled": True}
            continue

        if merged_group is None:
            continue

        if shipped_group is None:
            groups_diff[label] = merged_group
            continue

        group_diff = _diff_group(shipped_group, merged_group)
        if group_diff:
            groups_diff[label] = group_diff

    if groups_diff:
        diff["idPrefixGroups"] = _sorted_dict(groups_diff)

    return _sorted_dict(diff)


def _diff_group(shipped: Mapping[str, Any], merged: Mapping[str, Any]) -> Dict[str, Any]:
    diff: Dict[str, Any] = {}

    for key, merged_val in merged.items():
        shipped_val = shipped.get(key)
        if merged_val != shipped_val:
            diff[key] = merged_val

    return diff


def _normalise_id_prefixes(values: Any, plugin_name: str, group_label: str) -> list[Any]:
    try:
        entries = parse_prefix_entries(values)
    except Exception as exc:
        raise PluginGroupingError(f"unable to parse idPrefixes: {exc}") from exc
    if not entries:
        raise PluginGroupingError("idPrefixes must contain at least one non-empty value")
    try:
        return serialise_prefix_entries(entries)
    except Exception as exc:  # pragma: no cover - defensive guard
        raise PluginGroupingError(f"failed to serialise idPrefixes for {plugin_name}/{group_label}: {exc}") from exc


def _sorted_dict(mapping: Mapping[str, Any]) -> Dict[str, Any]:
    return {key: mapping[key] for key in sorted(mapping.keys(), key=str.casefold)}
