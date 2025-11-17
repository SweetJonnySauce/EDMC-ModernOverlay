"""Tkinter scaffolding for the Overlay Config tool."""

from __future__ import annotations

import tkinter as tk

from input_bindings import BindingConfig, BindingManager


class OverlayConfigApp(tk.Tk):
    """Basic UI skeleton that mirrors the design mockups."""

    def __init__(self) -> None:
        super().__init__()
        self.title("Overlay Config")
        self.geometry("960x600")
        self.minsize(640, 420)

        self._placement_open = True
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
        self.overlay_padding = 4
        self.overlay_border_width = 2

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
        self._binding_manager.register_action("close_app", self.close_application)
        self._binding_manager.activate()
        self.bind("<Configure>", self._handle_configure)

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

        self._create_selection_overlays()
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
                width=220,
                height=80,
            )
            frame.grid(
                row=index,
                column=0,
                sticky="nsew",
                pady=(1 if index > 0 else 0, 1 if index < len(sections) - 1 else 0),
            )
            frame.grid_propagate(True)
            text_label = tk.Label(frame, text=label_text, anchor="center", padx=6, pady=6)
            text_label.pack(fill="both", expand=True)
            self.sidebar.grid_rowconfigure(index, weight=weight)
            self.sidebar_cells.append(frame)

        self.sidebar.grid_columnconfigure(0, weight=1)

    def _create_selection_overlays(self) -> None:
        """Create reusable overlay canvases for selection highlights."""

        sidebar_bg = self.sidebar.cget("background")
        self.sidebar_overlay = tk.Frame(
            self.sidebar,
            bd=0,
            highlightthickness=0,
            background=sidebar_bg,
        )
        self.sidebar_overlay.place_forget()

        placement_bg = self.container.cget("background")
        self.placement_overlay = tk.Frame(
            self.container,
            bd=0,
            highlightthickness=0,
            background=placement_bg,
        )
        self.placement_overlay.place_forget()

    def toggle_placement_window(self) -> None:
        """Switch between the open and closed placement window layouts."""

        self._placement_open = not self._placement_open
        if not self._placement_open and self.widget_focus_area == "placement":
            self.widget_focus_area = "sidebar"
        self._apply_placement_state()
        self._refresh_widget_focus()

    def focus_sidebar_up(self) -> None:
        """Move sidebar focus upward."""

        if not getattr(self, "sidebar_cells", None):
            return
        new_index = max(0, self._sidebar_focus_index - 1)
        self._set_sidebar_focus(new_index)
        self._refresh_widget_focus()

    def focus_sidebar_down(self) -> None:
        """Move sidebar focus downward."""

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

    def move_widget_focus_left(self) -> None:
        """Handle left arrow behavior in widget select mode."""

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
            self.sidebar_overlay.place_forget()
            return
        if self.widget_focus_area != "sidebar":
            self.sidebar_overlay.place_forget()
            return

        frame = self.sidebar_cells[self._sidebar_focus_index]
        frame.update_idletasks()
        width = frame.winfo_width()
        height = frame.winfo_height()
        x = frame.winfo_x()
        y = frame.winfo_y()
        pad = self.overlay_padding
        overlay_width = max(width + (pad * 2), self.overlay_border_width * 2)
        overlay_height = max(height + (pad * 2), self.overlay_border_width * 2)
        self.sidebar_overlay.place(x=x - pad, y=y - pad, width=overlay_width, height=overlay_height)
        color = "#888888" if self.widget_select_mode else "#000000"
        self.sidebar_overlay.configure(
            highlightthickness=self.overlay_border_width,
            highlightbackground=color,
            highlightcolor=color,
            bd=0,
        )
        self.sidebar_overlay.tkraise()
        frame.tkraise()

    def _update_placement_focus_highlight(self) -> None:
        is_active = self.widget_focus_area == "placement" and self._placement_open
        if not is_active:
            self.placement_overlay.place_forget()
            return

        self.placement_frame.update_idletasks()
        width = self.placement_frame.winfo_width()
        height = self.placement_frame.winfo_height()
        x = self.placement_frame.winfo_x()
        y = self.placement_frame.winfo_y()
        pad = self.overlay_padding
        overlay_width = max(width + (pad * 2), self.overlay_border_width * 2)
        overlay_height = max(height + (pad * 2), self.overlay_border_width * 2)
        self.placement_overlay.place(
            x=x - pad,
            y=y - pad,
            width=overlay_width,
            height=overlay_height,
        )
        color = "#888888" if self.widget_select_mode else "#000000"
        self.placement_overlay.configure(
            highlightthickness=self.overlay_border_width,
            highlightbackground=color,
            highlightcolor=color,
            bd=0,
        )
        self.placement_overlay.tkraise()
        self.placement_frame.tkraise()

    def _refresh_widget_focus(self) -> None:
        if hasattr(self, "sidebar_cells"):
            self._update_sidebar_highlight()
        self._update_placement_focus_highlight()

    def close_application(self) -> None:
        """Close the Overlay Config window."""

        if getattr(self, "widget_select_mode", True):
            self.destroy()

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
        self._refresh_widget_focus()


def launch() -> None:
    """Entry point used by other modules."""

    app = OverlayConfigApp()
    app.mainloop()


if __name__ == "__main__":
    launch()
