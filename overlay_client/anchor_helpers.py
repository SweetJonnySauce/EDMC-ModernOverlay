"""Shared justification helpers for overlay payloads (pure, no Qt)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, Mapping, Optional, Sequence, Tuple

from overlay_client.group_transform import GroupTransform  # type: ignore
from overlay_client.payload_justifier import JustificationRequest, calculate_offsets  # type: ignore

GroupKeyTuple = Tuple[str, Optional[str]]


@dataclass(frozen=True)
class CommandContext:
    identifier: int
    key: GroupKeyTuple
    bounds: Tuple[float, float, float, float]
    raw_min_x: Optional[float]
    right_just_multiplier: int
    justification: str
    suffix: Optional[str]
    plugin: Optional[str]
    item_id: str


def compute_justification_offsets(
    commands: Sequence[CommandContext],
    transform_by_group: Mapping[GroupKeyTuple, Optional[GroupTransform]],
    base_overlay_bounds: Mapping[GroupKeyTuple, Tuple[float, float, float, float]],
    base_scale: float,
    trace_fn: Optional[Callable[[Optional[str], str, str, Dict[str, float]], None]] = None,
) -> Dict[int, float]:
    requests: Sequence[JustificationRequest] = []
    req_list = []
    trace_targets: Dict[int, Tuple[Optional[str], str, str, float, Optional[float], float]] = {}
    for ctx in commands:
        justification_dx = 0.0
        key = ctx.key
        transform = transform_by_group.get(key)
        justification = (ctx.justification or "left").strip().lower()
        suffix = ctx.suffix
        if suffix is None:
            continue
        if justification not in {"center", "right"}:
            continue
        width = float(ctx.bounds[2]) - float(ctx.bounds[0])
        base_bounds = base_overlay_bounds.get(key)
        baseline_width = None
        if base_bounds is not None:
            scale_value = base_scale
            if not isinstance(scale_value, (int, float)) or scale_value == 0.0:
                scale_value = 1.0
            baseline_width = (base_bounds[2] - base_bounds[0]) * scale_value
        if trace_fn:
            trace_targets[ctx.identifier] = (
                ctx.plugin,
                ctx.item_id,
                suffix,
                width,
                baseline_width if baseline_width is not None else 0.0,
                justification_dx,
            )
            trace_fn(
                ctx.plugin,
                ctx.item_id,
                "justify:measure",
                {
                    "width_px": width,
                    "baseline_px": baseline_width if baseline_width is not None else 0.0,
                    "suffix": suffix,
                    "justification": justification,
                },
            )
        delta = 0.0
        if justification == "right" and ctx.raw_min_x is not None:
            multiplier = ctx.right_just_multiplier or 0
            if multiplier and transform is not None:
                base_delta = _right_justification_delta(transform, ctx.raw_min_x)
                delta = base_delta * float(multiplier)
        req_list.append(
            JustificationRequest(
                identifier=ctx.identifier,
                key=key,
                suffix=suffix,
                justification=justification,
                width=width,
                baseline_width=baseline_width,
                right_justification_delta_px=delta,
            )
        )
    requests = req_list
    if not requests:
        return {}
    offset_map = calculate_offsets(requests)
    if not offset_map:
        return {}
    return offset_map


def _right_justification_delta(
    transform: Optional[GroupTransform],
    payload_min_x: Optional[float],
) -> float:
    if transform is None or payload_min_x is None:
        return 0.0
    justification = (getattr(transform, "payload_justification", "left") or "left").strip().lower()
    if justification != "right":
        return 0.0
    reference = getattr(transform, "bounds_min_x", None)
    try:
        reference_value = float(reference)
        payload_value = float(payload_min_x)
    except (TypeError, ValueError):
        return 0.0
    if not (reference_value == reference_value and payload_value == payload_value):
        return 0.0
    delta = payload_value - reference_value
    if delta == 0.0:
        return 0.0
    return delta
