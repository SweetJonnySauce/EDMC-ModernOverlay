from __future__ import annotations

from typing import Any, Mapping

from overlay_client.transform_helpers import (
    apply_inverse_group_scale,
    compute_message_transform,
    compute_rect_transform,
    compute_vector_transform,
)
from overlay_client.payload_transform import build_payload_transform_context
from overlay_client.viewport_helper import ScaleMode, ViewportTransform
from overlay_client.viewport_transform import FillAxisMapping, FillViewport, LegacyMapper, ViewportState


def _fill(
    *,
    scale: float = 1.0,
    base_offset_x: float = 0.0,
    base_offset_y: float = 0.0,
    overflow_x: bool = False,
    overflow_y: bool = False,
) -> FillViewport:
    return FillViewport(
        scale=scale,
        base_offset_x=base_offset_x,
        base_offset_y=base_offset_y,
        visible_width=100.0,
        visible_height=80.0,
        overflow_x=overflow_x,
        overflow_y=overflow_y,
        axis_x=FillAxisMapping(),
        axis_y=FillAxisMapping(),
        band_min_x=0.0,
        band_max_x=0.0,
        band_min_y=0.0,
        band_max_y=0.0,
        band_anchor_x=0.0,
        band_anchor_y=0.0,
    )


def _mapper(scale: float = 1.0, mode: ScaleMode = ScaleMode.FIT, overflow_x: bool = False, overflow_y: bool = False) -> LegacyMapper:
    transform = ViewportTransform(
        mode=mode,
        scale=scale,
        offset=(0.0, 0.0),
        scaled_size=(1280.0 * scale, 960.0 * scale),
        overflow_x=overflow_x,
        overflow_y=overflow_y,
    )
    return LegacyMapper(scale_x=scale, scale_y=scale, offset_x=0.0, offset_y=0.0, transform=transform)


def _state() -> ViewportState:
    return ViewportState(width=1280.0, height=960.0, device_ratio=1.0)


def _trace_recorder():
    calls = []

    def trace(stage: str, details: Mapping[str, Any]) -> None:
        calls.append((stage, details))

    return calls, trace


def _remap_context(scale_x: float, scale_y: float, offset_x: float, offset_y: float) -> Any:
    transform = ViewportTransform(
        mode=ScaleMode.FILL,
        scale=1.0,
        offset=(0.0, 0.0),
        scaled_size=(1280.0, 960.0),
        overflow_x=False,
        overflow_y=False,
    )
    mapper = LegacyMapper(
        scale_x=1.0,
        scale_y=1.0,
        offset_x=0.0,
        offset_y=0.0,
        transform=transform,
    )
    fill = FillViewport(
        scale=1.0,
        base_offset_x=offset_x,
        base_offset_y=offset_y,
        visible_width=100.0,
        visible_height=80.0,
        overflow_x=False,
        overflow_y=False,
        axis_x=FillAxisMapping(),
        axis_y=FillAxisMapping(),
        band_min_x=0.0,
        band_max_x=0.0,
        band_min_y=0.0,
        band_max_y=0.0,
        band_anchor_x=0.0,
        band_anchor_y=0.0,
    )
    return mapper, fill, scale_x, scale_y, offset_x, offset_y


def test_apply_inverse_group_scale_scales_rel_to_anchor():
    fill = _fill(scale=2.0)
    anchor = (10.0, 10.0)
    base_anchor = (10.0, 10.0)
    scaled = apply_inverse_group_scale(12.0, 14.0, anchor, base_anchor, fill)
    assert scaled == (11.0, 12.0)


def test_apply_inverse_group_scale_no_scale_change():
    fill = _fill(scale=1.0)
    anchor = (5.0, 5.0)
    result = apply_inverse_group_scale(9.0, 9.0, anchor, anchor, fill)
    assert result == (9.0, 9.0)


def test_compute_message_transform_basic_offsets_and_translation():
    fill = _fill(scale=1.0, base_offset_x=5.0, base_offset_y=7.0)
    mapper = _mapper(scale=1.0, mode=ScaleMode.FIT)
    calls, trace = _trace_recorder()
    adjusted_left, adjusted_top, base_left, base_top, anchor, dx, dy = compute_message_transform(
        "plugin",
        "item",
        fill,
        transform_context=None,
        transform_meta=None,
        mapper=mapper,
        group_transform=None,
        overlay_bounds_hint=None,
        raw_left=10.0,
        raw_top=20.0,
        offset_x=2.0,
        offset_y=3.0,
        selected_anchor=None,
        base_anchor_point=None,
        anchor_for_transform=None,
        base_translation_dx=3.0,
        base_translation_dy=4.0,
        trace_fn=trace,
        collect_only=False,
    )
    assert (adjusted_left, adjusted_top) == (12.0, 23.0)
    assert (base_left, base_top) == (12.0, 23.0)
    assert anchor is None
    assert (dx, dy) == (3.0, 4.0)
    assert ("paint:message_input", {"x": 10.0, "y": 20.0, "scale": 1.0, "offset_x": 5.0, "offset_y": 7.0, "mode": "fit"}) in calls


def test_compute_message_transform_with_anchor_and_inverse_scale_remap():
    mapper, fill, scale_x_meta, scale_y_meta, offset_x_meta, offset_y_meta = _remap_context(
        scale_x=2.0, scale_y=2.0, offset_x=4.0, offset_y=6.0
    )
    transform_meta = {"scale": {"x": scale_x_meta, "y": scale_y_meta}, "offset": {"x": offset_x_meta, "y": offset_y_meta}}
    calls, trace = _trace_recorder()
    adjusted_left, adjusted_top, base_left, base_top, anchor, dx, dy = compute_message_transform(
        "plugin",
        "item",
        fill,
        transform_context=None,
        transform_meta=transform_meta,
        mapper=mapper,
        group_transform=None,
        overlay_bounds_hint=None,
        raw_left=2.0,
        raw_top=4.0,
        offset_x=1.0,
        offset_y=1.0,
        selected_anchor=(2.0, 3.0),
        base_anchor_point=(2.0, 3.0),
        anchor_for_transform=(2.0, 3.0),
        base_translation_dx=0.0,
        base_translation_dy=0.0,
        trace_fn=trace,
        collect_only=False,
    )
    # Remap applies scale/offset meta around the anchor; translation remains zero here.
    assert (adjusted_left, adjusted_top) == (9.0, 15.0)
    assert (base_left, base_top) == (9.0, 15.0)
    assert anchor == (2.0, 3.0)
    assert (dx, dy) == (0.0, 0.0)
    assert any(stage == "paint:message_input" for stage, _ in calls)


def test_compute_rect_transform_fill_mode_applies_inverse_and_translation():
    fill = _fill(scale=2.0)
    mapper = _mapper(scale=2.0, mode=ScaleMode.FILL)
    calls, trace = _trace_recorder()
    transformed, base_points, ref_bounds, anchor = compute_rect_transform(
        "plugin",
        "item",
        fill,
        transform_context=None,
        transform_meta=None,
        mapper=mapper,
        group_transform=None,
        raw_x=0.0,
        raw_y=0.0,
        raw_w=10.0,
        raw_h=10.0,
        offset_x=0.0,
        offset_y=0.0,
        selected_anchor=(0.0, 0.0),
        base_anchor_point=(0.0, 0.0),
        anchor_for_transform=(0.0, 0.0),
        base_translation_dx=5.0,
        base_translation_dy=6.0,
        trace_fn=trace,
        collect_only=False,
    )
    # With inverse scaling at 2x, points halve then translate by (5,6)
    assert transformed == [(5.0, 6.0), (10.0, 6.0), (5.0, 11.0), (10.0, 11.0)]
    assert base_points == [(0.0, 0.0), (5.0, 0.0), (0.0, 5.0), (5.0, 5.0)]
    assert ref_bounds == (0.0 + 5.0, 0.0 + 6.0, 5.0 + 5.0, 5.0 + 6.0)
    assert anchor == (5.0, 6.0)
    assert any(call[0] == "paint:rect_translation" for call in calls)


def test_compute_rect_transform_with_anchor_and_reference_bounds():
    fill = _fill(scale=1.0, base_offset_x=3.0, base_offset_y=4.0)
    mapper = _mapper(scale=1.0, mode=ScaleMode.FIT)
    calls, trace = _trace_recorder()
    transform_context = build_payload_transform_context(fill)
    transformed, base_points, ref_bounds, anchor = compute_rect_transform(
        "plugin",
        "item",
        fill,
        transform_context=transform_context,
        transform_meta={"pivot": {"x": 1.0, "y": 2.0}, "offset": {"x": 1.0, "y": -1.0}},
        mapper=mapper,
        group_transform=None,
        raw_x=2.0,
        raw_y=3.0,
        raw_w=4.0,
        raw_h=5.0,
        offset_x=0.5,
        offset_y=1.0,
        selected_anchor=(3.0, 4.0),
        base_anchor_point=(3.0, 4.0),
        anchor_for_transform=(3.0, 4.0),
        base_translation_dx=0.0,
        base_translation_dy=0.0,
        trace_fn=trace,
        collect_only=False,
    )
    assert anchor is None
    assert base_points == [(3.5, 3.0), (7.5, 3.0), (3.5, 8.0), (7.5, 8.0)]
    assert ref_bounds is None
    assert transformed == [
        (3.5, 3.0),
        (7.5, 3.0),
        (3.5, 8.0),
        (7.5, 8.0),
    ]
    assert any(stage == "paint:rect_input" for stage, _ in calls)


def test_compute_vector_transform_guard_insufficient_points():
    fill = _fill(scale=1.0)
    mapper = _mapper(scale=1.0, mode=ScaleMode.FIT)
    result = compute_vector_transform(
        "plugin",
        "item",
        fill,
        transform_context=None,
        transform_meta=None,
        mapper=mapper,
        group_transform=None,
        item_data={"base_color": "#fff"},
        raw_points=[{"x": 1, "y": 2}],
        offset_x=0.0,
        offset_y=0.0,
        selected_anchor=None,
        base_anchor_point=None,
        anchor_for_transform=None,
        base_translation_dx=0.0,
        base_translation_dy=0.0,
        trace_fn=None,
        collect_only=False,
    )
    vector_payload, screen_points, overlay_bounds, base_overlay_bounds, effective_anchor, raw_min_x, trace_cb = result
    assert vector_payload is None
    assert screen_points == []
    assert overlay_bounds is None
    assert base_overlay_bounds is None
    assert effective_anchor is None
    assert raw_min_x == 1.0
    assert trace_cb is None


def test_compute_vector_transform_single_point_marker():
    fill = _fill(scale=1.0)
    mapper = _mapper(scale=1.0, mode=ScaleMode.FIT)
    result = compute_vector_transform(
        "plugin",
        "item",
        fill,
        transform_context=None,
        transform_meta=None,
        mapper=mapper,
        group_transform=None,
        item_data={"base_color": "#fff"},
        raw_points=[{"x": 1, "y": 2, "marker": "cross"}],
        offset_x=0.0,
        offset_y=0.0,
        selected_anchor=None,
        base_anchor_point=None,
        anchor_for_transform=None,
        base_translation_dx=0.0,
        base_translation_dy=0.0,
        trace_fn=None,
        collect_only=False,
    )
    vector_payload, screen_points, overlay_bounds, base_overlay_bounds, effective_anchor, raw_min_x, trace_cb = result
    assert vector_payload is not None
    assert vector_payload["points"][0]["x"] == 1.0
    assert vector_payload["points"][0]["y"] == 2.0
    assert screen_points == [(1, 2)]
    assert overlay_bounds == (1.0, 2.0, 1.0, 2.0)
    assert base_overlay_bounds == (1.0, 2.0, 1.0, 2.0)
    assert effective_anchor is None
    assert raw_min_x == 1.0
    assert trace_cb is None


def test_compute_vector_transform_basic_points_and_bounds():
    fill = _fill(scale=1.0, base_offset_x=2.0, base_offset_y=3.0)
    mapper = _mapper(scale=1.0, mode=ScaleMode.FIT)
    calls, trace = _trace_recorder()
    vector_payload, screen_points, overlay_bounds, base_overlay_bounds, effective_anchor, raw_min_x, trace_cb = compute_vector_transform(
        "plugin",
        "item",
        fill,
        transform_context=None,
        transform_meta=None,
        mapper=mapper,
        group_transform=None,
        item_data={"base_color": "#fff"},
        raw_points=[{"x": 0, "y": 0}, {"x": 2, "y": 4}],
        offset_x=1.0,
        offset_y=1.0,
        selected_anchor=None,
        base_anchor_point=None,
        anchor_for_transform=None,
        base_translation_dx=0.0,
        base_translation_dy=0.0,
        trace_fn=trace,
        collect_only=False,
    )
    assert vector_payload is not None
    assert vector_payload["points"][0]["x"] == 1.0 and vector_payload["points"][0]["y"] == 1.0
    assert vector_payload["points"][1]["x"] == 3.0 and vector_payload["points"][1]["y"] == 5.0
    assert screen_points == [(3, 4), (5, 8)]
    assert overlay_bounds == (1.0, 1.0, 3.0, 5.0)
    assert base_overlay_bounds == (1.0, 1.0, 3.0, 5.0)
    assert effective_anchor is None
    assert raw_min_x == 0.0
    assert trace_cb is not None
    assert any(call[0] == "paint:raw_points" for call in calls)


def test_compute_vector_transform_with_anchor_translation_and_bounds():
    fill = _fill(scale=1.0, base_offset_x=0.5, base_offset_y=0.5)
    mapper = _mapper(scale=1.0, mode=ScaleMode.FILL)
    calls, trace = _trace_recorder()
    vector_payload, screen_points, overlay_bounds, base_overlay_bounds, effective_anchor, raw_min_x, trace_cb = compute_vector_transform(
        "plugin",
        "item",
        fill,
        transform_context=None,
        transform_meta={"offset": {"x": 1.0, "y": -1.0}},
        mapper=mapper,
        group_transform=None,
        item_data={"base_color": "#fff"},
        raw_points=[{"x": 1, "y": 1}, {"x": 3, "y": 4}],
        offset_x=2.0,
        offset_y=-1.0,
        selected_anchor=(2.0, 2.0),
        base_anchor_point=(2.0, 2.0),
        anchor_for_transform=(2.0, 2.0),
        base_translation_dx=1.0,
        base_translation_dy=-2.0,
        trace_fn=trace,
        collect_only=False,
    )
    assert vector_payload is not None
    assert vector_payload["points"][0]["x"] == 5.0 and vector_payload["points"][0]["y"] == -3.0
    assert vector_payload["points"][1]["x"] == 7.0 and vector_payload["points"][1]["y"] == 0.0
    assert screen_points == [(6, -2), (8, 0)]
    assert overlay_bounds == (5.0, -3.0, 7.0, 0.0)
    assert base_overlay_bounds == (4.0, -1.0, 6.0, 2.0)
    assert effective_anchor == (3.0, 0.0)
    assert raw_min_x == 1.0
    assert trace_cb is not None
    assert any(stage == "paint:raw_points" for stage, _ in calls)
