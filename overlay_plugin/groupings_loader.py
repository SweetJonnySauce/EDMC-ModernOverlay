"""Shared loader for overlay groupings with user override support.

This helper merges the shipped overlay_groupings.json with an optional
overlay_groupings.user.json, applying the same normalisation rules as the
public API. It tolerates malformed user entries, keeps a last-good merged
view, and exposes basic diagnostics for callers.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple

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

LOGGER = logging.getLogger("EDMC.ModernOverlay.GroupingsLoader")


@dataclass(frozen=True)
class _Signature:
    shipped_mtime_ns: Optional[int]
    shipped_size: Optional[int]
    user_mtime_ns: Optional[int]
    user_size: Optional[int]


class GroupingsLoader:
    """Load and merge shipped + user overlay grouping files.

    The merged view keeps shipped defaults and overlays user entries per the
    documented rules: user values replace shipped fields per plugin/group,
    user-only entries are allowed, and `disabled: true` hides shipped entries.
    """

    def __init__(self, shipped_path: Path, user_path: Optional[Path] = None, logger: Optional[logging.Logger] = None) -> None:
        self._shipped_path = shipped_path
        self._user_path = user_path or shipped_path.with_name("overlay_groupings.user.json")
        self._logger = logger or LOGGER
        self._merged: Dict[str, Any] = {}
        self._last_signature: Optional[_Signature] = None
        self._last_reload_ts: Optional[float] = None
        self._stale: bool = False

    # Public API ---------------------------------------------------------

    def load(self) -> Dict[str, Any]:
        """Force a reload, updating cached merge and signature."""

        signature = self._current_signature()
        merged = self._load_and_merge()
        self._merged = merged
        self._last_signature = signature
        self._last_reload_ts = time.time()
        self._stale = False
        return merged

    def reload_if_changed(self) -> bool:
        """Reload when either file's mtime/size changed; return True if reloaded."""

        signature = self._current_signature()
        if signature == self._last_signature:
            return False
        try:
            merged = self._load_and_merge()
        except Exception:
            # Keep last-good; mark stale and retain signature to avoid thrash.
            self._stale = True
            self._last_signature = signature
            return False
        self._merged = merged
        self._last_signature = signature
        self._last_reload_ts = time.time()
        self._stale = False
        return True

    def merged(self) -> Dict[str, Any]:
        """Return the current merged view (may be last-good if stale)."""

        return dict(self._merged)

    def paths(self) -> Mapping[str, Path]:
        return {"shipped": self._shipped_path, "user": self._user_path}

    def diagnostics(self) -> Mapping[str, Any]:
        return {
            "paths": self.paths(),
            "last_reload_ts": self._last_reload_ts,
            "stale": self._stale,
            "signature": self._last_signature,
        }

    # Internal helpers ---------------------------------------------------

    def _current_signature(self) -> _Signature:
        def _sig(path: Path) -> Tuple[Optional[int], Optional[int]]:
            try:
                stat = path.stat()
            except FileNotFoundError:
                return None, None
            except OSError as exc:  # pragma: no cover - filesystem issues
                self._logger.debug("Failed to stat %s: %s", path, exc)
                return None, None
            return stat.st_mtime_ns, stat.st_size

        shipped_mtime, shipped_size = _sig(self._shipped_path)
        user_mtime, user_size = _sig(self._user_path)
        return _Signature(shipped_mtime, shipped_size, user_mtime, user_size)

    def _load_and_merge(self) -> Dict[str, Any]:
        shipped = self._read_json(self._shipped_path, allow_missing=True)
        user = self._read_json(self._user_path, allow_missing=True)
        merged = self._merge_groupings(shipped, user)
        return merged

    def _read_json(self, path: Path, *, allow_missing: bool) -> Dict[str, Any]:
        try:
            raw = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            if allow_missing:
                return {}
            raise
        except OSError as exc:  # pragma: no cover - filesystem issues
            self._logger.warning("Unable to read %s: %s", path, exc)
            raise
        if not raw.strip():
            return {}
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            self._logger.warning("Invalid JSON in %s: %s", path, exc)
            raise
        if not isinstance(data, dict):
            self._logger.warning("%s must contain a JSON object at the root", path)
            raise PluginGroupingError(f"{path} must contain a JSON object at the root")
        return data

    def _merge_groupings(self, shipped: Mapping[str, Any], user: Mapping[str, Any]) -> Dict[str, Any]:
        merged: Dict[str, Any] = {}
        shipped_plugins = shipped if isinstance(shipped, Mapping) else {}
        user_plugins = user if isinstance(user, Mapping) else {}

        # Pass through metadata keys (leading underscore) from user payload.
        for key, value in user_plugins.items():
            if isinstance(key, str) and key.startswith("_"):
                merged[key] = value

        for plugin_name, base_entry in shipped_plugins.items():
            try:
                result = self._merge_plugin(plugin_name, base_entry, user_plugins.get(plugin_name))
            except Exception as exc:
                self._logger.warning("Skipping plugin %s due to merge error: %s", plugin_name, exc)
                continue
            if result is not None:
                merged[plugin_name] = result

        for plugin_name, user_entry in user_plugins.items():
            if plugin_name in merged:
                continue
            if isinstance(plugin_name, str) and plugin_name.startswith("_"):
                continue
            try:
                result = self._merge_plugin(plugin_name, None, user_entry)
            except Exception as exc:
                self._logger.warning("Skipping user-only plugin %s due to merge error: %s", plugin_name, exc)
                continue
            if result is not None:
                merged[plugin_name] = result

        return merged

    def _merge_plugin(self, name: str, base_entry: Any, user_entry: Any) -> Optional[Dict[str, Any]]:
        base_entry = base_entry if isinstance(base_entry, Mapping) else {}
        user_entry = user_entry if isinstance(user_entry, Mapping) else {}

        if self._is_disabled(user_entry):
            return None

        merged: Dict[str, Any] = {}

        base_matching = base_entry.get("matchingPrefixes")
        user_matching = user_entry.get("matchingPrefixes")
        try:
            if user_matching is not None:
                merged["matchingPrefixes"] = list(_normalise_prefixes(user_matching, "matchingPrefixes"))
            elif base_matching is not None:
                merged["matchingPrefixes"] = list(_normalise_prefixes(base_matching, "matchingPrefixes"))
        except PluginGroupingError as exc:
            raise PluginGroupingError(f"plugin {name}: matchingPrefixes invalid: {exc}") from exc

        groups: Dict[str, Any] = {}
        base_groups = base_entry.get("idPrefixGroups") if isinstance(base_entry, Mapping) else None
        base_groups = base_groups if isinstance(base_groups, Mapping) else {}
        user_groups = user_entry.get("idPrefixGroups") if isinstance(user_entry, Mapping) else None
        user_groups = user_groups if isinstance(user_groups, Mapping) else {}

        # Merge shipped groups, applying user overrides/disable.
        for group_label, base_group_entry in base_groups.items():
            user_group_entry = user_groups.get(group_label)
            group_result = self._merge_group(name, group_label, base_group_entry, user_group_entry)
            if group_result is not None:
                groups[group_label] = group_result

        # Add user-only groups.
        for group_label, user_group_entry in user_groups.items():
            if group_label in groups:
                continue
            group_result = self._merge_group(name, group_label, None, user_group_entry)
            if group_result is not None:
                groups[group_label] = group_result

        if groups:
            merged["idPrefixGroups"] = groups

        return merged

    def _merge_group(
        self,
        plugin_name: str,
        group_label: str,
        base_entry: Any,
        user_entry: Any,
    ) -> Optional[Dict[str, Any]]:
        base_entry = base_entry if isinstance(base_entry, Mapping) else {}
        user_entry = user_entry if isinstance(user_entry, Mapping) else {}

        if self._is_disabled(user_entry):
            return None

        merged: Dict[str, Any] = {}

        # idPrefixes
        user_prefixes = user_entry.get("idPrefixes")
        base_prefixes = base_entry.get("idPrefixes")
        try:
            if user_prefixes is not None:
                merged["idPrefixes"] = self._normalise_id_prefixes(user_prefixes, plugin_name, group_label)
            elif base_prefixes is not None:
                merged["idPrefixes"] = self._normalise_id_prefixes(base_prefixes, plugin_name, group_label)
        except PluginGroupingError as exc:
            raise PluginGroupingError(f"plugin {plugin_name} group {group_label}: idPrefixes invalid: {exc}") from exc

        # Anchors/justification/offsets
        anchor = self._select(user_entry, base_entry, "idPrefixGroupAnchor", _normalise_anchor)
        if anchor is not None:
            merged["idPrefixGroupAnchor"] = anchor

        payload_justification = self._select(user_entry, base_entry, "payloadJustification", _normalise_justification)
        if payload_justification is not None:
            merged["payloadJustification"] = payload_justification
        marker_label_position = self._select(
            user_entry,
            base_entry,
            "markerLabelPosition",
            _normalise_marker_label_position,
        )
        if marker_label_position is not None:
            merged["markerLabelPosition"] = marker_label_position

        offset_x = self._select(user_entry, base_entry, "offsetX", lambda value: _normalise_offset(value, "offsetX"))
        if offset_x is not None:
            merged["offsetX"] = offset_x

        offset_y = self._select(user_entry, base_entry, "offsetY", lambda value: _normalise_offset(value, "offsetY"))
        if offset_y is not None:
            merged["offsetY"] = offset_y

        background_color = self._select_background_color(user_entry, base_entry, plugin_name, group_label)
        if background_color is not None:
            merged["backgroundColor"] = background_color

        border_color = self._select_background_border_color(user_entry, base_entry, plugin_name, group_label)
        if border_color is not None:
            merged["backgroundBorderColor"] = border_color

        border_width = self._select_background_border(user_entry, base_entry, plugin_name, group_label)
        if border_width is not None:
            merged["backgroundBorderWidth"] = border_width

        # Carry over any other fields from base/user (user wins) except disabled.
        for source in (base_entry, user_entry):
            for key, value in source.items():
                if key in {
                    "idPrefixes",
                    "idPrefixGroupAnchor",
                    "payloadJustification",
                    "markerLabelPosition",
                    "offsetX",
                    "offsetY",
                    "backgroundColor",
                    "backgroundBorderColor",
                    "backgroundBorderWidth",
                    "disabled",
                }:
                    continue
                merged[key] = value

        return merged if merged else {}

    def _normalise_id_prefixes(self, values: Any, plugin_name: str, group_label: str) -> list[Any]:
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

    def _select(self, user_entry: Mapping[str, Any], base_entry: Mapping[str, Any], key: str, normaliser) -> Optional[Any]:
        value = user_entry.get(key, None)
        if value is not None:
            return normaliser(value)
        value = base_entry.get(key, None)
        if value is None:
            return None
        return normaliser(value)

    def _select_background_color(
        self, user_entry: Mapping[str, Any], base_entry: Mapping[str, Any], plugin_name: str, group_label: str
    ) -> Optional[str]:
        user_has_value = "backgroundColor" in user_entry
        user_value = user_entry.get("backgroundColor", None)
        if user_has_value:
            if user_value is None:
                return None
            try:
                return _normalise_background_color(user_value)
            except PluginGroupingError as exc:
                self._logger.warning(
                    "plugin %s group %s: invalid user backgroundColor %s", plugin_name, group_label, exc
                )
        base_value = base_entry.get("backgroundColor", None)
        if base_value is None:
            return None
        try:
            return _normalise_background_color(base_value)
        except PluginGroupingError as exc:
            self._logger.warning(
                "plugin %s group %s: invalid shipped backgroundColor %s", plugin_name, group_label, exc
            )
            return None

    def _select_background_border(
        self, user_entry: Mapping[str, Any], base_entry: Mapping[str, Any], plugin_name: str, group_label: str
    ) -> Optional[int]:
        user_has_value = "backgroundBorderWidth" in user_entry
        user_value = user_entry.get("backgroundBorderWidth", None)
        if user_has_value:
            if user_value is None:
                return None
            try:
                return _normalise_border_width(user_value, "backgroundBorderWidth")
            except PluginGroupingError as exc:
                self._logger.warning(
                    "plugin %s group %s: invalid user backgroundBorderWidth %s", plugin_name, group_label, exc
                )
        base_value = base_entry.get("backgroundBorderWidth", None)
        if base_value is None:
            return None
        try:
            return _normalise_border_width(base_value, "backgroundBorderWidth")
        except PluginGroupingError as exc:
            self._logger.warning(
                "plugin %s group %s: invalid shipped backgroundBorderWidth %s", plugin_name, group_label, exc
            )
            return None

    def _select_background_border_color(
        self, user_entry: Mapping[str, Any], base_entry: Mapping[str, Any], plugin_name: str, group_label: str
    ) -> Optional[str]:
        user_has_value = "backgroundBorderColor" in user_entry
        user_value = user_entry.get("backgroundBorderColor", None)
        if user_has_value:
            if user_value is None:
                return None
            try:
                return _normalise_background_color(user_value)
            except PluginGroupingError as exc:
                self._logger.warning(
                    "plugin %s group %s: invalid user backgroundBorderColor %s", plugin_name, group_label, exc
                )
        base_value = base_entry.get("backgroundBorderColor", None)
        if base_value is None:
            return None
        try:
            return _normalise_background_color(base_value)
        except PluginGroupingError as exc:
            self._logger.warning(
                "plugin %s group %s: invalid shipped backgroundBorderColor %s", plugin_name, group_label, exc
            )
            return None

    @staticmethod
    def _is_disabled(entry: Mapping[str, Any]) -> bool:
        disabled = entry.get("disabled") if isinstance(entry, Mapping) else None
        if disabled is None:
            return False
        if isinstance(disabled, bool):
            return disabled
        # Invalid types are ignored with a warning.
        LOGGER.warning("Ignoring non-boolean disabled flag: %s", disabled)
        return False


def merge_groupings_dicts(shipped: Mapping[str, Any], user: Mapping[str, Any], logger: Optional[logging.Logger] = None) -> Dict[str, Any]:
    """Merge shipped + user mapping using GroupingsLoader rules (pure, no IO)."""

    loader = GroupingsLoader(Path("shipped"), Path("user"), logger=logger or LOGGER)
    return loader._merge_groupings(shipped, user)
