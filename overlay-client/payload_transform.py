"""Helpers for applying payload and group transformations."""
from __future__ import annotations

import math
from typing import Any, Callable, Iterable, List, Mapping, Optional, Sequence, Tuple, TYPE_CHECKING

from PyQt6.QtGui import QFont, QFontMetrics

from legacy_store import LegacyItem

if TYPE_CHECKING:  # pragma: no cover
    from overlay_client import FillViewport


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
) -> Tuple[float, float]:
    pivot_x, pivot_y, scale_x_meta, scale_y_meta, offset_x_meta, offset_y_meta = transform_components(transform_meta)
    return fill.remap_point(
        raw_x,
        raw_y,
        pivot_x,
        pivot_y,
        scale_x_meta,
        scale_y_meta,
        offset_x_meta,
        offset_y_meta,
    )


def remap_rect_points(
    fill: "FillViewport",
    transform_meta: Optional[Mapping[str, Any]],
    raw_x: float,
    raw_y: float,
    raw_w: float,
    raw_h: float,
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
    return [(mapper_x(cx), mapper_y(cy)) for cx, cy in corners]


def remap_vector_points(
    fill: "FillViewport",
    transform_meta: Optional[Mapping[str, Any]],
    points: Sequence[Mapping[str, Any]],
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
        resolved.append((mapper_x(px), mapper_y(py), point))
    return resolved


def accumulate_group_bounds(
    bounds: "GroupBounds",
    item: LegacyItem,
    scale: float,
    group_scale_hint: float,
    font_family: str,
    preset_point_size: Callable[[str], float],
) -> None:
    from group_transform import GroupBounds  # local import to avoid cycles

    assert isinstance(bounds, GroupBounds)
    data = item.data
    if not isinstance(data, Mapping):
        return
    logical = logical_mapping(data)
    transform_meta = data.get("__mo_transform__") if isinstance(data, Mapping) else None

    def transform_point(x_val: float, y_val: float) -> Tuple[float, float]:
        return apply_transform_meta_to_point(transform_meta, x_val, y_val)

    kind = item.kind
    if scale <= 0.0:
        scale = 1.0
    try:
        if kind == "message":
            x_val = float(logical.get("x", data.get("x", 0.0)))
            y_val = float(logical.get("y", data.get("y", 0.0)))
            size_label = str(data.get("size", "normal")) if isinstance(data, Mapping) else "normal"
            font = QFont(font_family)
            font.setPointSizeF(preset_point_size(size_label))
            metrics = QFontMetrics(font)
            text_value = str(data.get("text", ""))
            text_width_px = max(metrics.horizontalAdvance(text_value), 0)
            line_height_px = max(metrics.height(), 0)
            scale_block = transform_meta.get("scale") if isinstance(transform_meta, Mapping) else None
            scale_x_meta = _safe_float(scale_block.get("x"), 1.0) if isinstance(scale_block, Mapping) else 1.0
            scale_y_meta = _safe_float(scale_block.get("y"), 1.0) if isinstance(scale_block, Mapping) else 1.0
            if not math.isfinite(group_scale_hint) or math.isclose(group_scale_hint, 0.0, rel_tol=1e-9, abs_tol=1e-9):
                group_scale_hint = 1.0
            effective_scale_x = scale * group_scale_hint
            effective_scale_y = scale * group_scale_hint
            width_logical = (text_width_px * scale_x_meta) / effective_scale_x
            line_height_logical = (line_height_px * scale_y_meta) / effective_scale_y
            adj_x, adj_y = transform_point(x_val, y_val)
            bounds.update_rect(
                adj_x,
                adj_y,
                adj_x + max(0.0, width_logical),
                adj_y + max(0.0, line_height_logical),
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
    "remap_point",
    "remap_rect_points",
    "remap_vector_points",
    "transform_components",
]
