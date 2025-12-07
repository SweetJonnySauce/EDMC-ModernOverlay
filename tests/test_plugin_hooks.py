from __future__ import annotations

import load


def test_plugin_start_stop_idempotent(monkeypatch, tmp_path):
    # Stub out Preferences and runtime to avoid real side effects
    class DummyPrefs:
        def __init__(self, *_args, **_kwargs):
            self.controller_launch_command = "!ovr"

        def save(self):
            return

    class DummyRuntime:
        def __init__(self, *args, **kwargs):
            self.started = 0
            self.stopped = 0

        def start(self):
            self.started += 1
            return load.PLUGIN_NAME

        def stop(self):
            self.stopped += 1

    monkeypatch.setattr(load, "_PluginRuntime", DummyRuntime)
    monkeypatch.setattr(load, "Preferences", DummyPrefs)

    result1 = load.plugin_start3(str(tmp_path))
    result2 = load.plugin_start3(str(tmp_path))

    assert result1 == load.PLUGIN_NAME
    assert result2 == load.PLUGIN_NAME
    assert isinstance(load._plugin, DummyRuntime)
    # plugin_start3 is idempotent at the hook level; DummyRuntime start guard would live inside the runtime.
    assert load._plugin.started == 1

    load.plugin_stop()
    load.plugin_stop()

    assert load._plugin is None
    # No exception on double stop
