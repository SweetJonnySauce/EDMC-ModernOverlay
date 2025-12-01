from __future__ import annotations

import os

import pytest
from PyQt6.QtWidgets import QApplication

from overlay_client.overlay_client import OverlayWindow

if not os.getenv("PYQT_TESTS"):
    pytest.skip("PYQT_TESTS not set; skipping PyQt-dependent test", allow_module_level=True)


@pytest.fixture(scope="module")
def app():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


class _DummyWindow:
    _TEXT_CACHE_MAX = 512

    def __init__(self, ratio: float = 1.0, fallbacks: tuple[str, ...] = ()) -> None:
        self._text_cache = {}
        self._text_block_cache = {}
        self._text_cache_generation = 0
        self._text_cache_context = None
        self._text_measurer = None
        self._font_family = "TestFont"
        self._font_fallbacks = tuple(fallbacks)
        self._measure_stats = {"calls": 0}
        self._dev_mode_enabled = False
        self._ratio = ratio

    def devicePixelRatioF(self) -> float:  # noqa: N802 - Qt compatibility
        return self._ratio

    def set_ratio(self, ratio: float) -> None:
        self._ratio = ratio

    def _invalidate_text_cache(self, reason=None):  # noqa: ANN001 - signature match
        return OverlayWindow._invalidate_text_cache(self, reason)

    def _ensure_text_cache_context(self, family):  # noqa: ANN001 - signature match
        return OverlayWindow._ensure_text_cache_context(self, family)

    def _apply_font_fallbacks(self, *_args, **_kwargs) -> None:
        return None


def test_text_cache_hits_and_misses(app) -> None:  # noqa: ARG001 - fixture required
    window = _DummyWindow()

    first = OverlayWindow._measure_text(window, "hello", 10.0, None)
    assert window._measure_stats.get("cache_miss") == 1
    assert window._measure_stats.get("cache_hit", 0) == 0
    assert ("hello", 10.0, "TestFont") in window._text_cache

    second = OverlayWindow._measure_text(window, "hello", 10.0, None)
    assert window._measure_stats.get("cache_hit") == 1
    assert first == second


def test_text_cache_invalidated_on_font_change(app) -> None:  # noqa: ARG001 - fixture required
    window = _DummyWindow()
    OverlayWindow._measure_text(window, "hello", 10.0, None)
    window._text_block_cache[("hello", 10.0, "TestFont", (), 1.0, 0)] = (10, 10)
    resets_before = window._measure_stats.get("cache_reset", 0)
    generation_before = window._text_cache_generation
    window._font_family = "NewFont"

    OverlayWindow._measure_text(window, "hello", 10.0, None)

    assert window._measure_stats.get("cache_reset", 0) == resets_before + 1
    assert window._text_cache_generation == generation_before + 1
    assert ("hello", 10.0, "NewFont") in window._text_cache
    assert window._text_block_cache == {}


def test_text_cache_invalidated_on_ratio_change(app) -> None:  # noqa: ARG001 - fixture required
    window = _DummyWindow()
    OverlayWindow._measure_text(window, "hello", 10.0, None)
    resets_before = window._measure_stats.get("cache_reset", 0)
    generation_before = window._text_cache_generation
    window.set_ratio(1.25)

    OverlayWindow._measure_text(window, "hello", 10.0, None)

    assert window._measure_stats.get("cache_reset", 0) == resets_before + 1
    assert window._text_cache_generation == generation_before + 1
    assert ("hello", 10.0, "TestFont") in window._text_cache
    assert window._measure_stats.get("cache_miss", 0) >= 1


def test_text_cache_invalidated_on_fallback_change(app) -> None:  # noqa: ARG001 - fixture required
    window = _DummyWindow(fallbacks=("EmojiA",))
    OverlayWindow._measure_text(window, "hello", 10.0, None)
    window._font_fallbacks = ("EmojiB",)
    resets_before = window._measure_stats.get("cache_reset", 0)
    generation_before = window._text_cache_generation

    OverlayWindow._measure_text(window, "hello", 10.0, None)

    assert window._measure_stats.get("cache_reset", 0) == resets_before + 1
    assert window._text_cache_generation == generation_before + 1
