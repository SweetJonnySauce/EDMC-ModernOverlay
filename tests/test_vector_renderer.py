from __future__ import annotations

from typing import List, Tuple

import importlib.util
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT_DIR / "overlay-client" / "vector_renderer.py"
spec = importlib.util.spec_from_file_location("vector_renderer_test", MODULE_PATH)
assert spec and spec.loader
vector_renderer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vector_renderer)

VectorPainterAdapter = vector_renderer.VectorPainterAdapter
render_vector = vector_renderer.render_vector


class FakeAdapter(VectorPainterAdapter):
    def __init__(self) -> None:
        self.operations: List[Tuple[str, Tuple]] = []
        self._current_pen: Tuple[str, int] | None = None

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
