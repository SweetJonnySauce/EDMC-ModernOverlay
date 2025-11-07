"""Viewport scaling helpers decoupled from Qt widgets."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Optional, Tuple

from group_transform import GroupTransform
from viewport_helper import ViewportTransform


@dataclass(frozen=True)
class ViewportState:
    width: float
    height: float
    device_ratio: float = 1.0


@dataclass(frozen=True)
class LegacyMapper:
    scale_x: float
    scale_y: float
    offset_x: float
    offset_y: float
    transform: ViewportTransform


@dataclass(frozen=True)
class FillAxisMapping:
    def remap(self, raw: float, pivot: float, scale_meta: float, offset_meta: float) -> float:
        return pivot + (raw - pivot) * scale_meta + offset_meta


@dataclass(frozen=True)
class FillViewport:
    scale: float
    base_offset_x: float
    base_offset_y: float
    visible_width: float
    visible_height: float
    overflow_x: bool
    overflow_y: bool
    axis_x: FillAxisMapping
    axis_y: FillAxisMapping
    band_min_x: float = 0.0
    band_max_x: float = 0.0
    band_min_y: float = 0.0
    band_max_y: float = 0.0
    band_anchor_x: float = 0.0
    band_anchor_y: float = 0.0
    band_clamped_x: bool = False
    band_clamped_y: bool = False

    def overlay_mapper_x(self, pivot: float, scale_meta: float, offset_meta: float) -> Callable[[float], float]:
        axis = self.axis_x

        def mapper(raw: float) -> float:
            return axis.remap(raw, pivot, scale_meta, offset_meta)

        return mapper

    def overlay_mapper_y(self, pivot: float, scale_meta: float, offset_meta: float) -> Callable[[float], float]:
        axis = self.axis_y

        def mapper(raw: float) -> float:
            return axis.remap(raw, pivot, scale_meta, offset_meta)

        return mapper

    def remap_point(
        self,
        raw_x: float,
        raw_y: float,
        pivot_x: float,
        pivot_y: float,
        scale_x_meta: float,
        scale_y_meta: float,
        offset_x_meta: float,
        offset_y_meta: float,
    ) -> Tuple[float, float]:
        return (
            self.axis_x.remap(raw_x, pivot_x, scale_x_meta, offset_x_meta),
            self.axis_y.remap(raw_y, pivot_y, scale_y_meta, offset_y_meta),
        )

    def screen_x(self, overlay_value: float) -> float:
        return overlay_value * self.scale + self.base_offset_x

    def screen_y(self, overlay_value: float) -> float:
        return overlay_value * self.scale + self.base_offset_y


def build_viewport(
    mapper: LegacyMapper,
    state: ViewportState,
    group_transform: Optional[GroupTransform],
    base_width: float,
    base_height: float,
) -> FillViewport:
    transform = mapper.transform
    base_scale = _safe_float(transform.scale, 0.0)
    scale_value = base_scale

    visible_width = _safe_float(state.width, 1.0)
    visible_height = _safe_float(state.height, 1.0)

    overflow_x = transform.overflow_x
    overflow_y = transform.overflow_y

    if group_transform is not None:
        band_min_x = _safe_float(group_transform.band_min_x, 0.0)
        band_max_x = _safe_float(group_transform.band_max_x, 0.0)
        band_min_y = _safe_float(group_transform.band_min_y, 0.0)
        band_max_y = _safe_float(group_transform.band_max_y, 0.0)
        band_anchor_x = _safe_float(group_transform.band_anchor_x, 0.0)
        band_anchor_y = _safe_float(group_transform.band_anchor_y, 0.0)
        band_clamped_x = bool(group_transform.band_clamped_x)
        band_clamped_y = bool(group_transform.band_clamped_y)
    else:
        band_min_x = band_max_x = band_min_y = band_max_y = 0.0
        band_anchor_x = band_anchor_y = 0.0
        band_clamped_x = band_clamped_y = False

    axis_x = FillAxisMapping()
    axis_y = FillAxisMapping()

    return FillViewport(
        scale=scale_value,
        base_offset_x=mapper.offset_x,
        base_offset_y=mapper.offset_y,
        visible_width=visible_width,
        visible_height=visible_height,
        overflow_x=overflow_x,
        overflow_y=overflow_y,
        axis_x=axis_x,
        axis_y=axis_y,
        band_min_x=band_min_x,
        band_max_x=band_max_x,
        band_min_y=band_min_y,
        band_max_y=band_max_y,
        band_anchor_x=band_anchor_x,
        band_anchor_y=band_anchor_y,
        band_clamped_x=band_clamped_x,
        band_clamped_y=band_clamped_y,
    )


def legacy_scale_components(mapper: LegacyMapper, state: ViewportState) -> Tuple[float, float]:
    scale_x = mapper.scale_x
    scale_y = mapper.scale_y
    ratio = state.device_ratio if state.device_ratio > 0.0 else 1.0
    return max(scale_x * ratio, 0.01), max(scale_y * ratio, 0.01)


def scaled_point_size(
    state: ViewportState,
    base_point: float,
    font_scale_diag: float,
    font_min_point: float,
    font_max_point: float,
    legacy_mapper: LegacyMapper,
    use_physical: bool = True,
) -> float:
    if use_physical:
        scale_x, scale_y = legacy_scale_components(legacy_mapper, state)
    else:
        scale_x, scale_y = legacy_mapper.scale_x, legacy_mapper.scale_y
    diagonal_scale = font_scale_diag if font_scale_diag > 0.0 else math.sqrt((scale_x * scale_x + scale_y * scale_y) / 2.0)
    return max(font_min_point, min(font_max_point, base_point * diagonal_scale))


def _safe_float(value: float, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(result):
        return default
    return result
