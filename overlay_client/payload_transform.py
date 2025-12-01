"""Helpers for applying payload and group transformations."""
from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from PyQt6.QtGui import QFont, QFontMetrics

from overlay_client.font_utils import apply_font_fallbacks

from overlay_client.legacy_store import LegacyItem
from overlay_client.viewport_helper import BASE_HEIGHT, BASE_WIDTH

if TYPE_CHECKING:  # pragma: no cover
    from overlay_client import FillViewport
    from overlay_client.group_transform import GroupBounds


class PayloadAxisContext:
    __slots__ = ("overflow", "min_bound", "max_bound")

    def __init__(self, overflow: bool, min_bound: float, max_bound: float) -> None:
        self.overflow = overflow
        self.min_bound = min_bound
        self.max_bound = max_bound


class PayloadTransformContext:
    __slots__ = ("axis_x", "axis_y")

    def __init__(self, axis_x: PayloadAxisContext, axis_y: PayloadAxisContext) -> None:
        self.axis_x = axis_x
        self.axis_y = axis_y


def build_payload_transform_context(fill: "FillViewport") -> PayloadTransformContext:
    axis_x = PayloadAxisContext(
        overflow=fill.overflow_x,
        min_bound=0.0,
        max_bound=BASE_WIDTH,
    )
    axis_y = PayloadAxisContext(
        overflow=fill.overflow_y,
        min_bound=0.0,
        max_bound=BASE_HEIGHT,
    )
    return PayloadTransformContext(axis_x=axis_x, axis_y=axis_y)


def _clamp_axis(value: float, axis: PayloadAxisContext) -> float:
    if axis.overflow:
        return value
    if value < axis.min_bound:
        return axis.min_bound
    if value > axis.max_bound:
        return axis.max_bound
    return value


def remap_axis_value(value: float, axis: PayloadAxisContext) -> float:
    return _clamp_axis(value, axis)


def _clamp_axis(value: float, axis: PayloadAxisContext) -> float:
    if axis.overflow:
        return value
    if value < axis.min_bound:
        return axis.min_bound
    if value > axis.max_bound:
        return axis.max_bound
    return value


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def transform_components(meta: Optional[Mapping[str, Any]]) -> Tuple[float, float, float, float, float, float]:
    if not isinstance(meta, Mapping):
        return 0.0, 0.0, 1.0, 1.0, 0.0, 0.0

    pivot_block = meta.get("pivot")
    if isinstance(pivot_block, Mapping):
        pivot_x = _safe_float(pivot_block.get("x"), 0.0)
        pivot_y = _safe_float(pivot_block.get("y"), 0.0)
    else:
        pivot_x = 0.0
        pivot_y = 0.0

    scale_block = meta.get("scale")
    if isinstance(scale_block, Mapping):
        scale_x = _safe_float(scale_block.get("x"), 1.0)
        scale_y = _safe_float(scale_block.get("y"), 1.0)
    else:
        scale_x = 1.0
        scale_y = 1.0

    offset_block = meta.get("offset")
    if isinstance(offset_block, Mapping):
        offset_x = _safe_float(offset_block.get("x"), 0.0)
        offset_y = _safe_float(offset_block.get("y"), 0.0)
    else:
        offset_x = 0.0
        offset_y = 0.0

    return pivot_x, pivot_y, scale_x, scale_y, offset_x, offset_y


def logical_mapping(data: Mapping[str, Any]) -> Mapping[str, Any]:
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


def apply_transform_meta_to_point(
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
        pivot_x = _safe_float(pivot_block.get("x"), 0.0)
        pivot_y = _safe_float(pivot_block.get("y"), 0.0)
    else:
        pivot_x = 0.0
        pivot_y = 0.0

    scale_block = meta.get("scale")
    if isinstance(scale_block, Mapping):
        scale_x = _safe_float(scale_block.get("x"), 1.0)
        scale_y = _safe_float(scale_block.get("y"), 1.0)
    else:
        scale_x = 1.0
        scale_y = 1.0

    offset_block = meta.get("offset")
    if isinstance(offset_block, Mapping):
        offset_x = _safe_float(offset_block.get("x"), 0.0)
        offset_y = _safe_float(offset_block.get("y"), 0.0)
    else:
        offset_x = 0.0
        offset_y = 0.0

    scaled_x = pivot_x + (x_adj - pivot_x) * scale_x
    scaled_y = pivot_y + (y_adj - pivot_y) * scale_y
    fill_x = fill_dx if math.isfinite(fill_dx) else 0.0
    fill_y = fill_dy if math.isfinite(fill_dy) else 0.0
    return scaled_x + offset_x + fill_x, scaled_y + offset_y + fill_y


def remap_point(
    fill: "FillViewport",
    transform_meta: Optional[Mapping[str, Any]],
    raw_x: float,
    raw_y: float,
    context: Optional[PayloadTransformContext] = None,
) -> Tuple[float, float]:
    pivot_x, pivot_y, scale_x_meta, scale_y_meta, offset_x_meta, offset_y_meta = transform_components(transform_meta)
    point = fill.remap_point(
        raw_x,
        raw_y,
        pivot_x,
        pivot_y,
        scale_x_meta,
        scale_y_meta,
        offset_x_meta,
        offset_y_meta,
    )
    if context is None:
        return point
    clamped_x = _clamp_axis(point[0], context.axis_x)
    clamped_y = _clamp_axis(point[1], context.axis_y)
    return clamped_x, clamped_y


def remap_rect_points(
    fill: "FillViewport",
    transform_meta: Optional[Mapping[str, Any]],
    raw_x: float,
    raw_y: float,
    raw_w: float,
    raw_h: float,
    context: Optional[PayloadTransformContext] = None,
) -> List[Tuple[float, float]]:
    pivot_x, pivot_y, scale_x_meta, scale_y_meta, offset_x_meta, offset_y_meta = transform_components(transform_meta)
    mapper_x = fill.overlay_mapper_x(pivot_x, scale_x_meta, offset_x_meta)
    mapper_y = fill.overlay_mapper_y(pivot_y, scale_y_meta, offset_y_meta)
    corners = [
        (raw_x, raw_y),
        (raw_x + raw_w, raw_y),
        (raw_x, raw_y + raw_h),
        (raw_x + raw_w, raw_y + raw_h),
    ]
    points = [(mapper_x(cx), mapper_y(cy)) for cx, cy in corners]
    if context is None:
        return points
    return [(_clamp_axis(px, context.axis_x), _clamp_axis(py, context.axis_y)) for px, py in points]


def remap_vector_points(
    fill: "FillViewport",
    transform_meta: Optional[Mapping[str, Any]],
    points: Sequence[Mapping[str, Any]],
    context: Optional[PayloadTransformContext] = None,
) -> List[Tuple[float, float, Mapping[str, Any]]]:
    pivot_x, pivot_y, scale_x_meta, scale_y_meta, offset_x_meta, offset_y_meta = transform_components(transform_meta)
    mapper_x = fill.overlay_mapper_x(pivot_x, scale_x_meta, offset_x_meta)
    mapper_y = fill.overlay_mapper_y(pivot_y, scale_y_meta, offset_y_meta)
    resolved: List[Tuple[float, float, Mapping[str, Any]]] = []
    for point in points:
        if not isinstance(point, Mapping):
            continue
        try:
            px = float(point.get("x", 0.0))
            py = float(point.get("y", 0.0))
        except (TypeError, ValueError):
            continue
        mapped_x = mapper_x(px)
        mapped_y = mapper_y(py)
        if context is not None:
            mapped_x = _clamp_axis(mapped_x, context.axis_x)
            mapped_y = _clamp_axis(mapped_y, context.axis_y)
        resolved.append((mapped_x, mapped_y, point))
    return resolved


def _measure_text_block(metrics: QFontMetrics, text_value: str) -> Tuple[int, int]:
    """Return the pixel width/height of a potentially multi-line text block."""
    if metrics is None:
        return 0, 0
    normalised = (
        str(text_value)
        .replace("\r\n", "\n")
        .replace("\r", "\n")
    )
    lines = normalised.split("\n")
    if not lines:
        lines = [""]
    max_width = 0
    for line in lines:
        try:
            advance = metrics.horizontalAdvance(line)
        except Exception:
            advance = 0
        if advance > max_width:
            max_width = advance
    line_spacing = max(metrics.lineSpacing(), metrics.height(), 0)
    if line_spacing <= 0:
        line_spacing = 0
    total_height = line_spacing * max(1, len(lines))
    return max(0, max_width), max(0, total_height)


def accumulate_group_bounds(
    bounds: "GroupBounds",
    item: LegacyItem,
    pixels_per_overlay_unit: float,
    font_family: str,
    preset_point_size: Callable[[str], float],
    font_fallbacks: Optional[Sequence[str]] = None,
    *,
    text_block_cache: Optional[Dict[Tuple[str, float, str, Tuple[str, ...], float, int], Tuple[int, int]]] = None,
    cache_generation: int = 0,
    device_ratio: float = 1.0,
) -> None:
    from overlay_client.group_transform import GroupBounds  # local import to avoid cycles

    assert isinstance(bounds, GroupBounds)
    data = item.data
    if not isinstance(data, Mapping):
        return
    logical = logical_mapping(data)
    transform_meta = data.get("__mo_transform__") if isinstance(data, Mapping) else None

    def transform_point(x_val: float, y_val: float) -> Tuple[float, float]:
        return apply_transform_meta_to_point(transform_meta, x_val, y_val)

    kind = item.kind
    if pixels_per_overlay_unit <= 0.0 or not math.isfinite(pixels_per_overlay_unit):
        pixels_per_overlay_unit = 1.0
    try:
        if kind == "message":
            x_val = float(logical.get("x", data.get("x", 0.0)))
            y_val = float(logical.get("y", data.get("y", 0.0)))
            size_label = str(data.get("size", "normal")) if isinstance(data, Mapping) else "normal"
            point_size = preset_point_size(size_label)
            normalised_text = (
                str(data.get("text", ""))
                .replace("\r\n", "\n")
                .replace("\r", "\n")
            )
            fallback_tuple = tuple(font_fallbacks) if font_fallbacks else ()
            cache_key: Optional[Tuple[str, float, str, Tuple[str, ...], float, int]] = None
            cached_block: Optional[Tuple[int, int]] = None
            if text_block_cache is not None:
                cache_key = (
                    normalised_text,
                    point_size,
                    font_family,
                    fallback_tuple,
                    round(device_ratio or 1.0, 3),
                    int(cache_generation or 0),
                )
                cached_block = text_block_cache.get(cache_key)
            font = QFont(font_family)
            apply_font_fallbacks(font, font_fallbacks)
            font.setPointSizeF(point_size)
            metrics = QFontMetrics(font)
            text_value = normalised_text
            if cached_block is not None:
                text_width_px, block_height_px = cached_block
            else:
                text_width_px, block_height_px = _measure_text_block(metrics, text_value)
            if text_width_px <= 0 and text_value:
                try:
                    text_width_px = max(metrics.averageCharWidth() * len(text_value), 0)
                except Exception:
                    text_width_px = 0
            if block_height_px <= 0 and text_value:
                block_height_px = metrics.height()
            if cached_block is None and cache_key is not None and text_block_cache is not None:
                text_block_cache[cache_key] = (text_width_px, block_height_px)
                if len(text_block_cache) > 512:
                    text_block_cache.pop(next(iter(text_block_cache)))
            width_logical = max(0.0, text_width_px / pixels_per_overlay_unit)
            height_logical = max(0.0, block_height_px / pixels_per_overlay_unit)
            adj_x, adj_y = transform_point(x_val, y_val)
            bounds.update_rect(
                adj_x,
                adj_y,
                adj_x + width_logical,
                adj_y + height_logical,
            )
        elif kind == "rect":
            x_val = float(logical.get("x", data.get("x", 0.0)))
            y_val = float(logical.get("y", data.get("y", 0.0)))
            w_val = float(logical.get("w", data.get("w", 0.0)))
            h_val = float(logical.get("h", data.get("h", 0.0)))
            corners = [
                transform_point(x_val, y_val),
                transform_point(x_val + w_val, y_val),
                transform_point(x_val, y_val + h_val),
                transform_point(x_val + w_val, y_val + h_val),
            ]
            xs = [pt[0] for pt in corners]
            ys = [pt[1] for pt in corners]
            bounds.update_rect(min(xs), min(ys), max(xs), max(ys))
        elif kind == "vector":
            points = logical.get("points") if isinstance(logical, Mapping) else None
            if not isinstance(points, list):
                points = data.get("points") if isinstance(data, Mapping) else None
            if isinstance(points, list):
                for point in points:
                    if not isinstance(point, Mapping):
                        continue
                    try:
                        px = float(point.get("x", 0.0))
                        py = float(point.get("y", 0.0))
                    except (TypeError, ValueError):
                        continue
                    adj_x, adj_y = transform_point(px, py)
                    bounds.update_point(adj_x, adj_y)
        else:
            x_val = float(logical.get("x", data.get("x", 0.0)))
            y_val = float(logical.get("y", data.get("y", 0.0)))
            adj_x, adj_y = transform_point(x_val, y_val)
            bounds.update_point(adj_x, adj_y)
    except (TypeError, ValueError):
        pass


def determine_group_anchor(item: LegacyItem) -> Tuple[float, float]:
    data = item.data
    if not isinstance(data, Mapping):
        return 0.0, 0.0
    logical = logical_mapping(data)
    transform_meta = data.get("__mo_transform__") if isinstance(data, Mapping) else None
    kind = item.kind
    try:
        if kind == "vector":
            points = logical.get("points") if isinstance(logical, Mapping) else None
            if not isinstance(points, list) or not points:
                points = data.get("points") if isinstance(data, Mapping) else None
            if isinstance(points, list):
                for point in points:
                    if not isinstance(point, Mapping):
                        continue
                    px = _safe_float(point.get("x"), 0.0)
                    py = _safe_float(point.get("y"), 0.0)
                    return apply_transform_meta_to_point(transform_meta, px, py)
            return 0.0, 0.0
        if kind == "rect":
            px = _safe_float(logical.get("x", data.get("x", 0.0)), 0.0)
            py = _safe_float(logical.get("y", data.get("y", 0.0)), 0.0)
            return apply_transform_meta_to_point(transform_meta, px, py)
        if kind == "message":
            px = _safe_float(logical.get("x", data.get("x", 0.0)), 0.0)
            py = _safe_float(logical.get("y", data.get("y", 0.0)), 0.0)
            return apply_transform_meta_to_point(transform_meta, px, py)
    except (TypeError, ValueError):
        return 0.0, 0.0
    return 0.0, 0.0


__all__ = [
    "apply_transform_meta_to_point",
    "accumulate_group_bounds",
    "determine_group_anchor",
    "logical_mapping",
    "remap_axis_value",
    "remap_point",
    "remap_rect_points",
    "remap_vector_points",
    "transform_components",
]
