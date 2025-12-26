from __future__ import annotations

import tkinter as tk
from typing import Callable, Optional

from overlay_controller.selection_overlay import SelectionOverlay
from overlay_controller.widgets import (
    AbsoluteXYWidget,
    AnchorSelectorWidget,
    BackgroundWidget,
    IdPrefixGroupWidget,
    JustificationWidget,
    OffsetSelectorWidget,
    SidebarTipHelper,
)


class LayoutBuilder:
    """Builds placement/sidebar layout and focus map."""

    def __init__(self, app: tk.Tk) -> None:
        self.app = app

    def build(
        self,
        *,
        sidebar_width: int,
        sidebar_pad: int,
        container_pad_left: int,
        container_pad_right_open: int,
        container_pad_right_closed: int,
        container_pad_vertical: int,
        placement_overlay_padding: int,
        preview_canvas_padding: int,
        overlay_padding: int,
        overlay_border_width: int,
        placement_min_width: int,
        sidebar_selectable: bool,
        on_sidebar_click: Callable[[int], None],
        on_placement_click: Callable[[], None],
        on_idprefix_selected: Callable[[], None],
        on_offset_changed: Callable[[str, bool], None],
        on_absolute_changed: Callable[[str], None],
        on_anchor_changed: Callable[[str, bool], None],
        on_justification_changed: Callable[[str], None],
        on_background_changed: Callable[[Optional[str], Optional[str], Optional[int]], None],
        load_idprefix_options: Callable[[], list[str]],
    ) -> dict[str, object]:
        app = self.app
        container = tk.Frame(app)
        container.grid(
            row=0,
            column=0,
            sticky="nsew",
            padx=(container_pad_left, container_pad_right_open),
            pady=(container_pad_vertical, container_pad_vertical),
        )
        app.grid_rowconfigure(0, weight=1)
        app.grid_columnconfigure(0, weight=1)
        container.grid_rowconfigure(0, weight=1)
        container.grid_columnconfigure(0, weight=0, minsize=sidebar_width)
        container.grid_columnconfigure(1, weight=1)

        placement_frame = tk.Frame(
            container,
            bd=0,
            relief="flat",
            background="#f5f5f5",
        )
        preview_canvas = tk.Canvas(
            placement_frame,
            bd=0,
            highlightthickness=1,
            relief="solid",
            background="#202020",
        )
        preview_canvas.pack(fill="both", expand=True)
        preview_canvas.bind("<Button-1>", lambda _e: on_placement_click(), add="+")
        placement_frame.bind("<Button-1>", lambda _e: on_placement_click(), add="+")
        preview_canvas.bind("<Configure>", lambda _e: app._draw_preview())  # type: ignore[attr-defined]

        sidebar = tk.Frame(
            container,
            width=sidebar_width,
            bd=0,
            highlightthickness=0,
        )
        sidebar.grid(row=0, column=0, sticky="ns", padx=(0, sidebar_pad))

        indicator_bg = container.cget("background")
        indicator_wrapper = tk.Frame(
            container,
            width=app.indicator_hit_width,  # type: ignore[attr-defined]
            height=app.indicator_height,  # type: ignore[attr-defined]
            bd=0,
            highlightthickness=0,
            bg=indicator_bg,
        )
        indicator_wrapper.pack_propagate(False)
        indicator_canvas = tk.Canvas(
            indicator_wrapper,
            width=app.indicator_hit_width,  # type: ignore[attr-defined]
            height=app.indicator_height,  # type: ignore[attr-defined]
            highlightthickness=0,
            bg=indicator_bg,
        )
        indicator_canvas.pack(fill="both", expand=True)

        sidebar_overlay = SelectionOverlay(
            parent=sidebar,
            padding=overlay_padding,
            border_width=overlay_border_width,
        )
        placement_overlay = SelectionOverlay(
            parent=container,
            padding=placement_overlay_padding,
            border_width=overlay_border_width,
            corner_radius=0,
        )

        sections = [
            ("idprefix group selector", 0, True),
            ("offset selector", 0, True),
            ("absolute x/y", 0, True),
            ("anchor selector", 0, True),
            ("payload justification", 0, True),
            ("background color", 0, True),
            ("Handy tips will show up here in the future", 1, False),
        ]

        sidebar_cells: list[tk.Frame] = []
        focus_widgets: dict[tuple[str, int], object] = {}
        selectable_index = 0
        sidebar_context_frame = None

        idprefix_widget = None
        offset_widget = None
        absolute_widget = None
        anchor_widget = None
        justification_widget = None
        background_widget = None
        tip_helper = None

        for index, (label_text, weight, is_selectable) in enumerate(sections):
            default_height = 120 if label_text == "anchor selector" else 80
            frame = tk.Frame(
                sidebar,
                bd=0,
                relief="flat",
                width=0 if index == 0 else 220,
                height=0 if index == 0 else default_height,
            )
            frame.grid(
                row=index,
                column=0,
                sticky="nsew",
                pady=(
                    overlay_padding if index == 0 else 1,
                    overlay_padding if index == len(sections) - 1 else 1,
                ),
                padx=(overlay_padding, overlay_padding),
            )
            frame.grid_propagate(True)

            focus_index = selectable_index if is_selectable else None
            if is_selectable:
                selectable_index += 1

            if index == 0:
                idprefix_widget = IdPrefixGroupWidget(frame, options=load_idprefix_options())
                if is_selectable and focus_index is not None:
                    idprefix_widget.set_focus_request_callback(lambda idx=focus_index: on_sidebar_click(idx))
                idprefix_widget.set_selection_change_callback(lambda _sel=None: on_idprefix_selected())
                idprefix_widget.pack(fill="both", expand=True, padx=0, pady=0)
                if is_selectable and focus_index is not None:
                    focus_widgets[("sidebar", focus_index)] = idprefix_widget
            elif index == 1:
                offset_widget = OffsetSelectorWidget(frame)
                if is_selectable and focus_index is not None:
                    offset_widget.set_focus_request_callback(lambda idx=focus_index: on_sidebar_click(idx))
                offset_widget.set_change_callback(on_offset_changed)
                offset_widget.pack(expand=True)
                if is_selectable and focus_index is not None:
                    focus_widgets[("sidebar", focus_index)] = offset_widget
            elif index == 2:
                absolute_widget = AbsoluteXYWidget(frame)
                if is_selectable and focus_index is not None:
                    absolute_widget.set_focus_request_callback(lambda idx=focus_index: on_sidebar_click(idx))
                absolute_widget.set_change_callback(on_absolute_changed)
                absolute_widget.pack(fill="both", expand=True, padx=0, pady=0)
                if is_selectable and focus_index is not None:
                    focus_widgets[("sidebar", focus_index)] = absolute_widget
            elif index == 3:
                frame.configure(height=140)
                frame.grid_propagate(False)
                anchor_widget = AnchorSelectorWidget(frame)
                if is_selectable and focus_index is not None:
                    anchor_widget.set_focus_request_callback(lambda idx=focus_index: on_sidebar_click(idx))
                anchor_widget.set_change_callback(on_anchor_changed)
                anchor_widget.pack(fill="both", expand=True, padx=4, pady=4)
                if is_selectable and focus_index is not None:
                    focus_widgets[("sidebar", focus_index)] = anchor_widget
            elif index == 4:
                justification_widget = JustificationWidget(frame)
                if is_selectable and focus_index is not None:
                    justification_widget.set_focus_request_callback(lambda idx=focus_index: on_sidebar_click(idx))
                justification_widget.set_change_callback(on_justification_changed)
                justification_widget.pack(fill="both", expand=True, padx=4, pady=4)
                if is_selectable and focus_index is not None:
                    focus_widgets[("sidebar", focus_index)] = justification_widget
            elif index == 5:
                background_widget = BackgroundWidget(frame)
                if is_selectable and focus_index is not None:
                    background_widget.set_focus_request_callback(lambda idx=focus_index: on_sidebar_click(idx))
                background_widget.set_change_callback(on_background_changed)
                background_widget.pack(fill="both", expand=True, padx=4, pady=4)
                if is_selectable and focus_index is not None:
                    focus_widgets[("sidebar", focus_index)] = background_widget
            else:
                tip_helper = SidebarTipHelper(frame)
                tip_helper.pack(fill="both", expand=True, padx=2, pady=2)

            if is_selectable and focus_index is not None:
                frame.bind("<Button-1>", lambda _e, idx=focus_index: on_sidebar_click(idx), add="+")
                for child in frame.winfo_children():
                    child.bind("<Button-1>", lambda _e, idx=focus_index: on_sidebar_click(idx), add="+")

            grow_weight = 1 if index == len(sections) - 1 else 0
            row_opts = {"weight": grow_weight}
            if index == 3:
                row_opts["minsize"] = 220
            sidebar.grid_rowconfigure(index, **row_opts)
            if is_selectable and focus_index is not None:
                sidebar_cells.append(frame)
            else:
                sidebar_context_frame = frame

        sidebar.grid_columnconfigure(0, weight=1)

        return {
            "container": container,
            "placement_frame": placement_frame,
            "preview_canvas": preview_canvas,
            "sidebar": sidebar,
            "sidebar_cells": sidebar_cells,
            "focus_widgets": focus_widgets,
            "sidebar_context_frame": sidebar_context_frame,
            "indicator_wrapper": indicator_wrapper,
            "indicator_canvas": indicator_canvas,
            "sidebar_overlay": sidebar_overlay,
            "placement_overlay": placement_overlay,
            "idprefix_widget": idprefix_widget,
            "offset_widget": offset_widget,
            "absolute_widget": absolute_widget,
            "anchor_widget": anchor_widget,
            "justification_widget": justification_widget,
            "background_widget": background_widget,
            "tip_helper": tip_helper,
            "sidebar_selectable": sidebar_selectable,
            "placement_min_width": placement_min_width,
            "preview_canvas_padding": preview_canvas_padding,
        }
