from __future__ import annotations

import pytest

from overlay_client.follow_geometry import ScreenInfo, _convert_native_rect_to_qt


def test_convert_native_rect_scales_when_dpr_and_geometries_match() -> None:
    screen = ScreenInfo(
        name="test",
        logical_geometry=(0, 0, 2560, 1440),
        native_geometry=(0, 0, 2560, 1440),
        device_ratio=1.4,
    )
    rect = (0, 0, 2560, 1440)

    converted, info = _convert_native_rect_to_qt(rect, screen)

    assert info is not None
    assert info[0] == "test"
    assert info[1] == pytest.approx(1 / 1.4)
    assert info[2] == pytest.approx(1 / 1.4)
    assert converted == (
        0,
        0,
        int(round(2560 / 1.4)),
        int(round(1440 / 1.4)),
    )


def test_convert_native_rect_keeps_identity_for_near_unity_dpr() -> None:
    screen = ScreenInfo(
        name="test",
        logical_geometry=(0, 0, 1000, 800),
        native_geometry=(0, 0, 1000, 800),
        device_ratio=1.02,
    )
    rect = (0, 0, 1000, 800)

    converted, info = _convert_native_rect_to_qt(rect, screen)

    assert converted == rect
    assert info is not None
    assert info[1] == pytest.approx(1.0)
    assert info[2] == pytest.approx(1.0)
