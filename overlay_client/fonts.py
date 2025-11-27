"""Font resolution helpers for the overlay client."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Optional, Tuple

from PyQt6.QtGui import QFont, QFontDatabase

from overlay_client.font_utils import apply_font_fallbacks  # type: ignore

if TYPE_CHECKING:
    from overlay_client.overlay_client import OverlayWindow  # type: ignore

_LOGGER_NAME = "EDMC.ModernOverlay.Client"
_CLIENT_LOGGER = logging.getLogger(_LOGGER_NAME)


def _resolve_font_family(window: "OverlayWindow") -> str:
    fonts_dir = Path(__file__).resolve().parent / "fonts"
    default_family = "Segoe UI"

    def try_font_file(font_path: Path, label: str) -> Optional[str]:
        if not font_path.exists():
            return None
        try:
            font_id = QFontDatabase.addApplicationFont(str(font_path))
        except Exception as exc:
            _CLIENT_LOGGER.warning("Failed to load %s font from %s: %s", label, font_path, exc)
            return None
        if font_id == -1:
            _CLIENT_LOGGER.warning("%s font file at %s could not be registered; falling back", label, font_path)
            return None
        families = QFontDatabase.applicationFontFamilies(font_id)
        if families:
            family = families[0]
            _CLIENT_LOGGER.debug("Using %s font family '%s' from %s", label, family, font_path)
            return family
        _CLIENT_LOGGER.warning("%s font registered but no families reported; falling back", label)
        return None

    def find_font_case_insensitive(filename: str) -> Optional[Path]:
        if not filename:
            return None
        target = filename.lower()
        if not fonts_dir.exists():
            return None
        for child in fonts_dir.iterdir():
            if child.is_file() and child.name.lower() == target:
                return child
        return None

    preferred_marker = fonts_dir / "preferred_fonts.txt"
    preferred_files: list[Path] = []
    if preferred_marker.exists():
        try:
            for raw_line in preferred_marker.read_text(encoding="utf-8").splitlines():
                candidate_name = raw_line.strip()
                if not candidate_name or candidate_name.startswith(("#", ";")):
                    continue
                candidate_path = find_font_case_insensitive(candidate_name)
                if candidate_path:
                    preferred_files.append(candidate_path)
                else:
                    _CLIENT_LOGGER.warning(
                        "Preferred font '%s' listed in %s but not found", candidate_name, preferred_marker
                    )
        except Exception as exc:
            _CLIENT_LOGGER.warning("Failed to read preferred fonts list at %s: %s", preferred_marker, exc)

    standard_candidates = [
        ("SourceSans3-Regular.ttf", "Source Sans 3"),
        ("Eurocaps.ttf", "Eurocaps"),
    ]

    candidate_paths: list[Tuple[Path, str]] = []
    seen: set[Path] = set()

    def add_candidate(path: Optional[Path], label: str) -> None:
        if not path:
            return
        try:
            resolved = path.resolve()
        except Exception:
            resolved = path
        if resolved in seen:
            return
        seen.add(resolved)
        candidate_paths.append((path, label))

    for preferred_path in preferred_files:
        add_candidate(preferred_path, f"Preferred font '{preferred_path.name}'")

    for filename, label in standard_candidates:
        add_candidate(find_font_case_insensitive(filename), label)

    for path, label in candidate_paths:
        family = try_font_file(path, label)
        if family:
            return family

    installed_candidates = [
        "Source Sans 3",
        "SourceSans3",
        "Source Sans",
        "Source Sans 3 Regular",
        "Eurocaps",
        "Euro Caps",
        "EUROCAPS",
    ]
    try:
        available = set(QFontDatabase.families())
    except Exception as exc:
        _CLIENT_LOGGER.warning("Could not enumerate installed fonts: %s", exc)
        available = set()
    for candidate in installed_candidates:
        if candidate in available:
            _CLIENT_LOGGER.debug("Using installed font family '%s'", candidate)
            return candidate

    _CLIENT_LOGGER.warning("Preferred fonts unavailable; falling back to %s", default_family)
    return default_family


def _resolve_emoji_font_families(window: "OverlayWindow") -> Tuple[str, ...]:
    fonts_dir = Path(__file__).resolve().parent / "fonts"

    def find_font_case_insensitive(filename: str) -> Optional[Path]:
        if not filename:
            return None
        target = filename.lower()
        if not fonts_dir.exists():
            return None
        for child in fonts_dir.iterdir():
            if child.is_file() and child.name.lower() == target:
                return child
        return None

    try:
        available_lookup = {name.casefold(): name for name in QFontDatabase.families()}
    except Exception as exc:
        _CLIENT_LOGGER.warning("Could not enumerate installed fonts for emoji fallbacks: %s", exc)
        available_lookup = {}

    fallback_families: list[str] = []
    seen: set[str] = set()
    base_family = (window._font_family or "").strip()
    if base_family:
        seen.add(base_family.casefold())

    def add_family(name: Optional[str]) -> None:
        if not name:
            return
        lowered = name.casefold()
        if lowered in seen:
            return
        seen.add(lowered)
        fallback_families.append(name)

    def register_font_file(path: Optional[Path], label: str) -> None:
        if not path:
            return
        try:
            font_id = QFontDatabase.addApplicationFont(str(path))
        except Exception as exc:
            _CLIENT_LOGGER.warning("Failed to load %s font from %s: %s", label, path, exc)
            return
        if font_id == -1:
            _CLIENT_LOGGER.warning("%s font file at %s could not be registered; skipping", label, path)
            return
        families = QFontDatabase.applicationFontFamilies(font_id)
        if not families:
            _CLIENT_LOGGER.warning("%s font registered but reported no families; skipping", label)
            return
        for family in families:
            available_lookup[family.casefold()] = family
            add_family(family)

    def add_if_available(candidate: str, *, warn: bool = False) -> None:
        resolved = available_lookup.get(candidate.casefold())
        if resolved:
            add_family(resolved)
        elif warn:
            _CLIENT_LOGGER.warning("Emoji fallback '%s' listed in emoji_fallbacks.txt but not installed", candidate)

    fallback_marker = fonts_dir / "emoji_fallbacks.txt"
    if fallback_marker.exists():
        try:
            for raw_line in fallback_marker.read_text(encoding="utf-8").splitlines():
                candidate = raw_line.strip()
                if not candidate or candidate.startswith(("#", ";")):
                    continue
                path = find_font_case_insensitive(candidate)
                if path:
                    register_font_file(path, f"emoji fallback '{path.name}'")
                else:
                    add_if_available(candidate, warn=True)
        except Exception as exc:
            _CLIENT_LOGGER.warning("Failed to read emoji fallback list at %s: %s", fallback_marker, exc)

    bundled_candidates = [
        "unifont-17.0.03.otf",
    ]
    for filename in bundled_candidates:
        register_font_file(find_font_case_insensitive(filename), f"emoji fallback '{filename}'")

    if fallback_families:
        _CLIENT_LOGGER.debug("Emoji fallbacks enabled: %s", ", ".join(fallback_families))
    else:
        _CLIENT_LOGGER.debug("No emoji fallback fonts discovered; %s will be used alone", window._font_family)
    return tuple(fallback_families)


def _apply_font_fallbacks(window: "OverlayWindow", font: QFont) -> None:
    apply_font_fallbacks(font, getattr(window, "_font_fallbacks", ()))
