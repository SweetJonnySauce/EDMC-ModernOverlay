from __future__ import annotations

from typing import MutableSet

from overlay_client.paint_commands import _LegacyPaintCommand


def log_offscreen_payload(
    *,
    command: _LegacyPaintCommand,
    offset_x: float,
    offset_y: float,
    window_width: int,
    window_height: int,
    offscreen_payloads: MutableSet[str],
    log_fn,
) -> None:
    """Track when a payload renders fully offscreen and emit a warning once."""
    bounds = command.bounds
    payload_id = command.legacy_item.item_id or ""
    if not bounds or not payload_id:
        if payload_id:
            offscreen_payloads.discard(payload_id)
        return
    left = float(bounds[0]) + float(offset_x)
    top = float(bounds[1]) + float(offset_y)
    right = float(bounds[2]) + float(offset_x)
    bottom = float(bounds[3]) + float(offset_y)
    offscreen = (
        right < 0.0
        or bottom < 0.0
        or left >= float(window_width)
        or top >= float(window_height)
    )
    if offscreen:
        if payload_id not in offscreen_payloads:
            plugin_name = command.legacy_item.plugin or "unknown"
            offscreen_payloads.add(payload_id)
            log_fn(
                "Payload '%s' from plugin '%s' rendered completely outside the overlay window "
                "(bounds=(%.1f, %.1f)-(%.1f, %.1f), window=%dx%d)",
                payload_id,
                plugin_name,
                left,
                top,
                right,
                bottom,
                window_width,
                window_height,
            )
    else:
        offscreen_payloads.discard(payload_id)
