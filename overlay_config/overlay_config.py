"""Tkinter scaffolding for the Overlay Config tool."""

from __future__ import annotations

import json
import tkinter as tk
import platform
import re
import subprocess
from pathlib import Path
from tkinter import ttk

from input_bindings import BindingConfig, BindingManager
from selection_overlay import SelectionOverlay


class IdPrefixGroupWidget(tk.Frame):
    """Composite control with a dropdown selector (placeholder for future inputs)."""

    def __init__(self, parent: tk.Widget, options: list[str] | None = None) -> None:
        super().__init__(parent, bd=0, highlightthickness=0, bg=parent.cget("background"))
        self._choices = options or []
        self._selection = tk.StringVar()

        self.dropdown = ttk.Combobox(
            self,
            values=self._choices,
            state="readonly",
            textvariable=self._selection,
            width=24,
        )
        if self._choices:
            self.dropdown.current(0)

        self.columnconfigure(0, weight=0)
        self.rowconfigure(0, weight=0)

        self.dropdown.grid(row=0, column=0, padx=0, pady=0, sticky="n")

    def on_focus_enter(self) -> None:
        """Called when the host enters focus mode for this widget."""

        try:
            self.dropdown.focus_set()
        except Exception:
            pass

    def on_focus_exit(self) -> None:
        """Called when the host exits focus mode for this widget."""

        # No-op for now; placeholder for future controls.
        return

    def handle_key(self, keysym: str) -> bool:
        """Process keys while this widget has focus mode active."""

        key = keysym.lower()
        if key in {"space", "down"}:
            try:
                self.dropdown.event_generate("<Down>")
            except Exception:
                pass
            return True
        if key == "return":
            try:
                self.dropdown.event_generate("<Return>")
            except Exception:
                pass
            return True
        return False


class OverlayConfigApp(tk.Tk):
    """Basic UI skeleton that mirrors the design mockups."""

    def __init__(self) -> None:
        super().__init__()
        self.withdraw()
        self.title("Overlay Config")
        self.geometry("960x600")
        self.minsize(640, 420)
        self._pending_close_job: str | None = None
        self._focus_close_delay_ms = 200
        self._moving_guard_job: str | None = None
        self._moving_guard_active = False
        self._move_guard_timeout_ms = 500
        self._pending_focus_out = False

        self._placement_open = False
        self._open_width = 960
        self.sidebar_width = 260
        self.sidebar_pad = 12
        self.sidebar_pad_closed = 0
        self.container_pad_left = 12
        self.container_pad_right_open = 12
        self.container_pad_right_closed = 2
        self.container_pad_vertical = 12
        self.placement_min_width = 450
        self.closed_min_width = 0
        self.indicator_width = 12
        self.indicator_height = 72
        self.indicator_hit_padding = max(4, self.indicator_height // 6)
        self.indicator_hit_width = self.indicator_width + (self.indicator_hit_padding * 2)
        self.indicator_gap = 0

        self._current_right_pad = self.container_pad_right_open
        self._current_sidebar_pad = self.sidebar_pad
        self.indicator_count = 3
        self.widget_focus_area = "sidebar"
        self.widget_select_mode = True
        self.overlay_padding = 8
        self.overlay_border_width = 3
        self._focus_widgets: dict[tuple[str, int], object] = {}

        self._build_layout()
        self._binding_config = BindingConfig.load()
        self._binding_manager = BindingManager(self, self._binding_config)
        self._binding_manager.register_action(
            "indicator_toggle",
            self.toggle_placement_window,
            widgets=[self.indicator_wrapper, self.indicator_canvas],
        )
        self._binding_manager.register_action(
            "sidebar_focus_up",
            self.focus_sidebar_up,
        )
        self._binding_manager.register_action(
            "sidebar_focus_down",
            self.focus_sidebar_down,
        )
        self._binding_manager.register_action(
            "widget_move_left",
            self.move_widget_focus_left,
        )
        self._binding_manager.register_action(
            "widget_move_right",
            self.move_widget_focus_right,
        )
        self._binding_manager.register_action("enter_focus", self.enter_focus_mode)
        self._binding_manager.register_action("exit_focus", self.exit_focus_mode)
        self._binding_manager.register_action("close_app", self.close_application)
        self._binding_manager.activate()
        self.bind("<Configure>", self._handle_configure)
        self.bind("<FocusIn>", self._handle_focus_in)
        self.bind("<Return>", self._handle_return_key, add="+")
        self.after(0, self._center_and_show)

    def _build_layout(self) -> None:
        """Create the split view with placement and sidebar sections."""

        self.container = tk.Frame(self)
        self.container.grid(
            row=0,
            column=0,
            sticky="nsew",
            padx=(self.container_pad_left, self.container_pad_right_open),
            pady=(self.container_pad_vertical, self.container_pad_vertical),
        )

        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self.container.grid_rowconfigure(0, weight=1)
        self.container.grid_columnconfigure(0, weight=0, minsize=self.sidebar_width)
        self.container.grid_columnconfigure(1, weight=1)

        # Placement window placeholder (open state)
        self.placement_frame = tk.Frame(
            self.container,
            bd=0,
            relief="flat",
            background="#f5f5f5",
        )
        placement_label = tk.Label(
            self.placement_frame,
            text="placement window (open)",
            anchor="nw",
            bg="#f5f5f5",
            padx=8,
            pady=6,
        )
        placement_label.pack(fill="both", expand=True)
        self.placement_frame.bind("<Button-1>", self._handle_placement_click, add="+")
        placement_label.bind("<Button-1>", self._handle_placement_click, add="+")

        # Sidebar with individual selector sections
        self.sidebar = tk.Frame(
            self.container,
            width=self.sidebar_width,
            bd=0,
            highlightthickness=0,
        )
        self.sidebar.grid(row=0, column=0, sticky="nsw", padx=(0, self.sidebar_pad))
        self._build_sidebar_sections()
        self.sidebar.grid_propagate(False)

        indicator_bg = self.container.cget("background")
        self.indicator_wrapper = tk.Frame(
            self.container,
            width=self.indicator_hit_width,
            height=self.indicator_height,
            bd=0,
            highlightthickness=0,
            bg=indicator_bg,
        )
        self.indicator_wrapper.pack_propagate(False)
        self.indicator_canvas = tk.Canvas(
            self.indicator_wrapper,
            width=self.indicator_width,
            height=self.indicator_height,
            highlightthickness=0,
            bg=indicator_bg,
        )
        self.indicator_canvas.pack(expand=True)

        self.sidebar_overlay = SelectionOverlay(
            parent=self.sidebar,
            padding=self.overlay_padding,
            border_width=self.overlay_border_width,
        )
        self.placement_overlay = SelectionOverlay(
            parent=self.container,
            padding=self.overlay_padding,
            border_width=self.overlay_border_width,
            corner_radius=0,
        )
        self._apply_placement_state()
        self._refresh_widget_focus()
        self._current_direction = "left"

    def _build_sidebar_sections(self) -> None:
        """Create labeled boxes that will hold future controls."""

        sections = [
            ("idprefix group selector", 3),
            ("offset selector", 2),
            ("absolute x/y", 1),
            ("anchor selector", 3),
            ("payload justification", 1),
            ("zoom selector (future implementation)", 1),
        ]

        self.sidebar_cells: list[tk.Frame] = []
        self._sidebar_focus_index = 0
        self.widget_select_mode = True

        for index, (label_text, weight) in enumerate(sections):
            frame = tk.Frame(
                self.sidebar,
                bd=0,
                relief="flat",
                width=0 if index == 0 else 220,
                height=0 if index == 0 else 80,
            )
            frame.grid(
                row=index,
                column=0,
                sticky="nsew",
                pady=(
                    self.overlay_padding if index == 0 else 1,
                    self.overlay_padding if index == len(sections) - 1 else 1,
                ),
                padx=(self.overlay_padding, self.overlay_padding),
            )
            frame.grid_propagate(True)
            if index == 0:
                self.idprefix_widget = IdPrefixGroupWidget(frame, options=self._load_idprefix_options())
                self.idprefix_widget.pack(anchor="n", padx=0, pady=0)
                self._focus_widgets[("sidebar", index)] = self.idprefix_widget
            else:
                text_label = tk.Label(frame, text=label_text, anchor="center", padx=6, pady=6)
                text_label.pack(fill="both", expand=True)
            frame.bind(
                "<Button-1>", lambda event, idx=index: self._handle_sidebar_click(idx), add="+"
            )
            for child in frame.winfo_children():
                child.bind("<Button-1>", lambda event, idx=index: self._handle_sidebar_click(idx), add="+")
            self.sidebar.grid_rowconfigure(index, weight=weight)
            self.sidebar_cells.append(frame)

        self.sidebar.grid_columnconfigure(0, weight=1)

    def toggle_placement_window(self) -> None:
        """Switch between the open and closed placement window layouts."""

        self._placement_open = not self._placement_open
        if not self._placement_open and self.widget_focus_area == "placement":
            self.widget_focus_area = "sidebar"
        self._apply_placement_state()
        self._refresh_widget_focus()

    def focus_sidebar_up(self) -> None:
        """Move sidebar focus upward."""

        if self._handle_active_widget_key("Up"):
            return "break"
        if not self.widget_select_mode:
            return
        if not getattr(self, "sidebar_cells", None):
            return
        new_index = max(0, self._sidebar_focus_index - 1)
        self._set_sidebar_focus(new_index)
        self._refresh_widget_focus()

    def focus_sidebar_down(self) -> None:
        """Move sidebar focus downward."""

        if self._handle_active_widget_key("Down"):
            return "break"
        if not self.widget_select_mode:
            return
        if not getattr(self, "sidebar_cells", None):
            return
        new_index = min(len(self.sidebar_cells) - 1, self._sidebar_focus_index + 1)
        self._set_sidebar_focus(new_index)
        self._refresh_widget_focus()

    def _set_sidebar_focus(self, index: int) -> None:
        if not (0 <= index < len(self.sidebar_cells)):
            return
        self._sidebar_focus_index = index
        self._update_sidebar_highlight()

    def _handle_sidebar_click(self, index: int, _event: tk.Event[tk.Misc] | None = None) -> None:  # type: ignore[name-defined]
        """Move selection to a sidebar cell and enter focus mode."""

        if not getattr(self, "sidebar_cells", None):
            return
        if not (0 <= index < len(self.sidebar_cells)):
            return
        self.widget_focus_area = "sidebar"
        self._set_sidebar_focus(index)
        self.widget_select_mode = False
        self._on_focus_mode_entered()
        self._refresh_widget_focus()
        try:
            self.focus_set()
        except Exception:
            pass

    def _handle_placement_click(self, _event: tk.Event[tk.Misc] | None = None) -> None:  # type: ignore[name-defined]
        """Move selection to the placement area and enter focus mode."""

        if not self._placement_open:
            return
        self.widget_focus_area = "placement"
        self.widget_select_mode = False
        self._refresh_widget_focus()
        try:
            self.focus_set()
        except Exception:
            pass

    def move_widget_focus_left(self) -> None:
        """Handle left arrow behavior in widget select mode."""

        if self._handle_active_widget_key("Left"):
            return "break"
        if not self.widget_select_mode:
            return
        if self.widget_focus_area == "placement":
            self.widget_focus_area = "sidebar"
            self._refresh_widget_focus()
        elif self.widget_focus_area == "sidebar" and self._placement_open:
            self._placement_open = False
            self._apply_placement_state()
            self.widget_focus_area = "sidebar"
            self._refresh_widget_focus()

    def move_widget_focus_right(self) -> None:
        """Handle right arrow behavior in widget select mode."""

        if self._handle_active_widget_key("Right"):
            return "break"
        if not self.widget_select_mode:
            return
        if self.widget_focus_area == "sidebar":
            if not self._placement_open:
                self._placement_open = True
                self._apply_placement_state()
            self.widget_focus_area = "placement"
            self._refresh_widget_focus()
        elif self.widget_focus_area == "placement":
            self.widget_focus_area = "placement"
            self._refresh_widget_focus()

    def _update_sidebar_highlight(self) -> None:
        if not self.sidebar_cells:
            self.sidebar_overlay.hide()
            return
        if self.widget_focus_area != "sidebar":
            self.sidebar_overlay.hide()
            return

        frame = self.sidebar_cells[self._sidebar_focus_index]
        color = "#888888" if self.widget_select_mode else "#000000"
        self.sidebar_overlay.show(frame, color)

    def _update_placement_focus_highlight(self) -> None:
        is_active = self.widget_focus_area == "placement" and self._placement_open
        if not is_active:
            self.placement_overlay.hide()
            return

        color = "#888888" if self.widget_select_mode else "#000000"
        self.placement_overlay.show(self.placement_frame, color)

    def _refresh_widget_focus(self) -> None:
        if hasattr(self, "sidebar_cells"):
            self._update_sidebar_highlight()
        self._update_placement_focus_highlight()

    def close_application(self, event: tk.Event[tk.Misc] | None = None) -> None:  # type: ignore[name-defined]
        """Close the Overlay Config window."""

        if event is not None:
            keysym = getattr(event, "keysym", "") or ""
            if keysym.lower() == "escape" and not self.widget_select_mode:
                self.exit_focus_mode()
                return
            if self._handle_active_widget_key(keysym):
                return

        if self._is_focus_out_event(event):
            # Ignore focus changes that stay within this window or its popdowns.
            if self._is_internal_focus_shift(event) or self._is_focus_within_app():
                return
            if self._moving_guard_active:
                self._pending_focus_out = True
                return
            self._schedule_focus_out_close()
            return

        self._finalize_close()

    def _finalize_close(self) -> None:
        """Close immediately, respecting focus mode behavior."""

        self._cancel_pending_close()
        self._pending_focus_out = False
        if not getattr(self, "widget_select_mode", True):
            self.exit_focus_mode()
            return
        self.destroy()

    def _handle_focus_in(self, _event: tk.Event[tk.Misc]) -> None:  # type: ignore[name-defined]
        """Cancel any delayed close when the window regains focus."""

        self._cancel_pending_close()
        self._pending_focus_out = False

    def _is_focus_out_event(self, event: tk.Event[tk.Misc] | None) -> bool:  # type: ignore[name-defined]
        """Return True if the event represents a real focus loss worth acting on."""

        if event is None:
            return False
        event_type = getattr(event, "type", None)
        event_type_name = getattr(event_type, "name", None) or str(event_type)
        is_focus_out = (
            event_type == tk.EventType.FocusOut
            or event_type_name.endswith("FocusOut")
            or event_type == 9
        )
        if not is_focus_out:
            return False

        mode = getattr(event, "mode", None)
        mode_name = getattr(mode, "name", None) or str(mode)
        mode_label = mode_name.split(".")[-1]
        grab_related = mode in (1, 2, 3) or mode_label in {
            "NotifyGrab",
            "NotifyUngrab",
            "NotifyWhileGrabbed",
        }
        if grab_related:
            return False

        return True

    def _cancel_pending_close(self) -> None:
        if self._pending_close_job is not None:
            try:
                self.after_cancel(self._pending_close_job)
            except Exception:
                pass
            self._pending_close_job = None

    def _schedule_focus_out_close(self) -> None:
        self._cancel_pending_close()
        self._pending_close_job = self.after(self._focus_close_delay_ms, self._close_if_unfocused)

    def _close_if_unfocused(self) -> None:
        self._pending_close_job = None
        self._pending_focus_out = False
        if self._is_focus_within_app():
            return
        self._finalize_close()

    def _is_app_focused(self) -> bool:
        try:
            focus_widget = self.focus_get()
        except Exception:
            return False
        return bool(focus_widget and focus_widget.winfo_toplevel() == self)

    def _safe_focus_get(self) -> tk.Misc | None:  # type: ignore[name-defined]
        try:
            return self.focus_get()
        except Exception:
            return None

    def _is_focus_within_app(self) -> bool:
        """Return True if focus is within this window or a known popdown."""

        focus_widget = self._safe_focus_get()
        if focus_widget is None:
            return False
        try:
            if focus_widget.winfo_toplevel() == self:
                return True
        except Exception:
            return False
        try:
            klass = focus_widget.winfo_class().lower()
            name = focus_widget.winfo_name().lower()
        except Exception:
            return False
        return "combobox" in klass or "popdown" in name

    def _is_internal_focus_shift(self, event: tk.Event[tk.Misc] | None) -> bool:  # type: ignore[name-defined]
        """Return True if focus is shifting within our widgets (e.g., combobox popdown)."""

        widgets: list[tk.Misc] = []  # type: ignore[name-defined]
        event_widget = getattr(event, "widget", None)
        if event_widget is not None:
            widgets.append(event_widget)
        focus_widget = self._safe_focus_get()
        if focus_widget is not None:
            widgets.append(focus_widget)

        for widget in widgets:
            try:
                klass = widget.winfo_class().lower()
                name = widget.winfo_name().lower()
            except Exception:
                continue
            if "combobox" in klass or "popdown" in name:
                return True

        return False

    def _get_active_focus_widget(self) -> object | None:
        if self.widget_focus_area == "sidebar":
            key = ("sidebar", getattr(self, "_sidebar_focus_index", -1))
        else:
            return None
        return self._focus_widgets.get(key)

    def _handle_active_widget_key(self, keysym: str) -> bool:
        widget = self._get_active_focus_widget()
        if widget is None:
            return False

        if self.widget_select_mode:
            self.widget_select_mode = False
            self._on_focus_mode_entered()
            self._refresh_widget_focus()

        if keysym.lower() == "escape":
            self.exit_focus_mode()
            return True

        handler = getattr(widget, "handle_key", None)
        try:
            handled = bool(handler(keysym)) if handler is not None else False
        except Exception:
            handled = True
        # Always consume keys in focus mode to keep focus locked, unless Escape handled above.
        return handled or True

    def _on_focus_mode_entered(self) -> None:
        widget = self._get_active_focus_widget()
        if widget is None:
            return
        handler = getattr(widget, "on_focus_enter", None)
        if handler:
            try:
                handler()
            except Exception:
                pass

    def _on_focus_mode_exited(self) -> None:
        widget = self._get_active_focus_widget()
        if widget is None:
            return
        handler = getattr(widget, "on_focus_exit", None)
        if handler:
            try:
                handler()
            except Exception:
                pass

    def _load_idprefix_options(self) -> list[str]:
        root = Path(__file__).resolve().parents[1]
        path = root / "overlay_groupings.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        options: list[str] = []
        if isinstance(payload, dict):
            for plugin_name, entry in sorted(payload.items(), key=lambda item: item[0].casefold()):
                groups = entry.get("idPrefixGroups") if isinstance(entry, dict) else None
                if not isinstance(groups, dict):
                    continue
                for label in sorted(groups.keys(), key=str.casefold):
                    options.append(f"{plugin_name} — {label}")
        return options

    def _on_configure_activity(self) -> None:
        """Track recent move/resize to avoid closing during window drag."""

        self._moving_guard_active = True
        if self._moving_guard_job is not None:
            try:
                self.after_cancel(self._moving_guard_job)
            except Exception:
                pass
        self._moving_guard_job = self.after(self._move_guard_timeout_ms, self._handle_move_guard_expired)
        self._cancel_pending_close()

    def _handle_move_guard_expired(self) -> None:
        self._moving_guard_job = None
        self._moving_guard_active = False
        if self._pending_focus_out and not self._is_app_focused():
            self._schedule_focus_out_close()
        self._pending_focus_out = False

    def enter_focus_mode(self, _event: tk.Event[tk.Misc] | None = None) -> str | None:  # type: ignore[name-defined]
        """Lock the current selection so arrows no longer move it."""

        if not self.widget_select_mode:
            return
        self.widget_select_mode = False
        self._on_focus_mode_entered()
        self._refresh_widget_focus()
        return "break"

    def exit_focus_mode(self) -> None:
        """Return to selection mode so the highlight can move again."""

        if self.widget_select_mode:
            return
        self.widget_select_mode = True
        self._on_focus_mode_exited()
        self._refresh_widget_focus()

    def _apply_placement_state(self) -> None:
        """Show the correct placement frame for the current state."""

        self.update_idletasks()
        current_height = max(self.winfo_height(), 420)
        open_outer_padding = self.container_pad_left + self.container_pad_right_open
        closed_outer_padding = self.container_pad_left + self.container_pad_right_closed
        sidebar_total_open = self.sidebar_width + self.sidebar_pad
        sidebar_total_closed = self.sidebar_width
        open_min_width = open_outer_padding + sidebar_total_open + self.placement_min_width
        closed_min_width = closed_outer_padding + sidebar_total_closed + self.closed_min_width

        if self._placement_open:
            self.container.grid_configure(
                padx=(self.container_pad_left, self.container_pad_right_open)
            )
            self._current_right_pad = self.container_pad_right_open
            self.placement_frame.grid(
                row=0,
                column=1,
                sticky="nsew",
                padx=(0, self.overlay_padding),
                pady=(self.overlay_padding, self.overlay_padding),
            )
            self.container.grid_columnconfigure(1, weight=1, minsize=self.placement_min_width)
            self.update_idletasks()
            target_width = max(self._open_width, self.winfo_reqwidth(), open_min_width)
            self.minsize(open_min_width, 420)
            self.geometry(f"{int(target_width)}x{int(current_height)}")
            self._current_direction = "left"
            self._show_indicator(direction="left")
        else:
            self.container.grid_configure(
                padx=(self.container_pad_left, self.container_pad_right_closed)
            )
            self._current_right_pad = self.container_pad_right_closed
            self._open_width = max(
                self.winfo_width(),
                self.winfo_reqwidth(),
                open_min_width,
            )
            self.placement_frame.grid_forget()
            self.container.grid_columnconfigure(1, weight=0, minsize=0)
            self.update_idletasks()
            collapsed_width = max(self.winfo_reqwidth(), closed_min_width)
            self.minsize(closed_min_width, 420)
            self.geometry(f"{int(collapsed_width)}x{int(current_height)}")
            self._current_direction = "right"
            self._show_indicator(direction="right")

        pad = self.sidebar_pad if self._placement_open else self.sidebar_pad_closed
        self.sidebar.grid(row=0, column=0, sticky="nsw", padx=(0, pad))
        self._current_sidebar_pad = pad
        self._refresh_widget_focus()

    def _show_indicator(self, direction: str) -> None:
        """Display a triangle indicator; direction is 'left' or 'right'."""

        self.update_idletasks()
        sidebar_right = self.sidebar.winfo_x() + self.sidebar.winfo_width()
        pad_between = self._current_sidebar_pad
        gap_available = max(0, pad_between)
        hit_width = max(
            self.indicator_width,
            min(self.indicator_hit_width, gap_available or self.indicator_width),
        )
        self.indicator_wrapper.config(width=hit_width)
        if gap_available > 0:
            indicator_x = sidebar_right + (gap_available - hit_width) / 2
        else:
            indicator_x = sidebar_right
        y = max(
            self.container_pad_vertical,
            (self.container.winfo_height() - self.indicator_height) / 2,
        )
        self.indicator_wrapper.place(x=indicator_x, y=y)
        self.indicator_canvas.delete("all")
        arrow_height = self.indicator_height / self.indicator_count
        for i in range(self.indicator_count):
            top = i * arrow_height
            if direction == "left":
                points = (
                    self.indicator_width,
                    top,
                    self.indicator_width,
                    top + arrow_height,
                    0,
                    top + (arrow_height / 2),
                )
            else:
                points = (
                    0,
                    top,
                    0,
                    top + arrow_height,
                    self.indicator_width,
                    top + (arrow_height / 2),
                )
            self.indicator_canvas.create_polygon(*points, fill="black")

    def _hide_indicator(self) -> None:
        """Hide the collapse indicator."""

        self.indicator_canvas.place_forget()

    def _handle_configure(self, _event: tk.Event[tk.Misc]) -> None:  # type: ignore[name-defined]
        """Re-center the indicator when the window is resized."""

        if not self._placement_open:
            self._show_indicator(direction=self._current_direction)
        self._on_configure_activity()
        self._refresh_widget_focus()

    def _handle_return_key(self, _event: tk.Event[tk.Misc]) -> str | None:  # type: ignore[name-defined]
        if self._handle_active_widget_key("Return"):
            return "break"
        return None

    def _center_and_show(self) -> None:
        """Center the window before making it visible to avoid jumpiness."""

        self._center_on_screen()
        try:
            self.deiconify()
            self.lift()
        except Exception:
            pass

    def _center_on_screen(self) -> None:
        """Position the window at the center of the available screen."""

        self.update_idletasks()
        width = max(1, self.winfo_width() or self.winfo_reqwidth())
        height = max(1, self.winfo_height() or self.winfo_reqheight())
        origin_x, origin_y, screen_width, screen_height = self._get_primary_screen_bounds()

        x = max(0, int(origin_x + (screen_width - width) / 2))
        y = max(0, int(origin_y + (screen_height - height) / 2))
        self.geometry(f"{width}x{height}+{x}+{y}")

    def _get_primary_screen_bounds(self) -> tuple[int, int, int, int]:
        """Return (x, y, width, height) for the primary monitor."""

        # Platform-specific primary monitor detection; fallback to Tk defaults.
        bounds = self._get_windows_primary_bounds()
        if bounds:
            return bounds

        bounds = self._get_xrandr_primary_bounds()
        if bounds:
            return bounds

        width = max(1, self.winfo_screenwidth())
        height = max(1, self.winfo_screenheight())
        return 0, 0, width, height

    def _get_windows_primary_bounds(self) -> tuple[int, int, int, int] | None:
        if platform.system() != "Windows":
            return None
        try:
            import ctypes

            user32 = ctypes.windll.user32
            # Ensure correct dimensions on high-DPI displays.
            try:
                user32.SetProcessDPIAware()
            except Exception:
                pass
            width = int(user32.GetSystemMetrics(0))
            height = int(user32.GetSystemMetrics(1))
            return 0, 0, width, height
        except Exception:
            return None

    def _get_xrandr_primary_bounds(self) -> tuple[int, int, int, int] | None:
        if platform.system() != "Linux":
            return None
        try:
            result = subprocess.run(
                ["xrandr", "--query"],
                check=True,
                capture_output=True,
                text=True,
            )
        except (FileNotFoundError, subprocess.CalledProcessError):
            return None

        for line in result.stdout.splitlines():
            if " primary " not in line:
                continue
            match = re.search(r"(\d+)x(\d+)\+(-?\d+)\+(-?\d+)", line)
            if not match:
                continue
            width, height, x, y = map(int, match.groups())
            return x, y, width, height

        return None


def launch() -> None:
    """Entry point used by other modules."""

    app = OverlayConfigApp()
    app.mainloop()


if __name__ == "__main__":
    launch()
