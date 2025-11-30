from __future__ import annotations

from overlay_client.overlay_client import OverlayWindow
from overlay_client.interaction_controller import InteractionController


class _StubFrame:
    def __init__(self, w: int, h: int) -> None:
        self._w = w
        self._h = h

    def width(self) -> int:
        return self._w

    def height(self) -> int:
        return self._h


def test_current_physical_size_defaults_ratio_and_logs(monkeypatch):
    logs = []

    def _debug(msg: str, *args) -> None:
        logs.append(msg % args if args else msg)

    window = type(
        "Stub",
        (),
        {
            "frameGeometry": lambda self: _StubFrame(100, 50),
            "windowHandle": lambda self: type("WH", (), {"devicePixelRatio": lambda self: (_ for _ in ()).throw(RuntimeError("fail"))})(),
            "_current_physical_size": OverlayWindow._current_physical_size,
        },
    )()
    monkeypatch.setattr("overlay_client.overlay_client._CLIENT_LOGGER.debug", _debug)

    width, height = window._current_physical_size()  # type: ignore[attr-defined]

    assert (width, height) == (100.0, 50.0)
    assert any("devicePixelRatio" in msg for msg in logs)


def test_viewport_state_defaults_ratio_and_logs(monkeypatch):
    logs = []

    def _debug(msg: str, *args) -> None:
        logs.append(msg % args if args else msg)

    window = type(
        "Stub",
        (),
        {
            "width": lambda self: 200,
            "height": lambda self: 100,
            "devicePixelRatioF": lambda self: (_ for _ in ()).throw(AttributeError("no dpr")),
            "_viewport_state": OverlayWindow._viewport_state,
        },
    )()
    monkeypatch.setattr("overlay_client.overlay_client._CLIENT_LOGGER.debug", _debug)

    state = window._viewport_state()  # type: ignore[attr-defined]

    assert state.device_ratio == 1.0
    assert any("devicePixelRatioF unavailable" in msg for msg in logs)


def test_set_children_click_through_logs_failure(monkeypatch):
    logs: list[str] = []

    def _debug(msg: str, *args) -> None:
        logs.append(msg % args if args else msg)

    child = type(
        "StubChild",
        (),
        {
            "setAttribute": lambda self, *_args, **_kwargs: (_ for _ in ()).throw(AttributeError("no attr")),
        },
    )()
    window = type(
        "StubWindow",
        (),
        {
            "message_label": child,
            "_set_children_click_through": OverlayWindow._set_children_click_through,
        },
    )()
    monkeypatch.setattr("overlay_client.overlay_client._CLIENT_LOGGER.debug", _debug)
    monkeypatch.setattr("overlay_client.overlay_client._CLIENT_LOGGER.warning", _debug)

    window._set_children_click_through(True)  # type: ignore[attr-defined]

    assert any("Failed to set click-through on child" in msg for msg in logs)


def test_interaction_controller_logs_transient_parent_failure(monkeypatch):
    logs: list[str] = []

    def _log(msg: str, *args) -> None:
        if "%s" in msg and args:
            logs.append(msg % args[: msg.count("%s")])
        else:
            logs.append(msg)

    controller = InteractionController(
        is_wayland_fn=lambda: True,
        log_fn=_log,
        prepare_window_fn=lambda _window: None,
        apply_click_through_fn=lambda _transparent: None,
        set_transient_parent_fn=lambda _parent: (_ for _ in ()).throw(AttributeError("fail")),
        clear_transient_parent_ids_fn=lambda: None,
        window_handle_fn=lambda: object(),
        set_widget_attribute_fn=lambda *_args, **_kwargs: None,
        set_window_flag_fn=lambda *_args, **_kwargs: None,
        ensure_visible_fn=lambda: None,
        raise_fn=lambda: None,
        set_children_attr_fn=lambda _transparent: None,
        transparent_input_supported=False,
        set_window_transparent_input_fn=lambda _transparent: None,
    )

    controller.handle_force_render_enter()

    assert any("Failed to clear transient parent on force-render" in msg for msg in logs)


def test_describe_screen_logs_on_failure(monkeypatch):
    logs: list[str] = []

    def _debug(msg: str, *args) -> None:
        logs.append(msg % args if args else msg)

    screen = type(
        "StubScreen",
        (),
        {
            "geometry": lambda self: (_ for _ in ()).throw(RuntimeError("boom")),
            "name": lambda self: "stub-screen",
        },
    )()
    window = type(
        "StubWindow",
        (),
        {"_describe_screen": OverlayWindow._describe_screen},
    )()
    monkeypatch.setattr("overlay_client.overlay_client._CLIENT_LOGGER.debug", _debug)
    monkeypatch.setattr("overlay_client.overlay_client._CLIENT_LOGGER.warning", _debug)

    description = window._describe_screen(screen)  # type: ignore[attr-defined]

    assert description == str(screen)
    assert any("Failed to describe screen" in msg for msg in logs)


def test_update_auto_legacy_scale_logs_ratio_failure(monkeypatch):
    logs: list[str] = []

    def _debug(msg: str, *args) -> None:
        logs.append(msg % args if args else msg)

    def _warning(msg: str, *args) -> None:
        logs.append(msg % args if args else msg)

    class _StubTransform:
        def __init__(self) -> None:
            self.scale = 1.0
            self.scaled_size = (1.0, 1.0)
            self.mode = type("Mode", (), {"value": "fit"})()
            self.overflow_x = False
            self.overflow_y = False

    class _StubMapper:
        def __init__(self) -> None:
            self.transform = _StubTransform()
            self.offset_x = 0.0
            self.offset_y = 0.0

    window = type(
        "StubWindow",
        (),
        {
            "_update_auto_legacy_scale": OverlayWindow._update_auto_legacy_scale,
            "_compute_legacy_mapper": lambda self: _StubMapper(),
            "devicePixelRatioF": lambda self: (_ for _ in ()).throw(RuntimeError("no dprf")),
            "_update_message_font": lambda self: None,
            "_current_physical_size": lambda self: (100.0, 50.0),
            "format_scale_debug": lambda self: "scale-debug",
            "_last_logged_scale": None,
            "_debug_message_point_size": 0.0,
        },
    )()
    monkeypatch.setattr("overlay_client.overlay_client.legacy_scale_components", lambda _mapper, _state: (1.0, 1.0))
    monkeypatch.setattr("overlay_client.overlay_client._CLIENT_LOGGER.debug", _debug)
    monkeypatch.setattr("overlay_client.overlay_client._CLIENT_LOGGER.warning", _warning)

    window._update_auto_legacy_scale(100, 50)  # type: ignore[attr-defined]

    assert any("devicePixelRatioF unavailable" in msg for msg in logs)
