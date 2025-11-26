from __future__ import annotations

import sys
from pathlib import Path

import pytest

OVERLAY_ROOT = Path(__file__).resolve().parents[1]
if str(OVERLAY_ROOT) not in sys.path:
    sys.path.append(str(OVERLAY_ROOT))

# PyQt-dependent tests are guarded by the pyqt_required marker (see tests/conftest.py).
try:
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtGui import QPainter, QPixmap
except Exception:  # pragma: no cover - import guard for environments without PyQt6
    pytest.skip("PyQt6 not available", allow_module_level=True)

from client_config import InitialClientSettings  # noqa: E402
from debug_config import DebugConfig  # noqa: E402
from legacy_store import LegacyItem  # noqa: E402
from overlay_client import OverlayWindow  # noqa: E402


@pytest.fixture
def qt_app():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.mark.pyqt_required
def test_grid_pixmap_cached_and_invalidated(qt_app):
    window = OverlayWindow(InitialClientSettings(), DebugConfig())
    window.resize(200, 200)
    window.set_background_opacity(0.5)  # enable grid alpha
    window.set_gridlines(enabled=True, spacing=40)

    alpha = int(255 * window._background_opacity)
    pix1 = window._grid_pixmap_for(200, 200, 40, alpha)
    pix2 = window._grid_pixmap_for(200, 200, 40, alpha)

    assert pix1 is not None
    assert pix1 is pix2  # cache hit

    window.set_gridlines(enabled=True, spacing=60)
    alpha = int(255 * window._background_opacity)
    pix3 = window._grid_pixmap_for(200, 200, 60, alpha)
    assert pix3 is not None
    assert pix3 is not pix2  # spacing invalidated cache

    window.set_background_opacity(0.3)
    alpha = int(255 * window._background_opacity)
    pix4 = window._grid_pixmap_for(200, 200, 60, alpha)
    assert pix4 is not None
    assert pix4 is not pix3  # opacity invalidated cache


@pytest.mark.pyqt_required
def test_legacy_render_cache_reuse_and_invalidate(monkeypatch, qt_app):
    window = OverlayWindow(InitialClientSettings(), DebugConfig())
    window.resize(200, 200)
    window._legacy_items.set("msg1", LegacyItem("msg1", "message", {"text": "hi"}, plugin="tester"))

    pixmap = QPixmap(200, 200)
    painter = QPainter(pixmap)

    rebuilds = 0
    original = window._render_pipeline._rebuild_legacy_render_cache

    def _wrapper(mapper, signature):
        nonlocal rebuilds
        rebuilds += 1
        return original(mapper, signature)

    monkeypatch.setattr(window._render_pipeline, "_rebuild_legacy_render_cache", _wrapper)

    window._paint_legacy(painter)
    window._paint_legacy(painter)
    assert rebuilds == 1  # second paint reused cache

    window._mark_legacy_cache_dirty()
    window._paint_legacy(painter)
    assert rebuilds == 2  # cache rebuilt after dirty flag

    painter.end()
