from __future__ import annotations

from typing import List, Optional, Tuple

from overlay_client.window_controller import WindowController
from overlay_client.window_tracking import WindowState


Geometry = Tuple[int, int, int, int]


def _state(
    *,
    x: int = 0,
    y: int = 0,
    width: int = 800,
    height: int = 600,
    is_foreground: bool = True,
    is_visible: bool = True,
    identifier: Optional[str] = "abcdef",
    global_x: Optional[int] = None,
    global_y: Optional[int] = None,
) -> WindowState:
    return WindowState(
        x=x,
        y=y,
        width=width,
        height=height,
        is_foreground=is_foreground,
        is_visible=is_visible,
        identifier=identifier,
        global_x=global_x,
        global_y=global_y,
    )


def test_resolve_and_apply_geometry_updates_window_and_clears_override() -> None:
    logs: List[str] = []
    controller = WindowController(log_fn=logs.append)
    # Start with current geometry different from desired; after set_geometry we return the target.
    current: Geometry = (0, 0, 100, 100)

    def current_geometry() -> Geometry:
        return current

    move_calls: List[Geometry] = []

    def move_to_screen(target: Geometry) -> None:
        move_calls.append(target)

    set_calls: List[Geometry] = []

    def set_geometry(target: Geometry) -> None:
        nonlocal current
        set_calls.append(target)
        current = target

    cleared: List[str] = []

    def clear_override(reason: str) -> None:
        cleared.append(reason)

    set_override_calls: List[Tuple[Geometry, Geometry, str, str]] = []

    def set_override(actual: Geometry, tracker: Geometry, reason: str, classification: str) -> None:
        set_override_calls.append((actual, tracker, reason, classification))

    target = controller.resolve_and_apply_geometry(
        tracker_qt_tuple=(10, 10, 200, 200),
        desired_tuple=(10, 10, 200, 200),
        override_rect=None,
        override_tracker=None,
        override_expired=False,
        current_geometry_fn=current_geometry,
        move_to_screen_fn=move_to_screen,
        set_geometry_fn=set_geometry,
        sync_base_dimensions_fn=lambda: None,
        classify_override_fn=lambda t, a: "wm_intervention",
        clear_override_fn=clear_override,
        set_override_fn=set_override,
        format_scale_debug_fn=lambda: "debug",
    )

    assert target == (10, 10, 200, 200)
    assert set_calls == [(10, 10, 200, 200)]
    assert move_calls == [(10, 10, 200, 200)]
    assert not set_override_calls
    assert not cleared  # no override present to clear


def test_resolve_and_apply_geometry_adopts_wm_override_when_actual_differs() -> None:
    logs: List[str] = []
    controller = WindowController(log_fn=logs.append)
    current: Geometry = (0, 0, 100, 100)

    def current_geometry() -> Geometry:
        return current

    def move_to_screen(target: Geometry) -> None:
        pass

    def set_geometry(target: Geometry) -> None:
        # Simulate WM enforcing a different size after setGeometry
        nonlocal current
        current = (target[0], target[1], target[2] - 50, target[3] - 50)

    cleared: List[str] = []

    def clear_override(reason: str) -> None:
        cleared.append(reason)

    set_override_calls: List[Tuple[Geometry, Geometry, str, str]] = []

    def set_override(actual: Geometry, tracker: Geometry, reason: str, classification: str) -> None:
        set_override_calls.append((actual, tracker, reason, classification))

    target = controller.resolve_and_apply_geometry(
        tracker_qt_tuple=(10, 10, 200, 200),
        desired_tuple=(10, 10, 200, 200),
        override_rect=None,
        override_tracker=None,
        override_expired=False,
        current_geometry_fn=current_geometry,
        move_to_screen_fn=move_to_screen,
        set_geometry_fn=set_geometry,
        sync_base_dimensions_fn=lambda: None,
        classify_override_fn=lambda t, a: "layout",
        clear_override_fn=clear_override,
        set_override_fn=set_override,
        format_scale_debug_fn=lambda: "debug",
    )

    assert target == (10, 10, 150, 150)
    assert set_override_calls == [((10, 10, 150, 150), (10, 10, 200, 200), "geometry mismatch", "layout")]
    assert not cleared


def test_post_process_follow_state_updates_visibility_and_fullscreen_hint() -> None:
    logs: List[str] = []
    controller = WindowController(log_fn=logs.append)
    visibility: List[bool] = []
    auto_scale_calls: List[Tuple[int, int]] = []
    transient_calls: List[str] = []
    fullscreen_called: List[bool] = []

    def update_visibility(show: bool) -> None:
        visibility.append(show)

    def auto_scale(w: int, h: int) -> None:
        auto_scale_calls.append((w, h))

    def ensure_parent(identifier: str) -> None:
        transient_calls.append(identifier)

    def fullscreen_hint() -> bool:
        fullscreen_called.append(True)
        return True

    state = _state(width=1920, height=1080, is_foreground=True, is_visible=True, identifier="abc123")
    controller.post_process_follow_state(
        state,
        (0, 0, 1920, 1080),
        force_render=False,
        update_follow_visibility_fn=update_visibility,
        update_auto_scale_fn=auto_scale,
        ensure_transient_parent_fn=ensure_parent,
        fullscreen_hint_fn=fullscreen_hint,
    )

    assert visibility == [True]
    assert auto_scale_calls == [(1920, 1080)]
    assert transient_calls == ["abc123"]
    assert fullscreen_called == [True]
    assert controller._last_follow_state == state
    assert controller._last_visibility_state is True
