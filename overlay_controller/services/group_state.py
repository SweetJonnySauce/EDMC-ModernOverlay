"""Group/config state service extracted from the controller UI."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple

from overlay_plugin.groupings_diff import diff_groupings, is_empty_diff
from overlay_plugin.overlay_api import PluginGroupingError, _normalise_background_color, _normalise_border_width
from overlay_plugin.groupings_loader import GroupingsLoader

ABS_BASE_WIDTH = 1280.0
ABS_BASE_HEIGHT = 960.0


@dataclass
class GroupSnapshot:
    plugin: str
    label: str
    anchor_token: str
    transform_anchor_token: str
    offset_x: float
    offset_y: float
    base_bounds: Tuple[float, float, float, float]
    base_anchor: Tuple[float, float]
    transform_bounds: Optional[Tuple[float, float, float, float]]
    transform_anchor: Optional[Tuple[float, float]]
    has_transform: bool = False
    cache_timestamp: float = 0.0
    background_color: Optional[str] = None
    background_border_color: Optional[str] = None
    background_border_width: int = 0


class GroupStateService:
    """Read-only grouping/config service with snapshot synthesis helpers."""

    def __init__(
        self,
        *,
        root: Optional[Path] = None,
        shipped_path: Optional[Path] = None,
        user_groupings_path: Optional[Path] = None,
        cache_path: Optional[Path] = None,
        loader: Optional[GroupingsLoader] = None,
    ) -> None:
        self._root = root or Path(__file__).resolve().parents[2]
        self._shipped_path = shipped_path or (self._root / "overlay_groupings.json")
        default_user_path: Path = self._root / "overlay_groupings.user.json"
        self._user_path = user_groupings_path or Path(
            os.environ.get("MODERN_OVERLAY_USER_GROUPINGS_PATH", default_user_path)
        )
        self._cache_path = cache_path or (self._root / "overlay_group_cache.json")
        self._loader = loader or GroupingsLoader(self._shipped_path, self._user_path)
        self._groupings_data: Dict[str, object] = {}
        self._groupings_cache: Dict[str, object] = self._load_groupings_cache()
        self._idprefix_entries: list[tuple[str, str]] = []
        self._edit_nonce: str = ""

    @property
    def idprefix_entries(self) -> list[tuple[str, str]]:
        return list(self._idprefix_entries)

    def refresh_cache(self) -> Dict[str, object]:
        self._groupings_cache = self._load_groupings_cache()
        return self._groupings_cache

    def cache_changed(self, new_cache: Dict[str, object]) -> bool:
        return self._strip_timestamps(new_cache) != self._strip_timestamps(self._groupings_cache)

    def reload_groupings_if_changed(
        self,
        *,
        last_edit_ts: float | None = None,
        now: float | None = None,
        delay_seconds: float = 5.0,
    ) -> bool:
        """Reload merged groupings if files changed and not within the post-edit delay."""

        if last_edit_ts is not None:
            now_ts = now if now is not None else time.time()
            if now_ts - last_edit_ts <= delay_seconds:
                return False
        try:
            changed = bool(self._loader.reload_if_changed())
        except Exception:
            return False
        if changed:
            try:
                self._groupings_data = self._loader.merged()
            except Exception:
                self._groupings_data = {}
        return changed

    def load_options(self) -> list[str]:
        try:
            self._loader.reload_if_changed()
        except Exception:
            pass
        try:
            self._groupings_data = self._loader.merged()
        except Exception:
            self._groupings_data = {}

        options: list[str] = []
        self._idprefix_entries.clear()
        cache_groups = self._groupings_cache.get("groups") if isinstance(self._groupings_cache, dict) else {}

        for plugin_name, entry in sorted(self._groupings_data.items(), key=lambda item: item[0].casefold()):
            groups = entry.get("idPrefixGroups") if isinstance(entry, dict) else None
            if not isinstance(groups, dict):
                continue
            labels = sorted(groups.keys(), key=str.casefold)

            def _prefix(label: str) -> str:
                for sep in ("-", " "):
                    head, *rest = label.split(sep, 1)
                    if rest:
                        return head.strip().casefold()
                return label.strip().casefold()

            first_parts = {_prefix(lbl) for lbl in labels}
            show_plugin = len(first_parts) > 1
            plugin_cache = cache_groups.get(plugin_name) if isinstance(cache_groups, dict) else {}
            for label in labels:
                has_cache = isinstance(plugin_cache, dict) and isinstance(plugin_cache.get(label), dict)
                if not has_cache:
                    continue
                display = f"{plugin_name}: {label}" if show_plugin else label
                options.append(display)
                self._idprefix_entries.append((plugin_name, label))
        return options

    def snapshot(self, plugin_name: str, label: str) -> Optional[GroupSnapshot]:
        cfg = self._get_group_config(plugin_name, label)
        base_payload, transformed_payload, cache_ts = self._get_cache_record(plugin_name, label)
        if base_payload is None:
            return None

        anchor_token = str(
            cfg.get("idPrefixGroupAnchor")
            or (transformed_payload.get("anchor") if transformed_payload else "nw")
            or "nw"
        ).lower()
        transform_anchor_token = str(
            transformed_payload.get("anchor", anchor_token) if isinstance(transformed_payload, dict) else anchor_token
        ).lower()

        offset_x = float(cfg.get("offsetX", 0.0)) if isinstance(cfg, dict) else 0.0
        offset_y = float(cfg.get("offsetY", 0.0)) if isinstance(cfg, dict) else 0.0
        bg_color_raw = cfg.get("backgroundColor") if isinstance(cfg, dict) else None
        try:
            background_color = _normalise_background_color(bg_color_raw) if bg_color_raw is not None else None
        except PluginGroupingError:
            background_color = None
        bg_border_color_raw = cfg.get("backgroundBorderColor") if isinstance(cfg, dict) else None
        try:
            background_border_color = (
                _normalise_background_color(bg_border_color_raw) if bg_border_color_raw is not None else None
            )
        except PluginGroupingError:
            background_border_color = None
        bg_border_raw = cfg.get("backgroundBorderWidth") if isinstance(cfg, dict) else None
        try:
            background_border_width = _normalise_border_width(bg_border_raw, "backgroundBorderWidth") if bg_border_raw is not None else 0
        except PluginGroupingError:
            background_border_width = 0

        base_min_x = float(base_payload.get("base_min_x", 0.0))
        base_min_y = float(base_payload.get("base_min_y", 0.0))
        base_max_x = float(base_payload.get("base_max_x", base_min_x))
        base_max_y = float(base_payload.get("base_max_y", base_min_y))
        base_bounds = (base_min_x, base_min_y, base_max_x, base_max_y)
        base_anchor = self._compute_anchor_point(base_min_x, base_max_x, base_min_y, base_max_y, anchor_token)

        # Synthesize transform from base + offsets so preview/HUD stay aligned until client rewrites.
        trans_min_x = base_min_x + offset_x
        trans_min_y = base_min_y + offset_y
        trans_max_x = base_max_x + offset_x
        trans_max_y = base_max_y + offset_y
        transform_bounds = (trans_min_x, trans_min_y, trans_max_x, trans_max_y)
        transform_anchor = self._compute_anchor_point(
            trans_min_x, trans_max_x, trans_min_y, trans_max_y, transform_anchor_token
        )

        return GroupSnapshot(
            plugin=plugin_name,
            label=label,
            anchor_token=anchor_token,
            transform_anchor_token=transform_anchor_token,
            offset_x=offset_x,
            offset_y=offset_y,
            base_bounds=base_bounds,
            base_anchor=base_anchor,
            transform_bounds=transform_bounds,
            transform_anchor=transform_anchor,
            has_transform=True,
            cache_timestamp=cache_ts,
            background_color=background_color,
            background_border_color=background_border_color,
            background_border_width=background_border_width,
        )

    def persist_offsets(
        self,
        plugin_name: str,
        label: str,
        offset_x: float,
        offset_y: float,
        *,
        edit_nonce: str = "",
        write: bool = True,
        invalidate_cache: bool = True,
    ) -> None:
        self._edit_nonce = edit_nonce
        self._set_config_offsets(plugin_name, label, offset_x, offset_y)
        if write:
            self._write_groupings_config(edit_nonce=edit_nonce)
        if invalidate_cache:
            self._invalidate_group_cache_entry(plugin_name, label, edit_nonce=edit_nonce)

    def persist_anchor(
        self,
        plugin_name: str,
        label: str,
        anchor: str,
        *,
        edit_nonce: str = "",
        write: bool = True,
        invalidate_cache: bool = True,
    ) -> None:
        self._edit_nonce = edit_nonce
        self._set_group_value(plugin_name, label, "idPrefixGroupAnchor", anchor)
        if write:
            self._write_groupings_config(edit_nonce=edit_nonce)
        if invalidate_cache:
            self._invalidate_group_cache_entry(plugin_name, label, edit_nonce=edit_nonce)

    def persist_justification(
        self,
        plugin_name: str,
        label: str,
        justification: str,
        *,
        edit_nonce: str = "",
        write: bool = True,
        invalidate_cache: bool = True,
    ) -> None:
        self._edit_nonce = edit_nonce
        self._set_group_value(plugin_name, label, "payloadJustification", justification)
        if write:
            self._write_groupings_config(edit_nonce=edit_nonce)
        if invalidate_cache:
            self._invalidate_group_cache_entry(plugin_name, label, edit_nonce=edit_nonce)

    def persist_background(
        self,
        plugin_name: str,
        label: str,
        color: Optional[str],
        border_color: Optional[str],
        border_width: Optional[int],
        *,
        edit_nonce: str = "",
        write: bool = True,
        invalidate_cache: bool = True,
    ) -> None:
        self._edit_nonce = edit_nonce
        self._set_group_background(plugin_name, label, color, border_color, border_width)
        if write:
            self._write_groupings_config(edit_nonce=edit_nonce)
        if invalidate_cache:
            self._invalidate_group_cache_entry(plugin_name, label, edit_nonce=edit_nonce)

    def _load_groupings_cache(self) -> Dict[str, object]:
        try:
            payload = json.loads(self._cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        groups = payload.get("groups") if isinstance(payload, dict) else None
        payload["groups"] = groups if isinstance(groups, dict) else {}
        return payload

    def _get_group_config(self, plugin_name: str, label: str) -> Dict[str, object]:
        entry = self._groupings_data.get(plugin_name) if isinstance(self._groupings_data, dict) else None
        groups = entry.get("idPrefixGroups") if isinstance(entry, dict) else None
        group = groups.get(label) if isinstance(groups, dict) else None
        return group if isinstance(group, dict) else {}

    def _set_group_value(self, plugin_name: str, label: str, key: str, value: object) -> None:
        plugin_entry = self._groupings_data.setdefault(plugin_name, {})
        groups = plugin_entry.setdefault("idPrefixGroups", {})
        if not isinstance(groups, dict):
            groups = {}
            plugin_entry["idPrefixGroups"] = groups
        group = groups.get(label)
        if not isinstance(group, dict):
            group = {}
            groups[label] = group
        group[key] = value

    def _set_group_background(
        self,
        plugin_name: str,
        label: str,
        color: Optional[str],
        border_color: Optional[str],
        border_width: Optional[int],
    ) -> None:
        if not isinstance(self._groupings_data, dict):
            return
        entry = self._groupings_data.get(plugin_name)
        if not isinstance(entry, dict):
            entry = {}
            self._groupings_data[plugin_name] = entry
        groups = entry.get("idPrefixGroups")
        if not isinstance(groups, dict):
            groups = {}
            entry["idPrefixGroups"] = groups
        group = groups.get(label)
        if not isinstance(group, dict):
            group = {}
            groups[label] = group
        normalized_color: Optional[str]
        try:
            normalized_color = _normalise_background_color(color) if color is not None else None
        except PluginGroupingError:
            normalized_color = None
        group["backgroundColor"] = normalized_color
        try:
            normalized_border_color = _normalise_background_color(border_color) if border_color is not None else None
        except PluginGroupingError:
            normalized_border_color = None
        group["backgroundBorderColor"] = normalized_border_color
        if border_width is not None:
            try:
                group["backgroundBorderWidth"] = _normalise_border_width(border_width, "backgroundBorderWidth")
            except PluginGroupingError:
                group["backgroundBorderWidth"] = None

    def _get_cache_record(
        self, plugin_name: str, label: str
    ) -> tuple[Dict[str, object] | None, Dict[str, object] | None, float]:
        groups = self._groupings_cache.get("groups") if isinstance(self._groupings_cache, dict) else {}
        plugin_entry = groups.get(plugin_name) if isinstance(groups, dict) else {}
        entry = plugin_entry.get(label) if isinstance(plugin_entry, dict) else {}
        if not isinstance(entry, dict):
            return None, None, 0.0
        normalized = entry.get("base") or entry.get("normalized")
        normalized = normalized if isinstance(normalized, dict) else None
        transformed = entry.get("transformed")
        transformed = transformed if isinstance(transformed, dict) else None
        timestamp = float(entry.get("last_updated", 0.0)) if isinstance(entry, dict) else 0.0
        return normalized, transformed, timestamp

    @staticmethod
    def _anchor_sides(anchor: str) -> tuple[str, str]:
        token = (anchor or "").lower().replace("-", "").replace("_", "")
        h = "center"
        v = "center"
        if token in {"nw", "w", "sw", "left"} or "left" in token:
            h = "left"
        elif token in {"ne", "e", "se", "right"} or "right" in token:
            h = "right"
        if token in {"nw", "n", "ne", "top"} or "top" in token:
            v = "top"
        elif token in {"sw", "s", "se", "bottom"} or "bottom" in token:
            v = "bottom"
        return h, v

    def _compute_anchor_point(
        self, min_x: float, max_x: float, min_y: float, max_y: float, anchor: str
    ) -> tuple[float, float]:
        h, v = self._anchor_sides(anchor)
        ax = min_x if h == "left" else max_x if h == "right" else (min_x + max_x) / 2.0
        ay = min_y if v == "top" else max_y if v == "bottom" else (min_y + max_y) / 2.0
        return ax, ay

    def _write_groupings_config(self, *, edit_nonce: str = "") -> None:
        user_path = self._user_path
        shipped_path = self._shipped_path

        try:
            shipped_raw = json.loads(shipped_path.read_text(encoding="utf-8"))
        except Exception:
            shipped_raw = {}

        merged_view = self._groupings_data if isinstance(self._groupings_data, dict) else {}
        merged_view = self._round_offsets(merged_view)

        try:
            diff = diff_groupings(shipped_raw, merged_view)
        except Exception:
            return

        if is_empty_diff(diff):
            if user_path.exists():
                try:
                    user_path.write_text("{}\n", encoding="utf-8")
                except Exception:
                    pass
            return

        try:
            payload = dict(diff) if isinstance(diff, dict) else {}
            payload["_edit_nonce"] = edit_nonce
            text = json.dumps(payload, indent=2) + "\n"
            tmp_path = user_path.with_suffix(user_path.suffix + ".tmp")
            tmp_path.write_text(text, encoding="utf-8")
            tmp_path.replace(user_path)
        except Exception:
            pass

    @staticmethod
    def _round_offsets(payload: Dict[str, object]) -> Dict[str, object]:
        result: Dict[str, object] = {}
        for plugin_name, plugin_entry in payload.items():
            if not isinstance(plugin_entry, dict):
                result[plugin_name] = plugin_entry
                continue
            plugin_copy: Dict[str, object] = dict(plugin_entry)
            groups = plugin_entry.get("idPrefixGroups")
            if isinstance(groups, dict):
                groups_copy: Dict[str, object] = {}
                for label, group_entry in groups.items():
                    if not isinstance(group_entry, dict):
                        groups_copy[label] = group_entry
                        continue
                    group_copy: Dict[str, object] = dict(group_entry)
                    if "offsetX" in group_copy and isinstance(group_copy["offsetX"], (int, float)):
                        group_copy["offsetX"] = round(float(group_copy["offsetX"]), 3)
                    if "offsetY" in group_copy and isinstance(group_copy["offsetY"], (int, float)):
                        group_copy["offsetY"] = round(float(group_copy["offsetY"]), 3)
                    groups_copy[label] = group_copy
                plugin_copy["idPrefixGroups"] = groups_copy
            result[plugin_name] = plugin_copy
        return result

    @staticmethod
    def _strip_timestamps(node: object) -> object:
        if isinstance(node, dict):
            return {k: GroupStateService._strip_timestamps(v) for k, v in node.items() if k != "last_updated"}
        if isinstance(node, list):
            return [GroupStateService._strip_timestamps(v) for v in node]
        return node

    def _invalidate_group_cache_entry(self, plugin_name: str, label: str, *, edit_nonce: str = "") -> None:
        path = self._cache_path
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            raw = {}
        if not isinstance(raw, dict):
            raw = {}
        groups = raw.get("groups")
        if not isinstance(groups, dict):
            groups = {}
            raw["groups"] = groups
        plugin_entry = groups.get(plugin_name)
        if not isinstance(plugin_entry, dict):
            plugin_entry = {}
            groups[plugin_name] = plugin_entry
        entry = plugin_entry.get(label)
        if not isinstance(entry, dict):
            entry = {}
            plugin_entry[label] = entry

        entry["transformed"] = None
        base_entry = entry.get("base")
        if not isinstance(base_entry, dict):
            base_entry = {}
            entry["base"] = base_entry
        base_entry["has_transformed"] = False
        base_entry["edit_nonce"] = edit_nonce
        entry["last_updated"] = time.time()
        entry["edit_nonce"] = edit_nonce

        try:
            tmp_path = path.with_suffix(path.suffix + ".tmp")
            tmp_path.write_text(json.dumps(raw, indent=2), encoding="utf-8")
            tmp_path.replace(path)
            self._groupings_cache = raw
        except Exception:
            pass

    def _set_config_offsets(self, plugin_name: str, label: str, offset_x: float, offset_y: float) -> None:
        if not isinstance(self._groupings_data, dict):
            return
        entry = self._groupings_data.get(plugin_name)
        if not isinstance(entry, dict):
            entry = {}
            self._groupings_data[plugin_name] = entry
        groups = entry.get("idPrefixGroups")
        if not isinstance(groups, dict):
            groups = {}
            entry["idPrefixGroups"] = groups
        group = groups.get(label)
        if not isinstance(group, dict):
            group = {}
            groups[label] = group
        group["offsetX"] = round(offset_x, 3)
        group["offsetY"] = round(offset_y, 3)
