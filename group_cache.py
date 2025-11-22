"""Local cache support for overlay group placement snapshots."""
from __future__ import annotations

import copy
import json
import threading
import time
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

GROUP_CACHE_FILENAME = "overlay_group_cache.json"
_CACHE_VERSION = 1


def _default_state() -> Dict[str, Any]:
    return {"version": _CACHE_VERSION, "groups": {}}


def load_group_cache(path: Path) -> Dict[str, Any]:
    """Lightweight reader used by tools that consume cached placement data."""

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return _default_state()
    except (OSError, json.JSONDecodeError):
        return _default_state()
    if not isinstance(raw, dict):
        return _default_state()
    groups = raw.get("groups")
    if not isinstance(groups, dict):
        return _default_state()
    version = raw.get("version", _CACHE_VERSION)
    return {"version": version, "groups": groups}


class GroupPlacementCache:
    """Collects placement snapshots and persists them with debounce."""

    def __init__(
        self,
        path: Path,
        debounce_seconds: float = 10.0,
        logger: Any | None = None,
    ) -> None:
        self._path = path
        self._debounce_seconds = max(0.05, float(debounce_seconds))
        self._logger = logger
        self._lock = threading.Lock()
        self._flush_guard = threading.Lock()
        self._state: Dict[str, Any] = _default_state()
        self._dirty = False
        self._flush_timer: Optional[threading.Timer] = None
        self._ensure_parent()
        self._load_existing()

    def _log_debug(self, message: str) -> None:
        if self._logger is None:
            return
        try:
            self._logger.debug(message)
        except Exception:
            pass

    def _ensure_parent(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

    def _load_existing(self) -> None:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            self._write_snapshot(self._state)
            return
        except (OSError, json.JSONDecodeError) as exc:
            self._log_debug(f"Failed to load group cache: {exc}")
            return
        if not isinstance(raw, dict):
            return
        groups = raw.get("groups")
        if not isinstance(groups, dict):
            return
        with self._lock:
            self._state["groups"] = groups
            version = raw.get("version", _CACHE_VERSION)
            self._state["version"] = version if isinstance(version, int) else _CACHE_VERSION

    def update_group(
        self,
        plugin: str,
        suffix: Optional[str],
        normalized: Mapping[str, Any],
        transformed: Optional[Mapping[str, Any]],
    ) -> None:
        plugin_key = (plugin or "unknown").strip() or "unknown"
        suffix_key = (suffix or "").strip()
        normalized_payload = dict(normalized)
        transformed_payload = dict(transformed) if transformed is not None else None
        with self._lock:
            plugin_entry = self._state["groups"].setdefault(plugin_key, {})
            existing = plugin_entry.get(suffix_key)
            existing_normalized = existing.get("normalized") if isinstance(existing, dict) else None
            existing_transformed = existing.get("transformed") if isinstance(existing, dict) else None
            if existing_normalized == normalized_payload and existing_transformed == transformed_payload:
                return
            plugin_entry[suffix_key] = {
                "normalized": normalized_payload,
                "transformed": transformed_payload,
                "last_updated": time.time(),
            }
            self._dirty = True
        self._schedule_flush()

    def _schedule_flush(self) -> None:
        with self._lock:
            if self._flush_timer is not None and self._flush_timer.is_alive():
                return
            timer = threading.Timer(self._debounce_seconds, self._flush)
            timer.daemon = True
            self._flush_timer = timer
            timer.start()

    def _flush(self) -> None:
        with self._flush_guard:
            with self._lock:
                if not self._dirty:
                    self._flush_timer = None
                    return
                snapshot = copy.deepcopy(self._state)
                self._dirty = False
                self._flush_timer = None
            success = self._write_snapshot(snapshot)
        if not success:
            with self._lock:
                self._dirty = True
            self._schedule_flush()

    def _write_snapshot(self, snapshot: Mapping[str, Any]) -> bool:
        try:
            self._ensure_parent()
            tmp_path = self._path.with_suffix(self._path.suffix + ".tmp")
            tmp_path.write_text(json.dumps(snapshot, indent=2, sort_keys=True), encoding="utf-8")
            tmp_path.replace(self._path)
            return True
        except Exception as exc:
            self._log_debug(f"Failed to write group cache: {exc}")
            return False


def resolve_cache_path(root: Optional[Path] = None) -> Path:
    """Return the resolved cache path rooted at the given folder."""

    base = root if root is not None else Path(__file__).resolve().parent
    return base / GROUP_CACHE_FILENAME
