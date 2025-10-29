from __future__ import annotations

from typing import Any, Dict, List, Mapping


class VectorPainterAdapter:
    def set_pen(self, color: str, *, width: int = 2) -> None: ...
    def draw_line(self, x1: int, y1: int, x2: int, y2: int) -> None: ...
    def draw_circle_marker(self, x: int, y: int, radius: int, color: str) -> None: ...
    def draw_cross_marker(self, x: int, y: int, size: int, color: str) -> None: ...
    def draw_text(self, x: int, y: int, text: str, color: str) -> None: ...


def render_vector(
    adapter: VectorPainterAdapter,
    payload: Mapping[str, Any],
    scale_x: float,
    scale_y: float,
) -> None:
    base_color = str(payload.get("base_color") or "white")
    points: List[Mapping[str, Any]] = list(payload.get("points") or [])
    if len(points) < 2:
        return

    def scaled(point: Mapping[str, Any]) -> tuple[int, int]:
        x = int(round(float(point.get("x", 0)) * scale_x))
        y = int(round(float(point.get("y", 0)) * scale_y))
        return x, y

    scaled_points = [scaled(point) for point in points]

    for idx in range(len(points) - 1):
        color = points[idx + 1].get("color") or points[idx].get("color") or base_color
        adapter.set_pen(str(color))
        x1, y1 = scaled_points[idx]
        x2, y2 = scaled_points[idx + 1]
        adapter.draw_line(x1, y1, x2, y2)

    for idx, point in enumerate(points):
        marker = (point.get("marker") or "").lower()
        color = str(point.get("color") or base_color)
        x, y = scaled_points[idx]
        if marker == "circle":
            adapter.draw_circle_marker(x, y, radius=6, color=color)
        elif marker == "cross":
            adapter.draw_cross_marker(x, y, size=6, color=color)

        text = point.get("text")
        if text:
            adapter.draw_text(x + 8, y - 8, str(text), color)
