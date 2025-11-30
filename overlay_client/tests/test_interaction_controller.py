from __future__ import annotations

import types

from PyQt6.QtCore import Qt

from overlay_client.interaction_controller import InteractionController


def _build_controller(monkeypatch, *, is_wayland: bool = False, transparent_input_supported: bool = True):
    calls = types.SimpleNamespace(
        widget_attrs=[],
        children_attrs=[],
        window_flags=[],
        prepared=[],
        applied=[],
        transient_parents=[],
        cleared=0,
        ensured=0,
        raised=0,
        set_transparent=[],
        logs=[],
    )

    window_obj = object()
    controller = InteractionController(
        is_wayland_fn=lambda: is_wayland,
        log_fn=lambda msg, *args: calls.logs.append((msg, args)),
        prepare_window_fn=lambda window: calls.prepared.append(window),
        apply_click_through_fn=lambda flag: calls.applied.append(flag),
        set_transient_parent_fn=lambda parent: calls.transient_parents.append(parent),
        clear_transient_parent_ids_fn=lambda: setattr(calls, "cleared", calls.cleared + 1),
        window_handle_fn=lambda: window_obj,
        set_widget_attribute_fn=lambda attr, enabled: calls.widget_attrs.append((attr, enabled)),
        set_window_flag_fn=lambda flag, enabled: calls.window_flags.append((flag, enabled)),
        ensure_visible_fn=lambda: setattr(calls, "ensured", calls.ensured + 1),
        raise_fn=lambda: setattr(calls, "raised", calls.raised + 1),
        set_children_attr_fn=lambda enabled: calls.children_attrs.append(enabled),
        transparent_input_supported=transparent_input_supported,
        set_window_transparent_input_fn=lambda enabled: calls.set_transparent.append(enabled),
    )
    return controller, calls, window_obj


def test_click_through_applies_flags_and_is_idempotent(monkeypatch):
    controller, calls, window_obj = _build_controller(monkeypatch)

    controller.set_click_through(True)
    assert calls.widget_attrs == [(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)]
    assert calls.children_attrs == [True]
    assert (Qt.WindowType.WindowStaysOnTopHint, True) in calls.window_flags
    assert (Qt.WindowType.FramelessWindowHint, True) in calls.window_flags
    assert (Qt.WindowType.Tool, True) in calls.window_flags
    assert calls.prepared == [window_obj]
    assert calls.applied == [True]
    assert calls.set_transparent == [True]
    assert calls.ensured == 1
    assert calls.raised == 1
    assert calls.logs  # logged at least once

    # Idempotent when state unchanged and force not set
    controller.set_click_through(True)
    assert len(calls.applied) == 1
    assert calls.ensured == 1

    # Force reapply should call again
    controller.set_click_through(True, force=True, reason="force_reapply")
    assert len(calls.applied) == 2
    assert calls.logs[-1][1][1] == "force_reapply"

    # Toggle off
    controller.set_click_through(False)
    assert calls.applied[-1] is False
    assert calls.children_attrs[-1] is False


def test_reapply_current(monkeypatch):
    controller, calls, _ = _build_controller(monkeypatch)
    controller.set_click_through(True)
    calls.applied.clear()
    controller.reapply_current(reason="reapply")
    assert calls.applied == [True]
    assert calls.logs[-1][1][1] == "reapply"


def test_restore_drag_interactivity_respects_flags(monkeypatch):
    controller, calls, _ = _build_controller(monkeypatch)

    # Drag disabled -> no-op
    controller.restore_drag_interactivity(False, False, lambda: "debug")
    assert not calls.applied

    # Drag active -> no-op
    controller.restore_drag_interactivity(True, True, lambda: "debug")
    assert not calls.applied

    # Drag enabled and inactive -> click-through disabled
    controller.restore_drag_interactivity(True, False, lambda: "debug")
    assert calls.applied[-1] is False


def test_handle_force_render_reapplies_current(monkeypatch):
    controller, calls, _ = _build_controller(monkeypatch, is_wayland=True)
    controller.set_click_through(False)
    calls.applied.clear()
    monkeypatch.setattr("overlay_client.interaction_controller.sys.platform", "linux")

    controller.handle_force_render_enter()

    # First call applies transparent input (best-effort), then re-applies current False state.
    assert calls.applied[0] is True
    assert calls.applied[-1] is False
    assert calls.cleared == 1
    assert calls.transient_parents[-1] is None
