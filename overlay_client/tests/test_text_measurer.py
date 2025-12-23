from __future__ import annotations

from overlay_client.overlay_client import _MeasuredText, OverlayWindow


def test_injected_text_measurer_used_without_qt() -> None:
    called = []

    def fake_measurer(text: str, point_size: float, font_family: str) -> _MeasuredText:
        called.append((text, point_size, font_family))
        return _MeasuredText(width=123, ascent=7, descent=3)

    class Dummy:
        pass

    window = Dummy()
    window._text_measurer = fake_measurer  # type: ignore[attr-defined]
    window._font_family = "TestFont"  # type: ignore[attr-defined]
    window._apply_font_fallbacks = lambda *args, **kwargs: None  # type: ignore[attr-defined]

    width, ascent, descent = OverlayWindow._measure_text(window, "hello", 9.5, None)

    assert called == [("hello", 9.5, "TestFont")]
    assert width == 123
    assert ascent == 7
    assert descent == 3


def test_measure_text_multiline_uses_line_spacing() -> None:
    class Dummy:
        pass

    window = Dummy()
    window._text_measurer = lambda text, point_size, font_family: _MeasuredText(
        width=len(text) * 5,
        ascent=6,
        descent=4,
    )  # type: ignore[attr-defined]
    window._text_cache = None  # type: ignore[attr-defined]
    window._measure_stats = {}  # type: ignore[attr-defined]
    window._font_family = "TestFont"  # type: ignore[attr-defined]
    window._apply_font_fallbacks = lambda *args, **kwargs: None  # type: ignore[attr-defined]

    text = "aa\nbbb"
    width, ascent, descent = OverlayWindow._measure_text(window, text, 10.0, None)
    assert width == 15
    assert ascent == 6
    assert descent == 14
