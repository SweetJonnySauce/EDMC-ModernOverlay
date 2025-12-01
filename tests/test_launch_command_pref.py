from __future__ import annotations

import load


class _DummyRuntime:
    def __init__(self) -> None:
        self.controller_launches = 0

    # Methods used by the command helper
    def send_test_message(self, text: str, x: int | None = None, y: int | None = None) -> None:  # pragma: no cover - not used here
        pass

    def launch_overlay_controller(self) -> None:
        self.controller_launches += 1

    # Optional cycling hooks (unused in these tests)
    def cycle_payload_next(self) -> None:  # pragma: no cover - unused
        raise RuntimeError("unused in test")

    def cycle_payload_prev(self) -> None:  # pragma: no cover - unused
        raise RuntimeError("unused in test")


def _build_helper(prefix: str, previous_prefix: str | None = None) -> tuple[_DummyRuntime, object]:
    runtime = _DummyRuntime()
    helper = load._PluginRuntime._build_command_helper(runtime, prefix, previous_prefix=previous_prefix)
    return runtime, helper


def test_helper_uses_new_prefix_after_change():
    runtime, helper = _build_helper("!ovr", previous_prefix="!overlay")
    assert helper.handle_entry({"event": "SendText", "Message": "!ovr"}) is True
    assert runtime.controller_launches == 1
    # Old prefix should no longer be honoured once a custom command is set
    assert helper.handle_entry({"event": "SendText", "Message": "!overlay"}) is False
    assert runtime.controller_launches == 1


def test_helper_with_default_prefix_only_accepts_overlay():
    runtime, helper = _build_helper("!overlay")
    assert helper.handle_entry({"event": "SendText", "Message": "!overlay"}) is True
    assert runtime.controller_launches == 1
    assert helper.handle_entry({"event": "SendText", "Message": "!ovr"}) is False
    assert runtime.controller_launches == 1
