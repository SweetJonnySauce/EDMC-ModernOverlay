from __future__ import annotations

from typing import Callable, Optional


class StatusPresenter:
    """Handles overlay status banner formatting and dispatch."""

    def __init__(
        self,
        *,
        send_payload_fn: Callable[[dict], None],
        platform_label_fn: Callable[[], str],
        base_height: int,
        log_fn: Callable[[str, object, object], None],
    ) -> None:
        self._send_payload = send_payload_fn
        self._platform_label_fn = platform_label_fn
        self._base_height = base_height
        self._log = log_fn
        self._status_raw: str = "Initialising"
        self._status: str = self._status_raw
        self._show_status: bool = False
        self._status_bottom_margin: int = 20

    @property
    def status_raw(self) -> str:
        return self._status_raw

    @property
    def status(self) -> str:
        return self._status

    @property
    def show_status(self) -> bool:
        return self._show_status

    @property
    def status_bottom_margin(self) -> int:
        return self._status_bottom_margin

    def set_status_text(self, status: str) -> None:
        self._status_raw = status
        self._status = self._format_status_message(status)
        if self._show_status:
            self._show_overlay_status_message(self._status)

    def set_show_status(self, show: bool) -> None:
        flag = bool(show)
        if flag == self._show_status:
            return
        self._show_status = flag
        if flag:
            self._show_overlay_status_message(self._status)
        else:
            self._dismiss_overlay_status_message()

    def set_status_bottom_margin(self, margin: int, *, coerce_fn: Callable[[Optional[int], int], int]) -> None:
        value = coerce_fn(margin, self._status_bottom_margin)
        if value == self._status_bottom_margin:
            return
        self._status_bottom_margin = value
        self._log("Status bottom margin updated to %spx", self._status_bottom_margin)
        if self._show_status and self._status:
            self._show_overlay_status_message(self._status)

    def _format_status_message(self, status: str) -> str:
        message = status or ""
        if "Connected to 127.0.0.1:" not in message:
            return message
        platform_label = self._platform_label_fn()
        suffix = f" on {platform_label}"
        if message.endswith(suffix):
            return message
        return f"{message}{suffix}"

    def _show_overlay_status_message(self, status: str) -> None:
        message = (status or "").strip()
        if not message:
            return
        bottom_margin = max(0, self._status_bottom_margin)
        x_pos = 10
        y_pos = max(0, self._base_height - bottom_margin)
        payload = {
            "type": "message",
            "id": "__status_banner__",
            "text": message,
            "color": "#ffffff",
            "x": x_pos,
            "y": y_pos,
            "ttl": 0,
            "size": "normal",
            "plugin": "EDMCModernOverlay",
        }
        self._log(
            "Legacy status message dispatched: text='%s' ttl=%s x=%s y=%s",
            message,
            payload["ttl"],
            payload["x"],
            payload["y"],
        )
        self._send_payload(payload)

    def _dismiss_overlay_status_message(self) -> None:
        payload = {
            "type": "message",
            "id": "__status_banner__",
            "text": "",
            "ttl": 0,
            "plugin": "EDMCModernOverlay",
        }
        self._send_payload(payload)
