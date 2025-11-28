from __future__ import annotations

from overlay_client.anchor_helpers import CommandContext, compute_justification_offsets
from overlay_client.group_transform import GroupTransform


def test_vector_right_justification_uses_multiplier():
    key = ("plugin", "suffix")
    transform = GroupTransform(bounds_min_x=0.0, payload_justification="right")
    base_bounds = {key: (0.0, 0.0, 100.0, 10.0)}
    commands = [
        CommandContext(
            identifier=1,
            key=key,
            bounds=(0.0, 0.0, 50.0, 10.0),
            raw_min_x=10.0,
            right_just_multiplier=2,
            justification="right",
            suffix="suffix",
            plugin="plugin",
            item_id="v1",
        )
    ]

    offsets = compute_justification_offsets(
        commands,
        {key: transform},
        base_bounds,
        base_scale=1.0,
        trace_fn=None,
    )

    expected = (100.0 - 50.0) - (10.0 * 2)
    assert offsets[1] == expected
