from __future__ import annotations

import sys
from pathlib import Path

import pytest

OVERLAY_ROOT = Path(__file__).resolve().parents[1]
if str(OVERLAY_ROOT) not in sys.path:
    sys.path.append(str(OVERLAY_ROOT))

from payload_transform import _measure_text_block  # noqa: E402

pytestmark = pytest.mark.pyqt_required


class _FakeMetrics:
    def __init__(self, advance_per_char: int = 5, line_spacing: int = 12) -> None:
        self._advance = advance_per_char
        self._line_spacing = line_spacing

    def horizontalAdvance(self, text: str) -> int:  # noqa: N802
        return self._advance * len(text)

    def lineSpacing(self) -> int:  # noqa: N802
        return self._line_spacing

    def height(self) -> int:
        return self._line_spacing


def test_measure_text_block_single_line() -> None:
    metrics = _FakeMetrics(advance_per_char=7, line_spacing=14)
    width, height = _measure_text_block(metrics, "abc")

    assert width == 21
    assert height == 14


def test_measure_text_block_multi_line_picks_longest_line() -> None:
    metrics = _FakeMetrics(advance_per_char=4, line_spacing=10)
    width, height = _measure_text_block(metrics, "ab\nabcd\nx")

    assert width == 16  # longest line "abcd"
    assert height == 30  # 3 lines * 10 spacing


def test_measure_text_block_normalises_windows_line_endings() -> None:
    metrics = _FakeMetrics(advance_per_char=3, line_spacing=8)
    width, height = _measure_text_block(metrics, "aa\r\nbbb\rccc")

    assert width == 9  # "bbb" is widest
    assert height == 24  # 3 lines * 8
