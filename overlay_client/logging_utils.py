from __future__ import annotations

import logging
import os
import tempfile
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional


def resolve_logs_dir(base_path: Path, log_dir_name: str = "EDMCModernOverlay") -> Path:
    """
    Resolve the directory to store overlay logs.

    Strategy:
    - Use EDMC_OVERLAY_LOG_DIR if set.
    - Prefer an EDMC-style `EDMarketConnector/logs/<log_dir_name>` ancestor when available.
    - Fall back to XDG state/cache locations, then `cwd/logs/<log_dir_name>`.
    - Final fallback: tempdir/<log_dir_name>.
    The plugin/install directory is intentionally avoided so we don't write logs into the plug-in tree.
    """
    current = base_path.resolve()
    parents = current.parents
    candidates = []

    env_override = os.environ.get("EDMC_OVERLAY_LOG_DIR")
    if env_override:
        try:
            candidates.append(Path(env_override).expanduser())
        except Exception:
            pass

    edmc_root = next((p for p in parents if p.name == "EDMarketConnector"), None)
    if edmc_root is not None:
        candidates.append(edmc_root / "logs")

    state_home = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    cache_home = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    candidates.append(state_home / "EDMarketConnector" / "logs")
    candidates.append(cache_home / "EDMarketConnector" / "logs")
    candidates.append(Path.cwd() / "logs")

    for base in candidates:
        try:
            target = base / log_dir_name
            target.mkdir(parents=True, exist_ok=True)
            return target
        except Exception:
            continue

    temp_fallback = Path(tempfile.gettempdir()) / "EDMCModernOverlay" / log_dir_name
    temp_fallback.mkdir(parents=True, exist_ok=True)
    return temp_fallback


def build_rotating_file_handler(
    log_dir: Path,
    filename: str,
    *,
    retention: int = 5,
    max_bytes: int = 512 * 1024,
    formatter: Optional[logging.Formatter] = None,
) -> logging.Handler:
    """Construct a rotating file handler with sane defaults."""
    retention = max(1, retention)
    backup_count = max(0, retention - 1)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / filename
    handler = RotatingFileHandler(
        log_path,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    if formatter is not None:
        handler.setFormatter(formatter)
    return handler


def resolve_log_level(debug_enabled: bool) -> int:
    """Return a log level consistent with overlay_client debug behavior."""
    return logging.DEBUG if debug_enabled else logging.INFO
