from pathlib import Path

import pytest

from overlay_client import fonts


@pytest.fixture
def tmp_fonts_dir(tmp_path, monkeypatch):
    module_path = tmp_path / "module.py"
    module_path.write_text("# dummy module")
    fonts_dir = tmp_path / "fonts"
    fonts_dir.mkdir()
    monkeypatch.setattr(fonts, "__file__", str(module_path))
    return fonts_dir


def test_resolve_font_family_prefers_preferred_file(tmp_fonts_dir, monkeypatch):
    font_file = tmp_fonts_dir / "CustomFont.ttf"
    font_file.write_text("fake-font-bytes")
    (tmp_fonts_dir / "preferred_fonts.txt").write_text("CustomFont.ttf\n")

    class StubQFontDatabase:
        @staticmethod
        def addApplicationFont(path: str) -> int:
            return 1 if Path(path) == font_file else -1

        @staticmethod
        def applicationFontFamilies(font_id: int):
            return ["CustomFamily"] if font_id == 1 else []

        @staticmethod
        def families():
            return []

    monkeypatch.setattr(fonts, "QFontDatabase", StubQFontDatabase)

    window = type("W", (), {})()
    result = fonts._resolve_font_family(window)  # type: ignore[arg-type]
    assert result == "CustomFamily"


def test_resolve_emoji_font_families_reads_marker(tmp_fonts_dir, monkeypatch):
    emoji_file = tmp_fonts_dir / "emoji_fallbacks.txt"
    emoji_file.write_text("EmojiOne.otf\nMissingFont\n")
    bundled_font = tmp_fonts_dir / "EmojiOne.otf"
    bundled_font.write_text("fake-emoji-font")

    added = {}

    class StubQFontDatabase:
        @staticmethod
        def addApplicationFont(path: str) -> int:
            added[path] = added.get(path, 0) + 1
            return 2

        @staticmethod
        def applicationFontFamilies(font_id: int):
            return ["EmojiFamily"] if font_id == 2 else []

        @staticmethod
        def families():
            return ["Primary"]

    monkeypatch.setattr(fonts, "QFontDatabase", StubQFontDatabase)

    window = type("W", (), {"_font_family": "Primary"})()
    fallbacks = fonts._resolve_emoji_font_families(window)  # type: ignore[arg-type]

    assert ("EmojiFamily" in fallbacks)
    assert str(bundled_font) in added
