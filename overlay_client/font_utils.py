from __future__ import annotations

import logging
from typing import Sequence

from PyQt6.QtGui import QFont

_LOGGER = logging.getLogger("EDMC.ModernOverlay.Fonts")


def apply_font_fallbacks(font: QFont, fallback_families: Sequence[str] | None) -> None:
    """Attach fallback families to a QFont so emoji glyphs can be resolved."""
    if font is None or not fallback_families:
        return

    families: list[str] = []
    seen: set[str] = set()

    primary = font.family()
    if primary:
        families.append(primary)
        seen.add(primary.casefold())

    for fallback in fallback_families:
        name = (fallback or "").strip()
        if not name:
            continue
        lowered = name.casefold()
        if lowered in seen:
            continue
        seen.add(lowered)
        families.append(name)

    if len(families) <= 1:
        return

    set_families = getattr(font, "setFamilies", None)
    if callable(set_families):
        try:
            set_families(families)
        except Exception as exc:  # pragma: no cover - defensive guard
            _LOGGER.warning("Failed to set composite font families: %s", exc)
        return

    fallback_only = families[1:]
    set_fallback = getattr(font, "setFallbackFamilies", None)
    if callable(set_fallback) and fallback_only:
        try:
            set_fallback(fallback_only)
        except Exception as exc:  # pragma: no cover - defensive guard
            _LOGGER.warning("Failed to set fallback font families: %s", exc)
