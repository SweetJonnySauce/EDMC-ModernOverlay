from __future__ import annotations

import pytest
from PyQt6.QtGui import QPaintEvent, QShowEvent
from PyQt6.QtWidgets import QApplication

from overlay_client.client_config import InitialClientSettings
from overlay_client.debug_config import DebugConfig
from overlay_client.overlay_client import OverlayWindow, _LINE_WIDTH_DEFAULTS


@pytest.fixture
def qt_app():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.mark.pyqt_required
def test_setup_surface_initialises_defaults(qt_app):
    window = OverlayWindow(InitialClientSettings(), DebugConfig())
    try:
        assert window._gridline_spacing == 120
        assert window._line_width_defaults == _LINE_WIDTH_DEFAULTS
        assert window._text_cache == {}
        assert window._text_cache_generation == 0
        assert window._repaint_timer.interval() == window._REPAINT_DEBOUNCE_MS
        assert window._legacy_timer.isActive()
    finally:
        window._legacy_timer.stop()
        window._modifier_timer.stop()
        window._tracking_timer.stop()
        window.close()


@pytest.mark.pyqt_required
def test_show_event_delegates_to_setup_surface(monkeypatch, qt_app):
    window = OverlayWindow(InitialClientSettings(), DebugConfig())
    try:
        calls = []
        monkeypatch.setattr(window, "_apply_legacy_scale", lambda: calls.append("scale"))
        monkeypatch.setattr(window._platform_controller, "prepare_window", lambda _handle: calls.append("prepare"))
        monkeypatch.setattr(window._platform_controller, "apply_click_through", lambda transparent: calls.append(("click", transparent)))

        window.showEvent(QShowEvent())

        assert "scale" in calls
        assert "prepare" in calls
        assert ("click", True) in calls
    finally:
        window._legacy_timer.stop()
        window._modifier_timer.stop()
        window._tracking_timer.stop()
        window.close()


@pytest.mark.pyqt_required
def test_paint_event_calls_mixin(monkeypatch, qt_app):
    window = OverlayWindow(InitialClientSettings(), DebugConfig())
    try:
        captured = []
        monkeypatch.setattr(window, "_paint_overlay", lambda painter: captured.append(painter))
        event = QPaintEvent(window.rect())

        window.paintEvent(event)

        assert captured and captured[0] is not None
    finally:
        window._legacy_timer.stop()
        window._modifier_timer.stop()
        window._tracking_timer.stop()
        window.close()
