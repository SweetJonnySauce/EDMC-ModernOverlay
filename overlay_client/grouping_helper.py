from __future__ import annotations

import math
from typing import Any, Dict, Optional, Tuple, TYPE_CHECKING

from overlay_client.debug_config import DebugConfig
from overlay_client.group_transform import GroupBounds, GroupKey, GroupTransform, GroupTransformCache
from overlay_client.plugin_overrides import PluginOverrideManager
from overlay_client.viewport_helper import BASE_HEIGHT, BASE_WIDTH, ScaleMode
from overlay_client.payload_transform import accumulate_group_bounds
from overlay_client.render_pipeline import RenderSettings

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
        self._render_settings: Optional[RenderSettings] = None

    def reset(self) -> None:
        self._cache.reset()
        self._render_settings = None

    def set_render_settings(self, settings: RenderSettings) -> None:
        self._render_settings = settings

    def prepare(self, mapper: "_LegacyMapper") -> None:
        self._cache.reset()
        if mapper.transform.mode is not ScaleMode.FILL:
            return
        # Fill mode keeps grouped geometry at the original logical size by
        # counter-scaling around the anchor, so one overlay unit maps to one
        # on-screen pixel regardless of the viewport scale.
        pixel_scale = 1.0
        settings = self._render_settings

        def preset_point_size(label: str) -> float:
            if settings is not None:
                try:
                    return settings.preset_point_size(label)
                except Exception:
                    pass
            state = self._owner._viewport_state()
            return self._owner._legacy_preset_point_size(label, state, mapper)

        store = getattr(self._owner, "_payload_model").store
        group_bounds: Dict[Tuple[str, Optional[str]], GroupBounds] = {}
        text_block_cache = getattr(self._owner, "_text_block_cache", None)
        cache_generation = getattr(self._owner, "_text_cache_generation", 0)
        try:
            device_ratio = float(self._owner.devicePixelRatioF())
        except Exception:
            device_ratio = 1.0
        if device_ratio <= 0.0 or not math.isfinite(device_ratio):
            device_ratio = 1.0
        for item_id, legacy_item in store.items():
            group_key = self.group_key_for(item_id, legacy_item.plugin)
            key_tuple = group_key.as_tuple()
            bounds = group_bounds.setdefault(key_tuple, GroupBounds())
            accumulate_group_bounds(
                bounds,
                legacy_item,
                pixel_scale,
                settings.font_family if settings is not None else self._owner._font_family,
                preset_point_size,
                font_fallbacks=settings.font_fallbacks if settings is not None else self._owner._font_fallbacks,
                text_block_cache=text_block_cache,
                cache_generation=cache_generation,
                device_ratio=device_ratio,
            )

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
            _, anchor_token = self._group_preserve_fill_aspect(plugin_label, suffix)
            offset_x, offset_y = self._group_offsets(plugin_label, suffix)
            justification = self._group_payload_justification(plugin_label, suffix)
            marker_label_position = self._group_marker_label_position(plugin_label, suffix)
            background_color, background_border_color, background_border_width = self._group_background(
                plugin_label, suffix
            )
            anchor_x, anchor_y = self._anchor_from_bounds(bounds, anchor_token)
            band_min_x = _normalise(bounds.min_x, base_width)
            band_max_x = _normalise(bounds.max_x, base_width)
            band_min_y = _normalise(bounds.min_y, base_height)
            band_max_y = _normalise(bounds.max_y, base_height)
            anchor_norm_x = _normalise(anchor_x, base_width)
            anchor_norm_y = _normalise(anchor_y, base_height)
            self._cache.set(
                GroupKey(*key_tuple),
                GroupTransform(
                    dx=offset_x,
                    dy=offset_y,
                    band_min_x=band_min_x,
                    band_max_x=band_max_x,
                    band_min_y=band_min_y,
                    band_max_y=band_max_y,
                    band_anchor_x=anchor_norm_x,
                    band_anchor_y=anchor_norm_y,
                    bounds_min_x=bounds.min_x,
                    bounds_min_y=bounds.min_y,
                    bounds_max_x=bounds.max_x,
                    bounds_max_y=bounds.max_y,
                    anchor_token=(anchor_token or "nw").lower(),
                    payload_justification=justification,
                    marker_label_position=marker_label_position,
                    background_color=background_color,
                    background_border_color=background_border_color,
                    background_border_width=int(background_border_width or 0),
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

    def _group_offsets(self, plugin_label: Optional[str], suffix: Optional[str]) -> Tuple[float, float]:
        if self._override_manager is None:
            return (0.0, 0.0)
        return self._override_manager.group_offsets(plugin_label, suffix)

    def _group_payload_justification(self, plugin_label: Optional[str], suffix: Optional[str]) -> str:
        if self._override_manager is None:
            return "left"
        return self._override_manager.group_payload_justification(plugin_label, suffix)

    def _group_marker_label_position(self, plugin_label: Optional[str], suffix: Optional[str]) -> str:
        if self._override_manager is None:
            return "below"
        return self._override_manager.group_marker_label_position(plugin_label, suffix)

    def _group_background(
        self, plugin_label: Optional[str], suffix: Optional[str]
    ) -> Tuple[Optional[str], Optional[str], Optional[int]]:
        if self._override_manager is None:
            return None, None, None
        return self._override_manager.group_background(plugin_label, suffix)

    @staticmethod
    def _anchor_from_bounds(bounds: GroupBounds, token: Optional[str]) -> Tuple[float, float]:
        if not bounds.is_valid():
            return 0.0, 0.0
        mode = (token or "nw").strip().lower()
        if mode == "first":
            mode = "nw"
        elif mode == "centroid":
            mode = "center"
        center_x = (bounds.min_x + bounds.max_x) / 2.0
        center_y = (bounds.min_y + bounds.max_y) / 2.0
        if mode == "center":
            return center_x, center_y
        if mode == "top":
            return center_x, bounds.min_y
        if mode == "bottom":
            return center_x, bounds.max_y
        if mode == "left":
            return bounds.min_x, center_y
        if mode == "right":
            return bounds.max_x, center_y
        if mode == "ne":
            return bounds.max_x, bounds.min_y
        if mode == "sw":
            return bounds.min_x, bounds.max_y
        if mode == "se":
            return bounds.max_x, bounds.max_y
        # default and "nw"
        return bounds.min_x, bounds.min_y

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
