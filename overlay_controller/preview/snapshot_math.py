from __future__ import annotations

import math
from typing import Optional, Tuple

from overlay_client.group_transform import GroupTransform
from overlay_client.viewport_helper import BASE_HEIGHT as VC_BASE_HEIGHT, BASE_WIDTH as VC_BASE_WIDTH, ScaleMode
from overlay_client.viewport_transform import ViewportState, build_viewport, compute_proportional_translation
from overlay_client.window_utils import compute_legacy_mapper


def clamp_unit(value: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(number):
        return 0.0
    if number < 0.0:
        return 0.0
    if number > 1.0:
        return 1.0
    return number


def anchor_point_from_bounds(bounds: Tuple[float, float, float, float], anchor: str) -> Tuple[float, float]:
    min_x, min_y, max_x, max_y = bounds
    mid_x = (min_x + max_x) / 2.0
    mid_y = (min_y + max_y) / 2.0
    token = (anchor or "nw").strip().lower()
    if token in {"c", "center"}:
        return mid_x, mid_y
    if token in {"n", "top"}:
        return mid_x, min_y
    if token in {"ne"}:
        return max_x, min_y
    if token in {"right", "e"}:
        return max_x, mid_y
    if token in {"se"}:
        return max_x, max_y
    if token in {"bottom", "s"}:
        return mid_x, max_y
    if token in {"sw"}:
        return min_x, max_y
    if token in {"left", "w"}:
        return min_x, mid_y
    return min_x, min_y


def translate_snapshot_for_fill(
    snapshot,
    viewport_width: float,
    viewport_height: float,
    *,
    scale_mode_value: Optional[str] = None,
    anchor_token_override: Optional[str] = None,
):
    if snapshot is None or snapshot.has_transform:
        return snapshot
    scale_mode = (scale_mode_value or "fill").strip().lower()
    mapper = compute_legacy_mapper(scale_mode, float(max(viewport_width, 1.0)), float(max(viewport_height, 1.0)))
    transform = mapper.transform
    if transform.mode is not ScaleMode.FILL or not (transform.overflow_x or transform.overflow_y):
        return snapshot
    base_bounds = snapshot.base_bounds
    anchor_token = anchor_token_override or snapshot.transform_anchor_token or snapshot.anchor_token or "nw"
    anchor_point = anchor_point_from_bounds(base_bounds, anchor_token)
    base_width = VC_BASE_WIDTH if VC_BASE_WIDTH > 0.0 else 1.0
    base_height = VC_BASE_HEIGHT if VC_BASE_HEIGHT > 0.0 else 1.0
    clamp = clamp_unit
    group_transform = GroupTransform(
        dx=0.0,
        dy=0.0,
        band_min_x=clamp(base_bounds[0] / base_width),
        band_max_x=clamp(base_bounds[2] / base_width),
        band_min_y=clamp(base_bounds[1] / base_height),
        band_max_y=clamp(base_bounds[3] / base_height),
        band_anchor_x=clamp(anchor_point[0] / base_width),
        band_anchor_y=clamp(anchor_point[1] / base_height),
        bounds_min_x=base_bounds[0],
        bounds_min_y=base_bounds[1],
        bounds_max_x=base_bounds[2],
        bounds_max_y=base_bounds[3],
        anchor_token=anchor_token,
        payload_justification="left",
    )
    viewport_state = ViewportState(width=float(max(viewport_width, 1.0)), height=float(max(viewport_height, 1.0)))
    fill = build_viewport(mapper, viewport_state, group_transform, VC_BASE_WIDTH, VC_BASE_HEIGHT)
    dx, dy = compute_proportional_translation(fill, group_transform, anchor_point)
    if not (dx or dy):
        return snapshot
    trans_bounds = (
        base_bounds[0] + dx,
        base_bounds[1] + dy,
        base_bounds[2] + dx,
        base_bounds[3] + dy,
    )
    trans_anchor = (anchor_point[0] + dx, anchor_point[1] + dy)
    return type(snapshot)(
        plugin=snapshot.plugin,
        label=snapshot.label,
        anchor_token=snapshot.anchor_token,
        transform_anchor_token=anchor_token,
        offset_x=snapshot.offset_x,
        offset_y=snapshot.offset_y,
        base_bounds=snapshot.base_bounds,
        base_anchor=snapshot.base_anchor,
        transform_bounds=trans_bounds,
        transform_anchor=trans_anchor,
        has_transform=True,
        cache_timestamp=snapshot.cache_timestamp,
    )
