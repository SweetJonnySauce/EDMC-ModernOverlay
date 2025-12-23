"""Developer helper features for the Modern Overlay PyQt client."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Optional, TYPE_CHECKING

from overlay_client.client_config import DeveloperHelperConfig, InitialClientSettings
from overlay_client.logging_utils import build_rotating_file_handler, resolve_logs_dir

if TYPE_CHECKING:
    from overlay_client import OverlayWindow


_LOG_DIR_NAME = "EDMCModernOverlay"
_LOG_FILE_NAME = "overlay_client.log"
_MAX_LOG_BYTES = 512 * 1024


class DeveloperHelperController:
    """Apply developer helper preferences to the running overlay client."""

    def __init__(self, logger: logging.Logger, client_root: Path, initial: InitialClientSettings) -> None:
        self._logger = logger
        self._client_root = client_root
        self._log_handler: Optional[logging.Handler] = None
        self._log_path: Optional[Path] = None
        self._current_log_retention = max(1, initial.client_log_retention)
        self._configure_client_logging(self._current_log_retention)

    # Public API -----------------------------------------------------------

    @property
    def log_retention(self) -> int:
        return self._current_log_retention

    def apply_initial_window_state(self, window: "OverlayWindow", initial: InitialClientSettings) -> None:
        window.set_log_retention(self._current_log_retention)
        window.set_payload_opacity(getattr(initial, "global_payload_opacity", 100))
        window.set_force_render(initial.force_render)
        window.set_physical_clamp_enabled(getattr(initial, "physical_clamp_enabled", False))
        if getattr(initial, "physical_clamp_overrides", None):
            window.set_physical_clamp_overrides(getattr(initial, "physical_clamp_overrides"))
        window.set_follow_enabled(True)
        window.set_debug_overlay(initial.show_debug_overlay)
        window.set_font_bounds(initial.min_font_point, initial.max_font_point)
        window.set_legacy_font_step(getattr(initial, "legacy_font_step", 2.0))
        window.set_status_bottom_margin(initial.status_bottom_margin)
        window.set_debug_overlay_corner(getattr(initial, "debug_overlay_corner", "NW"))
        window.set_title_bar_compensation(initial.title_bar_enabled, initial.title_bar_height)
        window.set_cycle_payload_enabled(getattr(initial, "cycle_payload_ids", False))
        window.set_cycle_payload_copy_enabled(getattr(initial, "copy_payload_id_on_cycle", False))
        if getattr(initial, "scale_mode", None):
            window.set_scale_mode(initial.scale_mode)
        window.set_payload_nudge(initial.nudge_overflow_payloads, initial.payload_nudge_gutter)
        if hasattr(initial, "payload_log_delay_seconds"):
            window.set_payload_log_delay(getattr(initial, "payload_log_delay_seconds", 0.0))

    def apply_config(self, window: "OverlayWindow", payload: Dict[str, Any]) -> None:
        config = DeveloperHelperConfig.from_payload(payload)
        if config.background_opacity is not None:
            window.set_background_opacity(config.background_opacity)
        if config.global_payload_opacity is not None:
            window.set_payload_opacity(config.global_payload_opacity)
        if config.enable_drag is not None:
            window.set_drag_enabled(config.enable_drag)
        if config.gridlines_enabled is not None or config.gridline_spacing is not None:
            window.set_gridlines(
                enabled=config.gridlines_enabled if config.gridlines_enabled is not None else window.gridlines_enabled,
                spacing=config.gridline_spacing,
            )
        if config.show_status is not None:
            window.set_show_status(config.show_status)
        if config.status_bottom_margin is not None:
            window.set_status_bottom_margin(config.status_bottom_margin)
        if getattr(config, "debug_overlay_corner", None) is not None:
            window.set_debug_overlay_corner(config.debug_overlay_corner)
        if config.force_render is not None:
            window.set_force_render(config.force_render)
        if "physical_clamp_enabled" in payload:
            window.set_physical_clamp_enabled(payload.get("physical_clamp_enabled"))
        if "physical_clamp_overrides" in payload:
            window.set_physical_clamp_overrides(payload.get("physical_clamp_overrides"))
        if config.title_bar_enabled is not None or config.title_bar_height is not None:
            window.set_title_bar_compensation(config.title_bar_enabled, config.title_bar_height)
        if config.show_debug_overlay is not None:
            window.set_debug_overlay(config.show_debug_overlay)
        if config.min_font_point is not None or config.max_font_point is not None:
            window.set_font_bounds(config.min_font_point, config.max_font_point)
        if config.legacy_font_step is not None:
            window.set_legacy_font_step(config.legacy_font_step)
        if config.cycle_payload_ids is not None:
            window.set_cycle_payload_enabled(config.cycle_payload_ids)
        if config.copy_payload_id_on_cycle is not None:
            window.set_cycle_payload_copy_enabled(config.copy_payload_id_on_cycle)
        if config.scale_mode is not None:
            window.set_scale_mode(config.scale_mode)
        if config.nudge_overflow_payloads is not None or config.payload_nudge_gutter is not None:
            window.set_payload_nudge(config.nudge_overflow_payloads, config.payload_nudge_gutter)
        if getattr(config, "payload_log_delay_seconds", None) is not None:
            window.set_payload_log_delay(config.payload_log_delay_seconds)
        if 'platform_context' in payload:
            window.update_platform_context(payload.get('platform_context'))
        elif config.force_xwayland is not None:
            window.update_platform_context({'force_xwayland': config.force_xwayland})
        if config.client_log_retention is not None:
            self.set_log_retention(config.client_log_retention)
        window.set_log_retention(self._current_log_retention)

    def handle_legacy_payload(self, window: "OverlayWindow", payload: Dict[str, Any]) -> None:
        if payload.get("type") == "shape" and payload.get("shape") == "vect":
            points = payload.get("vector")
            if not isinstance(points, list) or not points:
                self._logger.warning("Vector payload ignored: requires at least two points (%s)", points)
                return
            if len(points) < 2:
                point = points[0] if isinstance(points[0], dict) else {}
                has_marker = bool(point.get("marker"))
                has_text = point.get("text") is not None and str(point.get("text")) != ""
                if not (has_marker or has_text):
                    self._logger.warning("Vector payload ignored: requires at least two points (%s)", points)
                    return
        window.handle_legacy_payload(payload)

    def set_log_retention(self, retention: int) -> None:
        try:
            numeric = int(retention)
        except (TypeError, ValueError):
            numeric = self._current_log_retention
        numeric = max(1, numeric)
        if numeric == self._current_log_retention:
            return
        self._configure_client_logging(numeric)
        self._logger.debug("Client log retention updated to %d", numeric)

    # Internal helpers ----------------------------------------------------

    def _configure_client_logging(self, retention: int) -> None:
        retention = max(1, retention)
        logs_dir = resolve_logs_dir(self._client_root)
        formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S")
        try:
            handler = build_rotating_file_handler(
                logs_dir,
                _LOG_FILE_NAME,
                retention=retention,
                max_bytes=_MAX_LOG_BYTES,
                formatter=formatter,
            )
        except Exception as exc:
            stream_handler = logging.StreamHandler()
            stream_handler.setFormatter(formatter)
            self._replace_handler(stream_handler)
            self._logger.warning("Failed to initialise file logging in %s: %s", logs_dir, exc)
            self._log_path = None
            self._current_log_retention = retention
            return

        self._replace_handler(handler)
        self._log_path = logs_dir / _LOG_FILE_NAME
        self._current_log_retention = retention
        self._logger.debug(
            "Client logging initialised: path=%s retention=%d max_bytes=%d backup_count=%d",
            self._log_path,
            retention,
            _MAX_LOG_BYTES,
            max(0, retention - 1),
        )

    def _replace_handler(self, handler: logging.Handler) -> None:
        if self._log_handler is not None:
            self._logger.removeHandler(self._log_handler)
            try:
                self._log_handler.close()
            except Exception:
                pass
        self._logger.addHandler(handler)
        self._log_handler = handler
