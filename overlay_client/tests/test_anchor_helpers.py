from __future__ import annotations

from overlay_client.anchor_helpers import (
    CommandContext,
    build_baseline_bounds,
    compute_justification_offsets,
)
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


def test_build_baseline_bounds_prefers_base():
    base = {("plugin", "suf"): (0.0, 0.0, 10.0, 5.0)}
    overlay = {("plugin", "suf"): (1.0, 1.0, 11.0, 6.0)}

    result = build_baseline_bounds(base, overlay)

    assert result[("plugin", "suf")] == (0.0, 0.0, 10.0, 5.0)


def test_build_baseline_bounds_falls_back_to_overlay():
    base = {}
    overlay = {("plugin", "suf"): (2.0, 2.0, 12.0, 7.0)}

    result = build_baseline_bounds(base, overlay)

    assert result[("plugin", "suf")] == (2.0, 2.0, 12.0, 7.0)


def test_mixed_widths_with_baseline_and_fallback():
    key = ("plugin", "suffix")
    transform_by_group = {key: GroupTransform(bounds_min_x=0.0, payload_justification="center")}
    base_overlay_bounds = {key: (0.0, 0.0, 200.0, 10.0)}
    overlay_bounds = {key: (0.0, 0.0, 100.0, 10.0)}
    commands = [
        CommandContext(
            identifier=1,
            key=key,
            bounds=(0.0, 0.0, 100.0, 10.0),
            raw_min_x=None,
            right_just_multiplier=0,
            justification="center",
            suffix="s",
            plugin="plugin",
            item_id="id1",
        ),
        CommandContext(
            identifier=2,
            key=key,
            bounds=(0.0, 0.0, 50.0, 10.0),
            raw_min_x=None,
            right_just_multiplier=0,
            justification="center",
            suffix="s",
            plugin="plugin",
            item_id="id2",
        ),
    ]
    baseline = build_baseline_bounds(base_overlay_bounds, overlay_bounds)

    offsets = compute_justification_offsets(
        commands,
        transform_by_group,
        baseline,
        base_scale=1.0,
        trace_fn=None,
    )

    # Baseline comes from base bounds (width 200); offsets are (200-100)/2 and (200-50)/2.
    assert offsets[1] == 50.0
    assert offsets[2] == 75.0


def test_right_justification_offsets_wider_than_baseline():
    key = ("plugin", "suffix")
    command = CommandContext(
        identifier=5,
        key=key,
        bounds=(0.0, 0.0, 120.0, 10.0),  # width > baseline
        raw_min_x=10.0,
        right_just_multiplier=1,
        justification="right",
        suffix="suffix",
        plugin="plugin",
        item_id="id5",
    )
    transform_by_group = {key: GroupTransform(bounds_min_x=0.0, payload_justification="right")}
    base_overlay_bounds = {key: (0.0, 0.0, 100.0, 10.0)}  # baseline width 100

    offsets = compute_justification_offsets(
        [command],
        transform_by_group,
        base_overlay_bounds,
        base_scale=1.0,
        trace_fn=None,
    )

    # delta = 100 - 120 = -20; minus right-just delta of 10 = -30px shift (moves left).
    assert offsets[5] == -30.0


def test_center_justification_offsets_wider_than_baseline():
    key = ("plugin", "suffix")
    command = CommandContext(
        identifier=6,
        key=key,
        bounds=(0.0, 0.0, 120.0, 10.0),  # width > baseline
        raw_min_x=None,
        right_just_multiplier=0,
        justification="center",
        suffix="suffix",
        plugin="plugin",
        item_id="id6",
    )
    base_overlay_bounds = {key: (0.0, 0.0, 100.0, 10.0)}  # baseline width 100

    offsets = compute_justification_offsets(
        [command],
        {key: None},
        base_overlay_bounds,
        base_scale=1.0,
        trace_fn=None,
    )

    # delta = (100 - 120)/2 = -10px shift (moves left).
    assert offsets[6] == -10.0
