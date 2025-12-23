"""Helpers for applying global payload opacity to colors."""
from __future__ import annotations

from typing import Any

from PyQt6.QtGui import QColor


def coerce_percent(value: Any, default: int = 100) -> int:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return default
    numeric = int(round(numeric))
    if numeric < 0:
        return 0
    if numeric > 100:
        return 100
    return numeric


def alpha_percent_from_qcolor(color: QColor) -> int:
    try:
        alpha = int(color.alpha())
    except Exception:
        return 100
    alpha = max(0, min(alpha, 255))
    return int(round((alpha / 255.0) * 100))


def effective_alpha_percent(base_percent: int, global_percent: int) -> int:
    base_percent = coerce_percent(base_percent, 100)
    global_percent = coerce_percent(global_percent, 100)
    if global_percent >= 100:
        return base_percent
    return max(0, base_percent + global_percent - 100)


def apply_global_payload_opacity(color: QColor, global_percent: Any) -> QColor:
    if not color.isValid():
        return color
    global_percent = coerce_percent(global_percent, 100)
    if global_percent >= 100:
        return color
    base_percent = alpha_percent_from_qcolor(color)
    effective_percent = effective_alpha_percent(base_percent, global_percent)
    new_alpha = int(round(255 * (effective_percent / 100.0)))
    if new_alpha == color.alpha():
        return color
    return QColor(color.red(), color.green(), color.blue(), new_alpha)
