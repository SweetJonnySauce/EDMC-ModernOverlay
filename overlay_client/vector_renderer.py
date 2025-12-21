from __future__ import annotations

from typing import Any, Callable, List, Mapping, Optional


class VectorPainterAdapter:
    def set_pen(self, color: str, *, width: Optional[int] = None) -> None: ...
    def draw_line(self, x1: int, y1: int, x2: int, y2: int) -> None: ...
    def draw_circle_marker(self, x: int, y: int, radius: int, color: str) -> None: ...
    def draw_cross_marker(self, x: int, y: int, size: int, color: str) -> None: ...
    def draw_text(self, x: int, y: int, text: str, color: str) -> None: ...


def render_vector(
    adapter: VectorPainterAdapter,
    payload: Mapping[str, Any],
    scale_x: float,
    scale_y: float,
    *,
    offset_x: float = 0.0,
    offset_y: float = 0.0,
    trace: Optional[Callable[[str, Mapping[str, Any]], None]] = None,
) -> None:
    base_color = str(payload.get("base_color") or "white")
    points: List[Mapping[str, Any]] = list(payload.get("points") or [])
    if len(points) < 2:
        return

    def scaled(point: Mapping[str, Any]) -> tuple[int, int]:
        x = int(round(float(point.get("x", 0)) * scale_x + offset_x))
        y = int(round(float(point.get("y", 0)) * scale_y + offset_y))
        return x, y

    scaled_points = [scaled(point) for point in points]
    if trace:
        trace(
            "render_vector:scaled_points",
            {
                "scaled_points": scaled_points,
                "scale_x": scale_x,
                "scale_y": scale_y,
                "offset_x": offset_x,
                "offset_y": offset_y,
            },
        )

    for idx in range(len(points) - 1):
        adapter.set_pen(base_color)
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
