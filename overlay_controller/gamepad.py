"""Optional gamepad bridge that maps an Xbox pad to controller actions."""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Callable, Dict, Tuple

try:
    import pygame
except Exception:  # pragma: no cover - optional dependency
    pygame = None  # type: ignore

LOGGER = logging.getLogger("EDMCModernOverlay.Controller")

# Xbox-style mapping based on SDL/pygame defaults.
_BUTTON_ACTIONS: Dict[int, str] = {
    0: "enter_focus",  # A
    1: "exit_focus",  # B
    2: "widget_activate",  # X
    4: "close_app",  # LB
    6: "absolute_focus_prev",  # Back/View
    7: "absolute_focus_next",  # Start/Menu
    10: "indicator_toggle",  # R3
}
_ALT_BUTTON = 5  # RB acts as the Alt modifier
_HAT_ACTIONS: Dict[Tuple[int, int], str] = {
    (0, 1): "sidebar_focus_up",
    (0, -1): "sidebar_focus_down",
    (-1, 0): "widget_move_left",
    (1, 0): "widget_move_right",
}
_ALT_HAT_ACTIONS: Dict[str, str] = {
    "sidebar_focus_up": "alt_widget_move_up",
    "sidebar_focus_down": "alt_widget_move_down",
    "widget_move_left": "alt_widget_move_left",
    "widget_move_right": "alt_widget_move_right",
}


def _env_flag(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "off", "no", ""}


class GamepadBridge:
    """Poll a pygame-backed gamepad and dispatch mapped actions."""

    def __init__(
        self,
        widget: Any,
        trigger_action: Callable[[str], bool],
        has_action: Callable[[str], bool],
        *,
        enabled: bool | None = None,
        poll_interval: float = 0.02,
    ) -> None:
        self.widget = widget
        self._trigger_action = trigger_action
        self._has_action = has_action
        self.poll_interval = poll_interval
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._alt_held = False
        self._enabled = enabled if enabled is not None else _env_flag("EDMC_OVERLAY_GAMEPAD", True)

    def start(self) -> None:
        if not self._enabled:
            return
        if pygame is None:
            LOGGER.info("Gamepad bridge disabled: pygame not available")
            return
        try:
            pygame.init()
            pygame.joystick.init()
        except Exception as exc:
            LOGGER.info("Gamepad bridge disabled: pygame init failed (%s)", exc)
            return
        if pygame.joystick.get_count() < 1:
            LOGGER.info("Gamepad bridge disabled: no joysticks detected")
            return
        try:
            joystick = pygame.joystick.Joystick(0)
            joystick.init()
            LOGGER.info("Gamepad bridge active with '%s'", joystick.get_name())
        except Exception as exc:
            LOGGER.info("Gamepad bridge disabled: joystick init failed (%s)", exc)
            return

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="gamepad-bridge", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._enabled = False
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=0.5)
        self._thread = None

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                for event in pygame.event.get():  # type: ignore[attr-defined]
                    self._handle_event(event)
            except Exception as exc:
                LOGGER.info("Gamepad bridge stopped after error: %s", exc)
                return
            time.sleep(self.poll_interval)

    def _handle_event(self, event: Any) -> None:
        etype = getattr(event, "type", None)
        if etype is None:
            return
        if etype == pygame.JOYBUTTONDOWN:  # type: ignore[attr-defined]
            self._handle_button_down(getattr(event, "button", -1))
        elif etype == pygame.JOYBUTTONUP:  # type: ignore[attr-defined]
            self._handle_button_up(getattr(event, "button", -1))
        elif etype == pygame.JOYHATMOTION:  # type: ignore[attr-defined]
            self._handle_hat(getattr(event, "value", (0, 0)))

    def _handle_button_down(self, button: int) -> None:
        if button == _ALT_BUTTON:
            self._alt_held = True
            return
        action = _BUTTON_ACTIONS.get(button)
        if action:
            self._dispatch(action)

    def _handle_button_up(self, button: int) -> None:
        if button == _ALT_BUTTON:
            self._alt_held = False

    def _handle_hat(self, value: Tuple[int, int]) -> None:
        action = _HAT_ACTIONS.get(value)
        if not action:
            return
        if self._alt_held:
            action = _ALT_HAT_ACTIONS.get(action, action)
        self._dispatch(action)

    def _dispatch(self, action: str) -> None:
        if not self._has_action(action):
            return

        def _call() -> None:
            self._trigger_action(action)

        try:
            self.widget.after(0, _call)
        except Exception:
            _call()
