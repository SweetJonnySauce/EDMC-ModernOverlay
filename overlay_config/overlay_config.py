"""Tkinter scaffolding for the Overlay Config tool."""

from __future__ import annotations

import tkinter as tk


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
        self.container_pad = 12
        self.placement_min_width = 450
        self.closed_min_width = 60

        self._build_layout()
        self.bind_all("<space>", self._handle_spacebar)

    def _build_layout(self) -> None:
        """Create the split view with placement and sidebar sections."""

        self.container = tk.Frame(self, padx=self.container_pad, pady=self.container_pad)
        self.container.grid(row=0, column=0, sticky="nsew")

        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self.container.grid_rowconfigure(0, weight=1)
        self.container.grid_columnconfigure(0, weight=0, minsize=self.sidebar_width)
        self.container.grid_columnconfigure(1, weight=1)

        # Placement window placeholder (open state)
        self.placement_frame = tk.Frame(
            self.container,
            bd=1,
            relief="solid",
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
        self.sidebar = tk.Frame(self.container, width=self.sidebar_width)
        self.sidebar.grid(row=0, column=0, sticky="nsw", padx=(0, self.sidebar_pad))
        self._build_sidebar_sections()
        self.sidebar.grid_propagate(False)

        info_label = tk.Label(
            self.container,
            text="Press space to open",
            anchor="w",
        )
        info_label.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(10, 0))

        self._apply_placement_state()

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

        for index, (label_text, weight) in enumerate(sections):
            frame = tk.Frame(self.sidebar, bd=1, relief="solid", width=220, height=80)
            frame.grid(
                row=index,
                column=0,
                sticky="nsew",
            )
            text_label = tk.Label(frame, text=label_text, anchor="center", padx=6, pady=6)
            text_label.pack(fill="both", expand=True)
            self.sidebar.grid_rowconfigure(index, weight=weight)

        self.sidebar.grid_columnconfigure(0, weight=1)

    def _handle_spacebar(self, event: tk.Event[tk.Misc]) -> None:  # type: ignore[name-defined]
        """Toggle the placement window visibility when the spacebar is pressed."""

        if event.keysym == "space":
            self.toggle_placement_window()

    def toggle_placement_window(self) -> None:
        """Switch between the open and closed placement window layouts."""

        self._placement_open = not self._placement_open
        self._apply_placement_state()

    def _apply_placement_state(self) -> None:
        """Show the correct placement frame for the current state."""

        self.update_idletasks()
        current_height = max(self.winfo_height(), 420)
        outer_padding = self.container_pad * 2
        sidebar_total = self.sidebar_width + self.sidebar_pad
        open_min_width = outer_padding + sidebar_total + self.placement_min_width
        closed_min_width = outer_padding + sidebar_total + self.closed_min_width

        if self._placement_open:
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
        else:
            self._open_width = max(
                self.winfo_width(),
                self.winfo_reqwidth(),
                open_min_width,
            )
            self.placement_frame.grid_forget()
            self.container.grid_columnconfigure(1, weight=0, minsize=0)
            self.update_idletasks()
            collapsed_width = max(self.winfo_reqwidth(), outer_padding + sidebar_total)
            self.minsize(outer_padding + sidebar_total, 420)
            self.geometry(f"{int(collapsed_width)}x{int(current_height)}")

        self.sidebar.grid(row=0, column=0, sticky="nsw", padx=(0, self.sidebar_pad))


def launch() -> None:
    """Entry point used by other modules."""

    app = OverlayConfigApp()
    app.mainloop()


if __name__ == "__main__":
    launch()
