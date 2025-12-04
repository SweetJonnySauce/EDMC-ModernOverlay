from types import SimpleNamespace

import overlay_client.render_surface as rs
from overlay_client.viewport_helper import ViewportTransform, ScaleMode


class _PainterStub:
    def __init__(self):
        self.draws = []

    def setBrush(self, *_args, **_kwargs):
        pass

    def setPen(self, *_args, **_kwargs):
        pass

    def drawRect(self, rect):
        self.draws.append(("rect", rect.x(), rect.y(), rect.width(), rect.height()))

    def drawEllipse(self, point, rx, ry):
        self.draws.append(("ellipse", point.x(), point.y(), rx, ry))


def _make_mapper(scale: float = 1.0):
    vt = ViewportTransform(
        mode=ScaleMode.FIT, scale=scale, offset=(0.0, 0.0), scaled_size=(1280.0, 960.0), overflow_x=False, overflow_y=False
    )
    return rs.LegacyMapper(scale_x=scale, scale_y=scale, offset_x=0.0, offset_y=0.0, transform=vt)


def _make_fill_mapper(overflow_y: bool = False):
    vt = ViewportTransform(
        mode=ScaleMode.FILL, scale=1.0, offset=(0.0, 0.0), scaled_size=(1280.0, 960.0), overflow_x=False, overflow_y=overflow_y
    )
    return rs.LegacyMapper(scale_x=1.0, scale_y=1.0, offset_x=0.0, offset_y=0.0, transform=vt)


def test_target_box_draws_only_for_active_group_when_active_mode():
    window = SimpleNamespace()
    window._controller_active_group = ("PluginA", "Group1")
    window.controller_mode_state = lambda: "active"
    bounds = rs._OverlayBounds(min_x=10, min_y=20, max_x=30, max_y=40)
    window._last_overlay_bounds_for_target = {("PluginA", "Group1"): bounds}
    window._last_transform_by_group = {("PluginA", "Group1"): SimpleNamespace(anchor_token="nw")}
    window._resolve_bounds_for_active_group = lambda ag, bm: bm.get(ag)
    window._fallback_bounds_from_cache = lambda ag, mapper=None, anchor_override=None: (None, None)
    window._line_width = lambda key: 1
    window._compute_legacy_mapper = lambda: _make_mapper(1.0)
    window._overlay_bounds_to_rect = lambda b, m: rs.QRect(int(b.min_x), int(b.min_y), int(b.max_x - b.min_x), int(b.max_y - b.min_y))
    window._overlay_point_to_screen = lambda pt, m: (int(pt[0]), int(pt[1]))
    window._anchor_from_overlay_bounds = lambda bounds, token: (bounds.min_x, bounds.min_y)
    window._anchor_from_overlay_bounds = lambda bounds, token: (bounds.min_x, bounds.min_y)

    painter = _PainterStub()
    rs.RenderSurfaceMixin._paint_controller_target_box(window, painter)  # type: ignore[misc]

    # One rect + one ellipse
    assert any(draw[0] == "rect" for draw in painter.draws)
    assert any(draw[0] == "ellipse" for draw in painter.draws)

    # Inactive mode -> no draw
    painter.draws.clear()
    window.controller_mode_state = lambda: "inactive"
    rs.RenderSurfaceMixin._paint_controller_target_box(window, painter)  # type: ignore[misc]
    assert painter.draws == []

    # Different active group -> no draw
    painter.draws.clear()
    window.controller_mode_state = lambda: "active"
    window._controller_active_group = ("PluginA", "Other")
    rs.RenderSurfaceMixin._paint_controller_target_box(window, painter)  # type: ignore[misc]
    assert painter.draws == []


def test_target_box_uses_base_bounds_when_no_transform(tmp_path=None):
    window = SimpleNamespace()
    window._controller_active_group = ("PluginB", "G1")
    window.controller_mode_state = lambda: "active"
    window._last_overlay_bounds_for_target = {}
    window._last_transform_by_group = {}
    window._resolve_bounds_for_active_group = lambda ag, bm: bm.get(ag)
    window._fallback_bounds_from_cache = lambda ag, mapper=None, anchor_override=None: rs.RenderSurfaceMixin._fallback_bounds_from_cache(window, ag, mapper, anchor_override=anchor_override)  # type: ignore[misc]
    window._line_width = lambda key: 1
    window._compute_legacy_mapper = lambda: _make_mapper(1.0)
    window._overlay_bounds_to_rect = lambda b, m: rs.QRect(int(b.min_x), int(b.min_y), int(b.max_x - b.min_x), int(b.max_y - b.min_y))
    window._overlay_point_to_screen = lambda pt, m: (int(pt[0]), int(pt[1]))
    window._overlay_bounds_from_cache_entry = lambda entry: rs.RenderSurfaceMixin._overlay_bounds_from_cache_entry(entry)
    window._build_bounds_with_anchor = lambda w, h, token, ax, ay: rs._OverlayBounds(min_x=ax, min_y=ay, max_x=ax + w, max_y=ay + h)
    window._anchor_from_overlay_bounds = lambda bounds, token: (bounds.min_x, bounds.min_y)
    cache_entry = {
        "base": {
            "base_min_x": 920.0,
            "base_min_y": 330.0,
            "base_max_x": 1070.0,
            "base_max_y": 380.0,
            "base_width": 150.0,
            "base_height": 50.0,
        },
        "transformed": None,
    }
    cache = SimpleNamespace(
        get_group=lambda plugin, suffix: cache_entry if (plugin, suffix) == ("PluginB", "G1") else None,
        _state={"groups": {"PluginB": {"G1": cache_entry}}},
    )
    window._group_cache = cache
    painter = _PainterStub()
    rs.RenderSurfaceMixin._paint_controller_target_box(window, painter)  # type: ignore[misc]
    # Expect rect at base_min_x/y (no reset to origin)
    rects = [d for d in painter.draws if d[0] == "rect"]
    assert rects
    rect = rects[0]
    assert rect[1] == 920
    assert rect[2] == 330


def test_target_box_uses_cache_fallback_and_anchor():
    window = SimpleNamespace()
    window._controller_active_group = ("PluginB", "G1")
    window._controller_active_anchor = None
    window.controller_mode_state = lambda: "active"
    window._last_overlay_bounds_for_target = {}
    window._last_transform_by_group = {}
    window._resolve_bounds_for_active_group = lambda ag, bm: bm.get(ag)
    window._fallback_bounds_from_cache = lambda ag, mapper=None, anchor_override=None: rs.RenderSurfaceMixin._fallback_bounds_from_cache(window, ag, mapper, anchor_override=anchor_override)  # type: ignore[misc]
    window._line_width = lambda key: 1
    window._compute_legacy_mapper = lambda: _make_mapper(1.0)
    window._overlay_bounds_to_rect = lambda b, m: rs.QRect(int(b.min_x), int(b.min_y), int(b.max_x - b.min_x), int(b.max_y - b.min_y))
    window._overlay_point_to_screen = lambda pt, m: (int(pt[0]), int(pt[1]))
    window._overlay_bounds_from_cache_entry = lambda entry: rs.RenderSurfaceMixin._overlay_bounds_from_cache_entry(entry)
    window._build_bounds_with_anchor = lambda w, h, token, ax, ay: rs._OverlayBounds(min_x=ax, min_y=ay, max_x=ax + w, max_y=ay + h)
    window._anchor_from_overlay_bounds = lambda bounds, token: (bounds.min_x, bounds.min_y)
    cache_entry = {
        "base": {"base_min_x": 0, "base_min_y": 0, "base_max_x": 10, "base_max_y": 10, "base_width": 10, "base_height": 10},
        "transformed": None,
    }
    cache = SimpleNamespace(
        get_group=lambda plugin, suffix: cache_entry if (plugin, suffix) == ("PluginB", "G1") else None,
        _state={"groups": {"PluginB": {"G1": cache_entry}}},
    )
    window._group_cache = cache
    painter = _PainterStub()
    rs.RenderSurfaceMixin._paint_controller_target_box(window, painter)  # type: ignore[misc]
    assert any(draw[0] == "rect" for draw in painter.draws)


def test_target_box_fallback_uses_anchor_override():
    window = SimpleNamespace()
    window._controller_active_group = ("PluginB", "G1")
    window._controller_active_anchor = "ne"
    window.controller_mode_state = lambda: "active"
    window._last_overlay_bounds_for_target = {}
    window._last_transform_by_group = {}
    window._resolve_bounds_for_active_group = lambda ag, bm: bm.get(ag)
    window._fallback_bounds_from_cache = lambda ag, mapper=None, anchor_override=None: rs.RenderSurfaceMixin._fallback_bounds_from_cache(window, ag, mapper, anchor_override=anchor_override)  # type: ignore[misc]
    window._line_width = lambda key: 1
    window._compute_legacy_mapper = lambda: _make_mapper(1.0)
    window._overlay_bounds_to_rect = lambda b, m: rs.QRect(int(b.min_x), int(b.min_y), int(b.max_x - b.min_x), int(b.max_y - b.min_y))
    window._overlay_point_to_screen = lambda pt, m: (int(pt[0]), int(pt[1]))
    window._overlay_bounds_from_cache_entry = lambda entry: rs.RenderSurfaceMixin._overlay_bounds_from_cache_entry(entry)
    window._build_bounds_with_anchor = lambda w, h, token, ax, ay: rs._OverlayBounds(min_x=ax, min_y=ay, max_x=ax + w, max_y=ay + h)

    def _anchor_from_overlay_bounds(bounds, token):
        if token == "ne":
            return (bounds.max_x, bounds.min_y)
        return (bounds.min_x, bounds.min_y)

    window._anchor_from_overlay_bounds = _anchor_from_overlay_bounds
    cache_entry = {
        "base": {"base_min_x": 0, "base_min_y": 0, "base_max_x": 10, "base_max_y": 10, "base_width": 10, "base_height": 10},
        "transformed": None,
    }
    cache = SimpleNamespace(
        get_group=lambda plugin, suffix: cache_entry if (plugin, suffix) == ("PluginB", "G1") else None,
        _state={"groups": {"PluginB": {"G1": cache_entry}}},
    )
    window._group_cache = cache
    painter = _PainterStub()
    rs.RenderSurfaceMixin._paint_controller_target_box(window, painter)  # type: ignore[misc]
    ellipses = [d for d in painter.draws if d[0] == "ellipse"]
    rects = [d for d in painter.draws if d[0] == "rect"]
    assert ellipses and rects
    # Anchor override should place dot at max_x/min_y = (10, 0).
    assert ellipses[0][1] == 10
    assert ellipses[0][2] == 0
    # And the rect should shift left so its max_x aligns with anchor (min_x == 0 here, width preserved).
    rect = rects[0]
    assert rect[1] == 0
    assert rect[2] == 0


def test_target_box_cache_fallback_applies_fill_translation():
    window = SimpleNamespace()
    window._controller_active_group = ("PluginB", "G1")
    window.controller_mode_state = lambda: "active"
    window._last_overlay_bounds_for_target = {}
    window._last_transform_by_group = {}
    window._resolve_bounds_for_active_group = lambda ag, bm: bm.get(ag)
    window._line_width = lambda key: 1
    window._compute_legacy_mapper = lambda: _make_fill_mapper(overflow_y=True)
    window._overlay_bounds_to_rect = lambda b, m: rs.QRect(int(b.min_x), int(b.min_y), int(b.max_x - b.min_x), int(b.max_y - b.min_y))
    window._overlay_point_to_screen = lambda pt, m: (int(pt[0]), int(pt[1]))
    window._overlay_bounds_from_cache_entry = lambda entry: rs.RenderSurfaceMixin._overlay_bounds_from_cache_entry(entry)
    window._build_bounds_with_anchor = lambda w, h, token, ax, ay: rs._OverlayBounds(min_x=ax, min_y=ay, max_x=ax + w, max_y=ay + h)
    window._anchor_from_overlay_bounds = lambda bounds, token: (bounds.min_x, bounds.min_y)
    window._viewport_state = lambda: rs.ViewportState(width=1280.0, height=480.0, device_ratio=1.0)
    cache_entry = {
        "base": {
            "base_min_x": 100.0,
            "base_min_y": 100.0,
            "base_max_x": 200.0,
            "base_max_y": 200.0,
            "base_width": 100.0,
            "base_height": 100.0,
        },
        "transformed": None,
    }
    cache = SimpleNamespace(
        get_group=lambda plugin, suffix: cache_entry if (plugin, suffix) == ("PluginB", "G1") else None,
        _state={"groups": {"PluginB": {"G1": cache_entry}}},
    )
    window._group_cache = cache
    painter = _PainterStub()
    rs.RenderSurfaceMixin._paint_controller_target_box(window, painter)  # type: ignore[misc]

    rects = [d for d in painter.draws if d[0] == "rect"]
    assert rects
    rect = rects[0]
    # Expect Y translated upwards from base_min_y=100 due to Fill overflow (scaled to y=50).
    assert rect[2] == 50
