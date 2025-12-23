from PyQt6.QtGui import QColor

from overlay_client.opacity_utils import (
    alpha_percent_from_qcolor,
    apply_global_payload_opacity,
    coerce_percent,
    effective_alpha_percent,
)


def test_coerce_percent_clamps_and_rounds():
    assert coerce_percent(50) == 50
    assert coerce_percent(100.4) == 100
    assert coerce_percent(-5) == 0
    assert coerce_percent(150) == 100
    assert coerce_percent("75") == 75


def test_alpha_percent_from_qcolor():
    color = QColor(10, 20, 30, 128)
    assert alpha_percent_from_qcolor(color) == 50


def test_effective_alpha_percent_reduces_by_global_delta():
    assert effective_alpha_percent(100, 80) == 80
    assert effective_alpha_percent(60, 80) == 40
    assert effective_alpha_percent(20, 70) == 0
    assert effective_alpha_percent(50, 100) == 50


def test_apply_global_payload_opacity_preserves_when_full():
    color = QColor(10, 20, 30, 200)
    updated = apply_global_payload_opacity(color, 100)
    assert updated.alpha() == 200


def test_apply_global_payload_opacity_reduces_alpha():
    base = QColor(10, 20, 30, 255)
    updated = apply_global_payload_opacity(base, 80)
    assert updated.alpha() == 204

    base = QColor(10, 20, 30, 128)
    updated = apply_global_payload_opacity(base, 80)
    assert updated.alpha() == 76

    base = QColor(10, 20, 30, 51)
    updated = apply_global_payload_opacity(base, 70)
    assert updated.alpha() == 0
