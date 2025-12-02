from types import SimpleNamespace

import overlay_controller.overlay_controller as oc


class _DropdownStub:
    def __init__(self, index: int = 0):
        self._index = index
        self.current_calls = []
        self.configure_calls = []
        self.set_calls = []

    def current(self, value: int | None = None):
        if value is not None:
            self.current_calls.append(value)
            self._index = value
        return self._index

    def configure(self, **kwargs):
        self.configure_calls.append(kwargs)

    def set(self, value):
        self.set_calls.append(value)


class _IdPrefixWidgetStub:
    def __init__(self, index: int = 0):
        self.dropdown = _DropdownStub(index=index)
        self.update_calls: list[tuple[list[str], int | None]] = []

    def update_options(self, options: list[str], selected_index: int | None = None):
        self.update_calls.append((options, selected_index))
        self.dropdown.configure(values=options)
        if selected_index is not None:
            self.dropdown.current(selected_index)
        else:
            self.dropdown.set("")


def test_refresh_idprefix_preserves_selection_when_present():
    calls = []

    def _set_enabled(flag: bool):
        calls.append(flag)

    app = SimpleNamespace(
        _idprefix_entries=[("PluginA", "Group1")],
        idprefix_widget=_IdPrefixWidgetStub(index=0),
        _grouping="PluginA",
        _id_prefix="Group1",
        _set_group_controls_enabled=_set_enabled,
        _get_current_group_selection=lambda: ("PluginA", "Group1"),
        _handle_idprefix_selected=lambda _sel=None: None,
    )

    def _load_opts():
        # Simulate cache still containing the same entry.
        app._idprefix_entries = [("PluginA", "Group1")]
        return ["PluginA: Group1"]

    app._load_idprefix_options = _load_opts  # type: ignore[attr-defined]

    oc.OverlayConfigApp._refresh_idprefix_options(app)

    assert app.idprefix_widget.update_calls == [(["PluginA: Group1"], 0)]
    # Controls should not be disabled.
    assert calls == []
    assert app.idprefix_widget.dropdown.current() == 0


def test_refresh_idprefix_disables_when_selection_missing():
    calls = []

    def _set_enabled(flag: bool):
        calls.append(flag)

    app = SimpleNamespace(
        _idprefix_entries=[("PluginA", "Group1")],
        idprefix_widget=_IdPrefixWidgetStub(index=0),
        _grouping="PluginA",
        _id_prefix="Group1",
        _set_group_controls_enabled=_set_enabled,
        _get_current_group_selection=lambda: ("PluginA", "Group1"),
        _handle_idprefix_selected=lambda _sel=None: None,
    )

    def _load_opts():
        # Cache now empty.
        app._idprefix_entries = []
        return []

    app._load_idprefix_options = _load_opts  # type: ignore[attr-defined]

    oc.OverlayConfigApp._refresh_idprefix_options(app)

    assert app.idprefix_widget.update_calls == [([], None)]
    assert calls == [False]
    assert app._grouping == ""
    assert app._id_prefix == ""
