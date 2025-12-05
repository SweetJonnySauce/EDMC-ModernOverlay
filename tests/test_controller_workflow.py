from __future__ import annotations

from tests.controller_workflow import validate_cache_consistency


def _cache_entry(offset_dx: float, offset_dy: float, *, delta: float = 0.0):
    return {
        "base": {
            "base_min_x": 100.0,
            "base_min_y": 200.0,
            "base_max_x": 150.0,
            "base_max_y": 260.0,
        },
        "transformed": {
            "trans_min_x": 100.0 + offset_dx + delta,
            "trans_min_y": 200.0 + offset_dy,
            "trans_max_x": 150.0 + offset_dx + delta,
            "trans_max_y": 260.0 + offset_dy,
            "offset_dx": offset_dx,
            "offset_dy": offset_dy,
        },
    }


def test_validate_cache_consistency_accepts_matching_offsets():
    payload = {
        "groups": {
            "Plugin": {
                "Group": _cache_entry(15.0, -10.0),
            }
        }
    }
    assert validate_cache_consistency(payload) == []


def test_validate_cache_consistency_flags_mismatch():
    payload = {
        "groups": {
            "Plugin": {
                "Group": _cache_entry(5.0, 5.0, delta=2.0),
            }
        }
    }
    issues = validate_cache_consistency(payload, tolerance=0.5)
    assert issues
    assert issues[0]["plugin"] == "Plugin"
    assert issues[0]["group"] == "Group"
