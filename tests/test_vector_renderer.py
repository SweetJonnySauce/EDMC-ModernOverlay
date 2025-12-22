from __future__ import annotations

from typing import List, Tuple

import importlib.util
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT_DIR / "overlay_client" / "vector_renderer.py"
spec = importlib.util.spec_from_file_location("vector_renderer_test", MODULE_PATH)
assert spec and spec.loader
vector_renderer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vector_renderer)

VectorPainterAdapter = vector_renderer.VectorPainterAdapter
render_vector = vector_renderer.render_vector


class FakeAdapter(VectorPainterAdapter):
    def __init__(self, *, text_height: int = 10) -> None:
        self.operations: List[Tuple[str, Tuple]] = []
        self._current_pen: Tuple[str, int] | None = None
        self._text_height = text_height

    def set_pen(self, color: str, *, width: int = 2) -> None:
        self._current_pen = (color, width)
        self.operations.append(("pen", (color, width)))

    def draw_line(self, x1: int, y1: int, x2: int, y2: int) -> None:
        self.operations.append(("line", (x1, y1, x2, y2, self._current_pen)))

    def draw_circle_marker(self, x: int, y: int, radius: int, color: str) -> None:
        self.operations.append(("circle", (x, y, radius, color)))

    def draw_cross_marker(self, x: int, y: int, size: int, color: str) -> None:
        self.operations.append(("cross", (x, y, size, color)))

    def draw_text(self, x: int, y: int, text: str, color: str) -> None:
        self.operations.append(("text", (x, y, text, color)))

    def measure_text_block(self, text: str) -> tuple[int, int]:
        width = len(text) * 6
        return width, self._text_height


def test_render_vector_generates_lines_and_markers():
    adapter = FakeAdapter()
    data = {
        "base_color": "#ffffff",
        "points": [
            {"x": 0, "y": 0},
            {"x": 10, "y": 0, "color": "red"},
            {"x": 10, "y": 10, "marker": "circle", "text": "Target"},
            {"x": 5, "y": 15, "marker": "cross", "color": "green"},
        ],
    }
    render_vector(adapter, data, scale_x=2.0, scale_y=1.0)

    ops = [op for op, _ in adapter.operations if op == "line"]
    assert len(ops) == 3

    # First line should end at scaled (20,0)
    first_line = next(val for op, val in adapter.operations if op == "line")
    assert first_line[:4] == (0, 0, 20, 0)

    # Final operations should include circle marker and text
    assert any(op == "circle" for op, _ in adapter.operations)
    assert any(op == "text" for op, _ in adapter.operations)
    assert any(op == "cross" for op, _ in adapter.operations)


def test_render_vector_lines_use_base_color_markers_use_point_color():
    adapter = FakeAdapter()
    data = {
        "base_color": "#ffffff",
        "points": [
            {"x": 0, "y": 0},
            {"x": 10, "y": 0, "color": "red"},
            {"x": 10, "y": 10, "marker": "circle", "text": "Target", "color": "green"},
        ],
    }
    render_vector(adapter, data, scale_x=1.0, scale_y=1.0)

    line_ops = [val for op, val in adapter.operations if op == "line"]
    assert len(line_ops) == 2
    for _, _, _, _, pen in line_ops:
        assert pen is not None
        assert pen[0] == "#ffffff"

    circle = next(val for op, val in adapter.operations if op == "circle")
    assert circle[3] == "green"
    text = next(val for op, val in adapter.operations if op == "text")
    assert text[3] == "green"


def test_render_vector_text_positions_follow_marker_label_position():
    data = {
        "base_color": "#ffffff",
        "points": [
            {"x": 0, "y": 50, "text": "Label"},
            {"x": 10, "y": 50},
        ],
    }
    adapter_below = FakeAdapter(text_height=10)
    render_vector(adapter_below, data, scale_x=1.0, scale_y=1.0, marker_label_position="below")
    text_below = next(val for op, val in adapter_below.operations if op == "text")
    assert text_below[1] == 57

    adapter_above = FakeAdapter(text_height=10)
    render_vector(adapter_above, data, scale_x=1.0, scale_y=1.0, marker_label_position="above")
    text_above = next(val for op, val in adapter_above.operations if op == "text")
    assert text_above[1] == 33

    adapter_centered = FakeAdapter(text_height=10)
    render_vector(adapter_centered, data, scale_x=1.0, scale_y=1.0, marker_label_position="centered")
    text_centered = next(val for op, val in adapter_centered.operations if op == "text")
    assert text_centered[1] == 45


def test_render_vector_text_position_defaults_to_below():
    data = {
        "base_color": "#ffffff",
        "points": [
            {"x": 0, "y": 20, "text": "Label"},
            {"x": 10, "y": 20},
        ],
    }
    adapter = FakeAdapter(text_height=10)
    render_vector(adapter, data, scale_x=1.0, scale_y=1.0, marker_label_position="invalid")
    text = next(val for op, val in adapter.operations if op == "text")
    assert text[1] == 27


def test_render_vector_multiline_text_uses_block_height_for_position():
    class MultiLineAdapter(FakeAdapter):
        def __init__(self, *, line_spacing: int = 12) -> None:
            super().__init__(text_height=line_spacing)
            self._line_spacing = line_spacing

        def measure_text_block(self, text: str) -> tuple[int, int]:
            normalised = str(text).replace("\r\n", "\n").replace("\r", "\n")
            lines = normalised.split("\n") or [""]
            width = max(len(line) for line in lines) * 6
            return width, self._line_spacing * len(lines)

    data = {
        "base_color": "#ffffff",
        "points": [
            {"x": 0, "y": 50, "text": "Line1\nLine2"},
            {"x": 10, "y": 50},
        ],
    }
    adapter = MultiLineAdapter(line_spacing=12)
    render_vector(adapter, data, scale_x=1.0, scale_y=1.0, marker_label_position="above")
    text = next(val for op, val in adapter.operations if op == "text")
    assert text[1] == 19
    assert text[2] == "Line1\nLine2"
