"""Developer helper features for the Modern Overlay PyQt client."""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Dict, Optional, TYPE_CHECKING

from client_config import DeveloperHelperConfig, InitialClientSettings

if TYPE_CHECKING:
    from overlay_client import OverlayWindow


_LOG_DIR_NAME = "EDMC-ModernOverlay"
_LOG_FILE_NAME = "overlay-client.log"
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
        window.set_force_render(initial.force_render)
        window.set_follow_enabled(True)
        window.set_debug_overlay(initial.show_debug_overlay)
        window.set_font_bounds(initial.min_font_point, initial.max_font_point)
        window.set_status_bottom_margin(initial.status_bottom_margin)

    def apply_config(self, window: "OverlayWindow", payload: Dict[str, Any]) -> None:
        config = DeveloperHelperConfig.from_payload(payload)
        if config.background_opacity is not None:
            window.set_background_opacity(config.background_opacity)
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
        if config.force_render is not None:
            window.set_force_render(config.force_render)
        if config.show_debug_overlay is not None:
            window.set_debug_overlay(config.show_debug_overlay)
        if config.min_font_point is not None or config.max_font_point is not None:
            window.set_font_bounds(config.min_font_point, config.max_font_point)
        if 'platform_context' in payload:
            window.update_platform_context(payload.get('platform_context'))
        elif config.force_xwayland is not None:
            window.update_platform_context({'force_xwayland': config.force_xwayland})
        if config.client_log_retention is not None:
            self.set_log_retention(config.client_log_retention)
        window.set_log_retention(self._current_log_retention)

    def handle_legacy_payload(self, window: "OverlayWindow", payload: Dict[str, Any]) -> None:
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
        logs_dir = self._resolve_logs_dir()
        log_path = logs_dir / _LOG_FILE_NAME
        backup_count = max(0, retention - 1)
        formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S")
        try:
            handler = RotatingFileHandler(
                log_path,
                maxBytes=_MAX_LOG_BYTES,
                backupCount=backup_count,
                encoding="utf-8",
            )
        except Exception as exc:
            stream_handler = logging.StreamHandler()
            stream_handler.setFormatter(formatter)
            self._replace_handler(stream_handler)
            self._logger.warning("Failed to initialise file logging at %s: %s", log_path, exc)
            self._log_path = None
            self._current_log_retention = retention
            return

        handler.setFormatter(formatter)
        self._replace_handler(handler)
        self._log_path = log_path
        self._current_log_retention = retention
        self._logger.debug(
            "Client logging initialised: path=%s retention=%d max_bytes=%d backup_count=%d",
            log_path,
            retention,
            _MAX_LOG_BYTES,
            backup_count,
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

    def _resolve_logs_dir(self) -> Path:
        current = self._client_root.resolve()
        parents = current.parents
        candidates = []
        if len(parents) >= 3:
            candidates.append(parents[2] / "logs")
        if len(parents) >= 2:
            candidates.append(parents[1] / "logs")
        candidates.append(Path.cwd() / "logs")
        for base in candidates:
            try:
                target = base / _LOG_DIR_NAME
                target.mkdir(parents=True, exist_ok=True)
                return target
            except Exception:
                continue
        fallback = current / "logs" / _LOG_DIR_NAME
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback
