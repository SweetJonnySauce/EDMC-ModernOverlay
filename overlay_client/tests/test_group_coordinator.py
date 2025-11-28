from __future__ import annotations

from overlay_client.group_coordinator import GroupCoordinator, ScreenBounds


class _StubOverrideManager:
    def __init__(self, mapping):
        self._mapping = mapping

    def grouping_key_for(self, plugin_name, item_id):
        value = self._mapping.get(item_id)
        if isinstance(value, Exception):
            raise value
        return value


class _StubCache:
    def __init__(self):
        self.calls = []

    def update_group(self, plugin, suffix, normalized, transformed):
        self.calls.append((plugin, suffix, normalized, transformed))


def test_resolve_group_key_uses_override_and_fallbacks():
    overrides = _StubOverrideManager(
        {
            "item-override": ("override_plugin", "suffix-1"),
            "blank-plugin": ("", "suffix-2"),
        }
    )
    coordinator = GroupCoordinator()

    override_key = coordinator.resolve_group_key("item-override", "base_plugin", overrides)
    assert override_key.as_tuple() == ("override_plugin", "suffix-1")

    fallback_to_plugin = coordinator.resolve_group_key("blank-plugin", "base_plugin", overrides)
    assert fallback_to_plugin.as_tuple() == ("base_plugin", "suffix-2")

    default_key = coordinator.resolve_group_key("plain", "plugin-name", None)
    assert default_key.as_tuple() == ("plugin-name", "item:plain")

    unknown_key = coordinator.resolve_group_key("", None, None)
    assert unknown_key.as_tuple() == ("unknown", None)


def test_update_cache_normalizes_payloads():
    cache = _StubCache()
    coordinator = GroupCoordinator(cache=cache)
    key = ("plugin", "sfx")
    base_payloads = {
        key: {
            "plugin": " plugin ",
            "suffix": " sfx ",
            "min_x": "1.2349",
            "min_y": -2,
            "width": 3.3339,
            "height": 4.0,
            "max_x": float("nan"),
            "max_y": 6.7891,
            "has_transformed": True,
            "offset_x": 1.2222,
            "offset_y": "3.4567",
        }
    }
    transform_payloads = {
        key: {
            "min_x": -5.4444,
            "min_y": 8.8888,
            "width": 9.9,
            "height": "10.1111",
            "max_x": 12.3456,
            "max_y": "14.9999",
            "anchor": "NE",
            "justification": "Right",
            "nudge_dx": "2",
            "nudge_dy": 0.6,
            "nudged": 1,
            "offset_dx": 0.4444,
            "offset_dy": "0.6666",
        }
    }

    coordinator.update_cache_from_payloads(base_payloads, transform_payloads)

    assert len(cache.calls) == 1
    plugin_label, suffix_label, normalized, transformed = cache.calls[0]
    assert plugin_label == "plugin"
    # Suffix is passed through (no trim) to mirror current behavior.
    assert suffix_label == " sfx "
    assert normalized == {
        "base_min_x": 1.235,
        "base_min_y": -2.0,
        "base_width": 3.334,
        "base_height": 4.0,
        "base_max_x": 0.0,
        "base_max_y": 6.789,
        "has_transformed": True,
        "offset_x": 1.222,
        "offset_y": 3.457,
    }
    assert transformed == {
        "trans_min_x": -5.444,
        "trans_min_y": 8.889,
        "trans_width": 9.9,
        "trans_height": 10.111,
        "trans_max_x": 12.346,
        "trans_max_y": 15.0,
        "anchor": "ne",
        "justification": "right",
        "nudge_dx": 2,
        "nudge_dy": 0,
        "nudged": True,
        "offset_dx": 0.444,
        "offset_dy": 0.667,
    }


def test_compute_group_nudges_respects_enable_and_gutter():
    bounds_map = {
        ("plugin", "a"): ScreenBounds(min_x=-20.0, max_x=30.0, min_y=10.0, max_y=90.0),
        ("plugin", "b"): ScreenBounds(min_x=10.0, max_x=20.0, min_y=10.0, max_y=20.0),
    }
    coordinator = GroupCoordinator()

    translations = coordinator.compute_group_nudges(bounds_map, 100, 100, enabled=True, gutter=10)
    assert translations == {("plugin", "a"): (30, 0)}

    disabled = coordinator.compute_group_nudges(bounds_map, 100, 100, enabled=False, gutter=10)
    assert disabled == {}


def test_update_cache_ignores_missing_transform_payload():
    cache = _StubCache()
    coordinator = GroupCoordinator(cache=cache)
    key = ("p", None)
    base_payloads = {key: {"plugin": "p", "suffix": None, "has_transformed": True}}
    transform_payloads = {}

    coordinator.update_cache_from_payloads(base_payloads, transform_payloads)

    assert len(cache.calls) == 1
    plugin_label, suffix_label, normalized, transformed = cache.calls[0]
    assert plugin_label == "p"
    assert suffix_label is None
    assert normalized["has_transformed"] is True
    assert transformed is None


def test_compute_group_nudges_skips_invalid_bounds_and_handles_vertical_overflow():
    bounds_map = {
        ("plug", "good"): ScreenBounds(min_x=10.0, max_x=20.0, min_y=-50.0, max_y=-10.0),
        ("plug", "invalid"): ScreenBounds(min_x=5.0, max_x=1.0, min_y=0.0, max_y=0.0),
    }
    coordinator = GroupCoordinator()

    translations = coordinator.compute_group_nudges(bounds_map, window_width=40, window_height=40, enabled=True, gutter=5)
    assert translations == {("plug", "good"): (0, 50)}


def test_resolve_group_key_falls_back_on_override_error():
    overrides = _StubOverrideManager({"boom": RuntimeError("fail")})
    coordinator = GroupCoordinator()

    key = coordinator.resolve_group_key("boom", "base_plugin", overrides)
    assert key.as_tuple() == ("base_plugin", "item:boom")
