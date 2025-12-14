from __future__ import annotations

import logging

import pytest

import overlay_client.follow_geometry as follow_geometry_module

from overlay_client.follow_geometry import ScreenInfo, _convert_native_rect_to_qt


def test_convert_native_rect_clamp_off_fractional_dpr_matches_beta1_baseline() -> None:
    screen = ScreenInfo(
        name="beta1-fractional",
        logical_geometry=(0, 0, 2560, 1440),
        native_geometry=(0, 0, 2560, 1440),
        device_ratio=1.5,
    )
    rect = (0, 0, 2560, 1440)

    converted, info = _convert_native_rect_to_qt(rect, screen, physical_clamp_enabled=False)

    assert converted == (
        0,
        0,
        int(round(2560 / 1.5)),
        int(round(1440 / 1.5)),
    )
    assert info is not None
    assert info[0] == "beta1-fractional"
    assert info[1] == pytest.approx(1 / 1.5)
    assert info[2] == pytest.approx(1 / 1.5)


def test_convert_native_rect_clamp_off_integer_dpr_matches_beta1_baseline() -> None:
    screen = ScreenInfo(
        name="beta1-integer",
        logical_geometry=(0, 0, 2560, 1440),
        native_geometry=(0, 0, 2560, 1440),
        device_ratio=2.0,
    )
    rect = (0, 0, 2560, 1440)

    converted, info = _convert_native_rect_to_qt(rect, screen, physical_clamp_enabled=False)

    assert converted == (
        0,
        0,
        int(round(2560 / 2.0)),
        int(round(1440 / 2.0)),
    )
    assert info is not None
    assert info[0] == "beta1-integer"
    assert info[1] == pytest.approx(1 / 2.0)
    assert info[2] == pytest.approx(1 / 2.0)


def test_convert_native_rect_clamp_off_near_unity_dpr_matches_beta1() -> None:
    screen = ScreenInfo(
        name="beta1-near-unity",
        logical_geometry=(0, 0, 1000, 800),
        native_geometry=(0, 0, 1000, 800),
        device_ratio=1.02,
    )
    rect = (0, 0, 1000, 800)

    converted, info = _convert_native_rect_to_qt(rect, screen, physical_clamp_enabled=False)

    assert converted == (
        0,
        0,
        int(round(1000 / 1.02)),
        int(round(800 / 1.02)),
    )
    assert info is not None
    assert info[0] == "beta1-near-unity"
    assert info[1] == pytest.approx(1 / 1.02)
    assert info[2] == pytest.approx(1 / 1.02)


def test_convert_native_rect_clamp_off_mismatched_geometry_matches_beta1_baseline() -> None:
    screen = ScreenInfo(
        name="beta1-mismatch",
        logical_geometry=(0, 0, 1920, 1080),
        native_geometry=(0, 0, 2560, 1440),
        device_ratio=1.25,
    )
    rect = (0, 0, 2560, 1440)

    converted, info = _convert_native_rect_to_qt(rect, screen, physical_clamp_enabled=False)

    assert converted == (0, 0, 1920, 1080)
    assert info is not None
    assert info[0] == "beta1-mismatch"
    assert info[1] == pytest.approx(1920 / 2560)
    assert info[2] == pytest.approx(1080 / 1440)


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

    assert converted == (
        0,
        0,
        int(round(1000 / 1.02)),
        int(round(800 / 1.02)),
    )
    assert info is not None
    assert info[1] == pytest.approx(1 / 1.02)
    assert info[2] == pytest.approx(1 / 1.02)


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


def test_clamp_on_fractional_dpr_preserves_scale_without_overrides(caplog: pytest.LogCaptureFixture) -> None:
    follow_geometry_module._last_normalisation_log = None
    logger = logging.getLogger("EDMC.ModernOverlay.Client")
    previous_propagate = logger.propagate
    caplog.set_level(logging.DEBUG, logger="EDMC.ModernOverlay.Client")
    screen = ScreenInfo(
        name="clamp-fractional",
        logical_geometry=(0, 0, 2560, 1440),
        native_geometry=(0, 0, 2560, 1440),
        device_ratio=1.4,
    )
    rect = (0, 0, 2560, 1440)

    try:
        logger.propagate = True
        converted, info = _convert_native_rect_to_qt(rect, screen, physical_clamp_enabled=True)
    finally:
        logger.propagate = previous_propagate

    assert converted == rect
    assert info is not None
    assert info[1] == pytest.approx(1.0)
    assert info[2] == pytest.approx(1.0)
    clamp_logs = [rec for rec in caplog.records if "Physical clamp applied" in rec.getMessage()]
    assert len(clamp_logs) == 1


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


def test_convert_native_rect_uses_override_when_available() -> None:
    screen = ScreenInfo(
        name="override",
        logical_geometry=(0, 0, 100, 100),
        native_geometry=(0, 0, 100, 100),
        device_ratio=1.4,
    )
    rect = (0, 0, 100, 100)

    converted, info = _convert_native_rect_to_qt(
        rect,
        screen,
        physical_clamp_enabled=True,
        physical_clamp_overrides={"override": 1.25},
    )

    assert converted == (0, 0, 125, 125)
    assert info is not None
    assert info[1] == pytest.approx(1.25)
    assert info[2] == pytest.approx(1.25)


def test_clamp_on_override_clamps_to_minimum() -> None:
    screen = ScreenInfo(
        name="min-override",
        logical_geometry=(0, 0, 100, 100),
        native_geometry=(0, 0, 100, 100),
        device_ratio=1.4,
    )
    rect = (0, 0, 100, 100)

    converted, info = _convert_native_rect_to_qt(
        rect,
        screen,
        physical_clamp_enabled=True,
        physical_clamp_overrides={"min-override": 0.2},
    )

    assert converted == (0, 0, 50, 50)
    assert info is not None
    assert info[1] == pytest.approx(0.5)
    assert info[2] == pytest.approx(0.5)


def test_clamp_on_override_clamps_to_maximum() -> None:
    screen = ScreenInfo(
        name="max-override",
        logical_geometry=(0, 0, 100, 100),
        native_geometry=(0, 0, 100, 100),
        device_ratio=1.4,
    )
    rect = (0, 0, 100, 100)

    converted, info = _convert_native_rect_to_qt(
        rect,
        screen,
        physical_clamp_enabled=True,
        physical_clamp_overrides={"max-override": 5.0},
    )

    assert converted == (0, 0, 300, 300)
    assert info is not None
    assert info[1] == pytest.approx(3.0)
    assert info[2] == pytest.approx(3.0)


def test_convert_native_rect_ignores_override_when_disabled() -> None:
    screen = ScreenInfo(
        name="disabled",
        logical_geometry=(0, 0, 1000, 800),
        native_geometry=(0, 0, 1000, 800),
        device_ratio=1.4,
    )
    rect = (0, 0, 1000, 800)

    converted, info = _convert_native_rect_to_qt(
        rect,
        screen,
        physical_clamp_enabled=False,
        physical_clamp_overrides={"disabled": 1.25},
    )

    assert converted == (0, 0, int(round(1000 / 1.4)), int(round(800 / 1.4)))
    assert info is not None
    assert info[1] == pytest.approx(1 / 1.4)
    assert info[2] == pytest.approx(1 / 1.4)


def test_convert_native_rect_skips_invalid_override_scale() -> None:
    screen = ScreenInfo(
        name="bad-override",
        logical_geometry=(0, 0, 2560, 1440),
        native_geometry=(0, 0, 2560, 1440),
        device_ratio=1.4,
    )
    rect = (0, 0, 2560, 1440)

    converted, info = _convert_native_rect_to_qt(
        rect,
        screen,
        physical_clamp_enabled=True,
        physical_clamp_overrides={"bad-override": 0.0},
    )

    assert converted == rect
    assert info is not None
    assert info[1] == pytest.approx(1.0)
    assert info[2] == pytest.approx(1.0)


def test_clamp_on_invalid_overrides_are_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    screen = ScreenInfo(
        name="bad-values",
        logical_geometry=(0, 0, 100, 100),
        native_geometry=(0, 0, 100, 100),
        device_ratio=1.4,
    )
    rect = (0, 0, 100, 100)

    converted, info = _convert_native_rect_to_qt(
        rect,
        screen,
        physical_clamp_enabled=True,
        physical_clamp_overrides={"bad-values": float("nan")},
    )

    assert converted == rect
    assert info is not None
    assert info[1] == pytest.approx(1.0)
    assert info[2] == pytest.approx(1.0)


def test_convert_native_rect_dispatches_to_standard_when_clamp_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[tuple[int, int, int, int], ScreenInfo]] = []

    def fake_standard(rect, screen_info):
        calls.append((rect, screen_info))
        return (1, 2, 3, 4), ("legacy", 1.0, 1.0, 1.0)

    monkeypatch.setattr(follow_geometry_module, "_convert_native_rect_to_qt_standard", fake_standard)
    monkeypatch.setattr(
        follow_geometry_module,
        "_convert_native_rect_to_qt_clamp",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("clamp path should not run")),
    )

    screen = ScreenInfo(
        name="dispatch-legacy",
        logical_geometry=(0, 0, 100, 100),
        native_geometry=(0, 0, 100, 100),
        device_ratio=1.25,
    )
    rect = (0, 0, 100, 100)

    converted, info = _convert_native_rect_to_qt(rect, screen, physical_clamp_enabled=False)

    assert calls == [(rect, screen)]
    assert converted == (1, 2, 3, 4)
    assert info == ("legacy", 1.0, 1.0, 1.0)


def test_convert_native_rect_dispatches_to_clamp_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []

    def fake_clamp(rect, screen_info, *, physical_clamp_overrides=None):
        calls.append({"rect": rect, "screen": screen_info, "overrides": physical_clamp_overrides})
        return (9, 9, 9, 9), ("clamp", 2.0, 2.0, 2.0)

    monkeypatch.setattr(
        follow_geometry_module,
        "_convert_native_rect_to_qt_standard",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("legacy path should not run")),
    )
    monkeypatch.setattr(follow_geometry_module, "_convert_native_rect_to_qt_clamp", fake_clamp)

    screen = ScreenInfo(
        name="dispatch-clamp",
        logical_geometry=(0, 0, 100, 100),
        native_geometry=(0, 0, 100, 100),
        device_ratio=1.5,
    )
    rect = (0, 0, 100, 100)

    converted, info = _convert_native_rect_to_qt(rect, screen, physical_clamp_enabled=True, physical_clamp_overrides={"dispatch-clamp": 2.0})

    assert calls == [{"rect": rect, "screen": screen, "overrides": {"dispatch-clamp": 2.0}}]
    assert converted == (9, 9, 9, 9)
    assert info == ("clamp", 2.0, 2.0, 2.0)


def test_dispatcher_matches_standard_outputs_for_baselines(monkeypatch: pytest.MonkeyPatch) -> None:
    from overlay_client.follow_geometry import _convert_native_rect_to_qt_standard

    baselines = [
        (
            (0, 0, 2560, 1440),
            ScreenInfo(
                name="beta1-fractional",
                logical_geometry=(0, 0, 2560, 1440),
                native_geometry=(0, 0, 2560, 1440),
                device_ratio=1.5,
            ),
        ),
        (
            (0, 0, 2560, 1440),
            ScreenInfo(
                name="beta1-integer",
                logical_geometry=(0, 0, 2560, 1440),
                native_geometry=(0, 0, 2560, 1440),
                device_ratio=2.0,
            ),
        ),
        (
            (0, 0, 1920, 1080),
            ScreenInfo(
                name="beta1-mismatch",
                logical_geometry=(0, 0, 1920, 1080),
                native_geometry=(0, 0, 2560, 1440),
                device_ratio=1.25,
            ),
        ),
    ]

    for rect, screen in baselines:
        expected, expected_info = _convert_native_rect_to_qt_standard(rect, screen)
        converted, info = _convert_native_rect_to_qt(rect, screen, physical_clamp_enabled=False)
        assert converted == expected
        assert info == expected_info


def test_standard_path_emits_no_clamp_logs(caplog: pytest.LogCaptureFixture) -> None:
    follow_geometry_module._last_normalisation_log = None
    caplog.set_level(logging.DEBUG, logger="EDMC.ModernOverlay.Client")
    screen = ScreenInfo(
        name="no-log",
        logical_geometry=(0, 0, 2560, 1440),
        native_geometry=(0, 0, 2560, 1440),
        device_ratio=1.4,
    )
    rect = (0, 0, 2560, 1440)

    _convert_native_rect_to_qt(rect, screen, physical_clamp_enabled=False)

    clamp_logs = [rec for rec in caplog.records if "Physical clamp applied" in rec.getMessage()]
    override_logs = [rec for rec in caplog.records if "Per-monitor clamp override" in rec.getMessage()]
    assert not clamp_logs
    assert not override_logs


def test_clamp_path_emits_clamp_logs_once(caplog: pytest.LogCaptureFixture) -> None:
    follow_geometry_module._last_normalisation_log = None
    logger = logging.getLogger("EDMC.ModernOverlay.Client")
    previous_propagate = logger.propagate
    caplog.set_level(logging.DEBUG, logger="EDMC.ModernOverlay.Client")
    screen = ScreenInfo(
        name="with-log",
        logical_geometry=(0, 0, 2560, 1440),
        native_geometry=(0, 0, 2560, 1440),
        device_ratio=1.4,
    )
    rect = (0, 0, 2560, 1440)

    try:
        logger.propagate = True
        _convert_native_rect_to_qt(
            rect,
            screen,
            physical_clamp_enabled=True,
            physical_clamp_overrides={"with-log": 1.25},
        )
        _convert_native_rect_to_qt(
            rect,
            screen,
            physical_clamp_enabled=True,
            physical_clamp_overrides={"with-log": 1.25},
        )
        clamp_logs = [rec for rec in caplog.records if "Physical clamp applied" in rec.getMessage()]
        override_logs = [rec for rec in caplog.records if "Per-monitor clamp override applied" in rec.getMessage()]
    finally:
        logger.propagate = previous_propagate
    assert len(clamp_logs) == 1
    assert len(override_logs) == 1


def test_follow_surface_routes_flag_to_standard_or_clamp(monkeypatch: pytest.MonkeyPatch) -> None:
    from overlay_client.follow_surface import FollowSurfaceMixin

    calls: list[str] = []

    def fake_standard(rect, screen_info):
        calls.append("standard")
        return rect, ("std", 1.0, 1.0, 1.0)

    def fake_clamp(rect, screen_info, *, physical_clamp_overrides=None):
        calls.append("clamp")
        return rect, ("clamp", 2.0, 2.0, 2.0)

    monkeypatch.setattr(follow_geometry_module, "_convert_native_rect_to_qt_standard", fake_standard)
    monkeypatch.setattr(follow_geometry_module, "_convert_native_rect_to_qt_clamp", fake_clamp)

    class DummyWindow(FollowSurfaceMixin):
        def __init__(self):
            self._physical_clamp_enabled = False
            self._physical_clamp_overrides = None

        def _screen_info_for_native_rect(self, rect):
            return ScreenInfo(
                name="dummy",
                logical_geometry=(0, 0, 100, 100),
                native_geometry=(0, 0, 100, 100),
                device_ratio=1.0,
            )

    window = DummyWindow()
    window._convert_native_rect_to_qt((0, 0, 10, 10))
    window._physical_clamp_enabled = True
    window._physical_clamp_overrides = {"dummy": 2.0}
    window._convert_native_rect_to_qt((0, 0, 10, 10))

    assert calls == ["standard", "clamp"]


def test_follow_surface_ignores_overrides_when_clamp_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    from overlay_client.follow_surface import FollowSurfaceMixin

    calls: list[str] = []

    def fake_standard(rect, screen_info):
        calls.append("standard")
        return rect, ("std", 1.0, 1.0, 1.0)

    def fake_clamp(rect, screen_info, *, physical_clamp_overrides=None):
        calls.append("clamp")
        return rect, ("clamp", 2.0, 2.0, 2.0)

    monkeypatch.setattr(follow_geometry_module, "_convert_native_rect_to_qt_standard", fake_standard)
    monkeypatch.setattr(follow_geometry_module, "_convert_native_rect_to_qt_clamp", fake_clamp)

    class DummyWindow(FollowSurfaceMixin):
        def __init__(self):
            self._physical_clamp_enabled = False
            self._physical_clamp_overrides = {"dummy": 2.0}

        def _screen_info_for_native_rect(self, rect):
            return ScreenInfo(
                name="dummy",
                logical_geometry=(0, 0, 100, 100),
                native_geometry=(0, 0, 100, 100),
                device_ratio=1.0,
            )

    window = DummyWindow()
    window._convert_native_rect_to_qt((0, 0, 10, 10))
    assert calls == ["standard"]


def test_follow_surface_applies_overrides_after_enabling_clamp(monkeypatch: pytest.MonkeyPatch) -> None:
    from overlay_client.follow_surface import FollowSurfaceMixin

    calls: list[str] = []

    def fake_standard(rect, screen_info):
        calls.append("standard")
        return rect, ("std", 1.0, 1.0, 1.0)

    def fake_clamp(rect, screen_info, *, physical_clamp_overrides=None):
        calls.append(("clamp", physical_clamp_overrides))
        return rect, ("clamp", 2.0, 2.0, 2.0)

    monkeypatch.setattr(follow_geometry_module, "_convert_native_rect_to_qt_standard", fake_standard)
    monkeypatch.setattr(follow_geometry_module, "_convert_native_rect_to_qt_clamp", fake_clamp)

    class DummyWindow(FollowSurfaceMixin):
        def __init__(self):
            self._physical_clamp_enabled = False
            self._physical_clamp_overrides = {"dummy": 1.5}

        def _screen_info_for_native_rect(self, rect):
            return ScreenInfo(
                name="dummy",
                logical_geometry=(0, 0, 100, 100),
                native_geometry=(0, 0, 100, 100),
                device_ratio=1.0,
            )

    window = DummyWindow()
    window._convert_native_rect_to_qt((0, 0, 10, 10))
    window._physical_clamp_enabled = True
    window._convert_native_rect_to_qt((0, 0, 10, 10))

    assert calls == ["standard", ("clamp", {"dummy": 1.5})]


def test_control_surface_overrides_do_not_apply_when_clamp_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    from overlay_client.control_surface import ControlSurfaceMixin

    calls: list[str] = []

    class DummyWindow(ControlSurfaceMixin):
        def __init__(self):
            self._physical_clamp_enabled = False
            self._physical_clamp_overrides = {}
            self._follow_enabled = False
            self._window_tracker = object()
            self._follow_controller = type(
                "C",
                (),
                {"reset_resume_window": lambda self: calls.append("reset_resume")},
            )()

        def _apply_follow_state(self, state):
            calls.append(("apply_follow", state))

        def update(self):
            calls.append("update")

    window = DummyWindow()
    window.set_physical_clamp_overrides({"dummy": 1.5})

    assert calls == ["reset_resume", "update"]


def test_follow_surface_routes_back_to_standard_after_disabling_clamp(monkeypatch: pytest.MonkeyPatch) -> None:
    from overlay_client.follow_surface import FollowSurfaceMixin

    calls: list[str] = []

    def fake_standard(rect, screen_info):
        calls.append("standard")
        return rect, ("std", 1.0, 1.0, 1.0)

    def fake_clamp(rect, screen_info, *, physical_clamp_overrides=None):
        calls.append("clamp")
        return rect, ("clamp", 2.0, 2.0, 2.0)

    monkeypatch.setattr(follow_geometry_module, "_convert_native_rect_to_qt_standard", fake_standard)
    monkeypatch.setattr(follow_geometry_module, "_convert_native_rect_to_qt_clamp", fake_clamp)

    class DummyWindow(FollowSurfaceMixin):
        def __init__(self):
            self._physical_clamp_enabled = True
            self._physical_clamp_overrides = {"dummy": 1.5}

        def _screen_info_for_native_rect(self, rect):
            return ScreenInfo(
                name="dummy",
                logical_geometry=(0, 0, 100, 100),
                native_geometry=(0, 0, 100, 100),
                device_ratio=1.0,
            )

    window = DummyWindow()
    window._convert_native_rect_to_qt((0, 0, 10, 10))
    window._physical_clamp_enabled = False
    window._convert_native_rect_to_qt((0, 0, 10, 10))

    assert calls == ["clamp", "standard"]


def test_overrides_and_clamp_logs_are_suppressed_when_flag_false(caplog: pytest.LogCaptureFixture) -> None:
    follow_geometry_module._last_normalisation_log = None
    caplog.set_level(logging.DEBUG, logger="EDMC.ModernOverlay.Client")
    screen = ScreenInfo(
        name="suppressed",
        logical_geometry=(0, 0, 2560, 1440),
        native_geometry=(0, 0, 2560, 1440),
        device_ratio=1.4,
    )
    rect = (0, 0, 2560, 1440)

    _convert_native_rect_to_qt(
        rect,
        screen,
        physical_clamp_enabled=False,
        physical_clamp_overrides={"suppressed": 1.25},
    )

    clamp_logs = [rec for rec in caplog.records if "Physical clamp applied" in rec.getMessage()]
    override_logs = [rec for rec in caplog.records if "Per-monitor clamp override" in rec.getMessage()]
    assert not clamp_logs
    assert not override_logs


def test_overrides_and_clamp_logs_emit_once_when_flag_true(caplog: pytest.LogCaptureFixture) -> None:
    follow_geometry_module._last_normalisation_log = None
    logger = logging.getLogger("EDMC.ModernOverlay.Client")
    previous_propagate = logger.propagate
    caplog.set_level(logging.DEBUG, logger="EDMC.ModernOverlay.Client")
    screen = ScreenInfo(
        name="emit",
        logical_geometry=(0, 0, 2560, 1440),
        native_geometry=(0, 0, 2560, 1440),
        device_ratio=1.4,
    )
    rect = (0, 0, 2560, 1440)

    try:
        logger.propagate = True
        _convert_native_rect_to_qt(
            rect,
            screen,
            physical_clamp_enabled=True,
            physical_clamp_overrides={"emit": 1.25},
        )
        _convert_native_rect_to_qt(
            rect,
            screen,
            physical_clamp_enabled=True,
            physical_clamp_overrides={"emit": 1.25},
        )
        clamp_logs = [rec for rec in caplog.records if "Physical clamp applied" in rec.getMessage()]
        override_logs = [rec for rec in caplog.records if "Per-monitor clamp override applied" in rec.getMessage()]
    finally:
        logger.propagate = previous_propagate
    assert len(clamp_logs) == 1
    assert len(override_logs) == 1


def test_dispatcher_uses_clamp_helper_when_flag_true(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []

    def fake_clamp(rect, screen_info, *, physical_clamp_overrides=None):
        calls.append({"rect": rect, "screen": screen_info, "overrides": physical_clamp_overrides})
        return rect, ("clamp", 2.0, 2.0, 2.0)

    monkeypatch.setattr(
        follow_geometry_module,
        "_convert_native_rect_to_qt_standard",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("standard path should not run")),
    )
    monkeypatch.setattr(follow_geometry_module, "_convert_native_rect_to_qt_clamp", fake_clamp)

    screen = ScreenInfo(
        name="dispatch-clamp2",
        logical_geometry=(0, 0, 100, 100),
        native_geometry=(0, 0, 100, 100),
        device_ratio=1.5,
    )
    rect = (0, 0, 100, 100)

    converted, info = _convert_native_rect_to_qt(
        rect,
        screen,
        physical_clamp_enabled=True,
        physical_clamp_overrides={"dispatch-clamp2": 1.75},
    )

    assert calls == [{"rect": rect, "screen": screen, "overrides": {"dispatch-clamp2": 1.75}}]
    assert converted == rect
    assert info == ("clamp", 2.0, 2.0, 2.0)


def test_resolve_wm_override_matches_beta1_when_override_active() -> None:
    tracker = (10, 10, 100, 100)
    desired = (20, 20, 100, 100)
    override_rect = (5, 5, 100, 100)
    override_tracker = (10, 10, 100, 100)

    target, clear_reason = follow_geometry_module._resolve_wm_override(
        tracker, desired, override_rect, override_tracker, override_expired=False
    )

    assert target == override_rect
    assert clear_reason is None


def test_resolve_wm_override_matches_beta1_when_tracker_realigns() -> None:
    tracker = (5, 5, 100, 100)
    desired = (20, 20, 100, 100)
    override_rect = (5, 5, 100, 100)
    override_tracker = (10, 10, 100, 100)

    target, clear_reason = follow_geometry_module._resolve_wm_override(
        tracker, desired, override_rect, override_tracker, override_expired=False
    )

    assert target == desired
    assert clear_reason == "tracker realigned with WM"


def test_resolve_wm_override_matches_beta1_when_expired_with_clamp_off() -> None:
    tracker = (10, 10, 100, 100)
    desired = (20, 20, 100, 100)
    override_rect = (5, 5, 100, 100)
    override_tracker = (10, 10, 100, 100)

    target, clear_reason = follow_geometry_module._resolve_wm_override(
        tracker, desired, override_rect, override_tracker, override_expired=True
    )

    assert target == desired
    assert clear_reason == "override timeout"
