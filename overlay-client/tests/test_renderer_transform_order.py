from __future__ import annotations

import sys
from pathlib import Path

import pytest

OVERLAY_ROOT = Path(__file__).resolve().parents[1]
if str(OVERLAY_ROOT) not in sys.path:
    sys.path.append(str(OVERLAY_ROOT))

pytest.importorskip("PyQt6")

from group_transform import GroupTransform  # noqa: E402
from overlay_client import OverlayWindow  # noqa: E402


def test_fill_overlay_delta_converts_pixels_to_overlay_units() -> None:
    transform = GroupTransform(dx=128.0, dy=-64.0)
    dx, dy = OverlayWindow._fill_overlay_delta(scale=2.0, transform=transform)

    assert dx == pytest.approx(64.0)
    assert dy == pytest.approx(-32.0)


def test_transform_meta_applies_fill_translation_before_scaling() -> None:
    meta = {
        "pivot": {"x": 27.0, "y": 587.0},
        "scale": {"x": 2.0, "y": 1.0},
        "offset": {"x": 0.0, "y": 150.0},
    }

    no_fill = OverlayWindow._apply_transform_meta_to_point(meta, 124.0, 464.0, 0.0, 0.0)
    with_fill = OverlayWindow._apply_transform_meta_to_point(meta, 124.0, 464.0, 10.0, -5.0)

    assert no_fill == pytest.approx((221.0, 614.0))
    assert with_fill == pytest.approx((231.0, 609.0))


def test_transform_meta_defaults_to_fill_only_when_metadata_missing() -> None:
    result = OverlayWindow._apply_transform_meta_to_point(None, 50.0, 75.0, -5.0, 12.0)

    assert result == pytest.approx((45.0, 87.0))
