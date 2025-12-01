"""Payload builder helpers for overlay calculations (pure math/state)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional, Tuple, TYPE_CHECKING

from overlay_client.group_transform import GroupTransform  # type: ignore
from overlay_client.payload_transform import (  # type: ignore
    PayloadTransformContext,
    build_payload_transform_context,
)
from overlay_client.viewport_helper import BASE_HEIGHT, BASE_WIDTH, ScaleMode  # type: ignore
from overlay_client.viewport_transform import LegacyMapper, FillViewport, build_viewport, compute_proportional_translation  # type: ignore

if TYPE_CHECKING:
    from overlay_client.overlay_client import _OverlayBounds  # type: ignore
    from overlay_client.viewport_transform import ViewportState  # type: ignore


GroupAnchorPointFn = Callable[[Optional[GroupTransform], PayloadTransformContext, Optional["_OverlayBounds"], bool], Optional[Tuple[float, float]]]
GroupBasePointFn = Callable[[Optional[GroupTransform], PayloadTransformContext, Optional["_OverlayBounds"], bool], Optional[Tuple[float, float]]]


@dataclass
class GroupContext:
    fill: FillViewport
    transform_context: PayloadTransformContext
    offset_x: float
    offset_y: float
    offset_norm_x: float
    offset_norm_y: float
    base_offset_x: float
    base_offset_y: float
    scale: float
    selected_anchor: Optional[Tuple[float, float]]
    base_anchor_point: Optional[Tuple[float, float]]
    anchor_for_transform: Optional[Tuple[float, float]]
    base_translation_dx: float
    base_translation_dy: float


def build_group_context(
    mapper: LegacyMapper,
    state: "ViewportState",
    group_transform: Optional[GroupTransform],
    overlay_bounds_hint: Optional["_OverlayBounds"],
    offset_x: float,
    offset_y: float,
    *,
    group_anchor_point: GroupAnchorPointFn,
    group_base_point: GroupBasePointFn,
) -> GroupContext:
    fill = build_viewport(mapper, state, group_transform, BASE_WIDTH, BASE_HEIGHT)
    transform_context = build_payload_transform_context(fill)
    base_width_norm = BASE_WIDTH if BASE_WIDTH > 0.0 else 1.0
    base_height_norm = BASE_HEIGHT if BASE_HEIGHT > 0.0 else 1.0
    offset_norm_x = offset_x / base_width_norm
    offset_norm_y = offset_y / base_height_norm
    selected_anchor: Optional[Tuple[float, float]] = None
    base_anchor_point: Optional[Tuple[float, float]] = None
    anchor_for_transform: Optional[Tuple[float, float]] = None
    base_translation_dx = 0.0
    base_translation_dy = 0.0
    if mapper.transform.mode is ScaleMode.FILL:
        use_overlay_bounds_x = (
            overlay_bounds_hint is not None
            and overlay_bounds_hint.is_valid()
            and not fill.overflow_x
        )
        base_anchor_point = group_base_point(
            group_transform,
            transform_context,
            overlay_bounds_hint,
            use_overlay_bounds_x=use_overlay_bounds_x,
        )
        anchor_for_transform = base_anchor_point
        if overlay_bounds_hint is not None and overlay_bounds_hint.is_valid():
            selected_anchor = group_anchor_point(
                group_transform,
                transform_context,
                overlay_bounds_hint,
                use_overlay_bounds_x=use_overlay_bounds_x,
            )
        if group_transform is not None and anchor_for_transform is not None:
            anchor_norm_override = (
                (group_transform.band_min_x or 0.0) + offset_norm_x,
                (group_transform.band_min_y or 0.0) + offset_norm_y,
            )
            base_translation_dx, base_translation_dy = compute_proportional_translation(
                fill,
                group_transform,
                anchor_for_transform,
                anchor_norm_override=anchor_norm_override,
            )

    return GroupContext(
        fill=fill,
        transform_context=transform_context,
        offset_x=offset_x,
        offset_y=offset_y,
        offset_norm_x=offset_norm_x,
        offset_norm_y=offset_norm_y,
        base_offset_x=fill.base_offset_x,
        base_offset_y=fill.base_offset_y,
        scale=fill.scale,
        selected_anchor=selected_anchor,
        base_anchor_point=base_anchor_point,
        anchor_for_transform=anchor_for_transform,
        base_translation_dx=base_translation_dx,
        base_translation_dy=base_translation_dy,
    )
