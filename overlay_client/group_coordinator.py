"""Coordinator scaffold for grouping, cache, and nudge logic (pure, no Qt)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Tuple

from overlay_client.group_transform import GroupKey


@dataclass
class ScreenBounds:
    """Simple bounds holder for screen-space rectangles."""

    min_x: float = float("inf")
    min_y: float = float("inf")
    max_x: float = float("-inf")
    max_y: float = float("-inf")

    def is_valid(self) -> bool:
        return self.min_x <= self.max_x and self.min_y <= self.max_y


class GroupCoordinator:
    """Pure coordinator for grouping/cache/nudge behavior."""

    def __init__(self, cache: Any = None, logger: Any = None) -> None:
        self._cache = cache
        self._logger = logger

    @staticmethod
    def resolve_group_key(
        item_id: str,
        plugin_name: Optional[str],
        override_manager: Any = None,
    ) -> GroupKey:
        """Resolve a group key using overrides when present."""

        if override_manager is not None:
            override_key = override_manager.grouping_key_for(plugin_name, item_id)
            if override_key is not None:
                plugin_label, suffix = override_key
                plugin_token = (plugin_label or plugin_name or "unknown").strip() or "unknown"
                return GroupKey(plugin=plugin_token, suffix=suffix)
        plugin_token = (plugin_name or "unknown").strip() or "unknown"
        suffix = f"item:{item_id}" if item_id else None
        return GroupKey(plugin=plugin_token, suffix=suffix)

    def update_cache_from_payloads(
        self,
        base_payloads: Mapping[Tuple[str, Optional[str]], Mapping[str, Any]],
        transform_payloads: Mapping[Tuple[str, Optional[str]], Mapping[str, Any]],
    ) -> Tuple[Tuple[str, Optional[str]], ...]:
        """Normalize and persist cache payloads."""

        cache = self._cache
        if cache is None:
            return tuple()
        updated: list[Tuple[str, Optional[str]]] = []
        for key, base_payload in base_payloads.items():
            plugin_label = (base_payload.get("plugin") or "").strip()
            suffix_label = base_payload.get("suffix")
            if isinstance(suffix_label, str) and suffix_label.strip().lower() in {
                "item:overlay-controller-status",
                "item:edmcmodernoverlay-controller-status",
            }:
                continue
            normalized = self._base_cache_payload(base_payload)
            transformed_payload = None
            if normalized.get("has_transformed"):
                raw_transform = transform_payloads.get(key)
                if raw_transform is not None:
                    transformed_payload = self._transformed_cache_payload(raw_transform)
            try:
                cache.update_group(plugin_label, suffix_label, normalized, transformed_payload)
                updated.append((plugin_label, suffix_label if isinstance(suffix_label, str) else None))
            except Exception:
                # Mirror current behavior: swallow cache errors to keep UI stable.
                continue
        return tuple(updated)

    def compute_group_nudges(
        self,
        bounds_by_group: Mapping[Tuple[str, Optional[str]], ScreenBounds],
        window_width: int,
        window_height: int,
        enabled: bool,
        gutter: int,
    ) -> Dict[Tuple[str, Optional[str]], Tuple[int, int]]:
        """Compute per-group nudge translations when enabled."""

        if not enabled or not bounds_by_group:
            return {}
        width = max(int(window_width), 1)
        height = max(int(window_height), 1)
        gutter_value = max(0, int(gutter))
        translations: Dict[Tuple[str, Optional[str]], Tuple[int, int]] = {}
        for key, bounds in bounds_by_group.items():
            if not bounds.is_valid():
                continue
            dx = self._compute_axis_nudge(bounds.min_x, bounds.max_x, width, gutter_value)
            dy = self._compute_axis_nudge(bounds.min_y, bounds.max_y, height, gutter_value)
            if dx or dy:
                translations[key] = (dx, dy)
        return translations

    @staticmethod
    def _cache_safe_float(value: Any) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return 0.0
        if not math.isfinite(number):
            return 0.0
        return round(number, 3)

    @staticmethod
    def _cache_safe_int(value: Any) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    def _base_cache_payload(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        return {
            "base_min_x": self._cache_safe_float(payload.get("min_x")),
            "base_min_y": self._cache_safe_float(payload.get("min_y")),
            "base_width": self._cache_safe_float(payload.get("width")),
            "base_height": self._cache_safe_float(payload.get("height")),
            "base_max_x": self._cache_safe_float(payload.get("max_x")),
            "base_max_y": self._cache_safe_float(payload.get("max_y")),
            "has_transformed": bool(payload.get("has_transformed", False)),
            "offset_x": self._cache_safe_float(payload.get("offset_x")),
            "offset_y": self._cache_safe_float(payload.get("offset_y")),
            "edit_nonce": str(payload.get("edit_nonce") or "").strip(),
            "controller_ts": self._cache_safe_float(payload.get("controller_ts")),
        }

    def _transformed_cache_payload(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        anchor_raw = payload.get("anchor") or "nw"
        justification_raw = payload.get("justification") or "left"
        return {
            "trans_min_x": self._cache_safe_float(payload.get("min_x")),
            "trans_min_y": self._cache_safe_float(payload.get("min_y")),
            "trans_width": self._cache_safe_float(payload.get("width")),
            "trans_height": self._cache_safe_float(payload.get("height")),
            "trans_max_x": self._cache_safe_float(payload.get("max_x")),
            "trans_max_y": self._cache_safe_float(payload.get("max_y")),
            "anchor": str(anchor_raw).strip().lower(),
            "justification": str(justification_raw).strip().lower(),
            "nudge_dx": self._cache_safe_int(payload.get("nudge_dx")),
            "nudge_dy": self._cache_safe_int(payload.get("nudge_dy")),
            "nudged": bool(payload.get("nudged", False)),
            "offset_dx": self._cache_safe_float(payload.get("offset_dx")),
            "offset_dy": self._cache_safe_float(payload.get("offset_dy")),
        }

    @staticmethod
    def _compute_axis_nudge(min_coord: float, max_coord: float, window_span: int, gutter: int) -> int:
        if window_span <= 0:
            return 0
        if not (math.isfinite(min_coord) and math.isfinite(max_coord)):
            return 0
        span = max(0.0, max_coord - min_coord)
        if span <= 0.0:
            return 0
        left_overflow = min_coord < 0.0
        right_overflow = max_coord > window_span
        if not (left_overflow or right_overflow):
            return 0
        dx = 0.0
        current_min = min_coord
        current_max = max_coord
        if left_overflow:
            shift = -current_min
            dx += shift
            current_min += shift
            current_max += shift
        if current_max > window_span:
            shift = current_max - window_span
            dx -= shift
            current_min -= shift
            current_max -= shift
        effective_gutter = min(max(0.0, float(gutter)), max(window_span - span, 0.0))
        if effective_gutter > 0.0:
            if left_overflow:
                extra = min(effective_gutter, max(0.0, window_span - current_max))
                dx += extra
                current_min += extra
                current_max += extra
            if right_overflow:
                extra = min(effective_gutter, max(0.0, current_min))
                dx -= extra
                current_min -= extra
                current_max -= extra
        return int(round(dx))
