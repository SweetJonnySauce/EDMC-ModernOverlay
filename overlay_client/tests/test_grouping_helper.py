from __future__ import annotations

import os
import pytest

if not os.getenv("PYQT_TESTS"):
    pytest.skip("PYQT_TESTS not set; skipping PyQt-dependent test", allow_module_level=True)

from overlay_client.group_transform import GroupBounds
from overlay_client.grouping_helper import FillGroupingHelper


def _build_bounds() -> GroupBounds:
    bounds = GroupBounds()
    bounds.update_rect(10.0, 5.0, 30.0, 45.0)
    return bounds


@pytest.mark.parametrize(
    ("anchor", "expected"),
    [
        ("center", (20.0, 25.0)),
        ("top", (20.0, 5.0)),
        ("bottom", (20.0, 45.0)),
        ("left", (10.0, 25.0)),
        ("right", (30.0, 25.0)),
    ],
)
def test_anchor_midpoints(anchor: str, expected: tuple[float, float]) -> None:
    bounds = _build_bounds()
    resolved = FillGroupingHelper._anchor_from_bounds(bounds, anchor)
    assert resolved[0] == pytest.approx(expected[0])
    assert resolved[1] == pytest.approx(expected[1])
