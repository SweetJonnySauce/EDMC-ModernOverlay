from __future__ import annotations

import logging

import pytest

import overlay_client.follow_geometry as follow_geometry_module

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


def test_convert_native_rect_clamps_when_flag_enabled() -> None:
    screen = ScreenInfo(
        name="test",
        logical_geometry=(0, 0, 2560, 1440),
        native_geometry=(0, 0, 2560, 1440),
        device_ratio=1.4,
    )
    rect = (0, 0, 2560, 1440)

    converted, info = _convert_native_rect_to_qt(rect, screen, physical_clamp_enabled=True)

    assert converted == rect
    assert info is not None
    assert info[1] == pytest.approx(1.0)
    assert info[2] == pytest.approx(1.0)


def test_convert_native_rect_flag_off_preserves_legacy_fractional_behavior() -> None:
    screen = ScreenInfo(
        name="legacy",
        logical_geometry=(0, 0, 2560, 1440),
        native_geometry=(0, 0, 2560, 1440),
        device_ratio=1.4,
    )
    rect = (0, 0, 2560, 1440)

    converted, info = _convert_native_rect_to_qt(rect, screen, physical_clamp_enabled=False)

    assert converted == (
        0,
        0,
        int(round(2560 / 1.4)),
        int(round(1440 / 1.4)),
    )
    assert info is not None
    assert info[1] == pytest.approx(1 / 1.4)
    assert info[2] == pytest.approx(1 / 1.4)


def test_convert_native_rect_flag_on_mismatched_geoms_falls_back() -> None:
    screen = ScreenInfo(
        name="mismatch",
        logical_geometry=(0, 0, 2560, 1440),
        native_geometry=(0, 0, 3840, 2160),
        device_ratio=1.4,
    )
    rect = (0, 0, 3840, 2160)

    converted, info = _convert_native_rect_to_qt(rect, screen, physical_clamp_enabled=True)

    assert converted == (
        0,
        0,
        int(round(3840 * (2560 / 3840))),
        int(round(2160 * (1440 / 2160))),
    )
    assert info is not None
    assert info[1] == pytest.approx(2560 / 3840)
    assert info[2] == pytest.approx(1440 / 2160)


def test_convert_native_rect_flag_on_integer_dpr_uses_legacy_scaling() -> None:
    screen = ScreenInfo(
        name="hidpi",
        logical_geometry=(0, 0, 2560, 1440),
        native_geometry=(0, 0, 2560, 1440),
        device_ratio=2.0,
    )
    rect = (0, 0, 2560, 1440)

    converted, info = _convert_native_rect_to_qt(rect, screen, physical_clamp_enabled=True)

    assert converted == (
        0,
        0,
        int(round(2560 / 2.0)),
        int(round(1440 / 2.0)),
    )
    assert info is not None
    assert info[1] == pytest.approx(1 / 2.0)
    assert info[2] == pytest.approx(1 / 2.0)


def test_convert_native_rect_coerces_non_finite_dpr() -> None:
    screen = ScreenInfo(
        name="bad",
        logical_geometry=(0, 0, 800, 600),
        native_geometry=(0, 0, 800, 600),
        device_ratio=0.0,
    )
    rect = (10, 10, 100, 50)

    converted, info = _convert_native_rect_to_qt(rect, screen, physical_clamp_enabled=True)

    assert converted == rect
    assert info is not None
    assert info[1] == pytest.approx(1.0)
    assert info[2] == pytest.approx(1.0)


def test_convert_native_rect_logs_clamp_once(caplog: pytest.LogCaptureFixture) -> None:
    follow_geometry_module._last_normalisation_log = None
    logger = logging.getLogger("EDMC.ModernOverlay.Client")
    previous_propagate = logger.propagate
    try:
        logger.propagate = True
        caplog.set_level(logging.DEBUG, logger="EDMC.ModernOverlay.Client")
        screen = ScreenInfo(
            name="log-test",
            logical_geometry=(0, 0, 2560, 1440),
            native_geometry=(0, 0, 2560, 1440),
            device_ratio=1.4,
        )
        rect = (0, 0, 2560, 1440)

        _convert_native_rect_to_qt(rect, screen, physical_clamp_enabled=True)
        _convert_native_rect_to_qt(rect, screen, physical_clamp_enabled=True)

        clamp_logs = [rec for rec in caplog.records if "Physical clamp applied" in rec.getMessage()]
    finally:
        logger.propagate = previous_propagate
    assert len(clamp_logs) == 1
