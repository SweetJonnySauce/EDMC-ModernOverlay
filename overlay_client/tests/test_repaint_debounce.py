from __future__ import annotations

import types
import os

import pytest

from overlay_client.overlay_client import OverlayWindow
from overlay_client.debug_config import DebugConfig
from overlay_client.client_config import InitialClientSettings
from PyQt6.QtWidgets import QApplication


@pytest.fixture
def qt_app(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", os.getenv("QT_QPA_PLATFORM", "offscreen"))
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


class DummyTimer:
    def __init__(self):
        self._active = False
        self.started = 0
        self.stopped = 0

    def isActive(self) -> bool:
        return self._active

    def start(self):
        self._active = True
        self.started += 1

    def stop(self):
        self._active = False
        self.stopped += 1


@pytest.fixture
def window(monkeypatch, qt_app):
    settings = InitialClientSettings()
    debug_config = DebugConfig(repaint_debounce_enabled=True, log_repaint_debounce=False)
    win = OverlayWindow(settings, debug_config)
    dummy_timer = DummyTimer()
    monkeypatch.setattr(win, "_repaint_timer", dummy_timer)
    monkeypatch.setattr(win, "update", types.MethodType(lambda self: setattr(self, "_updated", True), win))
    win._updated = False
    win._repaint_metrics["enabled"] = True
    return win


def test_should_bypass_debounce():
    assert OverlayWindow._should_bypass_debounce({"animate": True}) is True
    assert OverlayWindow._should_bypass_debounce({"ttl": 0.5}) is True
    assert OverlayWindow._should_bypass_debounce({"ttl": "0.7"}) is True
    assert OverlayWindow._should_bypass_debounce({"ttl": 2}) is False
    assert OverlayWindow._should_bypass_debounce({"ttl": "bad"}) is False
    assert OverlayWindow._should_bypass_debounce({}) is False


def test_request_repaint_immediate_bypasses_timer(window: OverlayWindow):
    timer = window._repaint_timer
    window._request_repaint("ingest", immediate=True)
    assert window._updated is True
    assert timer.started == 0


def test_request_repaint_uses_timer_when_enabled(window: OverlayWindow):
    timer = window._repaint_timer
    window._request_repaint("ingest", immediate=False)
    assert window._updated is False
    assert timer.started == 1
    assert timer.isActive() is True


def test_request_repaint_disables_debounce_when_configured(window: OverlayWindow):
    window._repaint_debounce_enabled = False
    timer = window._repaint_timer
    window._updated = False
    window._request_repaint("ingest", immediate=False)
    assert window._updated is True
    assert timer.started == 0
