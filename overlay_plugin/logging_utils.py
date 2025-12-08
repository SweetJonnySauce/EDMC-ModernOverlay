from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional


def build_rotating_payload_handler(
    log_dir: Path,
    filename: str,
    *,
    retention: int,
    max_bytes: int,
    formatter: Optional[logging.Formatter] = None,
) -> logging.Handler:
    """Construct a rotating file handler for payload logging."""
    retention = max(1, retention)
    backup_count = max(0, retention - 1)
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        log_dir / filename,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    if formatter is not None:
        handler.setFormatter(formatter)
    handler.setLevel(logging.DEBUG)
    return handler
