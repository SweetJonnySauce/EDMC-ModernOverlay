from __future__ import annotations

from typing import Callable


class VisibilityHelper:
    """Manages show/hide flow with logging while keeping Qt calls injected."""

    def __init__(self, log_fn: Callable[[str, object, object], None]) -> None:
        self._last_state: bool | None = None
        self._log = log_fn

    def update_visibility(
        self,
        show: bool,
        *,
        is_visible_fn: Callable[[], bool],
        show_fn: Callable[[], None],
        hide_fn: Callable[[], None],
        raise_fn: Callable[[], None],
        apply_drag_state_fn: Callable[[], None],
        format_scale_debug_fn: Callable[[], str],
    ) -> bool:
        if show:
            if not is_visible_fn():
                show_fn()
                raise_fn()
                apply_drag_state_fn()
        else:
            if is_visible_fn():
                hide_fn()
        if self._last_state != show:
            self._log(
                "Overlay visibility set to %s; %s",
                "visible" if show else "hidden",
                format_scale_debug_fn(),
            )
            self._last_state = show
        return show
