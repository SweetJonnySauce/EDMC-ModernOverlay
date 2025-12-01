from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
from PyQt6.QtWidgets import QApplication

sys.path.append(str(Path(__file__).resolve().parents[1]))  # noqa: E402

from overlay_client.client_config import InitialClientSettings  # noqa: E402
from overlay_client.debug_config import DebugConfig  # noqa: E402
from overlay_client.follow_geometry import ScreenInfo  # noqa: E402
from overlay_client.overlay_client import OverlayWindow  # noqa: E402
from overlay_client.window_tracking import WindowState  # noqa: E402


@pytest.fixture
def qt_app():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.mark.pyqt_required
def test_normalise_tracker_geometry_applies_title_bar_and_aspect_guard(monkeypatch, qt_app):
    settings = InitialClientSettings(title_bar_enabled=True, title_bar_height=10)
    window = OverlayWindow(settings, DebugConfig())
    monkeypatch.setattr(
        window,
        "_screen_info_for_native_rect",
        lambda rect: ScreenInfo(
            name="test",
            logical_geometry=(0, 0, 100, 100),
            native_geometry=(0, 0, 200, 200),
            device_ratio=2.0,
        ),
    )
    state = WindowState(x=10, y=20, width=80, height=60, is_foreground=True, is_visible=True)

    tracker_qt, tracker_native, norm_info, desired = window._normalise_tracker_geometry(state)

    assert tracker_native == (10, 20, 80, 60)
    assert tracker_qt == (5, 10, 40, 30)
    assert norm_info == ("test", 0.5, 0.5, 2.0)
    assert desired == (5, 15, 40, 25)
    assert window._last_title_bar_offset == 5


@pytest.mark.pyqt_required
def test_resolve_and_apply_geometry_updates_last_set_and_logs(monkeypatch, qt_app):
    window = OverlayWindow(InitialClientSettings(), DebugConfig())
    moves: list[Any] = []
    sets: list[Any] = []

    class DummyFollow:
        wm_override = None
        wm_override_tracker = None

        @staticmethod
        def override_expired() -> bool:
            return False

    class DummyController:
        def __init__(self):
            self.calls = []
            self._fullscreen_hint_logged = False

        def resolve_and_apply_geometry(self, tracker_qt_tuple, desired_tuple, **kwargs):
            self.calls.append((tracker_qt_tuple, desired_tuple, kwargs))
            kwargs["move_to_screen_fn"](desired_tuple)
            kwargs["set_geometry_fn"](desired_tuple)
            kwargs["sync_base_dimensions_fn"]()
            return desired_tuple

    window._follow_controller = DummyFollow()
    window._window_controller = DummyController()
    monkeypatch.setattr(window, "_sync_base_dimensions_to_widget", lambda: None)
    def _record_move(rect):
        if hasattr(rect, "getRect"):
            moves.append(tuple(rect.getRect()))
        else:
            moves.append(rect)

    def _record_set(rect):
        if hasattr(rect, "getRect"):
            sets.append(tuple(rect.getRect()))
        else:
            sets.append(rect)

    monkeypatch.setattr(window, "_move_to_screen", _record_move)
    monkeypatch.setattr(window, "setGeometry", _record_set)

    tracker = (1, 2, 3, 4)
    desired = (5, 6, 7, 8)

    target = window._resolve_and_apply_geometry(tracker, desired)

    assert target == desired
    assert window._last_set_geometry == desired
    assert window._last_geometry_log == desired
    assert moves == [desired]
    assert sets == [desired]


@pytest.mark.pyqt_required
def test_post_process_follow_state_calls_transient_parent_and_visibility(monkeypatch, qt_app):
    window = OverlayWindow(InitialClientSettings(), DebugConfig())
    visibility_calls: list[bool] = []
    parent_calls: list[Any] = []

    class DummyController:
        def __init__(self):
            self._fullscreen_hint_logged = False

        def post_process_follow_state(self, state, target_tuple, **kwargs):
            kwargs["update_auto_scale_fn"](target_tuple[2], target_tuple[3])
            kwargs["ensure_transient_parent_fn"](state.identifier or "")
            if kwargs["fullscreen_hint_fn"]():
                self._fullscreen_hint_logged = True
            should_show = kwargs["force_render"] or (state.is_visible and state.is_foreground)
            kwargs["update_follow_visibility_fn"](should_show)
            self._last_visibility_state = should_show

    window._window_controller = DummyController()
    monkeypatch.setattr(window, "_update_follow_visibility", lambda show: visibility_calls.append(show))
    monkeypatch.setattr(window, "_update_auto_legacy_scale", lambda w, h: None)
    monkeypatch.setattr(window, "_ensure_transient_parent", lambda ident: parent_calls.append(ident))
    monkeypatch.setattr(window, "_force_render", False, raising=False)
    monkeypatch.setattr(window, "_fullscreen_hint_logged", False, raising=False)

    state = WindowState(x=0, y=0, width=100, height=50, is_foreground=True, is_visible=False, identifier="abc")
    target = (0, 0, 100, 50)

    window._post_process_follow_state(state, target_tuple=target)

    assert len(parent_calls) == 1
    assert isinstance(parent_calls[0], WindowState)
    assert visibility_calls == [False]
    assert window._fullscreen_hint_logged in {False, True}
