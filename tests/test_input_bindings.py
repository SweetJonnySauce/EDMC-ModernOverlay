from __future__ import annotations

import logging
from pathlib import Path

import pytest

from overlay_controller.input_bindings import BindingConfig, BindingManager, ControlScheme


class DummyWidget:
    """Minimal stand-in for a Tk widget that can simulate bind failures."""

    def __init__(self, *, fail_sequences: set[str] | None = None) -> None:
        self.bound_sequences: list[str] = []
        self.unbound_sequences: list[str] = []
        self.fail_sequences = fail_sequences or set()

    def bind(self, sequence: str, callback, add: str | None = None):  # type: ignore[override]
        if sequence in self.fail_sequences:
            raise RuntimeError(f"Cannot bind {sequence}")
        self.bound_sequences.append(sequence)
        return "ok"

    def unbind(self, sequence: str):  # type: ignore[override]
        self.unbound_sequences.append(sequence)


def _make_config(bindings: dict[str, list[str]]) -> BindingConfig:
    scheme = ControlScheme(
        name="test",
        device_type="keyboard",
        display_name="Test",
        bindings=bindings,
    )
    return BindingConfig(
        schemes={"test": scheme},
        active_scheme="test",
        source_path=Path("dummy"),
    )


def test_activate_skips_invalid_sequences_and_logs(caplog: pytest.LogCaptureFixture) -> None:
    widget = DummyWidget(fail_sequences={"<ISO_Left_Tab>"})
    config = _make_config({"cycle": ["<Shift-Tab>", "<ISO_Left_Tab>"]})
    manager = BindingManager(widget, config)
    manager.register_action("cycle", lambda: None, widget=widget)

    with caplog.at_level(logging.WARNING, logger="EDMCModernOverlay.Controller"):
        manager.activate()

    assert widget.bound_sequences == ["<Shift-Tab>"]
    assert any("ISO_Left_Tab" in record.getMessage() for record in caplog.records)


def test_activate_skips_empty_sequences(caplog: pytest.LogCaptureFixture) -> None:
    widget = DummyWidget()
    config = _make_config({"move": ["", "   ", "<Left>"]})
    manager = BindingManager(widget, config)
    manager.register_action("move", lambda: None, widget=widget)

    with caplog.at_level(logging.WARNING, logger="EDMCModernOverlay.Controller"):
        manager.activate()

    assert widget.bound_sequences == ["<Left>"]
    # Two invalid sequences should have produced two warnings.
    empty_warnings = [record for record in caplog.records if "Skipping invalid binding" in record.getMessage()]
    assert len(empty_warnings) == 2
