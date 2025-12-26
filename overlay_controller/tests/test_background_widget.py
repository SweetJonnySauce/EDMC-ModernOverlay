import types

import pytest


@pytest.fixture()
def background_widget():
    try:
        import tkinter as tk
    except Exception as exc:  # pragma: no cover - environment guard
        pytest.skip(f"tkinter unavailable: {exc}")
    try:
        root = tk.Tk()
    except tk.TclError as exc:  # pragma: no cover - headless guard
        pytest.skip(f"Tk root unavailable: {exc}")
    root.withdraw()

    from overlay_controller.widgets.background import BackgroundWidget

    widget = BackgroundWidget(root)
    widget.pack()
    root.update_idletasks()
    yield widget
    try:
        root.destroy()
    except Exception:
        pass


def test_background_widget_left_right_respects_entry_cursor(background_widget):
    import tkinter as tk

    entry = background_widget._entry
    entry.delete(0, tk.END)
    entry.insert(0, "abcd")
    try:
        entry.selection_clear()
    except Exception:
        pass
    entry.icursor(2)
    background_widget._set_active_field("color")

    event = types.SimpleNamespace(widget=entry)
    result = background_widget.handle_key("Right", event)
    assert background_widget._active_field == "color"
    assert result is False

    entry.icursor(tk.END)
    try:
        entry.selection_clear()
    except Exception:
        pass
    result = background_widget.handle_key("Right", event)
    assert background_widget._active_field == "pick"
    assert result is True


def test_background_widget_left_right_respects_spin_cursor(background_widget):
    import tkinter as tk

    spin = background_widget._spin
    spin.delete(0, tk.END)
    spin.insert(0, "12")
    try:
        spin.selection_clear()
    except Exception:
        pass
    spin.icursor(1)
    background_widget._set_active_field("border")

    event = types.SimpleNamespace(widget=spin)
    result = background_widget.handle_key("Left", event)
    assert background_widget._active_field == "border"
    assert result is False

    spin.icursor(0)
    try:
        spin.selection_clear()
    except Exception:
        pass
    result = background_widget.handle_key("Left", event)
    assert background_widget._active_field == "border_pick"
    assert result is True


def test_background_widget_picker_applies_alpha(background_widget, monkeypatch):
    import overlay_controller.widgets.background as background

    widget = background_widget
    widget._color_var.set("#11223344")
    captured = {}

    def fake_askcolor(color=None, **_kwargs):
        captured["color"] = color
        return ((170, 187, 204), "#aabbcc")

    monkeypatch.setattr(background.colorchooser, "askcolor", fake_askcolor)

    widget._open_color_picker("color")

    assert captured["color"] == "#223344"
    assert widget._color_var.get() == "#11AABBCC"


def test_background_widget_picker_cancel_keeps_value(background_widget, monkeypatch):
    import overlay_controller.widgets.background as background

    widget = background_widget
    widget._color_var.set("#ABCDEF88")

    def fake_askcolor(*_args, **_kwargs):
        return (None, None)

    monkeypatch.setattr(background.colorchooser, "askcolor", fake_askcolor)

    widget._open_color_picker("color")

    assert widget._color_var.get() == "#ABCDEF88"
