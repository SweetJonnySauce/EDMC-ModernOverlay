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
