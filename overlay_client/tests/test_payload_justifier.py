from __future__ import annotations

# ruff: noqa: E402

import sys
from pathlib import Path

OVERLAY_ROOT = Path(__file__).resolve().parents[1]
if str(OVERLAY_ROOT) not in sys.path:
    sys.path.append(str(OVERLAY_ROOT))

from overlay_client.payload_justifier import JustificationRequest, calculate_offsets


def _request(identifier: str, width: float, justification: str = "right", suffix: str = "group"):
    return JustificationRequest(
        identifier=identifier,
        key=("Example", suffix),
        suffix=suffix,
        justification=justification,
        width=width,
    )


def test_right_alignment_shifts_all_but_widest() -> None:
    offsets = calculate_offsets(
        [
            _request("a", 40.0, justification="right"),
            _request("b", 10.0, justification="right"),
        ]
    )
    assert offsets["b"] == 30.0
    assert "a" not in offsets


def test_center_alignment_uses_half_difference() -> None:
    offsets = calculate_offsets(
        [
            _request("a", 100.0, justification="center"),
            _request("b", 60.0, justification="center"),
        ]
    )
    assert offsets["b"] == 20.0


def test_no_suffix_does_not_align() -> None:
    offsets = calculate_offsets(
        [
            JustificationRequest(
                identifier="a",
                key=("Example", None),
                suffix=None,
                justification="right",
                width=25.0,
            )
        ]
    )
    assert offsets == {}


def test_single_payload_needs_no_offset() -> None:
    offsets = calculate_offsets([_request("solo", 80.0, justification="right")])
    assert offsets == {}


def test_right_justification_delta_negative_or_nan_returns_zero() -> None:
    from overlay_client.anchor_helpers import _right_justification_delta
    from overlay_client.group_transform import GroupTransform

    transform = GroupTransform(bounds_min_x=10.0, payload_justification="right")
    assert _right_justification_delta(transform, 10.0) == 0.0
    assert _right_justification_delta(transform, float("nan")) == 0.0
    transform.payload_justification = "left"
    assert _right_justification_delta(transform, 12.0) == 0.0
