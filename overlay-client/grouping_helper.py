from __future__ import annotations

import math
from typing import Any, Dict, Mapping, Optional, Tuple, TYPE_CHECKING

from debug_config import DebugConfig
from group_transform import GroupBounds, GroupKey, GroupTransform, GroupTransformCache
from legacy_store import LegacyItem
from plugin_overrides import PluginOverrideManager
from viewport_helper import BASE_HEIGHT, BASE_WIDTH, ScaleMode
from payload_transform import accumulate_group_bounds, determine_group_anchor

if TYPE_CHECKING:  # pragma: no cover - import cycle guard
    from overlay_client import OverlayWindow, _LegacyMapper


class FillGroupingHelper:
    """Encapsulate fill-mode payload grouping and transform preparation."""

    def __init__(
        self,
        owner: "OverlayWindow",
        override_manager: Optional[PluginOverrideManager],
        logger,
        debug_config: DebugConfig,
    ) -> None:
        self._owner = owner
        self._override_manager = override_manager
        self._logger = logger
        self._debug_config = debug_config
        self._cache = GroupTransformCache()

    def reset(self) -> None:
        self._cache.reset()

    def prepare(self, mapper: "_LegacyMapper") -> None:
        self._cache.reset()
        if mapper.transform.mode is not ScaleMode.FILL:
            return
        scale = mapper.transform.scale
        if scale <= 0.0:
            scale = 1.0
        base_scale = scale
        compensate_scale = 1.0 / base_scale if base_scale > 1.0 else 1.0
        group_bounds: Dict[Tuple[str, Optional[str]], GroupBounds] = {}
        group_anchor: Dict[Tuple[str, Optional[str]], Tuple[float, float]] = {}
        group_scale_hints: Dict[Tuple[str, Optional[str]], float] = {}
        for item_id, legacy_item in self._owner._legacy_items.items():
            group_key = self.group_key_for(item_id, legacy_item.plugin)
            key_tuple = group_key.as_tuple()
            bounds = group_bounds.setdefault(key_tuple, GroupBounds())
            scale_hint = group_scale_hints.get(key_tuple)
            if scale_hint is None:
                scale_hint = 1.0
                if compensate_scale != 1.0 and self._group_has_override(group_key.plugin, group_key.suffix):
                    scale_hint = compensate_scale
                group_scale_hints[key_tuple] = scale_hint
            accumulate_group_bounds(
                bounds,
                legacy_item,
                scale,
                scale_hint,
                self._owner._font_family,
                self._owner._legacy_preset_point_size,
            )
            if key_tuple not in group_anchor:
                group_anchor[key_tuple] = determine_group_anchor(legacy_item)

        base_offset_x = mapper.offset_x
        base_offset_y = mapper.offset_y
        width = float(self._owner.width())
        height = float(self._owner.height())
        margin = 12.0
        base_width = BASE_WIDTH if BASE_WIDTH > 0.0 else 1.0
        base_height = BASE_HEIGHT if BASE_HEIGHT > 0.0 else 1.0

        def _normalise(value: float, base: float) -> float:
            if base <= 0.0:
                return 0.0
            return self._clamp_unit(self._safe_float(value, 0.0) / base)

        for key_tuple, bounds in group_bounds.items():
            if not bounds.is_valid():
                continue
            plugin_label, suffix = key_tuple
            group_label = str(plugin_label or "unknown")
            if suffix:
                group_label = f"{group_label}:{suffix}"
            group_scale = 1.0
            if compensate_scale != 1.0 and self._group_has_override(plugin_label, suffix):
                group_scale = compensate_scale
            effective_scale = scale * group_scale
            raw_proportion_x = self._compute_fill_proportion(
                BASE_WIDTH,
                effective_scale,
                width,
                mapper.transform.overflow_x,
            )
            raw_proportion_y = self._compute_fill_proportion(
                BASE_HEIGHT,
                effective_scale,
                height,
                mapper.transform.overflow_y,
            )
            proportion_x, proportion_y = self._normalise_group_proportions(
                raw_proportion_x,
                raw_proportion_y,
                mapper.transform.overflow_x,
                mapper.transform.overflow_y,
            )
            preserve_enabled, preserve_anchor = self._group_preserve_fill_aspect(plugin_label, suffix)
            anchor_coords = group_anchor.get(key_tuple)
            anchor_x, anchor_y = anchor_coords if anchor_coords is not None else (0.0, 0.0)
            if preserve_anchor == "centroid" or anchor_coords is None:
                if bounds.is_valid():
                    anchor_x = (bounds.min_x + bounds.max_x) / 2.0
                    anchor_y = (bounds.min_y + bounds.max_y) / 2.0
                else:
                    anchor_x = anchor_y = 0.0
            preserve_dx = 0.0
            preserve_dy = 0.0
            clamp_applied_x = False
            clamp_applied_y = False
            original_span_x = bounds.max_x - bounds.min_x
            original_span_y = bounds.max_y - bounds.min_y
            if mapper.transform.overflow_x and BASE_WIDTH > 0.0:
                clamped_min_x, clamped_max_x = self._clamp_bounds_to_canvas(
                    bounds.min_x,
                    bounds.max_x,
                    BASE_WIDTH,
                )
                if (
                    not math.isclose(clamped_min_x, bounds.min_x, rel_tol=1e-6, abs_tol=1e-6)
                    or not math.isclose(clamped_max_x, bounds.max_x, rel_tol=1e-6, abs_tol=1e-6)
                ):
                    clamp_applied_x = True
                    bounds.min_x = clamped_min_x
                    bounds.max_x = clamped_max_x
                    anchor_x = max(bounds.min_x, min(anchor_x, bounds.max_x))
                    self._logger.debug(
                        "fill clamp: group=%s axis=x span=%.1f→%.1f (base=%.1f)",
                        group_label,
                        original_span_x,
                        bounds.max_x - bounds.min_x,
                        BASE_WIDTH,
                    )
            if mapper.transform.overflow_y and BASE_HEIGHT > 0.0:
                clamped_min_y, clamped_max_y = self._clamp_bounds_to_canvas(
                    bounds.min_y,
                    bounds.max_y,
                    BASE_HEIGHT,
                )
                if (
                    not math.isclose(clamped_min_y, bounds.min_y, rel_tol=1e-6, abs_tol=1e-6)
                    or not math.isclose(clamped_max_y, bounds.max_y, rel_tol=1e-6, abs_tol=1e-6)
                ):
                    clamp_applied_y = True
                    bounds.min_y = clamped_min_y
                    bounds.max_y = clamped_max_y
                    anchor_y = max(bounds.min_y, min(anchor_y, bounds.max_y))
                    self._logger.debug(
                        "fill clamp: group=%s axis=y span=%.1f→%.1f (base=%.1f)",
                        group_label,
                        original_span_y,
                        bounds.max_y - bounds.min_y,
                        BASE_HEIGHT,
                    )
            min_x_for_delta = bounds.min_x
            max_x_for_delta = bounds.max_x
            min_y_for_delta = bounds.min_y
            max_y_for_delta = bounds.max_y
            if preserve_enabled:
                preserve_dx = anchor_x * (raw_proportion_x - 1.0)
                preserve_dy = anchor_y * (raw_proportion_y - 1.0)
                proportion_x = 1.0
                proportion_y = 1.0
                min_x_for_delta = bounds.min_x + preserve_dx
                max_x_for_delta = bounds.max_x + preserve_dx
                min_y_for_delta = bounds.min_y + preserve_dy
                max_y_for_delta = bounds.max_y + preserve_dy
            band_min_x = _normalise(bounds.min_x, base_width)
            band_max_x = _normalise(bounds.max_x, base_width)
            band_min_y = _normalise(bounds.min_y, base_height)
            band_max_y = _normalise(bounds.max_y, base_height)
            center_x_norm = _normalise((bounds.min_x + bounds.max_x) / 2.0, base_width)
            center_y_norm = _normalise((bounds.min_y + bounds.max_y) / 2.0, base_height)
            anchor_norm_x = _normalise(anchor_x, base_width)
            anchor_norm_y = _normalise(anchor_y, base_height)
            target_norm_x = anchor_norm_x if preserve_enabled else center_x_norm
            target_norm_y = anchor_norm_y if preserve_enabled else center_y_norm

            dx = self._compute_group_band_shift(
                overflow=mapper.transform.overflow_x,
                effective_scale=effective_scale,
                base_offset=base_offset_x,
                window_extent=width,
                proportion=proportion_x,
                preserve_shift=preserve_dx,
                min_val=bounds.min_x,
                max_val=bounds.max_x,
                anchor_val=anchor_x,
                target_norm=target_norm_x,
            )
            dy = self._compute_group_band_shift(
                overflow=mapper.transform.overflow_y,
                effective_scale=effective_scale,
                base_offset=base_offset_y,
                window_extent=height,
                proportion=proportion_y,
                preserve_shift=preserve_dy,
                min_val=bounds.min_y,
                max_val=bounds.max_y,
                anchor_val=anchor_y,
                target_norm=target_norm_y,
            )
            if not math.isfinite(dx):
                dx = 0.0
            if not math.isfinite(dy):
                dy = 0.0
            if not math.isclose(group_scale, 1.0, rel_tol=1e-9, abs_tol=1e-9):
                delta_scale = base_scale - effective_scale
                canvas_h = BASE_HEIGHT * base_scale
                if not math.isclose(delta_scale, 0.0, rel_tol=1e-9):
                    dx = self._compute_compensation_delta(
                        min_x_for_delta,
                        max_x_for_delta,
                        base_scale,
                        effective_scale,
                        base_offset_x,
                        width,
                        proportion_x,
                    )
                if canvas_h > height + 1e-6:
                    logical_center_y = (bounds.min_y + bounds.max_y) / 2.0
                    target_center = (logical_center_y / BASE_HEIGHT) * height
                    current_center = (logical_center_y * proportion_y + preserve_dy) * effective_scale + base_offset_y
                    dy = target_center - current_center
                    top = (bounds.min_y * proportion_y + preserve_dy) * effective_scale + base_offset_y + dy
                    bottom = (bounds.max_y * proportion_y + preserve_dy) * effective_scale + base_offset_y + dy
                    if top < 0.0:
                        dy -= top
                    elif bottom > height:
                        dy -= bottom - height

            overlay_left = bounds.min_x * proportion_x + preserve_dx
            overlay_right = bounds.max_x * proportion_x + preserve_dx
            overlay_top = bounds.min_y * proportion_y + preserve_dy
            overlay_bottom = bounds.max_y * proportion_y + preserve_dy
            screen_left = overlay_left * effective_scale + dx + base_offset_x
            screen_right = overlay_right * effective_scale + dx + base_offset_x
            if mapper.transform.overflow_x:
                if screen_left < margin:
                    shift = margin - screen_left
                    dx += shift
                    screen_left += shift
                    screen_right += shift
                if screen_right > width - margin:
                    shift = (width - margin) - screen_right
                    dx += shift
                    screen_left += shift
                    screen_right += shift
            screen_top = overlay_top * effective_scale + dy + base_offset_y
            screen_bottom = overlay_bottom * effective_scale + dy + base_offset_y
            if mapper.transform.overflow_y:
                if screen_top < 0.0:
                    shift = -screen_top
                    dy += shift
                    screen_top += shift
                    screen_bottom += shift
                if screen_bottom > height:
                    shift = height - screen_bottom
                    dy += shift
                    screen_top += shift
                    screen_bottom += shift

            self._cache.set(
                GroupKey(*key_tuple),
                GroupTransform(
                    dx=dx,
                    dy=dy,
                    scale=group_scale,
                    proportion_x=proportion_x,
                    proportion_y=proportion_y,
                    preserve_dx=preserve_dx,
                    preserve_dy=preserve_dy,
                    raw_proportion_x=raw_proportion_x,
                    raw_proportion_y=raw_proportion_y,
                    band_min_x=band_min_x,
                    band_max_x=band_max_x,
                    band_min_y=band_min_y,
                    band_max_y=band_max_y,
                    band_anchor_x=target_norm_x,
                    band_anchor_y=target_norm_y,
                    band_clamped_x=clamp_applied_x,
                    band_clamped_y=clamp_applied_y,
                    bounds_min_x=bounds.min_x,
                    bounds_min_y=bounds.min_y,
                    bounds_max_x=bounds.max_x,
                    bounds_max_y=bounds.max_y,
                    final_min_x=(screen_left - base_offset_x) / effective_scale if not math.isclose(effective_scale, 0.0, rel_tol=1e-9, abs_tol=1e-9) else bounds.min_x,
                    final_max_x=(screen_right - base_offset_x) / effective_scale if not math.isclose(effective_scale, 0.0, rel_tol=1e-9, abs_tol=1e-9) else bounds.max_x,
                ),
            )

    def group_key_for(self, item_id: str, plugin_name: Optional[str]) -> GroupKey:
        override_key: Optional[Tuple[str, Optional[str]]] = None
        if self._override_manager is not None:
            override_key = self._override_manager.grouping_key_for(plugin_name, item_id)
        if override_key is not None:
            plugin_token, suffix = override_key
            plugin_token = (plugin_token or plugin_name or "unknown").strip() or "unknown"
            return GroupKey(plugin=plugin_token, suffix=suffix)
        plugin_token = (plugin_name or "unknown").strip() or "unknown"
        suffix = f"item:{item_id}" if item_id else None
        return GroupKey(plugin=plugin_token, suffix=suffix)

    def get_transform(self, key: GroupKey) -> Optional[GroupTransform]:
        return self._cache.get(key)

    def transform_for_item(self, item_id: str, plugin_name: Optional[str]) -> Optional[GroupTransform]:
        group_key = self.group_key_for(item_id, plugin_name)
        return self._cache.get(group_key)

    def _group_has_override(self, plugin_label: Optional[str], suffix: Optional[str]) -> bool:
        if self._override_manager is None:
            return False
        return self._override_manager.group_is_configured(plugin_label, suffix)

    def _group_preserve_fill_aspect(self, plugin_label: Optional[str], suffix: Optional[str]) -> Tuple[bool, str]:
        if self._override_manager is None:
            return True, "first"
        return self._override_manager.group_preserve_fill_aspect(plugin_label, suffix)

    @staticmethod
    def _normalise_group_proportions(
        proportion_x: float,
        proportion_y: float,
        overflow_x: bool,
        overflow_y: bool,
    ) -> Tuple[float, float]:
        def _safe(value: float) -> float:
            if not math.isfinite(value) or value <= 0.0:
                return 1.0
            return value

        proportion_x = min(_safe(proportion_x), 1.0)
        proportion_y = min(_safe(proportion_y), 1.0)
        result_x = proportion_x if overflow_x else 1.0
        result_y = proportion_y if overflow_y else 1.0
        return result_x, result_y

    @staticmethod
    def _clamp_bounds_to_canvas(
        min_val: float,
        max_val: float,
        base_extent: float,
    ) -> Tuple[float, float]:
        if not math.isfinite(min_val) or not math.isfinite(max_val):
            return min_val, max_val
        if base_extent <= 0.0:
            return min_val, max_val
        span = max_val - min_val
        if span <= base_extent + 1e-6:
            return min_val, max_val
        center = (min_val + max_val) / 2.0
        half_extent = base_extent / 2.0
        new_min = center - half_extent
        new_max = center + half_extent
        if new_min < 0.0:
            adjustment = -new_min
            new_min = 0.0
            new_max += adjustment
        if new_max > base_extent:
            adjustment = new_max - base_extent
            new_max = base_extent
            new_min -= adjustment
        if new_min < 0.0:
            new_min = 0.0
        if new_max > base_extent:
            new_max = base_extent
        if new_max - new_min > base_extent:
            new_max = new_min + base_extent
        if new_max - new_min < 1e-6:
            new_min = 0.0
            new_max = base_extent
        return new_min, new_max
    def _logical_mapping(data: Mapping[str, Any]) -> Mapping[str, Any]:
        transform_meta = data.get("__mo_transform__") if isinstance(data, Mapping) else None
        if isinstance(transform_meta, Mapping):
            original = transform_meta.get("original")
            if isinstance(original, Mapping):
                points_meta = original.get("points")
                if isinstance(points_meta, list):
                    return original
                if any(key in original for key in ("x", "y", "w", "h")):
                    return original
        return data
    def _apply_transform_meta_to_point(
        meta: Optional[Mapping[str, Any]],
        x: float,
        y: float,
        fill_dx: float = 0.0,
        fill_dy: float = 0.0,
    ) -> Tuple[float, float]:
        x_adj = x
        y_adj = y
        if not isinstance(meta, Mapping):
            fill_x = fill_dx if math.isfinite(fill_dx) else 0.0
            fill_y = fill_dy if math.isfinite(fill_dy) else 0.0
            return x_adj + fill_x, y_adj + fill_y

        pivot_block = meta.get("pivot")
        if isinstance(pivot_block, Mapping):
            pivot_x = FillGroupingHelper._safe_float(pivot_block.get("x"), 0.0)
            pivot_y = FillGroupingHelper._safe_float(pivot_block.get("y"), 0.0)
        else:
            pivot_x = 0.0
            pivot_y = 0.0

        scale_block = meta.get("scale")
        if isinstance(scale_block, Mapping):
            scale_x = FillGroupingHelper._safe_float(scale_block.get("x"), 1.0)
            scale_y = FillGroupingHelper._safe_float(scale_block.get("y"), 1.0)
        else:
            scale_x = 1.0
            scale_y = 1.0

        offset_block = meta.get("offset")
        if isinstance(offset_block, Mapping):
            offset_x = FillGroupingHelper._safe_float(offset_block.get("x"), 0.0)
            offset_y = FillGroupingHelper._safe_float(offset_block.get("y"), 0.0)
        else:
            offset_x = 0.0
            offset_y = 0.0

        scaled_x = pivot_x + (x_adj - pivot_x) * scale_x
        scaled_y = pivot_y + (y_adj - pivot_y) * scale_y
        fill_x = fill_dx if math.isfinite(fill_dx) else 0.0
        fill_y = fill_dy if math.isfinite(fill_dy) else 0.0
        return scaled_x + offset_x + fill_x, scaled_y + offset_y + fill_y

    @staticmethod
    def _compute_fill_proportion(
        base_extent: float,
        effective_scale: float,
        window_extent: float,
        overflow: bool,
    ) -> float:
        if not overflow:
            return 1.0
        if not math.isfinite(base_extent) or base_extent <= 0.0:
            return 1.0
        if not math.isfinite(effective_scale) or effective_scale <= 0.0:
            return 1.0
        scaled_extent = base_extent * effective_scale
        if not math.isfinite(scaled_extent) or scaled_extent <= 0.0:
            return 1.0
        if not math.isfinite(window_extent) or window_extent <= 0.0:
            return 1.0
        if scaled_extent <= window_extent + 1e-6:
            return 1.0
        return max(window_extent / scaled_extent, 0.0)

    @staticmethod
    def _compute_group_band_shift(
        *,
        overflow: bool,
        effective_scale: float,
        base_offset: float,
        window_extent: float,
        proportion: float,
        preserve_shift: float,
        min_val: float,
        max_val: float,
        anchor_val: float,
        target_norm: float,
    ) -> float:
        if not overflow:
            return 0.0
        if not math.isfinite(window_extent) or window_extent <= 0.0:
            return 0.0
        if not math.isfinite(effective_scale) or math.isclose(effective_scale, 0.0, rel_tol=1e-9, abs_tol=1e-9):
            return 0.0
        if not math.isfinite(proportion) or proportion <= 0.0:
            proportion = 1.0
        if not math.isfinite(preserve_shift):
            preserve_shift = 0.0
        if not math.isfinite(anchor_val):
            anchor_val = (min_val + max_val) / 2.0
        safe_norm = FillGroupingHelper._clamp_unit(target_norm)
        anchor_overlay = anchor_val * proportion + preserve_shift
        current_screen = anchor_overlay * effective_scale + base_offset
        target_screen = safe_norm * window_extent
        return target_screen - current_screen

    @staticmethod
    def _compute_compensation_delta(
        min_val: float,
        max_val: float,
        base_scale: float,
        effective_scale: float,
        base_offset: float,
        extent: float,
        proportion: float = 1.0,
    ) -> float:
        if not math.isfinite(base_scale) or not math.isfinite(effective_scale):
            return 0.0
        if math.isclose(effective_scale, 0.0, abs_tol=1e-9):
            return 0.0
        if math.isclose(base_scale, effective_scale, rel_tol=1e-9):
            return 0.0
        if not math.isfinite(proportion) or proportion <= 0.0:
            proportion = 1.0
        physical_left = min_val * proportion * base_scale + base_offset
        physical_right = max_val * proportion * base_scale + base_offset
        left_margin = max(physical_left, 0.0)
        right_margin = max(extent - physical_right, 0.0)
        safe_scale = effective_scale if not math.isclose(effective_scale, 0.0, abs_tol=1e-9) else 1.0
        if right_margin + 1e-6 < left_margin:
            target_physical = min(extent, max(0.0, extent - right_margin))
            return (target_physical - base_offset) / (proportion * safe_scale) - max_val
        if left_margin + 1e-6 < right_margin:
            target_physical = max(0.0, left_margin)
            return (target_physical - base_offset) / (proportion * safe_scale) - min_val
        anchor_mid = (min_val + max_val) / 2.0
        target_physical = anchor_mid * proportion * base_scale + base_offset
        return (target_physical - base_offset) / (proportion * safe_scale) - anchor_mid

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _clamp_unit(value: float) -> float:
        if not math.isfinite(value):
            return 0.0
        if value < 0.0:
            return 0.0
        if value > 1.0:
            return 1.0
        return value
