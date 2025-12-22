import math
from typing import Any, Optional, Tuple

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor

from overlay_client.group_transform import GroupKey
from overlay_client.legacy_store import LegacyItem
from overlay_client.render_surface import RenderSurfaceMixin, _MeasuredText


class _StubMode:
    value = "fit"


class _StubTransform:
    def __init__(self) -> None:
        self.scale = 1.0
        self.scaled_size = (1.0, 1.0)
        self.mode = _StubMode()
        self.overflow_x = False
        self.overflow_y = False


class _StubMapper:
    def __init__(self, scale_x: float = 1.0, scale_y: float = 1.0) -> None:
        self.scale_x = scale_x
        self.scale_y = scale_y
        self.offset_x = 0.0
        self.offset_y = 0.0
        self.transform = _StubTransform()


class _StubSurface(RenderSurfaceMixin):
    def __init__(self) -> None:
        # Only initialise members touched by the tested helpers.
        self._line_widths = {}
        self._line_width_defaults = {}
        self._text_cache = {}
        self._text_block_cache = {}
        self._text_cache_generation = 0
        self._text_cache_context: Optional[Tuple[str, Tuple[str, ...], float]] = None
        self._font_fallbacks: Tuple[str, ...] = ()
        self._font_family = "Test"
        self._measure_stats: dict[str, Any] = {}
        self._text_measurer = None
        self._dev_mode_enabled = False
        self._debug_message_point_size = 0.0
        self._last_logged_scale = None
        self._font_scale_diag = 0.0

    def devicePixelRatioF(self) -> float:
        return 2.0

    def _compute_legacy_mapper(self) -> _StubMapper:
        return _StubMapper()

    def _update_message_font(self) -> None:
        return None

    def _current_physical_size(self) -> Tuple[float, float]:
        return (100.0, 50.0)

    def format_scale_debug(self) -> str:
        return "scale-debug"


class _StubFill:
    def __init__(self, scale: float = 1.0) -> None:
        self.scale = scale

    def screen_x(self, value: float) -> float:
        return value

    def screen_y(self, value: float) -> float:
        return value


class _StubGroupContext:
    def __init__(self) -> None:
        self.fill = _StubFill()
        self.transform_context = None
        self.scale = 1.0
        self.selected_anchor = None
        self.base_anchor_point = None
        self.anchor_for_transform = None
        self.base_translation_dx = 0.0
        self.base_translation_dy = 0.0


class _StubMapper:
    pass


class _RectSurface(_StubSurface):
    def __init__(self) -> None:
        super().__init__()
        self._line_width_defaults = {"legacy_rect": 2}

    def _line_width(self, key: str) -> int:
        return self._line_widths.get(key) or self._line_width_defaults.get(key, 1)

    def _viewport_state(self) -> object:
        return object()

    def _group_offsets(self, group_transform) -> Tuple[float, float]:  # noqa: ANN001
        return (0.0, 0.0)

    def _group_anchor_point(self, *args, **kwargs):  # noqa: ANN002, ANN003
        return None

    def _group_base_point(self, *args, **kwargs):  # noqa: ANN002, ANN003
        return None

    def _should_trace_payload(self, plugin_name: Optional[str], item_id: str) -> bool:
        return False

    def _compute_rect_transform(self, *args, **kwargs):  # noqa: ANN002, ANN003
        return ([(0.0, 0.0), (2.0, 0.0), (0.0, 1.0), (2.0, 1.0)], [], None, None)


def test_line_width_respects_override_defaults() -> None:
    surface = _StubSurface()
    surface._line_width_defaults = {"custom": 7}
    assert surface._line_width("custom") == 7
    surface._line_widths["custom"] = 3
    assert surface._line_width("custom") == 3


def test_update_auto_legacy_scale_uses_overlay_module_scale_fn(monkeypatch: pytest.MonkeyPatch) -> None:
    import overlay_client.overlay_client as overlay_module

    calls: list[Tuple[float, float]] = []

    def fake_scale_fn(mapper: _StubMapper, state: Any) -> Tuple[float, float]:
        calls.append((mapper.scale_x, mapper.scale_y))
        return 0.5, 0.25

    monkeypatch.setattr(overlay_module, "legacy_scale_components", fake_scale_fn, raising=False)

    surface = _StubSurface()
    mapper = _StubMapper(scale_x=1.5, scale_y=2.0)
    surface._compute_legacy_mapper = lambda: mapper  # type: ignore[assignment]
    surface._update_auto_legacy_scale(100, 50)

    assert calls == [(1.5, 2.0)]
    expected_diag = math.sqrt((0.5 * 0.5 + 0.25 * 0.25) / 2.0)
    assert math.isclose(surface._font_scale_diag, expected_diag, rel_tol=1e-6)
    assert surface._last_logged_scale is not None


def test_measure_text_uses_injected_measurer_and_resets_context() -> None:
    surface = _StubSurface()
    surface._text_cache = {"placeholder": (1, 2, 3)}
    surface._text_block_cache = {"placeholder": (4, 5)}

    surface._ensure_text_cache_context("TestFamily")

    assert surface._text_cache == {}
    assert surface._text_block_cache == {}
    assert surface._text_cache_generation == 1
    assert surface._text_cache_context == ("TestFamily", (), 2.0)

    measurer_calls: list[Tuple[str, float, str]] = []

    def measurer(text: str, point_size: float, family: str) -> _MeasuredText:
        measurer_calls.append((text, point_size, family))
        return _MeasuredText(width=10, ascent=2, descent=1)

    surface._text_measurer = measurer
    measured = surface._measure_text("hello", 12.0, "TestFamily")

    assert measured == (10, 2, 1)
    assert measurer_calls == [("hello", 12.0, "TestFamily")]


def test_qcolor_from_background_parses_rgba() -> None:
    color = RenderSurfaceMixin._qcolor_from_background("#11223344")
    assert isinstance(color, QColor)
    assert (color.red(), color.green(), color.blue(), color.alpha()) == (0x11, 0x22, 0x33, 0x44)


def _build_rect_command(surface: _RectSurface, border_spec: str, *, fill_spec: str = "#112233"):
    legacy_item = LegacyItem(
        item_id="rect-1",
        kind="rect",
        data={"color": border_spec, "fill": fill_spec, "x": 1.0, "y": 2.0, "w": 3.0, "h": 4.0},
        plugin="plugin",
    )
    return surface._build_rect_command(legacy_item, _StubMapper(), GroupKey("plugin"), None, None)


@pytest.mark.parametrize("border_spec", ["", "none", "dd5500,"])
def test_rect_command_invalid_border_color_skips_pen(monkeypatch: pytest.MonkeyPatch, border_spec: str) -> None:
    surface = _RectSurface()
    monkeypatch.setattr(
        "overlay_client.render_surface.build_group_context",
        lambda *args, **kwargs: _StubGroupContext(),
    )

    cmd = _build_rect_command(surface, border_spec)

    assert cmd is not None
    assert cmd.pen.style() == Qt.PenStyle.NoPen
    assert cmd.brush.color().name() == QColor("#112233").name()


def test_rect_command_valid_border_color_uses_pen(monkeypatch: pytest.MonkeyPatch) -> None:
    surface = _RectSurface()
    monkeypatch.setattr(
        "overlay_client.render_surface.build_group_context",
        lambda *args, **kwargs: _StubGroupContext(),
    )

    cmd = _build_rect_command(surface, "#ff00ff")

    assert cmd is not None
    assert cmd.pen.style() == Qt.PenStyle.SolidLine
    assert cmd.pen.color().name() == QColor("#ff00ff").name()
    assert cmd.pen.width() == surface._line_width("legacy_rect")
