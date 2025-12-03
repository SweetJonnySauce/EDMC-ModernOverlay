from overlay_client.control_surface import ControlSurfaceMixin


class _WindowStub(ControlSurfaceMixin):  # type: ignore[misc]
    def __init__(self):
        self._controller_active_group = None
        self.repaint_calls = []

    def _request_repaint(self, reason: str, *, immediate: bool = False) -> None:
        self.repaint_calls.append((reason, immediate))


def test_set_active_controller_group_updates_and_clears():
    window = _WindowStub()
    window.set_active_controller_group("PluginA", "Group1")
    assert window._controller_active_group == ("PluginA", "Group1")
    assert window.repaint_calls == [("controller_target", True)]

    # Duplicate should no-op
    window.set_active_controller_group("PluginA", "Group1")
    assert window.repaint_calls == [("controller_target", True)]

    # Changing selection updates value and repaint
    window.set_active_controller_group("PluginB", "Group2")
    assert window._controller_active_group == ("PluginB", "Group2")
    assert window.repaint_calls[-1] == ("controller_target", True)

    # Clearing removes active group and repaints
    window.set_active_controller_group(None, None)
    assert window._controller_active_group is None
    assert window.repaint_calls[-1] == ("controller_target", True)
