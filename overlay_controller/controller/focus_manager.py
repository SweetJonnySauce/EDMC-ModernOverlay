from __future__ import annotations

from overlay_controller.widgets import AbsoluteXYWidget


class FocusManager:
    """Manages sidebar focus map and binding registrations."""

    def __init__(self, app, binding_manager) -> None:
        self.app = app
        self.binding_manager = binding_manager

    def register_widget_bindings(self) -> None:
        absolute_widget = getattr(self.app, "absolute_widget", None)
        if isinstance(absolute_widget, AbsoluteXYWidget):
            targets = absolute_widget.get_binding_targets()
            self.binding_manager.register_action(
                "absolute_focus_next",
                absolute_widget.focus_next_field,
                widgets=targets,
            )
            self.binding_manager.register_action(
                "absolute_focus_prev",
                absolute_widget.focus_previous_field,
                widgets=targets,
            )

    def sidebar_click(self, idx: int) -> None:
        self.app._handle_sidebar_click(idx)  # type: ignore[attr-defined]
