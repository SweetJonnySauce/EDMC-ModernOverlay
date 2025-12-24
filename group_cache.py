"""Local cache support for overlay group placement snapshots."""
from __future__ import annotations

import copy
import json
import math
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
        self._last_write_metadata: Dict[tuple[str, str], Dict[str, Any]] = {}
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
        edit_nonce = str(normalized_payload.get("edit_nonce") or "").strip()
        controller_ts = normalized_payload.get("controller_ts")
        try:
            controller_ts_val = float(controller_ts)
        except (TypeError, ValueError):
            controller_ts_val = 0.0

        def _safe_float(value: Any, default: float = 0.0) -> float:
            try:
                number = float(value)
            except (TypeError, ValueError):
                return default
            if not math.isfinite(number):
                return default
            return number

        def _payload_size(payload: Mapping[str, Any]) -> tuple[float, float]:
            if any(key in payload for key in ("base_min_x", "base_min_y", "base_max_x", "base_max_y", "base_width", "base_height")):
                min_x = _safe_float(payload.get("base_min_x"))
                min_y = _safe_float(payload.get("base_min_y"))
                max_x = _safe_float(payload.get("base_max_x"))
                max_y = _safe_float(payload.get("base_max_y"))
                width = _safe_float(payload.get("base_width"), max_x - min_x)
                height = _safe_float(payload.get("base_height"), max_y - min_y)
            else:
                min_x = _safe_float(payload.get("trans_min_x"))
                min_y = _safe_float(payload.get("trans_min_y"))
                max_x = _safe_float(payload.get("trans_max_x"))
                max_y = _safe_float(payload.get("trans_max_y"))
                width = _safe_float(payload.get("trans_width"), max_x - min_x)
                height = _safe_float(payload.get("trans_height"), max_y - min_y)
            if width <= 0.0 or height <= 0.0:
                width = max(0.0, max_x - min_x)
                height = max(0.0, max_y - min_y)
            return width, height
        with self._lock:
            plugin_entry = self._state["groups"].setdefault(plugin_key, {})
            existing = plugin_entry.get(suffix_key)
            existing_normalized = existing.get("normalized") if isinstance(existing, dict) else None
            existing_transformed = existing.get("transformed") if isinstance(existing, dict) else None
            if existing_normalized == normalized_payload and existing_transformed == transformed_payload:
                return
            existing_last_visible = existing.get("last_visible_transformed") if isinstance(existing, dict) else None
            existing_max = existing.get("max_transformed") if isinstance(existing, dict) else None
            last_visible_transformed = dict(existing_last_visible) if isinstance(existing_last_visible, dict) else None
            max_transformed = dict(existing_max) if isinstance(existing_max, dict) else None
            width, height = _payload_size(normalized_payload)
            if width > 0.0 and height > 0.0:
                base_snapshot = {
                    "base_min_x": normalized_payload.get("base_min_x"),
                    "base_min_y": normalized_payload.get("base_min_y"),
                    "base_max_x": normalized_payload.get("base_max_x"),
                    "base_max_y": normalized_payload.get("base_max_y"),
                    "base_width": normalized_payload.get("base_width"),
                    "base_height": normalized_payload.get("base_height"),
                }
                last_visible_transformed = dict(base_snapshot)
                if isinstance(max_transformed, Mapping):
                    max_width, max_height = _payload_size(max_transformed)
                    if width >= max_width and height >= max_height:
                        max_transformed = dict(base_snapshot)
                else:
                    max_transformed = dict(base_snapshot)
            entry_payload: Dict[str, Any] = {
                "base": normalized_payload,
                "transformed": transformed_payload,
                "last_updated": time.time(),
            }
            if last_visible_transformed is not None:
                entry_payload["last_visible_transformed"] = last_visible_transformed
            if max_transformed is not None:
                entry_payload["max_transformed"] = max_transformed
            if edit_nonce:
                entry_payload["edit_nonce"] = edit_nonce
            if controller_ts_val > 0.0:
                entry_payload["controller_ts"] = controller_ts_val
            plugin_entry[suffix_key] = entry_payload
            self._last_write_metadata[(plugin_key, suffix_key)] = {
                "edit_nonce": edit_nonce,
                "controller_ts": controller_ts_val,
                "last_updated": entry_payload["last_updated"],
            }
            self._dirty = True
        self._schedule_flush()

    def reset(self) -> None:
        """Clear cached groups and persist an empty cache file immediately."""
        timer = None
        with self._lock:
            self._state = _default_state()
            self._dirty = False
            self._last_write_metadata.clear()
            timer = self._flush_timer
            self._flush_timer = None
        if timer is not None:
            try:
                timer.cancel()
            except Exception:
                pass
        if not self._write_snapshot(self._state):
            with self._lock:
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

    def configure_debounce(self, debounce_seconds: float) -> None:
        """Update debounce interval and re-arm pending flushes if needed."""

        new_value = max(0.05, float(debounce_seconds))
        timer: Optional[threading.Timer]
        dirty = False
        with self._lock:
            self._debounce_seconds = new_value
            timer = self._flush_timer
            dirty = self._dirty
            self._flush_timer = None
        if timer is not None:
            try:
                timer.cancel()
            except Exception:
                pass
        if dirty:
            self._schedule_flush()

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

    def flush_pending(self) -> None:
        """Force an immediate flush of pending cache writes."""

        self._flush()

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

    def get_group(self, plugin: str, suffix: Optional[str]) -> Optional[Dict[str, Any]]:
        groups = self._state.get("groups", {})
        if not isinstance(groups, dict):
            return None
        plugin_entry = groups.get(plugin)
        if not isinstance(plugin_entry, dict):
            return None
        return plugin_entry.get(suffix) if isinstance(plugin_entry, dict) else None

    def last_write_metadata(self, plugin: str, suffix: Optional[str]) -> Optional[Dict[str, Any]]:
        key = ((plugin or "unknown").strip() or "unknown", (suffix or "").strip())
        return self._last_write_metadata.get(key)


def resolve_cache_path(root: Optional[Path] = None) -> Path:
    """Return the resolved cache path rooted at the given folder."""

    base = root if root is not None else Path(__file__).resolve().parent
    return base / GROUP_CACHE_FILENAME
