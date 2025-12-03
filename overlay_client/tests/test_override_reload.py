from overlay_client.control_surface import ControlSurfaceMixin
from overlay_client.override_reload import force_reload_overrides
from overlay_client.payload_model import PayloadModel
from overlay_client.legacy_store import LegacyItem


def test_force_reload_overrides_resets_state_and_updates_plugins():
    logs = []

    def log_fn(message: str, *args):
        logs.append(message % args if args else message)

    class DummyOverrideManager:
        def __init__(self):
            self.forced = False
            self.generation = 1

        def force_reload(self):
            self.forced = True
            self.generation += 1

        def infer_plugin_name(self, payload):
            if payload.get("id") == "item-a":
                return "new-plugin"
            return payload.get("plugin")

    class DummyGroupingHelper:
        def __init__(self):
            self.reset_called = False

        def reset(self):
            self.reset_called = True

    override_manager = DummyOverrideManager()
    grouping_helper = DummyGroupingHelper()
    model = PayloadModel(lambda *_args, **_kwargs: None)
    model.store.set("item-a", LegacyItem(item_id="item-a", kind="message", data={"text": "hi"}, plugin="old-plugin"))
    model.store.set("item-b", LegacyItem(item_id="item-b", kind="message", data={"text": "bye"}, plugin="stay"))
    model._last_snapshots["item-a"] = (("snapshot",), 1)

    force_reload_overrides(override_manager, grouping_helper, model, log_fn)

    assert override_manager.forced is True
    assert grouping_helper.reset_called is True
    assert not model._last_snapshots  # type: ignore[attr-defined]
    assert model.store.get("item-a").plugin == "new-plugin"
    assert model.store.get("item-b").plugin == "stay"
    assert any("Override reload applied" in entry for entry in logs)


def test_handle_override_reload_dedupes_nonce():
    class FakeWindow(ControlSurfaceMixin):  # type: ignore[misc]
        def __init__(self):
            self._override_manager = type(
                "Mgr",
                (),
                {
                    "force_reload": lambda self: None,
                    "infer_plugin_name": lambda self, payload: payload.get("plugin"),
                    "generation": 1,
                },
            )()
            self._grouping_helper = type("GH", (), {"reset": lambda self: None})()
            self._payload_model = PayloadModel(lambda *_args, **_kwargs: None)
            self._mark_legacy_cache_dirty_called = 0
            self._repaint_calls = []
            self._last_override_reload_nonce = None

        def _mark_legacy_cache_dirty(self) -> None:
            self._mark_legacy_cache_dirty_called += 1

        def _request_repaint(self, reason: str, *, immediate: bool = False) -> None:
            self._repaint_calls.append((reason, immediate))

    window = FakeWindow()

    window.handle_override_reload({"nonce": "abc"})
    assert window._last_override_reload_nonce == "abc"
    assert window._mark_legacy_cache_dirty_called == 1
    assert window._repaint_calls == [("override_reload", True)]

    # Duplicate nonce should no-op.
    window.handle_override_reload({"nonce": "abc"})
    assert window._mark_legacy_cache_dirty_called == 1
    assert window._repaint_calls == [("override_reload", True)]
