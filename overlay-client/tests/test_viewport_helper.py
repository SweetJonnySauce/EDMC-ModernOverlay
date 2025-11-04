from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

OVERLAY_ROOT = Path(__file__).resolve().parents[1]
if str(OVERLAY_ROOT) not in sys.path:
    sys.path.append(str(OVERLAY_ROOT))

from viewport_helper import BASE_HEIGHT, BASE_WIDTH, ScaleMode, compute_viewport_transform


def test_fit_mode_baseline():
    transform = compute_viewport_transform(BASE_WIDTH, BASE_HEIGHT, ScaleMode.FIT)
    assert math.isclose(transform.scale, 1.0)
    assert transform.offset == (0.0, 0.0)
    assert transform.scaled_size == (BASE_WIDTH, BASE_HEIGHT)
    assert not transform.overflow_x
    assert not transform.overflow_y


@pytest.mark.parametrize(
    ("window_w", "window_h", "expected_scale", "expected_offset_x", "expected_offset_y"),
    [
        (1920.0, 1080.0, 1080.0 / BASE_HEIGHT, (1920.0 - (BASE_WIDTH * (1080.0 / BASE_HEIGHT))) / 2.0, 0.0),
        (3440.0, 1440.0, 1440.0 / BASE_HEIGHT, (3440.0 - (BASE_WIDTH * (1440.0 / BASE_HEIGHT))) / 2.0, 0.0),
        (1024.0, 768.0, 1024.0 / BASE_WIDTH, 0.0, (768.0 - (BASE_HEIGHT * (1024.0 / BASE_WIDTH))) / 2.0),
    ],
)
def test_fit_mode_offsets(window_w, window_h, expected_scale, expected_offset_x, expected_offset_y):
    transform = compute_viewport_transform(window_w, window_h, ScaleMode.FIT)
    assert math.isclose(transform.scale, expected_scale)
    assert math.isclose(transform.offset[0], expected_offset_x)
    assert math.isclose(transform.offset[1], expected_offset_y)
    assert not transform.overflow_x
    assert not transform.overflow_y


def test_fill_mode_wide_window_overflows_height():
    transform = compute_viewport_transform(3440.0, 1440.0, ScaleMode.FILL)
    assert math.isclose(transform.scale, 3440.0 / BASE_WIDTH)
    assert transform.offset == (0.0, 0.0)
    assert not transform.overflow_x
    assert transform.overflow_y
    scaled_w, scaled_h = transform.scaled_size
    assert math.isclose(scaled_w, 3440.0)
    assert scaled_h > 1440.0


def test_fill_mode_tall_window_overflows_width():
    transform = compute_viewport_transform(1200.0, 1600.0, ScaleMode.FILL)
    assert math.isclose(transform.scale, 1600.0 / BASE_HEIGHT)
    assert transform.overflow_x
    assert not transform.overflow_y


def test_compute_viewport_requires_positive_dimensions():
    with pytest.raises(ValueError):
        compute_viewport_transform(0, BASE_HEIGHT, ScaleMode.FIT)
    with pytest.raises(ValueError):
        compute_viewport_transform(1280, -1, ScaleMode.FILL)
