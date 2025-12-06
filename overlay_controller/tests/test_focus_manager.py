from __future__ import annotations

import types


def test_focus_manager_registers_absolute_bindings():
    import overlay_controller.overlay_controller as oc
    from overlay_controller.widgets.absolute import AbsoluteXYWidget

    class DummyBindingManager:
        def __init__(self) -> None:
            self.actions = {}

        def register_action(self, name, func, widgets=None):
            self.actions[name] = {"func": func, "widgets": widgets or []}

    class DummyAbsolute(AbsoluteXYWidget):  # type: ignore[misc]
        def __init__(self) -> None:
            self._targets = [object(), object()]

        def get_binding_targets(self):
            return self._targets

        def focus_next_field(self):
            return "next"

        def focus_previous_field(self):
            return "prev"

    app = types.SimpleNamespace(absolute_widget=DummyAbsolute())
    bindings = DummyBindingManager()
    fm = oc.FocusManager(app, bindings)

    fm.register_widget_bindings()

    assert "absolute_focus_next" in bindings.actions
    assert bindings.actions["absolute_focus_next"]["widgets"] == app.absolute_widget.get_binding_targets()
    assert bindings.actions["absolute_focus_prev"]["func"]() == "prev"
