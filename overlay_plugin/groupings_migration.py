"""Helpers for deciding when to migrate overlay groupings into the user layer.

Stage 3.1: migration trigger/heuristic only. No file writes beyond marker updates.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional, Tuple
import os


@dataclass(frozen=True)
class MigrationDecision:
    should_migrate: bool
    reason: str
    shipped_hash: Optional[str] = None
    marker_version: Optional[str] = None


def compute_hash(path: Path) -> Optional[str]:
    """Return sha256 hex digest of a file, or None on read failure."""

    try:
        data = path.read_bytes()
    except OSError:
        return None
    digest = hashlib.sha256()
    digest.update(data)
    return digest.hexdigest()


def load_marker(marker_path: Path) -> Tuple[Optional[str], Optional[str]]:
    """Return (shipped_hash, version) from marker, or (None, None) on failure."""

    try:
        raw = json.loads(marker_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None, None
    if not isinstance(raw, Mapping):
        return None, None
    shipped_hash = raw.get("shipped_hash")
    version = raw.get("version")
    return (shipped_hash if isinstance(shipped_hash, str) else None, version if isinstance(version, str) else None)


def write_marker(marker_path: Path, shipped_hash: str, version: Optional[str] = None) -> bool:
    """Write migration marker; returns True on success."""

    payload: dict[str, Any] = {"shipped_hash": shipped_hash}
    if isinstance(version, str):
        payload["version"] = version
    try:
        marker_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return True
    except OSError:
        return False


def should_migrate(
    shipped_path: Path,
    user_path: Path,
    marker_path: Path,
    current_version: Optional[str] = None,
) -> MigrationDecision:
    """Decide whether to migrate shipped groupings into the user layer."""

    if user_path.exists():
        return MigrationDecision(False, "user_exists")

    shipped_hash = compute_hash(shipped_path)
    if shipped_hash is None:
        return MigrationDecision(False, "shipped_unreadable")

    marker_hash, marker_version = load_marker(marker_path)

    if marker_hash is None:
        return MigrationDecision(True, "no_marker", shipped_hash, marker_version)

    if marker_hash != shipped_hash:
        return MigrationDecision(True, "shipped_hash_changed", shipped_hash, marker_version)

    if current_version and marker_version != current_version:
        # Allow re-run on version bump even if hash matches, to catch baked-in user edits.
        return MigrationDecision(True, "version_changed", shipped_hash, marker_version)

    return MigrationDecision(False, "already_migrated", shipped_hash, marker_version)


def migrate_shipped_to_user(
    shipped_path: Path,
    user_path: Path,
    marker_path: Path,
    current_version: Optional[str] = None,
) -> MigrationDecision:
    """Copy shipped groupings to user file if trigger says migrate; writes marker on success."""

    decision = should_migrate(shipped_path, user_path, marker_path, current_version=current_version)
    if not decision.should_migrate:
        return decision

    try:
        shipped_text = shipped_path.read_text(encoding="utf-8")
    except OSError:
        return MigrationDecision(False, "shipped_unreadable")

    try:
        json.loads(shipped_text)
    except json.JSONDecodeError:
        return MigrationDecision(False, "shipped_invalid_json")

    try:
        tmp_path = user_path.with_suffix(user_path.suffix + ".tmp")
        tmp_path.write_text(shipped_text, encoding="utf-8")
        os.replace(tmp_path, user_path)
    except OSError:
        return MigrationDecision(False, "user_write_failed")

    if decision.shipped_hash:
        write_marker(marker_path, decision.shipped_hash, current_version)

    return MigrationDecision(True, "migrated", decision.shipped_hash, current_version)
