from __future__ import annotations

from overlay_client.anchor_helpers import CommandContext, compute_justification_offsets
from overlay_client.group_transform import GroupTransform


def test_compute_justification_offsets_applies_right_delta_per_command():
    key = ("plugin", "suffix")
    command = CommandContext(
        identifier=1,
        key=key,
        bounds=(0.0, 0.0, 50.0, 10.0),
        raw_min_x=10.0,
        right_just_multiplier=1,
        justification="right",
        suffix="suffix",
        plugin="plugin",
        item_id="id1",
    )
    transform_by_group = {key: GroupTransform(bounds_min_x=0.0, payload_justification="right")}
    base_overlay_bounds = {key: (0.0, 0.0, 100.0, 10.0)}

    offsets = compute_justification_offsets(
        [command],
        transform_by_group,
        base_overlay_bounds,
        base_scale=1.0,
        trace_fn=None,
    )

    assert offsets[1] == 40.0


def test_center_justification_uses_scaled_baseline():
    key = ("plugin", "suffix")
    command = CommandContext(
        identifier=2,
        key=key,
        bounds=(0.0, 0.0, 120.0, 10.0),
        raw_min_x=None,
        right_just_multiplier=0,
        justification="center",
        suffix="suffix",
        plugin="plugin",
        item_id="id2",
    )
    base_overlay_bounds = {key: (0.0, 0.0, 100.0, 10.0)}

    offsets = compute_justification_offsets(
        [command],
        {key: None},
        base_overlay_bounds,
        base_scale=2.0,
        trace_fn=None,
    )

    # Baseline is scaled width (200); delta is (200-120)/2 = 40.
    assert offsets[2] == 40.0


def test_left_justification_produces_no_offset():
    key = ("plugin", "suffix")
    command = CommandContext(
        identifier=3,
        key=key,
        bounds=(0.0, 0.0, 80.0, 10.0),
        raw_min_x=None,
        right_just_multiplier=0,
        justification="left",
        suffix="suffix",
        plugin="plugin",
        item_id="id3",
    )
    base_overlay_bounds = {key: (0.0, 0.0, 120.0, 10.0)}

    offsets = compute_justification_offsets(
        [command],
        {key: None},
        base_overlay_bounds,
        base_scale=1.5,
        trace_fn=None,
    )

    assert offsets == {}


def test_trace_emits_when_baseline_missing():
    key = ("plugin", "suffix")
    command = CommandContext(
        identifier=4,
        key=key,
        bounds=(0.0, 0.0, 50.0, 10.0),
        raw_min_x=None,
        right_just_multiplier=0,
        justification="center",
        suffix="suffix",
        plugin="plugin",
        item_id="id4",
    )
    traces = []

    def _trace(plugin: str, item_id: str, stage: str, details: dict) -> None:
        traces.append((plugin, item_id, stage, details))

    offsets = compute_justification_offsets(
        [command],
        {key: None},
        base_overlay_bounds={},
        base_scale=1.0,
        trace_fn=_trace,
    )

    assert offsets == {}
    assert any(stage == "justify:baseline_missing" for _, _, stage, _ in traces)
