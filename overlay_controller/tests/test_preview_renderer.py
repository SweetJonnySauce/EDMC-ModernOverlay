from types import SimpleNamespace

from overlay_controller.preview.renderer import PreviewRenderer


class StubCanvas:
    def __init__(self, width=320, height=240) -> None:
        self._width = width
        self._height = height
        self.calls = []

    def winfo_width(self):
        return self._width

    def winfo_height(self):
        return self._height

    def __getitem__(self, key):
        if key == "width":
            return self._width
        if key == "height":
            return self._height
        raise KeyError(key)

    def create_rectangle(self, *args, **kwargs):
        self.calls.append(("rect", args, kwargs))

    def create_text(self, *args, **kwargs):
        self.calls.append(("text", args, kwargs))

    def create_oval(self, *args, **kwargs):
        self.calls.append(("oval", args, kwargs))

    def delete(self, *args, **kwargs):
        self.calls.append(("delete", args, kwargs))


def make_snapshot() -> SimpleNamespace:
    bounds = (0.0, 0.0, 100.0, 50.0)
    return SimpleNamespace(
        plugin="P",
        label="L",
        anchor_token="nw",
        transform_anchor_token="nw",
        offset_x=0.0,
        offset_y=0.0,
        base_bounds=bounds,
        base_anchor=(0.0, 0.0),
        transform_bounds=bounds,
        transform_anchor=(0.0, 0.0),
        has_transform=True,
        cache_timestamp=0.0,
    )


def test_renderer_draws_snapshot_once_with_signature_cache():
    canvas = StubCanvas()
    renderer = PreviewRenderer(canvas, padding=10, abs_width=100.0, abs_height=50.0)
    snapshot = make_snapshot()

    renderer.draw(
        ("P", "L"),
        snapshot,
        live_anchor_token="nw",
        scale_mode_value="fill",
        resolve_target_frame=lambda snap: (snap.transform_bounds, snap.transform_anchor),
        compute_anchor_point=lambda a, b, c, d, e: (0.0, 0.0),
    )
    first_calls = list(canvas.calls)
    assert first_calls, "Expected draw calls"

    # Second draw with same signature should no-op.
    renderer.draw(
        ("P", "L"),
        snapshot,
        live_anchor_token="nw",
        scale_mode_value="fill",
        resolve_target_frame=lambda snap: (snap.transform_bounds, snap.transform_anchor),
        compute_anchor_point=lambda a, b, c, d, e: (0.0, 0.0),
    )
    assert canvas.calls == first_calls


def test_renderer_handles_missing_selection_and_snapshot():
    canvas = StubCanvas()
    renderer = PreviewRenderer(canvas)

    renderer.draw(
        None,
        None,
        live_anchor_token=None,
        scale_mode_value="fill",
        resolve_target_frame=lambda snap: None,
        compute_anchor_point=lambda a, b, c, d, e: (0.0, 0.0),
    )
    assert any(call[0] == "text" and "(select a group)" in call[2].get("text", "") for call in canvas.calls)

    canvas.calls.clear()
    renderer.draw(
        ("P", "L"),
        None,
        live_anchor_token=None,
        scale_mode_value="fill",
        resolve_target_frame=lambda snap: None,
        compute_anchor_point=lambda a, b, c, d, e: (0.0, 0.0),
    )
    assert any(call[0] == "text" and "(awaiting cache)" in call[2].get("text", "") for call in canvas.calls)
