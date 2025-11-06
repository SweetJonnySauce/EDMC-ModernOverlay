from __future__ import annotations

import sys
from pathlib import Path

import pytest

OVERLAY_ROOT = Path(__file__).resolve().parents[1]
if str(OVERLAY_ROOT) not in sys.path:
    sys.path.append(str(OVERLAY_ROOT))

pytest.importorskip("PyQt6")

from group_transform import GroupTransform  # noqa: E402
from grouping_helper import FillGroupingHelper  # noqa: E402
from payload_transform import apply_transform_meta_to_point  # noqa: E402
from viewport_helper import BASE_HEIGHT, BASE_WIDTH  # noqa: E402
from viewport_transform import fill_overlay_delta  # noqa: E402


def test_fill_overlay_delta_converts_pixels_to_overlay_units() -> None:
    transform = GroupTransform(dx=128.0, dy=-64.0)
    dx, dy = fill_overlay_delta(scale=2.0, transform=transform)

    assert dx == pytest.approx(64.0)
    assert dy == pytest.approx(-32.0)


def test_fill_overlay_delta_honours_axis_proportion() -> None:
    transform = GroupTransform(dx=128.0, dy=0.0, proportion_x=0.5)
    dx, _ = fill_overlay_delta(scale=2.0, transform=transform)

    assert dx == pytest.approx(128.0)


def test_compute_fill_proportion_returns_ratio_when_overflow() -> None:
    ratio = FillGroupingHelper._compute_fill_proportion(
        BASE_WIDTH,
        effective_scale=1.5,
        window_extent=1280.0,
        overflow=True,
    )
    assert ratio == pytest.approx(1280.0 / (BASE_WIDTH * 1.5))


def test_compute_fill_proportion_defaults_without_overflow() -> None:
    ratio = FillGroupingHelper._compute_fill_proportion(
        BASE_HEIGHT,
        effective_scale=2.0,
        window_extent=2000.0,
        overflow=False,
    )
    assert ratio == pytest.approx(1.0)


def test_normalise_group_proportions_applies_only_overflow_axis_x() -> None:
    px, py = FillGroupingHelper._normalise_group_proportions(0.8, 1.0, overflow_x=True, overflow_y=False)
    assert px == pytest.approx(0.8)
    assert py == pytest.approx(1.0)


def test_normalise_group_proportions_handles_dual_overflow() -> None:
    px, py = FillGroupingHelper._normalise_group_proportions(0.75, 0.6, overflow_x=True, overflow_y=True)
    assert px == pytest.approx(0.75)
    assert py == pytest.approx(0.6)


def test_normalise_group_proportions_no_change_without_overflow() -> None:
    px, py = FillGroupingHelper._normalise_group_proportions(1.2, 1.0, overflow_x=False, overflow_y=False)
    assert px == pytest.approx(1.0)
    assert py == pytest.approx(1.0)


def test_normalise_group_proportions_applies_only_overflow_axis_y() -> None:
    px, py = FillGroupingHelper._normalise_group_proportions(1.0, 0.85, overflow_x=False, overflow_y=True)
    assert px == pytest.approx(1.0)
    assert py == pytest.approx(0.85)


def test_transform_meta_applies_fill_translation_before_scaling() -> None:
    meta = {
        "pivot": {"x": 27.0, "y": 587.0},
        "scale": {"x": 2.0, "y": 1.0},
        "offset": {"x": 0.0, "y": 150.0},
    }

    no_fill = apply_transform_meta_to_point(meta, 124.0, 464.0, 0.0, 0.0)
    with_fill = apply_transform_meta_to_point(meta, 124.0, 464.0, 10.0, -5.0)

    assert no_fill == pytest.approx((221.0, 614.0))
    assert with_fill == pytest.approx((231.0, 609.0))


def test_transform_meta_defaults_to_fill_only_when_metadata_missing() -> None:
    result = apply_transform_meta_to_point(None, 50.0, 75.0, -5.0, 12.0)

    assert result == pytest.approx((45.0, 87.0))
