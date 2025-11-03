#!/usr/bin/env python3
"""Render vector shapes from the EDR docking log on screen."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, List, Mapping, Optional

from PyQt6.QtCore import Qt, QPoint
from PyQt6.QtGui import QColor, QBrush, QFont, QPainter, QPen
from PyQt6.QtWidgets import QApplication, QWidget

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CLIENT_DIR = PROJECT_ROOT / "overlay-client"

if str(CLIENT_DIR) not in sys.path:
    sys.path.insert(0, str(CLIENT_DIR))

from vector_renderer import VectorPainterAdapter, render_vector  # noqa: E402

DEFAULT_WINDOW_WIDTH = 1280
DEFAULT_WINDOW_HEIGHT = 1024


@dataclass
class DockingVector:
    """Normalised vector payload extracted from the docking log."""

    ident: str
    base_color: str
    points: List[Mapping[str, Any]]

    def as_payload(self) -> Mapping[str, Any]:
        return {
            "base_color": self.base_color,
            "points": self.points,
        }


@dataclass
class DockingRect:
    """Rectangular shape payload."""

    ident: str
    border_color: str
    fill_color: Optional[str]
    x: float
    y: float
    w: float
    h: float


Shape = DockingVector | DockingRect


def _extract_json_segment(line: str) -> Optional[Mapping[str, Any]]:
    start = line.find("{")
    if start == -1:
        return None
    fragment = line[start:]
    try:
        decoded = json.loads(fragment)
    except json.JSONDecodeError:
        return None
    return decoded if isinstance(decoded, Mapping) else None


def _normalise_vector(record: Mapping[str, Any]) -> Optional[DockingVector]:
    payload = record.get("raw")
    if not isinstance(payload, Mapping):
        payload = record
    shape = payload.get("shape") or payload.get("type")
    if not isinstance(shape, str) or shape.lower() != "vect":
        return None
    vector = payload.get("vector")
    if not isinstance(vector, list) or len(vector) < 2:
        return None
    normalised_points: List[Mapping[str, Any]] = []
    for entry in vector:
        if not isinstance(entry, Mapping):
            continue
        try:
            float(entry.get("x", 0.0))
            float(entry.get("y", 0.0))
        except (TypeError, ValueError):
            continue
        normalised_points.append(dict(entry))
    if len(normalised_points) < 2:
        return None
    ident = str(payload.get("id") or record.get("id") or f"vector-{len(normalised_points)}")
    base_color = str(payload.get("color") or record.get("color") or "white")
    return DockingVector(ident=ident, base_color=base_color, points=normalised_points)


def _normalise_rect(record: Mapping[str, Any]) -> Optional[DockingRect]:
    payload = record.get("raw")
    if not isinstance(payload, Mapping):
        payload = record
    shape = payload.get("shape") or payload.get("type")
    if not isinstance(shape, str) or shape.lower() != "rect":
        return None
    try:
        x_val = float(payload.get("x", 0.0))
        y_val = float(payload.get("y", 0.0))
        w_val = float(payload.get("w", 0.0))
        h_val = float(payload.get("h", 0.0))
    except (TypeError, ValueError):
        return None
    if w_val <= 0.0 or h_val <= 0.0:
        return None
    ident = str(payload.get("id") or record.get("id") or f"rect-{x_val}-{y_val}")
    border = str(payload.get("color") or record.get("color") or "white")
    fill = payload.get("fill")
    if isinstance(fill, str) and fill.strip():
        fill_color = fill
    else:
        fill_color = None
    return DockingRect(
        ident=ident,
        border_color=border,
        fill_color=fill_color,
        x=x_val,
        y=y_val,
        w=w_val,
        h=h_val,
    )


def load_shapes(log_path: Path) -> List[Shape]:
    shapes: List[Shape] = []
    with log_path.open(encoding="utf-8") as handle:
        for raw_line in handle:
            record = _extract_json_segment(raw_line)
            if not record:
                continue
            rect = _normalise_rect(record)
            if rect:
                shapes.append(rect)
                continue
            vector = _normalise_vector(record)
            if vector:
                shapes.append(vector)
    return shapes


class _VectorPainterAdapter(VectorPainterAdapter):
    """Bridge ``render_vector`` calls to a ``QPainter`` instance."""

    def __init__(self, painter: QPainter, font_family: str = "Segoe UI") -> None:
        self._painter = painter
        self._font_family = font_family

    def set_pen(self, color: str, *, width: int = 2) -> None:
        q_color = QColor(color)
        if not q_color.isValid():
            q_color = QColor("white")
        pen = QPen(q_color)
        pen.setWidth(width)
        self._painter.setPen(pen)
        self._painter.setBrush(Qt.BrushStyle.NoBrush)

    def draw_line(self, x1: int, y1: int, x2: int, y2: int) -> None:
        self._painter.drawLine(x1, y1, x2, y2)

    def draw_circle_marker(self, x: int, y: int, radius: int, color: str) -> None:
        q_color = QColor(color)
        if not q_color.isValid():
            q_color = QColor("white")
        pen = QPen(q_color)
        pen.setWidth(2)
        self._painter.setPen(pen)
        self._painter.setBrush(QBrush(q_color))
        self._painter.drawEllipse(QPoint(x, y), radius, radius)

    def draw_cross_marker(self, x: int, y: int, size: int, color: str) -> None:
        self.set_pen(color, width=2)
        self._painter.drawLine(x - size, y - size, x + size, y + size)
        self._painter.drawLine(x - size, y + size, x + size, y - size)

    def draw_text(self, x: int, y: int, text: str, color: str) -> None:
        q_color = QColor(color)
        if not q_color.isValid():
            q_color = QColor("white")
        pen = QPen(q_color)
        self._painter.setPen(pen)
        font = QFont(self._font_family, 10)
        font.setWeight(QFont.Weight.Normal)
        self._painter.setFont(font)
        self._painter.drawText(x, y, text)


class ShapeCanvas(QWidget):
    """Simple widget that paints shape payloads in overlay coordinates."""

    def __init__(
        self,
        shapes: Iterable[Shape],
        *,
        width: int = DEFAULT_WINDOW_WIDTH,
        height: int = DEFAULT_WINDOW_HEIGHT,
    ) -> None:
        super().__init__()
        self._shapes = list(shapes)
        self._width = width
        self._height = height
        self.setWindowTitle("EDR Docking Shapes")
        self.resize(width, height)
        self._background = QColor(8, 12, 18)
        self._grid_pen = QPen(QColor(50, 60, 75, 120))
        self._grid_pen.setWidth(1)

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.fillRect(self.rect(), self._background)
        self._paint_grid(painter)

        adapter = _VectorPainterAdapter(painter)
        for shape in self._shapes:
            if isinstance(shape, DockingRect):
                self._paint_rect(painter, shape)
            elif isinstance(shape, DockingVector):
                payload = shape.as_payload()
                render_vector(
                    adapter,
                    payload,
                    scale_x=1.0,
                    scale_y=1.0,
                    offset_x=0.0,
                    offset_y=0.0,
                )
        painter.end()
        super().paintEvent(event)

    def _paint_rect(self, painter: QPainter, rect: DockingRect) -> None:
        if rect.fill_color:
            fill_color = QColor(rect.fill_color)
            if not fill_color.isValid():
                fill_color = QColor("transparent")
            brush = QBrush(fill_color)
        else:
            brush = Qt.BrushStyle.NoBrush
        border_color = QColor(rect.border_color)
        if not border_color.isValid():
            border_color = QColor("white")
        pen = QPen(border_color)
        pen.setWidth(2)
        painter.setPen(pen)
        if isinstance(brush, QBrush):
            painter.setBrush(brush)
        else:
            painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(int(rect.x), int(rect.y), int(rect.w), int(rect.h))

    def _paint_grid(self, painter: QPainter) -> None:
        painter.save()
        painter.setPen(self._grid_pen)
        step = 100
        for x in range(0, self._width + 1, step):
            painter.drawLine(x, 0, x, self._height)
        for y in range(0, self._height + 1, step):
            painter.drawLine(0, y, self._width, y)
        painter.restore()


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--log",
        action="append",
        type=Path,
        dest="log_files",
        help="Log file containing vector payloads; may be supplied multiple times.",
    )
    parser.add_argument(
        "positional_logs",
        nargs="*",
        type=Path,
        help="Optional positional log files containing vector payloads.",
    )
    parser.add_argument("--width", type=int, default=DEFAULT_WINDOW_WIDTH, help="Output window width in pixels.")
    parser.add_argument("--height", type=int, default=DEFAULT_WINDOW_HEIGHT, help="Output window height in pixels.")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_argument_parser()
    args = parser.parse_args(argv)
    configured_logs = list(args.log_files or [])
    configured_logs.extend(args.positional_logs)
    if not configured_logs:
        configured_logs.append(PROJECT_ROOT / "tests" / "edr-docking.log")

    missing = [path for path in configured_logs if not path.exists()]
    if missing:
        parser.error("Log file(s) not found: {}".format(", ".join(str(path) for path in missing)))

    shapes: List[Shape] = []
    for log_path in configured_logs:
        shapes.extend(load_shapes(log_path))

    if not shapes:
        parser.error("No vector or rect payloads found in the provided log file(s).")

    app = QApplication(sys.argv[:1])
    canvas = ShapeCanvas(shapes, width=args.width, height=args.height)
    canvas.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
