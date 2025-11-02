from __future__ import annotations

import sys
from pathlib import Path

import pytest

OVERLAY_ROOT = Path(__file__).resolve().parents[1]
if str(OVERLAY_ROOT) not in sys.path:
    sys.path.append(str(OVERLAY_ROOT))

from group_transform import GroupBounds, GroupKey, GroupTransform, GroupTransformCache  # noqa: E402


def test_group_bounds_update_point_and_rect():
    bounds = GroupBounds()
    bounds.update_point(10, 20)
    bounds.update_point(-5, 15)
    bounds.update_rect(30, -10, 40, 5)

    assert bounds.min_x == -5
    assert bounds.max_x == 40
    assert bounds.min_y == -10
    assert bounds.max_y == 20


def test_group_bounds_invalid_until_updated():
    bounds = GroupBounds()
    assert not bounds.is_valid()
    bounds.update_point(0, 0)
    assert bounds.is_valid()


def test_group_transform_cache_roundtrip():
    cache = GroupTransformCache()
    key = GroupKey("Test", "metrics")

    assert cache.get(key) is None

    transform = GroupTransform(dx=5.0, dy=-3.0)
    cache.set(key, transform)
    retrieved = cache.get(key)

    assert retrieved is transform
