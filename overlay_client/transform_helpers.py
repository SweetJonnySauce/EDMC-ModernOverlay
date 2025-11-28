"""Pure transform helpers for legacy payload calculations (no Qt types)."""
from __future__ import annotations

import math
from typing import Any, Callable, List, Mapping, Optional, Tuple

from overlay_client.payload_transform import remap_point  # type: ignore
from overlay_client.viewport_transform import FillViewport, inverse_group_axis  # type: ignore
from overlay_client.viewport_helper import ScaleMode  # type: ignore
from overlay_client.payload_transform import remap_rect_points  # type: ignore
from overlay_client.payload_transform import PayloadTransformContext  # type: ignore
from overlay_client.group_transform import GroupTransform  # type: ignore
from overlay_client.viewport_transform import LegacyMapper  # type: ignore

TraceFn = Callable[[str, Mapping[str, Any]], None]


def apply_inverse_group_scale(
    value_x: float,
    value_y: float,
    anchor: Optional[Tuple[float, float]],
    base_anchor: Optional[Tuple[float, float]],
    fill: FillViewport,
) -> Tuple[float, float]:
    scale = getattr(fill, "scale", 0.0)
    if not math.isfinite(scale) or math.isclose(scale, 0.0, rel_tol=1e-9, abs_tol=1e-9):
        return value_x, value_y
    if math.isclose(scale, 1.0, rel_tol=1e-9, abs_tol=1e-9):
        return value_x, value_y
    anchor_x = anchor[0] if anchor is not None else None
    anchor_y = anchor[1] if anchor is not None else None
    base_x = base_anchor[0] if base_anchor is not None else None
    base_y = base_anchor[1] if base_anchor is not None else None
    adjusted_x = inverse_group_axis(
        value_x,
        scale,
        getattr(fill, "overflow_x", False),
        anchor_x,
        base_x if (base_x is not None and not getattr(fill, "overflow_x", False)) else anchor_x,
    )
    adjusted_y = inverse_group_axis(
        value_y,
        scale,
        getattr(fill, "overflow_y", False),
        anchor_y,
        base_y if (base_y is not None and not getattr(fill, "overflow_y", False)) else anchor_y,
    )
    return adjusted_x, adjusted_y


def compute_message_transform(
    plugin_name: str,
    item_id: str,
    fill: FillViewport,
    transform_context: PayloadTransformContext,
    transform_meta: Any,
    mapper: LegacyMapper,
    group_transform: Optional[GroupTransform],
    overlay_bounds_hint: Optional[Any],
    raw_left: float,
    raw_top: float,
    offset_x: float,
    offset_y: float,
    selected_anchor: Optional[Tuple[float, float]],
    base_anchor_point: Optional[Tuple[float, float]],
    anchor_for_transform: Optional[Tuple[float, float]],
    base_translation_dx: float,
    base_translation_dy: float,
    trace_fn: Optional[TraceFn],
    collect_only: bool,
) -> Tuple[float, float, float, float, Optional[Tuple[float, float]], float, float]:
    if trace_fn is not None and not collect_only:
        trace_fn(
            "paint:message_input",
            {
                "x": raw_left,
                "y": raw_top,
                "scale": fill.scale,
                "offset_x": fill.base_offset_x,
                "offset_y": fill.base_offset_y,
                "mode": mapper.transform.mode.value,
            },
        )
    adjusted_left, adjusted_top = remap_point(fill, transform_meta, raw_left, raw_top, context=transform_context)
    if offset_x or offset_y:
        adjusted_left += offset_x
        adjusted_top += offset_y
    if mapper.transform.mode is ScaleMode.FILL:
        adjusted_left, adjusted_top = apply_inverse_group_scale(
            adjusted_left,
            adjusted_top,
            anchor_for_transform,
            base_anchor_point or anchor_for_transform,
            fill,
        )
    base_left_logical = adjusted_left
    base_top_logical = adjusted_top
    translation_dx = base_translation_dx
    translation_dy = base_translation_dy
    effective_anchor: Optional[Tuple[float, float]] = None
    if mapper.transform.mode is ScaleMode.FILL:
        if trace_fn is not None and not collect_only:
            trace_fn(
                "paint:message_translation",
                {
                    "base_translation_dx": base_translation_dx,
                    "base_translation_dy": base_translation_dy,
                    "right_justification_delta": 0.0,
                    "applied_translation_dx": translation_dx,
                },
            )
        adjusted_left += translation_dx
        adjusted_top += translation_dy
        if selected_anchor is not None:
            transformed_anchor = apply_inverse_group_scale(
                selected_anchor[0],
                selected_anchor[1],
                anchor_for_transform,
                base_anchor_point or anchor_for_transform,
                fill,
            )
            effective_anchor = (
                transformed_anchor[0] + translation_dx,
                transformed_anchor[1] + translation_dy,
            )
    return (
        adjusted_left,
        adjusted_top,
        base_left_logical,
        base_top_logical,
        effective_anchor,
        translation_dx,
        translation_dy,
    )


def compute_rect_transform(
    plugin_name: str,
    item_id: str,
    fill: FillViewport,
    transform_context: PayloadTransformContext,
    transform_meta: Any,
    mapper: LegacyMapper,
    group_transform: Optional[GroupTransform],
    raw_x: float,
    raw_y: float,
    raw_w: float,
    raw_h: float,
    offset_x: float,
    offset_y: float,
    selected_anchor: Optional[Tuple[float, float]],
    base_anchor_point: Optional[Tuple[float, float]],
    anchor_for_transform: Optional[Tuple[float, float]],
    base_translation_dx: float,
    base_translation_dy: float,
    trace_fn: Optional[TraceFn],
    collect_only: bool,
) -> Tuple[
    List[Tuple[float, float]],
    List[Tuple[float, float]],
    Optional[Tuple[float, float, float, float]],
    Optional[Tuple[float, float]],
]:
    if trace_fn is not None and not collect_only:
        trace_fn(
            "paint:rect_input",
            {
                "x": raw_x,
                "y": raw_y,
                "w": raw_w,
                "h": raw_h,
                "scale": fill.scale,
                "offset_x": fill.base_offset_x,
                "offset_y": fill.base_offset_y,
                "mode": mapper.transform.mode.value,
            },
        )
    transformed_overlay = remap_rect_points(fill, transform_meta, raw_x, raw_y, raw_w, raw_h, context=transform_context)
    if offset_x or offset_y:
        transformed_overlay = [
            (px + offset_x, py + offset_y)
            for px, py in transformed_overlay
        ]
    base_overlay_points: List[Tuple[float, float]] = []
    reference_overlay_bounds: Optional[Tuple[float, float, float, float]] = None
    effective_anchor: Optional[Tuple[float, float]] = None
    if mapper.transform.mode is ScaleMode.FILL:
        transformed_overlay = [
            apply_inverse_group_scale(px, py, anchor_for_transform, base_anchor_point or anchor_for_transform, fill)
            for px, py in transformed_overlay
        ]
        base_overlay_points = [tuple(pt) for pt in transformed_overlay]
        if base_overlay_points:
            base_xs = [pt[0] for pt in base_overlay_points]
            base_ys = [pt[1] for pt in base_overlay_points]
            reference_overlay_bounds = (
                min(base_xs) + base_translation_dx,
                min(base_ys) + base_translation_dy,
                max(base_xs) + base_translation_dx,
                max(base_ys) + base_translation_dy,
            )
        translation_dx = base_translation_dx
        if trace_fn is not None and not collect_only:
            trace_fn(
                "paint:rect_translation",
                {
                    "base_translation_dx": base_translation_dx,
                    "base_translation_dy": base_translation_dy,
                    "right_justification_delta": 0.0,
                    "applied_translation_dx": translation_dx,
                },
            )
        if translation_dx or base_translation_dy:
            transformed_overlay = [
                (px + translation_dx, py + base_translation_dy)
                for px, py in transformed_overlay
            ]
        if selected_anchor is not None:
            transformed_anchor = apply_inverse_group_scale(
                selected_anchor[0],
                selected_anchor[1],
                anchor_for_transform,
                base_anchor_point or anchor_for_transform,
                fill,
            )
            effective_anchor = (
                transformed_anchor[0] + translation_dx,
                transformed_anchor[1] + base_translation_dy,
            )
    else:
        base_overlay_points = [tuple(pt) for pt in transformed_overlay]
    return transformed_overlay, base_overlay_points, reference_overlay_bounds, effective_anchor
