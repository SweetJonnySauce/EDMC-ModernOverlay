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
    else:
        band_min_x = band_max_x = band_min_y = band_max_y = 0.0
        band_anchor_x = band_anchor_y = 0.0

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
    )


def compute_proportional_translation(
    fill: FillViewport,
    group_transform: Optional[GroupTransform],
    anchor_point: Optional[Tuple[float, float]],
    anchor_norm_override: Optional[Tuple[float, float]] = None,
) -> Tuple[float, float]:
    if group_transform is None or anchor_point is None:
        return 0.0, 0.0
    anchor_x, anchor_y = anchor_point
    if not (math.isfinite(anchor_x) and math.isfinite(anchor_y)):
        return 0.0, 0.0
    if anchor_norm_override is not None:
        anchor_norm_x = _safe_float(anchor_norm_override[0], 0.0)
        anchor_norm_y = _safe_float(anchor_norm_override[1], 0.0)
    else:
        anchor_norm_x = _safe_float(group_transform.band_anchor_x, 0.0)
        anchor_norm_y = _safe_float(group_transform.band_anchor_y, 0.0)
    scale_value = fill.scale
    if not math.isfinite(scale_value) or math.isclose(scale_value, 0.0, rel_tol=1e-9, abs_tol=1e-9):
        return 0.0, 0.0

    visible_width = _safe_float(fill.visible_width, 0.0)
    visible_height = _safe_float(fill.visible_height, 0.0)
    dx = 0.0
    dy = 0.0

    if fill.overflow_x and visible_width > 0.0:
        span_x = visible_width / scale_value
        anchor_norm_x = max(0.0, min(1.0, anchor_norm_x))
        target_x = anchor_norm_x * span_x
        dx = target_x - anchor_x

    if fill.overflow_y and visible_height > 0.0:
        span_y = visible_height / scale_value
        anchor_norm_y = max(0.0, min(1.0, anchor_norm_y))
        target_y = anchor_norm_y * span_y
        dy = target_y - anchor_y

    return dx, dy


def inverse_group_axis(
    value: float,
    scale: float,
    overflow_active: bool,
    anchor: Optional[float],
    base_reference: Optional[float],
) -> float:
    """Inverse-scale a coordinate while respecting overflow behaviour.

    Overflow axes keep the payload rigid around the declared anchor; fitted axes
    should stay pinned to their cached bounds, so we pivot around the base
    reference instead and avoid shifting when the anchor changes.
    """
    if not math.isfinite(scale) or math.isclose(scale, 0.0, rel_tol=1e-9, abs_tol=1e-9):
        return value
    if overflow_active:
        reference = anchor
    else:
        reference = base_reference if base_reference is not None else anchor
    if reference is None or not math.isfinite(reference):
        return value / scale
    return reference + (value - reference) / scale


def remap_anchor_value(
    anchor_norm: float,
    min_norm: float,
    max_norm: float,
    actual_min: float,
    actual_max: float,
) -> float:
    """Map a normalised anchor coordinate onto concrete bounds."""
    if not all(
        math.isfinite(value)
        for value in (anchor_norm, min_norm, max_norm, actual_min, actual_max)
    ):
        return actual_min
    denom = max_norm - min_norm
    if math.isclose(denom, 0.0, rel_tol=1e-9, abs_tol=1e-9):
        return actual_min
    ratio = (anchor_norm - min_norm) / denom
    return actual_min + ratio * (actual_max - actual_min)


def normalised_anchor_ratio(anchor_norm: float, min_norm: float, max_norm: float) -> float:
    denom = max_norm - min_norm
    if math.isclose(denom, 0.0, rel_tol=1e-9, abs_tol=1e-9):
        return 0.0
    return (anchor_norm - min_norm) / denom


def map_anchor_axis(
    anchor_norm: float,
    min_norm: float,
    max_norm: float,
    actual_min: float,
    actual_max: float,
    *,
    anchor_token: Optional[str] = None,
    axis: str = "x",
) -> float:
    anchor_token = (anchor_token or "").strip().lower()
    if axis == "x" and anchor_token in {"top", "bottom", "center"}:
        return (actual_min + actual_max) / 2.0
    ratio = max(0.0, min(1.0, normalised_anchor_ratio(anchor_norm, min_norm, max_norm)))
    if math.isclose(actual_max, actual_min, rel_tol=1e-9, abs_tol=1e-9):
        return actual_min
    if math.isclose(ratio, 0.5, rel_tol=1e-6, abs_tol=1e-6):
        return (actual_min + actual_max) / 2.0
    if math.isclose(ratio, 0.0, rel_tol=1e-6, abs_tol=1e-6):
        return actual_min
    if math.isclose(ratio, 1.0, rel_tol=1e-6, abs_tol=1e-6):
        return actual_max
    return remap_anchor_value(anchor_norm, min_norm, max_norm, actual_min, actual_max)


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
