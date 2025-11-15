from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

OVERLAY_ROOT = Path(__file__).resolve().parents[1]
if str(OVERLAY_ROOT) not in sys.path:
    sys.path.append(str(OVERLAY_ROOT))

from group_transform import GroupTransform  # noqa: E402
from viewport_helper import BASE_HEIGHT, BASE_WIDTH, ScaleMode, compute_viewport_transform  # noqa: E402
from viewport_transform import (  # noqa: E402
    LegacyMapper,
    ViewportState,
    build_viewport,
    compute_proportional_translation,
    inverse_group_axis,
    remap_anchor_value,
    legacy_scale_components,
    scaled_point_size,
)


def _make_mapper(mode: ScaleMode, window_w: float, window_h: float) -> LegacyMapper:
    transform = compute_viewport_transform(window_w, window_h, mode)
    return LegacyMapper(
        scale_x=transform.scale,
        scale_y=transform.scale,
        offset_x=transform.offset[0],
        offset_y=transform.offset[1],
        transform=transform,
    )


def test_build_viewport_fit_mode_defaults() -> None:
    mapper = _make_mapper(ScaleMode.FIT, BASE_WIDTH, BASE_HEIGHT)
    state = ViewportState(width=BASE_WIDTH, height=BASE_HEIGHT, device_ratio=1.0)

    fill = build_viewport(mapper, state, None, BASE_WIDTH, BASE_HEIGHT)

    assert not fill.overflow_x
    assert not fill.overflow_y
    assert fill.band_min_x == pytest.approx(0.0)
    assert fill.band_min_y == pytest.approx(0.0)


def test_build_viewport_fill_mode_respects_group_transform() -> None:
    window_w = BASE_WIDTH * 1.5
    window_h = BASE_HEIGHT
    mapper = _make_mapper(ScaleMode.FILL, window_w, window_h)
    state = ViewportState(width=window_w, height=window_h, device_ratio=1.0)
    group = GroupTransform(
        band_min_x=-10.0,
        band_max_x=20.0,
        band_min_y=-5.0,
        band_max_y=15.0,
        band_anchor_x=2.0,
        band_anchor_y=-3.0,
        bounds_min_x=-10.0,
        bounds_min_y=-5.0,
        bounds_max_x=20.0,
        bounds_max_y=15.0,
    )

    fill = build_viewport(mapper, state, group, BASE_WIDTH, BASE_HEIGHT)

    assert fill.overflow_y
    assert not fill.overflow_x
    assert fill.band_min_x == pytest.approx(group.band_min_x)
    assert fill.band_max_x == pytest.approx(group.band_max_x)
    assert fill.band_min_y == pytest.approx(group.band_min_y)
    assert fill.band_max_y == pytest.approx(group.band_max_y)
    assert fill.band_anchor_x == pytest.approx(group.band_anchor_x)
    assert fill.band_anchor_y == pytest.approx(group.band_anchor_y)


def test_compute_viewport_transform_fill_mode_pins_origin() -> None:
    narrower_width = BASE_WIDTH * 0.8
    transform = compute_viewport_transform(narrower_width, BASE_HEIGHT, ScaleMode.FILL)
    assert transform.offset[0] == pytest.approx(0.0)
    assert transform.offset[1] == pytest.approx(0.0)

    shorter_height = BASE_HEIGHT * 0.75
    transform_y = compute_viewport_transform(BASE_WIDTH, shorter_height, ScaleMode.FILL)
    assert transform_y.offset[0] == pytest.approx(0.0)
    assert transform_y.offset[1] == pytest.approx(0.0)


def test_legacy_scale_components_applies_device_ratio() -> None:
    mapper = _make_mapper(ScaleMode.FILL, BASE_WIDTH * 1.25, BASE_HEIGHT * 1.25)
    state = ViewportState(width=BASE_WIDTH, height=BASE_HEIGHT, device_ratio=1.5)

    scale_x, scale_y = legacy_scale_components(mapper, state)

    expected = mapper.scale_x * state.device_ratio
    assert scale_x == pytest.approx(expected)
    assert scale_y == pytest.approx(expected)


def test_scaled_point_size_clamps_to_bounds() -> None:
    mapper = _make_mapper(ScaleMode.FILL, BASE_WIDTH, BASE_HEIGHT)
    state = ViewportState(width=BASE_WIDTH, height=BASE_HEIGHT, device_ratio=2.0)

    point = scaled_point_size(
        state=state,
        base_point=10.0,
        font_scale_diag=0.0,
        font_min_point=8.0,
        font_max_point=12.0,
        legacy_mapper=mapper,
        use_physical=True,
    )

    # Device ratio should inflate the scale; clamping should keep the value within bounds.
    assert 8.0 <= point <= 12.0
    scale_x, scale_y = legacy_scale_components(mapper, state)
    diag_scale = math.sqrt((scale_x * scale_x + scale_y * scale_y) / 2.0)
    expected = max(8.0, min(12.0, 10.0 * diag_scale))
    assert point == pytest.approx(expected)


def test_compute_proportional_translation_overflow_x_axis() -> None:
    window_w = BASE_WIDTH
    window_h = BASE_HEIGHT * 2.0
    mapper = _make_mapper(ScaleMode.FILL, window_w, window_h)
    state = ViewportState(width=window_w, height=window_h, device_ratio=1.0)
    group = GroupTransform(
        band_anchor_x=0.5,
        band_anchor_y=0.25,
    )
    fill = build_viewport(mapper, state, group, BASE_WIDTH, BASE_HEIGHT)
    anchor_point = (480.0, 120.0)

    dx, dy = compute_proportional_translation(fill, group, anchor_point)

    expected_visible = window_w / fill.scale
    expected_target = group.band_anchor_x * expected_visible
    assert dx == pytest.approx(expected_target - anchor_point[0])
    assert dy == pytest.approx(0.0)


def test_compute_proportional_translation_overflow_y_axis() -> None:
    window_w = BASE_WIDTH * 2.0
    window_h = BASE_HEIGHT
    mapper = _make_mapper(ScaleMode.FILL, window_w, window_h)
    state = ViewportState(width=window_w, height=window_h, device_ratio=1.0)
    group = GroupTransform(
        band_anchor_x=0.25,
        band_anchor_y=0.75,
    )
    fill = build_viewport(mapper, state, group, BASE_WIDTH, BASE_HEIGHT)
    anchor_point = (200.0, 700.0)

    dx, dy = compute_proportional_translation(fill, group, anchor_point)

    expected_visible = window_h / fill.scale
    expected_target = group.band_anchor_y * expected_visible
    assert dx == pytest.approx(0.0)
    assert dy == pytest.approx(expected_target - anchor_point[1])


def test_inverse_group_axis_overflow_uses_anchor() -> None:
    value = 600.0
    anchor = 640.0
    scale = 1.5

    adjusted = inverse_group_axis(value, scale, overflow_active=True, anchor=anchor, base_reference=None)

    assert adjusted == pytest.approx(anchor + (value - anchor) / scale)


def test_inverse_group_axis_fitted_axis_uses_base_reference_even_if_zero() -> None:
    value = 322.0
    scale = 0.75

    adjusted = inverse_group_axis(value, scale, overflow_active=False, anchor=640.0, base_reference=0.0)

    assert adjusted == pytest.approx(value / scale)


def test_inverse_group_axis_falls_back_to_origin_when_no_reference() -> None:
    value = 600.0
    scale = 1.5

    adjusted = inverse_group_axis(value, scale, overflow_active=False, anchor=None, base_reference=None)

    assert adjusted == pytest.approx(value / scale)


def test_remap_anchor_value_matches_actual_bounds() -> None:
    anchor_norm = 0.8
    min_norm = 0.5
    max_norm = 0.9
    actual_min = 100.0
    actual_max = 200.0

    mapped = remap_anchor_value(anchor_norm, min_norm, max_norm, actual_min, actual_max)

    ratio = (anchor_norm - min_norm) / (max_norm - min_norm)
    expected = actual_min + ratio * (actual_max - actual_min)
    assert mapped == pytest.approx(expected)


def test_remap_anchor_value_handles_degenerate_span() -> None:
    mapped = remap_anchor_value(0.5, 0.5, 0.5, 42.0, 84.0)
    assert mapped == pytest.approx(42.0)
