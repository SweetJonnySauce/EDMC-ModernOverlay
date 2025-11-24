from __future__ import annotations

from overlay_plugin.journal_commands import build_command_helper


class _DummyRuntime:
    def __init__(self) -> None:
        self.messages: list[str] = []
        self.next_calls = 0
        self.prev_calls = 0
        self.cycle_enabled = True
        self.controller_launches = 0
        self.controller_enabled = True
        self.controller_should_fail = False

    def send_test_message(self, text: str, x: int | None = None, y: int | None = None) -> None:
        self.messages.append(text)

    def cycle_payload_next(self) -> None:
        if not self.cycle_enabled:
            raise RuntimeError("disabled")
        self.next_calls += 1

    def cycle_payload_prev(self) -> None:
        if not self.cycle_enabled:
            raise RuntimeError("disabled")
        self.prev_calls += 1

    def launch_overlay_controller(self) -> None:
        if not self.controller_enabled:
            raise RuntimeError("disabled")
        if self.controller_should_fail:
            raise RuntimeError("boom")
        self.controller_launches += 1


def build_helper(runtime: _DummyRuntime | None = None) -> tuple[_DummyRuntime, object]:
    runtime = runtime or _DummyRuntime()
    helper = build_command_helper(runtime)
    return runtime, helper


def test_non_sendtext_events_ignored():
    runtime, helper = build_helper()
    assert helper.handle_entry({"event": "Location"}) is False
    assert runtime.messages == []


def test_other_bang_commands_ignored():
    runtime, helper = build_helper()
    assert helper.handle_entry({"event": "SendText", "Message": "!help"}) is False
    assert runtime.messages == []


def test_overlay_help_command():
    runtime, helper = build_helper()
    assert helper.handle_entry({"event": "SendText", "Message": "!overlay help"}) is True
    assert runtime.messages[-1].startswith("Overlay commands:")


def test_overlay_launch_command():
    runtime, helper = build_helper()
    assert helper.handle_entry({"event": "SendText", "Message": "!overlay"}) is True
    assert runtime.controller_launches == 1
    assert runtime.messages == []


def test_overlay_next_command():
    runtime, helper = build_helper()
    assert helper.handle_entry({"event": "SendText", "Message": "!overlay next"}) is True
    assert runtime.next_calls == 1
    assert "next" in runtime.messages[-1].lower()


def test_overlay_prev_command():
    runtime, helper = build_helper()
    assert helper.handle_entry({"event": "SendText", "Message": "!overlay prev"}) is True
    assert runtime.prev_calls == 1
    assert "previous" in runtime.messages[-1].lower()


def test_overlay_unknown_subcommand():
    runtime, helper = build_helper()
    assert helper.handle_entry({"event": "SendText", "Message": "!overlay foo"}) is True
    assert "unknown overlay command" in runtime.messages[-1].lower()


def test_overlay_cycle_disabled_message():
    runtime, helper = build_helper()
    runtime.cycle_enabled = False
    assert helper.handle_entry({"event": "SendText", "Message": "!overlay next"}) is True
    assert "unavailable" in runtime.messages[-1].lower()


def test_overlay_launch_unavailable():
    runtime = _DummyRuntime()
    runtime.launch_overlay_controller = None  # type: ignore[assignment]
    runtime, helper = build_helper(runtime)
    assert helper.handle_entry({"event": "SendText", "Message": "!overlay"}) is True
    assert "unavailable" in runtime.messages[-1].lower()


def test_overlay_launch_failure():
    runtime, helper = build_helper()
    runtime.controller_should_fail = True
    assert helper.handle_entry({"event": "SendText", "Message": "!overlay"}) is True
    assert "failed" in runtime.messages[-1].lower()
    assert runtime.controller_launches == 0
