import types

import pytest


@pytest.fixture()
def anchor_widget():
    try:
        import tkinter as tk
    except Exception as exc:  # pragma: no cover - environment guard
        pytest.skip(f"tkinter unavailable: {exc}")
    try:
        root = tk.Tk()
    except tk.TclError as exc:  # pragma: no cover - headless guard
        pytest.skip(f"Tk root unavailable: {exc}")
    root.withdraw()

    import overlay_controller.overlay_controller as oc

    widget = oc.AnchorSelectorWidget(root)
    widget.canvas.config(width=120, height=120)
    widget._needs_static = True  # type: ignore[attr-defined]
    # Force an initial layout so coordinates are deterministic in tests.
    widget.canvas.update_idletasks()
    widget._draw()
    yield widget
    try:
        root.destroy()
    except Exception:
        pass


def _highlight_coords(widget) -> list[float]:
    widget.canvas.update_idletasks()
    widget._draw()
    coords = widget.canvas.coords("highlight")
    return coords


def test_anchor_highlight_matches_mapping(anchor_widget):
    anchor_widget.set_anchor("nw")
    coords = _highlight_coords(anchor_widget)
    cx, cy = anchor_widget._positions[4]  # center point
    assert coords[0] >= cx
    assert coords[1] >= cy

    anchor_widget.set_anchor("se")
    coords = _highlight_coords(anchor_widget)
    assert coords[2] <= cx
    assert coords[3] <= cy


def test_click_inverts_to_anchor(anchor_widget):
    # Clicking top-left should pick anchor "se" (highlight moves to top-left).
    top_left = anchor_widget._positions[0]
    event = types.SimpleNamespace(x=top_left[0], y=top_left[1])
    anchor_widget._handle_click(event)
    anchor_widget._draw()
    assert anchor_widget.get_anchor() == "se"
    coords = _highlight_coords(anchor_widget)
    cx, cy = anchor_widget._positions[4]
    assert coords[2] <= cx
    assert coords[3] <= cy


def test_arrow_navigation_preserves_relative_mapping(anchor_widget):
    # Start at "left", move up once -> "sw" (top-right highlight).
    anchor_widget.on_focus_enter()
    anchor_widget.set_anchor("left")
    anchor_widget.handle_key("Up")
    coords = _highlight_coords(anchor_widget)
    assert anchor_widget.get_anchor() == "sw"
    cx, cy = anchor_widget._positions[4]
    assert coords[0] >= cx
    assert coords[3] <= cy
