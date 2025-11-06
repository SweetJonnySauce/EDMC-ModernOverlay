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
    proportion: float = 1.0
    preserve_shift: float = 0.0
    fill_overlay_delta: float = 0.0

    def remap(self, raw: float, pivot: float, scale_meta: float, offset_meta: float) -> float:
        proportion = self._sanitise_proportion(self.proportion)
        preserve = self._sanitise_shift(self.preserve_shift)
        overlay_delta = self._sanitise_delta(self.fill_overlay_delta)
        fill_shift = overlay_delta * proportion
        base = raw * proportion + preserve + fill_shift
        pivot_adj = pivot * proportion + preserve + fill_shift
        offset_adj = offset_meta * proportion
        return pivot_adj + (base - pivot_adj) * scale_meta + offset_adj

    @staticmethod
    def _sanitise_proportion(value: float) -> float:
        if not math.isfinite(value) or value <= 0.0:
            return 1.0
        return value

    @staticmethod
    def _sanitise_shift(value: float) -> float:
        if not math.isfinite(value):
            return 0.0
        return value

    @staticmethod
    def _sanitise_delta(value: float) -> float:
        if not math.isfinite(value):
            return 0.0
        return value


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
    preserve_dx: float
    preserve_dy: float
    proportion_x: float
    proportion_y: float
    raw_proportion_x: float
    raw_proportion_y: float
    group_scale: float
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
    group_scale = _safe_float(group_transform.scale, 1.0) if group_transform else 1.0
    scale_value = base_scale * group_scale

    visible_width = _safe_float(state.width, 1.0)
    visible_height = _safe_float(state.height, 1.0)

    overflow_x = transform.overflow_x
    overflow_y = transform.overflow_y

    if not overflow_x and not overflow_y:
        proportion_x = proportion_y = raw_proportion_x = raw_proportion_y = 1.0
        preserve_dx = preserve_dy = fill_dx_overlay = fill_dy_overlay = 0.0
        band_min_x = band_max_x = band_min_y = band_max_y = 0.0
        band_anchor_x = band_anchor_y = 0.0
        band_clamped_x = band_clamped_y = False
    elif group_transform is not None:
        raw_proportion_x = _safe_proportion(group_transform.raw_proportion_x)
        raw_proportion_y = _safe_proportion(group_transform.raw_proportion_y)
        proportion_x = _safe_proportion(group_transform.proportion_x)
        proportion_y = _safe_proportion(group_transform.proportion_y)
        preserve_dx = _safe_float(group_transform.preserve_dx, 0.0)
        preserve_dy = _safe_float(group_transform.preserve_dy, 0.0)
        fill_dx_overlay = _compute_fill_overlay_delta(scale_value, _safe_float(group_transform.dx, 0.0), proportion_x)
        fill_dy_overlay = _compute_fill_overlay_delta(scale_value, _safe_float(group_transform.dy, 0.0), proportion_y)
        band_min_x = _safe_float(group_transform.band_min_x, 0.0)
        band_max_x = _safe_float(group_transform.band_max_x, 0.0)
        band_min_y = _safe_float(group_transform.band_min_y, 0.0)
        band_max_y = _safe_float(group_transform.band_max_y, 0.0)
        band_anchor_x = _safe_float(group_transform.band_anchor_x, 0.0)
        band_anchor_y = _safe_float(group_transform.band_anchor_y, 0.0)
        band_clamped_x = bool(group_transform.band_clamped_x)
        band_clamped_y = bool(group_transform.band_clamped_y)
    else:
        effective_scale = _safe_scale(base_scale, 1.0)
        raw_proportion_x = _compute_proportion(base_width, effective_scale, visible_width, overflow_x)
        raw_proportion_y = _compute_proportion(base_height, effective_scale, visible_height, overflow_y)
        proportion_x = _safe_proportion(raw_proportion_x)
        proportion_y = _safe_proportion(raw_proportion_y)
        preserve_dx = preserve_dy = fill_dx_overlay = fill_dy_overlay = 0.0
        band_min_x = band_max_x = band_min_y = band_max_y = 0.0
        band_anchor_x = band_anchor_y = 0.0
        band_clamped_x = band_clamped_y = False

    axis_x = FillAxisMapping(proportion=proportion_x, preserve_shift=preserve_dx, fill_overlay_delta=fill_dx_overlay)
    axis_y = FillAxisMapping(proportion=proportion_y, preserve_shift=preserve_dy, fill_overlay_delta=fill_dy_overlay)

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
        preserve_dx=preserve_dx,
        preserve_dy=preserve_dy,
        proportion_x=proportion_x,
        proportion_y=proportion_y,
        raw_proportion_x=raw_proportion_x,
        raw_proportion_y=raw_proportion_y,
        group_scale=group_scale,
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


def fill_overlay_delta(scale: float, transform: Optional[GroupTransform]) -> Tuple[float, float]:
    if transform is None:
        return 0.0, 0.0
    prop_x = _safe_proportion(transform.proportion_x)
    prop_y = _safe_proportion(transform.proportion_y)
    dx = _compute_fill_overlay_delta(scale, _safe_float(transform.dx, 0.0), prop_x)
    dy = _compute_fill_overlay_delta(scale, _safe_float(transform.dy, 0.0), prop_y)
    return dx, dy


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


def _compute_fill_overlay_delta(scale: float, delta_pixels: float, proportion: float) -> float:
    if not math.isfinite(delta_pixels) or math.isclose(delta_pixels, 0.0, rel_tol=1e-9, abs_tol=1e-9):
        return 0.0
    if not math.isfinite(scale) or math.isclose(scale, 0.0, rel_tol=1e-9, abs_tol=1e-9):
        return 0.0
    proportion_safe = _safe_proportion(proportion)
    if math.isclose(proportion_safe, 0.0, rel_tol=1e-9, abs_tol=1e-9):
        return 0.0
    return delta_pixels / (scale * proportion_safe)


def _compute_proportion(base_extent: float, effective_scale: float, window_extent: float, overflow: bool) -> float:
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


def _safe_float(value: float, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(result):
        return default
    return result


def _safe_scale(value: float, default: float = 1.0) -> float:
    result = _safe_float(value, default)
    if math.isclose(result, 0.0, rel_tol=1e-9, abs_tol=1e-9):
        return default
    return result


def _safe_proportion(value: float) -> float:
    if not math.isfinite(value) or value <= 0.0:
        return 1.0
    return value
