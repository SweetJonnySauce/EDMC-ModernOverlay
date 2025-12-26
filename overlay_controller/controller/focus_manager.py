from __future__ import annotations

from overlay_controller.widgets import AbsoluteXYWidget, BackgroundWidget


class FocusManager:
    """Manages sidebar focus map and binding registrations."""

    def __init__(self, app, binding_manager) -> None:
        self.app = app
        self.binding_manager = binding_manager
        self._snapshots = {}

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
        background_widget = getattr(self.app, "background_widget", None)
        if isinstance(background_widget, BackgroundWidget):
            targets = background_widget.get_binding_targets()
            self.binding_manager.register_action(
                "background_focus_next",
                background_widget.focus_next_field,
                widgets=targets,
            )
            self.binding_manager.register_action(
                "background_focus_prev",
                background_widget.focus_previous_field,
                widgets=targets,
            )

    def sidebar_click(self, idx: int) -> None:
        self.app._handle_sidebar_click(idx)  # type: ignore[attr-defined]

    # Focus/navigation helpers ------------------------------------------
    def set_sidebar_focus(self, index: int) -> None:
        sidebar_cells = getattr(self.app, "sidebar_cells", [])
        if not (0 <= index < len(sidebar_cells)):
            return
        self.app._sidebar_focus_index = index
        self.update_sidebar_highlight()

    def focus_sidebar_up(self, event=None):
        app = self.app
        if not app.widget_select_mode:
            if app._handle_active_widget_key("Up", event):
                return "break"
            return
        sidebar_cells = getattr(app, "sidebar_cells", None)
        if not sidebar_cells:
            return
        new_index = max(0, app._sidebar_focus_index - 1)
        self.set_sidebar_focus(new_index)
        self.refresh_widget_focus()

    def focus_sidebar_down(self, event=None):
        app = self.app
        if not app.widget_select_mode:
            if app._handle_active_widget_key("Down", event):
                return "break"
            return
        sidebar_cells = getattr(app, "sidebar_cells", None)
        if not sidebar_cells:
            return
        new_index = min(len(sidebar_cells) - 1, app._sidebar_focus_index + 1)
        self.set_sidebar_focus(new_index)
        self.refresh_widget_focus()

    def handle_sidebar_click(self, index: int) -> None:
        app = self.app
        sidebar_cells = getattr(app, "sidebar_cells", None)
        if not sidebar_cells or not (0 <= index < len(sidebar_cells)):
            return
        block_focus = (not getattr(app, "_group_controls_enabled", True)) and index > 0
        if block_focus:
            if not app.widget_select_mode:
                app.exit_focus_mode()
            app.widget_focus_area = "sidebar"
            self.set_sidebar_focus(index)
            self.refresh_widget_focus()
            try:
                app.focus_set()
            except Exception:
                pass
            return
        if not app.widget_select_mode and index != getattr(app, "_sidebar_focus_index", -1):
            app._on_focus_mode_exited()
        app.widget_focus_area = "sidebar"
        self.set_sidebar_focus(index)
        app.widget_select_mode = False
        app._on_focus_mode_entered()
        self.refresh_widget_focus()
        if app.widget_select_mode:
            try:
                app.focus_set()
            except Exception:
                pass
        else:
            target = app._get_active_focus_widget()
            focus_target = getattr(target, "focus_set", None)
            if callable(focus_target):
                try:
                    focus_target()
                except Exception:
                    pass

    def handle_placement_click(self, event=None):
        app = self.app
        if not app._placement_open:
            return
        if not app.widget_select_mode and app.widget_focus_area == "sidebar":
            app._on_focus_mode_exited()
        app.widget_focus_area = "placement"
        app.widget_select_mode = False
        self.refresh_widget_focus()
        if app.widget_select_mode:
            try:
                app.focus_set()
            except Exception:
                pass

    def move_widget_focus_left(self, event=None):
        app = self.app
        if not app.widget_select_mode:
            if app._handle_active_widget_key("Left", event):
                return "break"
            return
        if app._placement_open:
            app._placement_open = False
            app._apply_placement_state()
            app.widget_focus_area = "sidebar"
            self.refresh_widget_focus()

    def move_widget_focus_right(self, event=None):
        app = self.app
        if not app.widget_select_mode:
            if app._handle_active_widget_key("Right", event):
                return "break"
            return
        if not app._placement_open:
            app._placement_open = True
            app._apply_placement_state()
        app.widget_focus_area = "sidebar"
        self.refresh_widget_focus()

    def update_sidebar_highlight(self) -> None:
        app = self.app
        sidebar_cells = getattr(app, "sidebar_cells", None) or []
        if not sidebar_cells or app.widget_focus_area != "sidebar":
            app.sidebar_overlay.hide()
            return
        frame = sidebar_cells[app._sidebar_focus_index]
        color = "#888888" if app.widget_select_mode else "#000000"
        app.sidebar_overlay.show(frame, color)

    def update_placement_focus_highlight(self) -> None:
        app = self.app
        is_active = app.widget_focus_area == "placement" and app._placement_open
        if not is_active:
            app.placement_overlay.hide()
            return
        color = "#888888" if app.widget_select_mode else "#000000"
        app.placement_overlay.show(app.placement_frame, color)

    def update_contextual_tip(self) -> None:
        app = self.app
        helper = getattr(app, "tip_helper", None)
        if helper is None:
            return
        primary: str | None = None
        secondary: str | None = None
        controls_enabled = getattr(app, "_group_controls_enabled", True)
        in_sidebar = app.widget_focus_area == "sidebar" and bool(getattr(app, "sidebar_cells", None))

        if not in_sidebar:
            primary = "Use arrow keys to move between controls."
            secondary = "Press Enter to focus a control; Esc exits focus mode."
            helper.set_context(primary, secondary)
            return

        sidebar_cells = getattr(app, "sidebar_cells", []) or []
        idx = max(0, min(getattr(app, "_sidebar_focus_index", 0), len(sidebar_cells) - 1))
        if not controls_enabled and idx > 0:
            primary = "Waiting for overlay cache to populate this group."
            secondary = "Controls unlock once the latest payload arrives."
            helper.set_context(primary, secondary)
            return

        select_mode = app.widget_select_mode
        focus_hint = "Press Space to edit; arrows move the selection." if select_mode else "Press Space to exit."

        if idx == 0:
            primary = "Pick an ID prefix group to adjust."
            secondary = "Select the overlay group you want to adjust. The Controller needs to see an overlay at least once to manage it. Launch the game with the overlay running and do some activities that would trigger in-game overlays."
            if select_mode:
                secondary = "Select the overlay group you want to adjust; arrows move the selection."
                focus_hint = "Press Space to edit."
        elif idx == 1:
            primary = "Use Alt-click / Alt-arrow to move the overlay group to the screen edge."
        elif idx == 2:
            primary = "Set exact coordinates for this group."
            secondary = "Enter px or % values; Tab switches fields."
        elif idx == 3:
            primary = "Choose the anchor point used for transforms."
            secondary = "Use arrows or click dots to move the highlight."
        elif idx == 4:
            primary = "Set payload justification."
            secondary = "Left/Center/Right controls text alignment."
        elif idx == 5:
            primary = "Set background and border colors."
            secondary = "Enter #RRGGBB/#AARRGGBB or a named color; border width expands the fill."

        if focus_hint:
            secondary = f"{secondary} {focus_hint}" if secondary else focus_hint

        helper.set_context(primary, secondary)

    def refresh_widget_focus(self) -> None:
        app = self.app
        if hasattr(app, "sidebar_cells"):
            self.update_sidebar_highlight()
        self.update_placement_focus_highlight()
        try:
            app.indicator_wrapper.lift()
        except Exception:
            pass
        self.update_contextual_tip()
