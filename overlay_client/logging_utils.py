from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional


def resolve_logs_dir(base_path: Path, log_dir_name: str = "EDMCModernOverlay") -> Path:
    """
    Resolve the directory to store overlay logs.

    Strategy:
    - Prefer an EDMC-style `EDMarketConnector/logs/<log_dir_name>` ancestor when available.
    - Fall back to `cwd/logs/<log_dir_name>` if preferred location is unavailable.
    - Final fallback: `base_path/logs/<log_dir_name>`.
    """
    current = base_path.resolve()
    parents = current.parents
    candidates = []
    edmc_root = next((p for p in parents if p.name == "EDMarketConnector"), None)
    if edmc_root is not None:
        candidates.append(edmc_root / "logs")
    candidates.append(Path.cwd() / "logs")
    for base in candidates:
        try:
            target = base / log_dir_name
            target.mkdir(parents=True, exist_ok=True)
            return target
        except Exception:
            continue
    fallback = current / "logs" / log_dir_name
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


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
