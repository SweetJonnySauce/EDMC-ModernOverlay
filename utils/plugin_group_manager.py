#!/usr/bin/env python3
"""Interactive Plugin Group Manager for Modern Overlay."""

from __future__ import annotations

# ruff: noqa: E402

import argparse
import json
import logging
import math
import os
import queue
import re
import socket
import subprocess
import sys
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from dataclasses import dataclass
from pathlib import Path
from tkinter import messagebox, simpledialog, ttk
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Tuple

ROOT_DIR = Path(__file__).resolve().parents[1]
OVERLAY_CLIENT_DIR = ROOT_DIR / "overlay_client"
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from prefix_entries import (
    MATCH_MODE_EXACT,
    MATCH_MODE_STARTSWITH,
    PrefixEntry,
    parse_prefix_entries,
    serialise_prefix_entries,
)
from overlay_plugin.overlay_api import (
    PluginGroupingError,
    _normalise_background_color,
    _normalise_border_width,
    define_plugin_group,
    register_grouping_store,
)

try:
    from overlay_client.plugin_overrides import PluginOverrideManager
except Exception as exc:  # pragma: no cover - manager required for runtime
    raise SystemExit(f"Failed to import overlay_client.plugin_overrides: {exc}")


LOG = logging.getLogger("plugin-group-manager")
LOG.addHandler(logging.NullHandler())

GROUPINGS_PATH = ROOT_DIR / "overlay_groupings.json"
DEBUG_CONFIG_PATH = ROOT_DIR / "debug.json"
SETTINGS_PATH = ROOT_DIR / "overlay_settings.json"
TRACE_LOG_PATH = Path(__file__).resolve().with_name("plugin_group_manager_context.log")
PORT_PATH = ROOT_DIR / "port.json"
PAYLOAD_STORE_DIR = ROOT_DIR / "payload_store"
PAYLOAD_LOG_DIR_NAME = "EDMCModernOverlay"
PAYLOAD_LOG_BASENAMES = ("overlay-payloads.log", "overlay_payloads.log")
ANCHOR_CHOICES = ("nw", "ne", "sw", "se", "center", "top", "bottom", "left", "right")
PAYLOAD_JUSTIFICATION_CHOICES = ("left", "center", "right")
DEFAULT_PAYLOAD_JUSTIFICATION = "left"
MARKER_LABEL_POSITION_CHOICES = ("below", "above", "centered")
DEFAULT_MARKER_LABEL_POSITION = "below"
CONTROLLER_PREVIEW_BOX_MODE_CHOICES = ("last", "max")
DEFAULT_CONTROLLER_PREVIEW_BOX_MODE = "last"
GENERIC_PAYLOAD_TOKENS = {"vect", "shape", "text"}
GROUP_SELECTOR_STYLE = "ModernOverlayGroupSelect.TCombobox"
LEFT_COLUMN_WIDTH = 180
GROUP_INFO_WRAP = 360
LEFT_PANEL_WRAP = 520
DEFAULT_REPLAY_TTL = 1
REPLAY_WINDOW_WAIT_SECONDS = 2.0
MOCK_WINDOW_TITLE = "Elite - Dangerous (Stub)"
MOCK_WINDOW_PATH = ROOT_DIR / "utils" / "mock_elite_window.py"
REPLAY_RESOLUTIONS = [
    (1280, 960),
    (1280, 1024),
    (1024, 768),
    (1720, 1440),
    (1920, 800),
    (1920, 1080),
    (1440, 900),
    (1440, 960),
    (2560, 1080),
]
BASE_ASPECT_RATIO = 1280 / 960
BASE_WIDTH = 1280
BASE_HEIGHT = 960
_MISSING = object()


@dataclass(frozen=True)
class PayloadRecord:
    payload_id: str
    plugin: Optional[str] = None
    payload: Optional[Mapping[str, Any]] = None
    group: Optional[str] = None

    def label(self) -> str:
        if self.plugin:
            return f"{self.payload_id} ({self.plugin})"
        return self.payload_id

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {"payload_id": self.payload_id}
        if self.plugin:
            data["plugin"] = self.plugin
        if self.group:
            data["group"] = self.group
        if self.payload is not None:
            data["payload"] = self.payload
        return data

    def with_group(self, group: Optional[str]) -> "PayloadRecord":
        return PayloadRecord(self.payload_id, self.plugin, self.payload, group)


class NewPayloadStore:
    """Persisted cache of unmatched payload IDs discovered by watch/gather."""

    def __init__(self, cache_path: Path) -> None:
        self._path = cache_path
        self._lock = threading.Lock()
        self._records: Dict[str, Dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            self._records = {}
            return
        except (OSError, json.JSONDecodeError):
            self._records = {}
            return
        if isinstance(data, list):
            tmp: Dict[str, Dict[str, Any]] = {}
            for entry in data:
                if not isinstance(entry, Mapping):
                    continue
                payload_id = entry.get("payload_id")
                if not isinstance(payload_id, str) or not payload_id:
                    continue
                plugin_value = entry.get("plugin")
                plugin = plugin_value if isinstance(plugin_value, str) and plugin_value else None
                group_value = entry.get("group")
                group = group_value if isinstance(group_value, str) and group_value else None
                payload_data = entry.get("payload")
                payload_snapshot: Optional[Mapping[str, Any]]
                if isinstance(payload_data, Mapping):
                    payload_snapshot = dict(payload_data)
                else:
                    payload_snapshot = None
                tmp[payload_id] = {"plugin": plugin, "group": group, "payload": payload_snapshot}
            self._records = tmp

    def _save(self) -> None:
        payloads: List[Dict[str, Any]] = []
        for pid, data in sorted(self._records.items(), key=lambda item: item[0].casefold()):
            entry: Dict[str, Any] = {"payload_id": pid}
            plugin = data.get("plugin")
            if plugin:
                entry["plugin"] = plugin
            group = data.get("group")
            if group:
                entry["group"] = group
            payload_value = data.get("payload")
            if payload_value is not None:
                entry["payload"] = payload_value
            payloads.append(entry)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(payloads, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    def add(self, record: PayloadRecord) -> bool:
        payload_id = record.payload_id.strip()
        if not payload_id:
            return False
        plugin = record.plugin.strip() if isinstance(record.plugin, str) and record.plugin.strip() else None
        group = record.group.strip() if isinstance(record.group, str) and record.group.strip() else None
        payload_snapshot = dict(record.payload) if isinstance(record.payload, Mapping) else None
        with self._lock:
            if payload_id in self._records:
                entry = self._records[payload_id]
                if plugin and not entry.get("plugin"):
                    entry["plugin"] = plugin
                if group and not entry.get("group"):
                    entry["group"] = group
                if payload_snapshot and not entry.get("payload"):
                    entry["payload"] = payload_snapshot
                self._save()
                return False
            self._records[payload_id] = {"plugin": plugin, "group": group, "payload": payload_snapshot}
            self._save()
            return True

    def records(self) -> List[PayloadRecord]:
        with self._lock:
            snapshot = [
                PayloadRecord(
                    payload_id=pid,
                    plugin=data.get("plugin"),
                    payload=data.get("payload"),
                    group=data.get("group"),
                )
                for pid, data in sorted(self._records.items(), key=lambda item: item[0].casefold())
            ]
        return snapshot

    def get(self, payload_id: str) -> Optional[PayloadRecord]:
        with self._lock:
            data = self._records.get(payload_id)
            if data is None:
                return None
            return PayloadRecord(
                payload_id=payload_id,
                plugin=data.get("plugin"),
                payload=data.get("payload"),
                group=data.get("group"),
            )

    def remove(self, payload_id: str) -> bool:
        with self._lock:
            if payload_id in self._records:
                del self._records[payload_id]
                self._save()
                return True
        return False

    def remove_matched(self, matcher: "OverrideMatcher") -> int:
        removed = 0
        with self._lock:
            for payload_id, data in list(self._records.items()):
                if matcher.is_payload_grouped(data.get("plugin"), payload_id):
                    del self._records[payload_id]
                    removed += 1
            if removed:
                self._save()
        return removed

    def __len__(self) -> int:
        with self._lock:
            return len(self._records)


class OverrideMatcher:
    """Proxy around PluginOverrideManager for grouping lookups."""

    def __init__(self, config_path: Path) -> None:
        self._config_path = config_path
        self._logger = logging.getLogger("plugin-group-manager.override")
        self._logger.addHandler(logging.NullHandler())
        self._lock = threading.Lock()
        self._manager = PluginOverrideManager(config_path, self._logger)

    def is_payload_grouped(self, plugin: Optional[str], payload_id: Optional[str]) -> bool:
        if not payload_id:
            return False
        with self._lock:
            key = self._manager.grouping_key_for(plugin, payload_id)
            if key is None:
                return False
            _plugin_label, suffix = key
            return suffix is not None

    def refresh(self) -> None:
        with self._lock:
            self._manager.force_reload()

    def unmatched_group_for(self, plugin: Optional[str], payload_id: Optional[str]) -> Optional[str]:
        if not payload_id:
            return None
        with self._lock:
            key = self._manager.grouping_key_for(plugin, payload_id)
            if key is None:
                return None
            plugin_label, suffix = key
            if suffix is None:
                return plugin_label
        return None


class LogLocator:
    """Resolves payload log directories/files, mirroring plugin runtime logic."""

    def __init__(self, plugin_root: Path, override_dir: Optional[Path] = None) -> None:
        self._plugin_root = plugin_root.resolve()
        self._override_dir = override_dir
        self._log_dir = self._resolve_log_dir()

    @property
    def log_dir(self) -> Path:
        return self._log_dir

    def _resolve_log_dir(self) -> Path:
        if self._override_dir is not None:
            target = self._override_dir.expanduser()
            # If the override looks like a file, fall back to its parent directory.
            if target.suffix:
                target = target.parent
            target.mkdir(parents=True, exist_ok=True)
            return target

        plugin_root = self._plugin_root
        parents = plugin_root.parents
        candidates: List[Path] = []
        if len(parents) >= 2:
            candidates.append(parents[1] / "logs")
        if len(parents) >= 1:
            candidates.append(parents[0] / "logs")
        candidates.append(Path.cwd() / "logs")
        for base in candidates:
            target = base / PAYLOAD_LOG_DIR_NAME
            try:
                target.mkdir(parents=True, exist_ok=True)
                return target
            except OSError:
                continue
        fallback = plugin_root / "logs" / PAYLOAD_LOG_DIR_NAME
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback

    def primary_log_file(self) -> Optional[Path]:
        for name in PAYLOAD_LOG_BASENAMES:
            candidate = self._log_dir / name
            if candidate.exists():
                return candidate
        # fall back to first available rotated log
        rotated = self.all_log_files()
        return rotated[0] if rotated else None

    def all_log_files(self) -> List[Path]:
        files: Dict[str, Path] = {}
        for base in PAYLOAD_LOG_BASENAMES:
            for path in self._log_dir.glob(f"{base}*"):
                if path.is_file():
                    files[str(path)] = path
        return sorted(files.values())


class PayloadParser:
    """Extract payload metadata from log lines."""

    PAYLOAD_PATTERN = re.compile(
        r"Overlay payload(?: \[[^\]]+\])?(?: plugin=(?P<plugin>[^:]+))?: (?P<body>\{.*\})"
    )

    @classmethod
    def parse_line(cls, line: str) -> Optional[PayloadRecord]:
        if "Overlay payload" not in line or "Overlay legacy_raw" in line:
            return None
        match = cls.PAYLOAD_PATTERN.search(line)
        if not match:
            return None
        plugin = (match.group("plugin") or "").strip() or None
        body = match.group("body")
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            return None
        payload_id = cls._extract_payload_id(payload)
        if not payload_id:
            return None
        return PayloadRecord(payload_id=payload_id, plugin=plugin, payload=payload)

    @staticmethod
    def _extract_payload_id(payload: Mapping[str, object]) -> Optional[str]:
        primary = payload.get("id")
        if isinstance(primary, str) and primary:
            return primary
        raw = payload.get("raw")
        if isinstance(raw, Mapping):
            raw_id = raw.get("id")
            if isinstance(raw_id, str) and raw_id:
                return raw_id
        legacy = payload.get("legacy_raw")
        if isinstance(legacy, Mapping):
            legacy_id = legacy.get("id")
            if isinstance(legacy_id, str) and legacy_id:
                return legacy_id
        return None


class PayloadWatcher(threading.Thread):
    """Background tailer for the latest overlay payload log."""

    def __init__(
        self,
        locator: LogLocator,
        matcher: OverrideMatcher,
        store: NewPayloadStore,
        outbox: "queue.Queue[Tuple[str, object]]",
    ) -> None:
        super().__init__(daemon=True)
        self._locator = locator
        self._matcher = matcher
        self._store = store
        self._queue = outbox
        self._stop_event = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        while not self._stop_event.is_set():
            log_path = self._locator.primary_log_file()
            if log_path is None:
                self._queue.put(("status", "Waiting for overlay-payloads.log..."))
                time.sleep(2.0)
                continue
            try:
                stream = log_path.open("r", encoding="utf-8")
                stream.seek(0, os.SEEK_END)
                current_inode = log_path.stat().st_ino
                self._queue.put(("status", f"Tailing {log_path.name}"))
            except OSError as exc:
                self._queue.put(("error", f"Watcher cannot open {log_path}: {exc}"))
                time.sleep(2.0)
                continue
            try:
                while not self._stop_event.is_set():
                    line = stream.readline()
                    if line:
                        record = PayloadParser.parse_line(line)
                        if not record:
                            continue
                        unmatched_group = self._matcher.unmatched_group_for(record.plugin, record.payload_id)
                        if not self._matcher.is_payload_grouped(record.plugin, record.payload_id):
                            enriched = record if unmatched_group is None else record.with_group(unmatched_group)
                            if self._store.add(enriched):
                                self._queue.put(("payload_added", enriched))
                        continue
                    time.sleep(0.5)
                    try:
                        stat = log_path.stat()
                        if stat.st_ino != current_inode or stat.st_size < stream.tell():
                            self._queue.put(("status", "Log rotated, reopening..."))
                            break
                    except FileNotFoundError:
                        self._queue.put(("status", "Log rotated, reopening..."))
                        break
            finally:
                try:
                    stream.close()
                except Exception:
                    pass
        self._queue.put(("status", "Watcher stopped."))


class LogGatherer(threading.Thread):
    """Offline gatherer that scrapes every overlay payload log."""

    def __init__(
        self,
        locator: LogLocator,
        matcher: OverrideMatcher,
        store: NewPayloadStore,
        outbox: "queue.Queue[Tuple[str, object]]",
    ) -> None:
        super().__init__(daemon=True)
        self._locator = locator
        self._matcher = matcher
        self._store = store
        self._queue = outbox

    def run(self) -> None:
        files = self._locator.all_log_files()
        added = 0
        for path in files:
            try:
                with path.open("r", encoding="utf-8") as stream:
                    for line in stream:
                        record = PayloadParser.parse_line(line)
                        if not record:
                            continue
                        unmatched_group = self._matcher.unmatched_group_for(record.plugin, record.payload_id)
                        if not self._matcher.is_payload_grouped(record.plugin, record.payload_id):
                            enriched = record if unmatched_group is None else record.with_group(unmatched_group)
                            if self._store.add(enriched):
                                added += 1
            except OSError as exc:
                self._queue.put(("error", f"Failed to read {path}: {exc}"))
        self._queue.put(("gather_complete", {"added": added, "files": len(files)}))


def _normalise_notes(raw_notes: Optional[str]) -> List[str]:
    if not raw_notes:
        return []
    lines = [line.strip() for line in raw_notes.splitlines()]
    return [line for line in lines if line]


def _clean_prefixes(prefix_text: str) -> List[str]:
    if not prefix_text:
        return []
    prefixes = [token.strip() for token in prefix_text.split(",")]
    return [prefix for prefix in prefixes if prefix]


def _parse_id_prefix_text(prefix_text: str) -> List[PrefixEntry]:
    if not prefix_text:
        return []
    entries: List[PrefixEntry] = []
    seen: set[Tuple[str, str]] = set()
    for raw_token in prefix_text.split(","):
        token = raw_token.strip()
        if not token:
            continue
        match_mode = MATCH_MODE_STARTSWITH
        lower_token = token.casefold()
        if token.startswith("="):
            token = token[1:].strip()
            match_mode = MATCH_MODE_EXACT
        elif lower_token.endswith("=exact"):
            token = token[: -len("=exact")].strip()
            match_mode = MATCH_MODE_EXACT
        elif lower_token.endswith(" (exact)"):
            token = token[: -len(" (exact)")].strip()
            match_mode = MATCH_MODE_EXACT
        if not token:
            raise ValueError("ID prefixes must contain non-empty values.")
        entry = PrefixEntry(value=token, match_mode=match_mode)
        if entry.key in seen:
            continue
        entries.append(entry)
        seen.add(entry.key)
    return entries


def _format_id_prefix_entries(entries: Sequence[PrefixEntry]) -> str:
    tokens: List[str] = []
    for entry in entries:
        if entry.match_mode == MATCH_MODE_EXACT:
            tokens.append(f"={entry.value}")
        else:
            tokens.append(entry.value)
    return ", ".join(tokens)


class GroupConfigStore:
    """Helper around overlay_groupings.json mutations."""

    def __init__(self, path: Path) -> None:
        self._path = path
        # RLock avoids deadlocks when save() is called from other locked methods.
        self._lock = threading.RLock()
        self._data: Dict[str, MutableMapping[str, object]] = {}
        self._mtime: Optional[float] = None
        register_grouping_store(self._path)
        self._load()

    def _current_mtime(self) -> Optional[float]:
        try:
            return self._path.stat().st_mtime
        except OSError:
            return None

    def _load(self) -> None:
        with self._lock:
            self._load_unlocked()
            self._mtime = self._current_mtime()

    def _load_unlocked(self) -> None:
        try:
            raw_text = self._path.read_text(encoding="utf-8")
        except FileNotFoundError:
            self._data = {}
            return
        except OSError:
            self._data = {}
            return
        try:
            data = json.loads(raw_text)
        except json.JSONDecodeError:
            self._data = {}
            return
        if not isinstance(data, Mapping):
            self._data = {}
            return
        cleaned: Dict[str, MutableMapping[str, object]] = {}
        for plugin_name, payload in data.items():
            if not isinstance(plugin_name, str) or not isinstance(payload, Mapping):
                continue
            cleaned[plugin_name] = self._normalise_plugin_entry(dict(payload))
        self._data = cleaned

    def _reload_from_disk(self) -> None:
        self._load_unlocked()
        self._mtime = self._current_mtime()

    @staticmethod
    def _apply_define_plugin_group(**kwargs: object) -> None:
        try:
            define_plugin_group(**kwargs)
        except PluginGroupingError as exc:
            raise ValueError(str(exc)) from exc

    def refresh_if_changed(self) -> bool:
        with self._lock:
            current_mtime = self._current_mtime()
            if current_mtime == self._mtime:
                return False
            self._load_unlocked()
            self._mtime = self._current_mtime()
            return True

    def _normalise_plugin_entry(self, entry: MutableMapping[str, object]) -> MutableMapping[str, object]:
        normalised: MutableMapping[str, object] = {}
        prefixes = self._normalise_prefix_list(entry.get("matchingPrefixes"))
        if not prefixes:
            legacy_match = entry.get("__match__")
            if isinstance(legacy_match, Mapping):
                prefixes = self._normalise_prefix_list(legacy_match.get("id_prefixes"))
        if prefixes:
            normalised["matchingPrefixes"] = prefixes

        groups = self._normalise_group_map(entry)
        if groups:
            normalised["idPrefixGroups"] = groups

        notes = entry.get("notes")
        if notes:
            normalised["notes"] = notes
        return normalised

    @staticmethod
    def _normalise_prefix_list(raw_value: Any) -> List[str]:
        values: List[str] = []
        if isinstance(raw_value, str):
            values = [raw_value]
        elif isinstance(raw_value, Iterable) and not isinstance(raw_value, (str, bytes)):
            values = [entry for entry in raw_value if isinstance(entry, str)]
        seen: List[str] = []
        cleaned: List[str] = []
        for token in values:
            stripped = token.strip()
            if stripped and stripped not in seen:
                seen.append(stripped)
                cleaned.append(stripped)
        return cleaned

    @staticmethod
    def _coerce_prefix_entries(raw_value: Any) -> List[PrefixEntry]:
        entries = parse_prefix_entries(raw_value)
        if not entries:
            raise ValueError("At least one ID prefix is required.")
        return entries

    def _normalise_group_map(self, entry: Mapping[str, object]) -> Dict[str, Dict[str, object]]:
        groups: Dict[str, Dict[str, object]] = {}

        raw_groups = entry.get("idPrefixGroups")
        if isinstance(raw_groups, Mapping):
            for label, spec in raw_groups.items():
                if not isinstance(spec, Mapping):
                    continue
                label_value = str(label).strip() if isinstance(label, str) and label else None
                normalised = self._normalise_group_spec(dict(spec))
                key = label_value or (normalised.get("idPrefixes") or [None])[0]
                if key:
                    groups[key] = normalised

        legacy_grouping = entry.get("grouping")
        if isinstance(legacy_grouping, Mapping):
            legacy_groups = legacy_grouping.get("groups")
            if isinstance(legacy_groups, Mapping):
                for label, spec in legacy_groups.items():
                    if not isinstance(spec, Mapping):
                        continue
                    label_value = str(label).strip() if isinstance(label, str) and label else None
                    normalised = self._normalise_group_spec(dict(spec))
                    key = label_value or (normalised.get("idPrefixes") or [None])[0]
                    if key and key not in groups:
                        groups[key] = normalised
            legacy_prefixes = legacy_grouping.get("prefixes")
            if isinstance(legacy_prefixes, Mapping):
                for label, value in legacy_prefixes.items():
                    label_value = str(label).strip() if isinstance(label, str) and label else None
                    spec: Dict[str, object]
                    if isinstance(value, str):
                        spec = {"idPrefixes": [value]}
                    elif isinstance(value, Mapping):
                        spec = dict(value)
                    else:
                        continue
                    normalised = self._normalise_group_spec(spec)
                    key = label_value or (normalised.get("idPrefixes") or [None])[0]
                    if key and key not in groups:
                        groups[key] = normalised
            elif isinstance(legacy_prefixes, Iterable):
                for entry_value in legacy_prefixes:
                    if isinstance(entry_value, str) and entry_value:
                        normalised = self._normalise_group_spec({"idPrefixes": [entry_value]})
                        key = normalised.get("idPrefixes", [None])[0]
                        if key and key not in groups:
                            groups[key] = normalised

        return groups

    @staticmethod
    def _normalise_anchor(value: Any) -> Optional[str]:
        if not isinstance(value, str):
            return None
        token = value.strip().lower()
        if not token:
            return None
        if token == "first":
            token = "nw"
        elif token == "centroid":
            token = "center"
        if token in ANCHOR_CHOICES:
            return token
        return None

    @staticmethod
    def _normalise_justification(value: Any) -> Optional[str]:
        if not isinstance(value, str):
            return None
        token = value.strip().lower()
        if not token:
            return None
        if token in PAYLOAD_JUSTIFICATION_CHOICES:
            return token
        return None

    @staticmethod
    def _normalise_marker_label_position(value: Any) -> Optional[str]:
        if not isinstance(value, str):
            return None
        token = value.strip().lower()
        if not token:
            return None
        if token in MARKER_LABEL_POSITION_CHOICES:
            return token
        return None

    @staticmethod
    def _normalise_controller_preview_box_mode(value: Any) -> Optional[str]:
        if not isinstance(value, str):
            return None
        token = value.strip().lower()
        if not token:
            return None
        if token in CONTROLLER_PREVIEW_BOX_MODE_CHOICES:
            return token
        return None

    @staticmethod
    def _clean_offset_value(value: Any) -> Optional[float]:
        numeric: Optional[float]
        if isinstance(value, (int, float)):
            numeric = float(value)
        elif isinstance(value, str):
            token = value.strip()
            if not token:
                return None
            try:
                numeric = float(token)
            except ValueError:
                return None
        else:
            return None
        if not math.isfinite(numeric):
            return None
        if numeric.is_integer():
            return int(numeric)
        return numeric

    @classmethod
    def _coerce_offset_value(cls, value: Any, label: str) -> Optional[float]:
        if value is None:
            return None
        if isinstance(value, str) and not value.strip():
            return None
        cleaned = cls._clean_offset_value(value)
        if cleaned is None:
            raise ValueError(f"{label} must be a number.")
        return cleaned

    def _normalise_group_spec(self, spec: MutableMapping[str, object]) -> Dict[str, object]:
        prefix_entries = parse_prefix_entries(
            spec.get("idPrefixes")
            or spec.get("id_prefixes")
            or spec.get("prefixes")
            or spec.get("prefix")
            or []
        )
        cleaned: Dict[str, object] = {}
        if prefix_entries:
            cleaned["idPrefixes"] = serialise_prefix_entries(prefix_entries)
        anchor_token = self._normalise_anchor(spec.get("idPrefixGroupAnchor") or spec.get("anchor"))
        if anchor_token:
            cleaned["idPrefixGroupAnchor"] = anchor_token
        offset_x = self._clean_offset_value(spec.get("offsetX") or spec.get("offset_x"))
        if offset_x is not None:
            cleaned["offsetX"] = offset_x
        offset_y = self._clean_offset_value(spec.get("offsetY") or spec.get("offset_y"))
        if offset_y is not None:
            cleaned["offsetY"] = offset_y
        justification = self._normalise_justification(
            spec.get("payloadJustification") or spec.get("payload_justification") or spec.get("justification")
        )
        if justification:
            cleaned["payloadJustification"] = justification
        marker_label_position = self._normalise_marker_label_position(
            spec.get("markerLabelPosition") or spec.get("marker_label_position")
        )
        if marker_label_position:
            cleaned["markerLabelPosition"] = marker_label_position
        controller_preview_box_mode = self._normalise_controller_preview_box_mode(
            spec.get("controllerPreviewBoxMode") or spec.get("controller_preview_box_mode")
        )
        if controller_preview_box_mode:
            cleaned["controllerPreviewBoxMode"] = controller_preview_box_mode
        if "backgroundColor" in spec or "background_color" in spec:
            raw_color = spec.get("backgroundColor") or spec.get("background_color")
            if raw_color is None:
                cleaned["backgroundColor"] = None
            else:
                try:
                    cleaned["backgroundColor"] = _normalise_background_color(raw_color)
                except PluginGroupingError:
                    pass
        if "backgroundBorderColor" in spec or "background_border_color" in spec:
            raw_border_color = spec.get("backgroundBorderColor") or spec.get("background_border_color")
            if raw_border_color is None:
                cleaned["backgroundBorderColor"] = None
            else:
                try:
                    cleaned["backgroundBorderColor"] = _normalise_background_color(raw_border_color)
                except PluginGroupingError:
                    pass
        if "backgroundBorderWidth" in spec or "background_border_width" in spec:
            raw_border = spec.get("backgroundBorderWidth") or spec.get("background_border_width")
            if raw_border is None:
                cleaned["backgroundBorderWidth"] = None
            else:
                try:
                    cleaned["backgroundBorderWidth"] = _normalise_border_width(raw_border, "backgroundBorderWidth")
                except PluginGroupingError:
                    pass
        notes_value = spec.get("notes")
        if isinstance(notes_value, str) and notes_value.strip():
            cleaned["notes"] = notes_value.strip()
        return cleaned

    def save(self) -> None:
        with self._lock:
            ordered = {name: self._data[name] for name in sorted(self._data.keys())}
            self._path.write_text(json.dumps(ordered, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            self._mtime = self._current_mtime()

    def list_groups(self) -> List[str]:
        with self._lock:
            return sorted(self._data.keys(), key=str.casefold)

    def get_group(self, name: str) -> Optional[MutableMapping[str, object]]:
        with self._lock:
            entry = self._data.get(name)
            return dict(entry) if entry else None

    def iter_group_views(self) -> List[Dict[str, object]]:
        views: List[Dict[str, object]] = []
        with self._lock:
            for name in sorted(self._data.keys(), key=str.casefold):
                entry = self._data[name]
                groups_block = entry.get("idPrefixGroups", {})
                view_entries: List[Dict[str, object]] = []
                match_prefixes: List[str] = []

                def _append_prefix(token: object) -> None:
                    if isinstance(token, (str, int, float)):
                        cleaned = str(token).strip()
                        if cleaned and cleaned not in match_prefixes:
                            match_prefixes.append(cleaned)

                match_values = entry.get("matchingPrefixes")
                if isinstance(match_values, str):
                    _append_prefix(match_values)
                elif isinstance(match_values, Iterable) and not isinstance(match_values, (str, bytes)):
                    for token in match_values:
                        _append_prefix(token)

                if isinstance(groups_block, Mapping):
                    for label in sorted(groups_block.keys(), key=str.casefold):
                        spec = groups_block[label]
                        if not isinstance(spec, Mapping):
                            continue
                        prefixes_value = spec.get("idPrefixes") or spec.get("id_prefixes") or []
                        prefix_entries = parse_prefix_entries(prefixes_value)
                        display_prefixes = [entry.display_label() for entry in prefix_entries]
                        anchor = spec.get("idPrefixGroupAnchor") or spec.get("anchor") or ""
                        notes = spec.get("notes") or ""
                        raw_justification = spec.get("payloadJustification")
                        if isinstance(raw_justification, str) and raw_justification.strip():
                            justification = raw_justification.strip().lower()
                        else:
                            justification = DEFAULT_PAYLOAD_JUSTIFICATION
                        if justification not in PAYLOAD_JUSTIFICATION_CHOICES:
                            justification = DEFAULT_PAYLOAD_JUSTIFICATION
                        raw_marker_label_position = spec.get("markerLabelPosition")
                        if isinstance(raw_marker_label_position, str) and raw_marker_label_position.strip():
                            marker_label_position = raw_marker_label_position.strip().lower()
                        else:
                            marker_label_position = DEFAULT_MARKER_LABEL_POSITION
                        if marker_label_position not in MARKER_LABEL_POSITION_CHOICES:
                            marker_label_position = DEFAULT_MARKER_LABEL_POSITION
                        raw_preview_mode = spec.get("controllerPreviewBoxMode")
                        if isinstance(raw_preview_mode, str) and raw_preview_mode.strip():
                            controller_preview_box_mode = raw_preview_mode.strip().lower()
                        else:
                            controller_preview_box_mode = DEFAULT_CONTROLLER_PREVIEW_BOX_MODE
                        if controller_preview_box_mode not in CONTROLLER_PREVIEW_BOX_MODE_CHOICES:
                            controller_preview_box_mode = DEFAULT_CONTROLLER_PREVIEW_BOX_MODE
                        view_entries.append(
                            {
                                "label": label,
                                "prefixes": display_prefixes,
                                "prefixEntries": [entry.to_mapping() for entry in prefix_entries],
                                "anchor": anchor,
                                "offsetX": spec.get("offsetX"),
                                "offsetY": spec.get("offsetY"),
                                "payloadJustification": justification,
                                "markerLabelPosition": marker_label_position,
                                "controllerPreviewBoxMode": controller_preview_box_mode,
                                "backgroundColor": spec.get("backgroundColor"),
                                "backgroundBorderColor": spec.get("backgroundBorderColor"),
                                "backgroundBorderWidth": spec.get("backgroundBorderWidth"),
                                "notes": notes,
                            }
                        )
                notes = entry.get("notes") or []
                note_text = ""
                if isinstance(notes, Sequence) and not isinstance(notes, str):
                    note_text = "\n".join(str(item) for item in notes if item)
                elif isinstance(notes, str):
                    note_text = notes
                views.append(
                    {
                        "name": name,
                        "notes": note_text,
                        "groupings": view_entries,
                        "match_prefixes": match_prefixes,
                    }
                )
        return views

    def add_group(
        self,
        name: str,
        notes: Optional[str],
        initial_grouping: Optional[Dict[str, object]] = None,
        match_prefixes: Optional[Sequence[str]] = None,
    ) -> None:
        cleaned_name = name.strip()
        if not cleaned_name:
            raise ValueError("Group name is required.")
        with self._lock:
            if cleaned_name in self._data:
                raise ValueError(f"Group '{cleaned_name}' already exists.")
            cleaned_match = self._normalise_prefix_list(match_prefixes or [])
            cleaned_notes = _normalise_notes(notes)
            initial_label: Optional[str] = None
            initial_prefixes: Optional[List[object]] = None
            initial_anchor: Optional[str] = None
            initial_notes: Optional[str] = None
            if initial_grouping:
                label = initial_grouping.get("label")
                if isinstance(label, str) and label.strip():
                    initial_label = label.strip()
                    raw_prefixes = (
                        initial_grouping.get("idPrefixes")
                        or initial_grouping.get("id_prefixes")
                        or initial_grouping.get("prefixes")
                        or []
                    )
                    parsed_prefixes = parse_prefix_entries(raw_prefixes)
                    if parsed_prefixes:
                        initial_prefixes = serialise_prefix_entries(parsed_prefixes)
                    anchor_value = initial_grouping.get("anchor")
                    if isinstance(anchor_value, str) and anchor_value.strip():
                        initial_anchor = anchor_value.strip()
                    notes_value = initial_grouping.get("notes")
                    if isinstance(notes_value, str) and notes_value.strip():
                        initial_notes = notes_value.strip()

            if not cleaned_match and initial_prefixes:
                cleaned_match = self._normalise_prefix_list(initial_prefixes)

            update_kwargs: Dict[str, object] = {}
            if cleaned_match:
                update_kwargs["matching_prefixes"] = cleaned_match
            if initial_label and initial_prefixes:
                update_kwargs["id_prefix_group"] = initial_label
                update_kwargs["id_prefixes"] = initial_prefixes
                if initial_anchor:
                    update_kwargs["id_prefix_group_anchor"] = initial_anchor

            if update_kwargs:
                update_kwargs["plugin_group"] = cleaned_name
                self._apply_define_plugin_group(**update_kwargs)
                self._reload_from_disk()
                entry = self._data.get(cleaned_name, {})
                if cleaned_notes:
                    entry["notes"] = cleaned_notes
                elif notes is not None:
                    entry.pop("notes", None)
                if initial_label and initial_notes:
                    groups = entry.setdefault("idPrefixGroups", {})
                    group_entry = groups.get(initial_label, {})
                    if isinstance(group_entry, Mapping):
                        group_entry = dict(group_entry)
                    group_entry["notes"] = initial_notes
                    groups[initial_label] = group_entry
                self._data[cleaned_name] = entry
                self.save()
                return

            grouping_block: Dict[str, Dict[str, object]] = {}
            if initial_label:
                entry_spec = self._normalise_group_spec(
                    {
                        "idPrefixes": initial_prefixes or [],
                        "idPrefixGroupAnchor": initial_anchor,
                        "notes": initial_notes,
                    }
                )
                grouping_block[initial_label] = entry_spec
            entry: Dict[str, object] = {"idPrefixGroups": grouping_block}
            if cleaned_match:
                entry["matchingPrefixes"] = cleaned_match
            if cleaned_notes:
                entry["notes"] = cleaned_notes
            self._data[cleaned_name] = entry
            self.save()

    def delete_group(self, name: str) -> None:
        with self._lock:
            if name in self._data:
                del self._data[name]
                self.save()

    def update_group(
        self,
        original_name: str,
        *,
        new_name: Optional[str] = None,
        match_prefixes: Optional[Sequence[str]] = None,
        notes: Optional[str] = None,
    ) -> None:
        cleaned_original = original_name.strip()
        if not cleaned_original:
            raise ValueError("Group name is required.")
        with self._lock:
            entry = self._data.get(cleaned_original)
            if not entry:
                raise ValueError(f"Group '{original_name}' not found.")
            target_name = new_name.strip() if isinstance(new_name, str) and new_name.strip() else cleaned_original
            if target_name != cleaned_original and target_name in self._data:
                raise ValueError(f"Group '{target_name}' already exists.")

            if match_prefixes is not None:
                cleaned_matches = self._normalise_prefix_list(match_prefixes)
                if cleaned_matches:
                    self._apply_define_plugin_group(
                        plugin_group=cleaned_original,
                        matching_prefixes=cleaned_matches,
                    )
                    self._reload_from_disk()
                    entry = self._data.get(cleaned_original, {})
                else:
                    entry.pop("matchingPrefixes", None)

            if notes is not None:
                cleaned_notes = _normalise_notes(notes)
                if cleaned_notes:
                    entry["notes"] = cleaned_notes
                else:
                    entry.pop("notes", None)

            if target_name != cleaned_original:
                self._data[target_name] = entry
                del self._data[cleaned_original]
            self.save()

    def add_grouping(
        self,
        group_name: str,
        label: str,
        prefixes: Sequence[str],
        anchor: Optional[str],
        notes: Optional[str],
        offset_x: Optional[object] = None,
        offset_y: Optional[object] = None,
        payload_justification: Optional[str] = None,
        marker_label_position: Optional[str] = None,
        controller_preview_box_mode: Optional[str] = None,
        background_color: Optional[str] = None,
        background_border_color: Optional[str] = None,
        background_border_width: Optional[object] = None,
    ) -> None:
        prefix_entries = self._coerce_prefix_entries(prefixes)
        serialised_prefixes = serialise_prefix_entries(prefix_entries)
        cleaned_label = label.strip()
        if not cleaned_label:
            raise ValueError("Grouping label is required.")
        anchor_token = anchor.strip().lower() if isinstance(anchor, str) else None
        if anchor_token and anchor_token not in ANCHOR_CHOICES:
            raise ValueError(f"Anchor must be one of {', '.join(ANCHOR_CHOICES)}.")
        offset_x_value = self._coerce_offset_value(offset_x, "Offset X") if offset_x is not None else None
        offset_y_value = self._coerce_offset_value(offset_y, "Offset Y") if offset_y is not None else None
        justification_token = (
            self._normalise_justification(payload_justification) if payload_justification is not None else None
        )
        if not justification_token:
            justification_token = DEFAULT_PAYLOAD_JUSTIFICATION
        marker_label_position_token = (
            self._normalise_marker_label_position(marker_label_position) if marker_label_position is not None else None
        )
        if not marker_label_position_token:
            marker_label_position_token = DEFAULT_MARKER_LABEL_POSITION
        controller_preview_box_mode_token = (
            self._normalise_controller_preview_box_mode(controller_preview_box_mode)
            if controller_preview_box_mode is not None
            else None
        )
        if not controller_preview_box_mode_token:
            controller_preview_box_mode_token = DEFAULT_CONTROLLER_PREVIEW_BOX_MODE
        try:
            normalized_color = _normalise_background_color(background_color) if background_color is not None else None
        except PluginGroupingError as exc:
            raise ValueError(str(exc)) from exc
        try:
            normalized_border_color = (
                _normalise_background_color(background_border_color) if background_border_color is not None else None
            )
        except PluginGroupingError as exc:
            raise ValueError(str(exc)) from exc
        try:
            normalized_border = (
                _normalise_border_width(background_border_width, "backgroundBorderWidth")
                if background_border_width is not None
                else None
            )
        except PluginGroupingError as exc:
            raise ValueError(str(exc)) from exc
        with self._lock:
            entry = self._data.get(group_name)
            if not entry:
                raise ValueError(f"Group '{group_name}' not found.")
            groups = entry.setdefault("idPrefixGroups", {})
            if not isinstance(groups, dict):
                entry["idPrefixGroups"] = {}
                groups = entry["idPrefixGroups"]
            if cleaned_label in groups:
                raise ValueError(f"Grouping '{cleaned_label}' already exists for '{group_name}'.")
            update_kwargs: Dict[str, object] = {
                "plugin_group": group_name,
                "id_prefix_group": cleaned_label,
                "id_prefixes": serialised_prefixes,
            }
            if anchor_token:
                update_kwargs["id_prefix_group_anchor"] = anchor_token
            if offset_x_value is not None:
                update_kwargs["id_prefix_offset_x"] = offset_x_value
            if offset_y_value is not None:
                update_kwargs["id_prefix_offset_y"] = offset_y_value
            if justification_token:
                update_kwargs["payload_justification"] = justification_token
            if marker_label_position_token:
                update_kwargs["marker_label_position"] = marker_label_position_token
            if controller_preview_box_mode_token:
                update_kwargs["controller_preview_box_mode"] = controller_preview_box_mode_token
            if background_color is not None:
                update_kwargs["background_color"] = normalized_color
            if background_border_color is not None:
                update_kwargs["background_border_color"] = normalized_border_color
            if background_border_width is not None:
                update_kwargs["background_border_width"] = normalized_border

            self._apply_define_plugin_group(**update_kwargs)
            self._reload_from_disk()
            entry = self._data.get(group_name, {})
            groups = entry.setdefault("idPrefixGroups", {})
            if isinstance(groups, Mapping):
                group_entry = groups.get(cleaned_label, {})
                if isinstance(group_entry, Mapping):
                    group_entry = dict(group_entry)
                cleaned_notes = notes.strip() if isinstance(notes, str) else None
                if cleaned_notes:
                    group_entry["notes"] = cleaned_notes
                    groups[cleaned_label] = group_entry
                self._data[group_name] = entry
                self.save()

    def update_grouping(
        self,
        group_name: str,
        label: str,
        *,
        new_label: Optional[str] = None,
        prefixes: Optional[Sequence[str]] = None,
        anchor: Optional[str] = None,
        notes: Optional[str] = None,
        offset_x: Optional[object] = None,
        offset_y: Optional[object] = None,
        payload_justification: Optional[object] = None,
        marker_label_position: Optional[object] = None,
        controller_preview_box_mode: Optional[object] = None,
        background_color: object = _MISSING,
        background_border_color: object = _MISSING,
        background_border_width: object = _MISSING,
    ) -> None:
        original_label = label.strip()
        if not original_label:
            raise ValueError("Existing grouping label is required.")
        replacement_label = new_label.strip() if isinstance(new_label, str) and new_label.strip() else original_label
        with self._lock:
            entry = self._data.get(group_name)
            if not entry:
                raise ValueError(f"Group '{group_name}' not found.")
            groups = entry.get("idPrefixGroups")
            if not isinstance(groups, dict) or original_label not in groups:
                raise ValueError(f"Grouping '{original_label}' not found in '{group_name}'.")
            target_spec = groups[original_label]
            if not isinstance(target_spec, MutableMapping):
                target_spec = {}
                groups[original_label] = target_spec

            prefix_entries: Optional[List[PrefixEntry]] = None
            if prefixes is not None:
                prefix_entries = self._coerce_prefix_entries(prefixes)
            elif replacement_label != original_label:
                existing_prefixes = parse_prefix_entries(target_spec.get("idPrefixes") or [])
                if not existing_prefixes:
                    raise ValueError("At least one ID prefix is required.")
                prefix_entries = existing_prefixes

            anchor_value: Optional[str] = None
            clear_anchor = False
            if anchor is not None:
                anchor_token = anchor.strip().lower()
                if anchor_token:
                    if anchor_token not in ANCHOR_CHOICES:
                        raise ValueError(f"Anchor must be one of {', '.join(ANCHOR_CHOICES)}.")
                    anchor_value = anchor_token
                else:
                    clear_anchor = True
            elif replacement_label != original_label:
                existing_anchor = target_spec.get("idPrefixGroupAnchor")
                if isinstance(existing_anchor, str) and existing_anchor.strip():
                    anchor_value = existing_anchor.strip().lower()

            offset_x_value: Optional[float] = None
            clear_offset_x = False
            if offset_x is not None:
                offset_x_value = self._coerce_offset_value(offset_x, "Offset X")
                if offset_x_value is None:
                    clear_offset_x = True
            elif replacement_label != original_label and "offsetX" in target_spec:
                existing_offset_x = target_spec.get("offsetX")
                if isinstance(existing_offset_x, (int, float)):
                    offset_x_value = float(existing_offset_x)

            offset_y_value: Optional[float] = None
            clear_offset_y = False
            if offset_y is not None:
                offset_y_value = self._coerce_offset_value(offset_y, "Offset Y")
                if offset_y_value is None:
                    clear_offset_y = True
            elif replacement_label != original_label and "offsetY" in target_spec:
                existing_offset_y = target_spec.get("offsetY")
                if isinstance(existing_offset_y, (int, float)):
                    offset_y_value = float(existing_offset_y)

            justification_value: Optional[str] = None
            clear_justification = False
            if payload_justification is not None:
                justification_token = self._normalise_justification(payload_justification)
                if justification_token:
                    justification_value = justification_token
                else:
                    clear_justification = True
            elif replacement_label != original_label:
                existing_justification = target_spec.get("payloadJustification")
                if isinstance(existing_justification, str) and existing_justification.strip():
                    justification_value = existing_justification.strip().lower()

            marker_label_position_value: Optional[str] = None
            clear_marker_label_position = False
            if marker_label_position is not None:
                marker_label_position_token = self._normalise_marker_label_position(marker_label_position)
                if marker_label_position_token:
                    marker_label_position_value = marker_label_position_token
                else:
                    clear_marker_label_position = True
            elif replacement_label != original_label:
                existing_marker = target_spec.get("markerLabelPosition")
                if isinstance(existing_marker, str) and existing_marker.strip():
                    marker_label_position_value = existing_marker.strip().lower()

            controller_preview_value: Optional[str] = None
            clear_controller_preview = False
            if controller_preview_box_mode is not None:
                preview_mode_token = self._normalise_controller_preview_box_mode(controller_preview_box_mode)
                if preview_mode_token:
                    controller_preview_value = preview_mode_token
                else:
                    clear_controller_preview = True
            elif replacement_label != original_label:
                existing_preview = target_spec.get("controllerPreviewBoxMode")
                if isinstance(existing_preview, str) and existing_preview.strip():
                    controller_preview_value = existing_preview.strip().lower()

            background_color_value: Optional[str] = None
            set_background_color_none = False
            if background_color is not _MISSING:
                if background_color is None or background_color == "":
                    set_background_color_none = True
                else:
                    try:
                        background_color_value = _normalise_background_color(background_color)
                    except PluginGroupingError as exc:
                        raise ValueError(str(exc)) from exc
            elif replacement_label != original_label and "backgroundColor" in target_spec:
                existing_color = target_spec.get("backgroundColor")
                if existing_color is None:
                    set_background_color_none = True
                else:
                    try:
                        background_color_value = _normalise_background_color(existing_color)
                    except PluginGroupingError as exc:
                        raise ValueError(str(exc)) from exc

            background_border_color_value: Optional[str] = None
            set_background_border_color_none = False
            if background_border_color is not _MISSING:
                if background_border_color is None or background_border_color == "":
                    set_background_border_color_none = True
                else:
                    try:
                        background_border_color_value = _normalise_background_color(background_border_color)
                    except PluginGroupingError as exc:
                        raise ValueError(str(exc)) from exc
            elif replacement_label != original_label and "backgroundBorderColor" in target_spec:
                existing_border_color = target_spec.get("backgroundBorderColor")
                if existing_border_color is None:
                    set_background_border_color_none = True
                else:
                    try:
                        background_border_color_value = _normalise_background_color(existing_border_color)
                    except PluginGroupingError as exc:
                        raise ValueError(str(exc)) from exc

            background_border_value: Optional[int] = None
            clear_background_border = False
            if background_border_width is not _MISSING:
                if background_border_width is None or background_border_width == "":
                    clear_background_border = True
                else:
                    try:
                        background_border_value = _normalise_border_width(background_border_width, "backgroundBorderWidth")
                    except PluginGroupingError as exc:
                        raise ValueError(str(exc)) from exc
            elif replacement_label != original_label and "backgroundBorderWidth" in target_spec:
                existing_border = target_spec.get("backgroundBorderWidth")
                if existing_border is None:
                    clear_background_border = True
                else:
                    try:
                        background_border_value = _normalise_border_width(existing_border, "backgroundBorderWidth")
                    except PluginGroupingError as exc:
                        raise ValueError(str(exc)) from exc

            use_api = (
                prefix_entries is not None
                or anchor_value is not None
                or offset_x_value is not None
                or offset_y_value is not None
                or justification_value is not None
                or marker_label_position_value is not None
                or controller_preview_value is not None
                or background_color_value is not None
                or background_border_color_value is not None
                or background_border_value is not None
                or replacement_label != original_label
            )

            if use_api:
                if replacement_label != original_label and replacement_label in groups:
                    raise ValueError(f"Grouping '{replacement_label}' already exists for '{group_name}'.")
                update_kwargs: Dict[str, object] = {
                    "plugin_group": group_name,
                    "id_prefix_group": replacement_label,
                }
                if prefix_entries is not None:
                    update_kwargs["id_prefixes"] = serialise_prefix_entries(prefix_entries)
                if anchor_value is not None:
                    update_kwargs["id_prefix_group_anchor"] = anchor_value
                if offset_x_value is not None:
                    update_kwargs["id_prefix_offset_x"] = offset_x_value
                if offset_y_value is not None:
                    update_kwargs["id_prefix_offset_y"] = offset_y_value
                if justification_value is not None:
                    update_kwargs["payload_justification"] = justification_value
                if marker_label_position_value is not None:
                    update_kwargs["marker_label_position"] = marker_label_position_value
                if controller_preview_value is not None:
                    update_kwargs["controller_preview_box_mode"] = controller_preview_value
                if background_color_value is not None:
                    update_kwargs["background_color"] = background_color_value
                if background_border_color_value is not None:
                    update_kwargs["background_border_color"] = background_border_color_value
                if background_border_value is not None:
                    update_kwargs["background_border_width"] = background_border_value

                self._apply_define_plugin_group(**update_kwargs)
                self._reload_from_disk()
                entry = self._data.get(group_name, {})
                groups = entry.get("idPrefixGroups")
                if not isinstance(groups, dict):
                    raise ValueError(f"Group '{group_name}' no longer exists.")
                target_spec = groups.get(replacement_label, {})
                if not isinstance(target_spec, MutableMapping):
                    target_spec = {}
                if clear_anchor:
                    target_spec.pop("idPrefixGroupAnchor", None)
                if clear_offset_x:
                    target_spec.pop("offsetX", None)
                if clear_offset_y:
                    target_spec.pop("offsetY", None)
                if clear_justification:
                    target_spec.pop("payloadJustification", None)
                if clear_marker_label_position:
                    target_spec.pop("markerLabelPosition", None)
                if clear_controller_preview:
                    target_spec.pop("controllerPreviewBoxMode", None)
                if set_background_color_none:
                    target_spec["backgroundColor"] = None
                if set_background_border_color_none:
                    target_spec["backgroundBorderColor"] = None
                if clear_background_border:
                    target_spec.pop("backgroundBorderWidth", None)
                if notes is not None:
                    cleaned_notes = notes.strip()
                    if cleaned_notes:
                        target_spec["notes"] = cleaned_notes
                    else:
                        target_spec.pop("notes", None)
                groups[replacement_label] = target_spec
                if replacement_label != original_label and original_label in groups:
                    groups.pop(original_label, None)
                entry["idPrefixGroups"] = groups
                self._data[group_name] = entry
                self.save()
                return

            if clear_anchor:
                target_spec.pop("idPrefixGroupAnchor", None)
            if clear_offset_x:
                target_spec.pop("offsetX", None)
            if clear_offset_y:
                target_spec.pop("offsetY", None)
            if clear_justification:
                target_spec.pop("payloadJustification", None)
            if clear_marker_label_position:
                target_spec.pop("markerLabelPosition", None)
            if clear_controller_preview:
                target_spec.pop("controllerPreviewBoxMode", None)
            if set_background_color_none:
                target_spec["backgroundColor"] = None
            if set_background_border_color_none:
                target_spec["backgroundBorderColor"] = None
            if clear_background_border:
                target_spec.pop("backgroundBorderWidth", None)
            if notes is not None:
                cleaned_notes = notes.strip()
                if cleaned_notes:
                    target_spec["notes"] = cleaned_notes
                else:
                    target_spec.pop("notes", None)
            self.save()

    def delete_grouping(self, group_name: str, label: str) -> None:
        with self._lock:
            entry = self._data.get(group_name)
            if not entry:
                return
            groups = entry.get("idPrefixGroups")
            if not isinstance(groups, dict):
                return
            if label in groups:
                del groups[label]
                self.save()

class NewGroupDialog(simpledialog.Dialog):
    """Dialog for creating a brand new plugin group."""

    def __init__(self, parent: tk.Tk, title: str = "Create new group", suggestion: Optional[Mapping[str, object]] = None) -> None:
        self._suggestion = suggestion or {}
        super().__init__(parent, title=title)

    def body(self, master: tk.Tk) -> tk.Widget:  # type: ignore[override]
        ttk.Label(master, text="Group name").grid(row=0, column=0, sticky="w")
        default_name = str(self._suggestion.get("name") or "")
        self.name_var = tk.StringVar(value=default_name)
        ttk.Entry(master, textvariable=self.name_var, width=40).grid(row=0, column=1, sticky="ew")

        master.grid_columnconfigure(1, weight=1)
        ttk.Label(master, text="Match prefixes (comma separated)").grid(row=1, column=0, sticky="w")
        default_prefixes = ", ".join(self._suggestion.get("match_prefixes", [])) if self._suggestion else ""
        self.match_prefix_var = tk.StringVar(value=default_prefixes)
        ttk.Entry(master, textvariable=self.match_prefix_var, width=40).grid(row=1, column=1, sticky="ew")

        ttk.Label(master, text="Notes (optional)").grid(row=2, column=0, sticky="nw")
        self.notes_text = tk.Text(master, width=40, height=4, font=tkfont.nametofont("TkDefaultFont"))
        default_notes = str(self._suggestion.get("notes") or "")
        if default_notes:
            self.notes_text.insert("1.0", default_notes)
        self.notes_text.grid(row=2, column=1, sticky="nsew")
        master.rowconfigure(2, weight=1)
        return master

    def validate(self) -> bool:  # type: ignore[override]
        if not self.name_var.get().strip():
            messagebox.showerror("Validation error", "Group name is required.")
            return False
        if not _clean_prefixes(self.match_prefix_var.get()):
            messagebox.showerror("Validation error", "Enter at least one match prefix.")
            return False
        return True

    def result_data(self) -> Dict[str, object]:
        notes_text = self.notes_text.get("1.0", tk.END).strip()
        return {
            "name": self.name_var.get().strip(),
            "match_prefixes": _clean_prefixes(self.match_prefix_var.get()),
            "notes": notes_text,
        }

    def apply(self) -> None:  # type: ignore[override]
        self.result = self.result_data()


class EditGroupDialog(simpledialog.Dialog):
    """Dialog for editing plugin group metadata."""

    def __init__(self, parent: tk.Tk, group_name: str, entry: Mapping[str, object]) -> None:
        self._original_name = group_name
        self._entry = entry
        super().__init__(parent, title=f"Edit group '{group_name}'")

    def body(self, master: tk.Tk) -> tk.Widget:  # type: ignore[override]
        ttk.Label(master, text="Group name").grid(row=0, column=0, sticky="w")
        self.name_var = tk.StringVar(value=self._original_name)
        ttk.Entry(master, textvariable=self.name_var, width=40).grid(row=0, column=1, sticky="ew")

        current_matches: List[str] = []
        match_values = self._entry.get("matchingPrefixes")
        if isinstance(match_values, str):
            text = match_values.strip()
            if text:
                current_matches.append(text)
        elif isinstance(match_values, Iterable) and not isinstance(match_values, (str, bytes)):
            for token in match_values:
                if isinstance(token, (str, int, float)):
                    text = str(token).strip()
                    if text:
                        current_matches.append(text)
        master.grid_columnconfigure(1, weight=1)
        ttk.Label(master, text="Match prefixes (comma separated)").grid(row=1, column=0, sticky="w")
        self.match_prefix_var = tk.StringVar(value=", ".join(current_matches))
        ttk.Entry(master, textvariable=self.match_prefix_var, width=40).grid(row=1, column=1, sticky="ew")

        existing_notes = ""
        notes_entry = self._entry.get("notes")
        if isinstance(notes_entry, Sequence) and not isinstance(notes_entry, str):
            existing_notes = "\n".join(str(item) for item in notes_entry if item)
        elif isinstance(notes_entry, str):
            existing_notes = notes_entry
        ttk.Label(master, text="Notes (optional)").grid(row=2, column=0, sticky="nw")
        self.notes_text = tk.Text(master, width=40, height=4, font=tkfont.nametofont("TkDefaultFont"))
        if existing_notes:
            self.notes_text.insert("1.0", existing_notes)
        self.notes_text.grid(row=2, column=1, sticky="nsew")
        master.rowconfigure(2, weight=1)
        return master

    def validate(self) -> bool:  # type: ignore[override]
        if not self.name_var.get().strip():
            messagebox.showerror("Validation error", "Group name is required.")
            return False
        if not _clean_prefixes(self.match_prefix_var.get()):
            messagebox.showerror("Validation error", "Enter at least one match prefix.")
            return False
        return True

    def result_data(self) -> Dict[str, object]:
        return {
            "name": self.name_var.get().strip(),
            "match_prefixes": _clean_prefixes(self.match_prefix_var.get()),
            "notes": self.notes_text.get("1.0", tk.END).strip(),
        }

    def apply(self) -> None:  # type: ignore[override]
        self.result = self.result_data()


class NewGroupingDialog(simpledialog.Dialog):
    """Dialog for adding a grouping to an existing plugin."""

    def __init__(
        self,
        parent: tk.Tk,
        group_name: str,
        suggestion: Optional[Mapping[str, object]] = None,
    ) -> None:
        self._group_name = group_name
        self._suggestion = suggestion or {}
        super().__init__(parent, title=f"Add grouping to {group_name}")

    def body(self, master: tk.Tk) -> tk.Widget:  # type: ignore[override]
        ttk.Label(master, text=f"Group: {self._group_name}").grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(master, text="Label").grid(row=1, column=0, sticky="w")
        default_label = str(self._suggestion.get("label") or "")
        self.label_var = tk.StringVar(value=default_label)
        ttk.Entry(master, textvariable=self.label_var, width=40).grid(row=1, column=1, sticky="ew")

        ttk.Label(master, text="ID prefixes (use '=value' for exact matches)").grid(row=2, column=0, sticky="w")
        suggested_entries = parse_prefix_entries(self._suggestion.get("prefixEntries")) if self._suggestion else []
        if not suggested_entries and self._suggestion:
            suggested_entries = parse_prefix_entries(self._suggestion.get("prefixes"))
        prefix_values = _format_id_prefix_entries(suggested_entries)
        self.prefix_var = tk.StringVar(value=prefix_values)
        ttk.Entry(master, textvariable=self.prefix_var, width=40).grid(row=2, column=1, sticky="ew")

        ttk.Label(master, text="Anchor").grid(row=3, column=0, sticky="w")
        default_anchor = str(self._suggestion.get("anchor") or "nw")
        self.anchor_var = tk.StringVar(value=default_anchor or "nw")
        ttk.Combobox(master, values=ANCHOR_CHOICES, textvariable=self.anchor_var, state="readonly").grid(
            row=3, column=1, sticky="w"
        )

        ttk.Label(master, text="Payload justification").grid(row=4, column=0, sticky="w")
        suggestion_just = str(
            self._suggestion.get("payloadJustification") or DEFAULT_PAYLOAD_JUSTIFICATION
        ).strip().lower()
        if suggestion_just not in PAYLOAD_JUSTIFICATION_CHOICES:
            suggestion_just = DEFAULT_PAYLOAD_JUSTIFICATION
        self.justification_var = tk.StringVar(value=suggestion_just)
        ttk.Combobox(
            master,
            values=PAYLOAD_JUSTIFICATION_CHOICES,
            textvariable=self.justification_var,
            state="readonly",
        ).grid(row=4, column=1, sticky="w")

        ttk.Label(master, text="Marker label position").grid(row=5, column=0, sticky="w")
        suggestion_marker = str(
            self._suggestion.get("markerLabelPosition")
            or self._suggestion.get("marker_label_position")
            or DEFAULT_MARKER_LABEL_POSITION
        ).strip().lower()
        if suggestion_marker not in MARKER_LABEL_POSITION_CHOICES:
            suggestion_marker = DEFAULT_MARKER_LABEL_POSITION
        self.marker_label_position_var = tk.StringVar(value=suggestion_marker)
        ttk.Combobox(
            master,
            values=MARKER_LABEL_POSITION_CHOICES,
            textvariable=self.marker_label_position_var,
            state="readonly",
        ).grid(row=5, column=1, sticky="w")

        ttk.Label(master, text="Controller preview box").grid(row=6, column=0, sticky="w")
        suggestion_preview = str(
            self._suggestion.get("controllerPreviewBoxMode")
            or self._suggestion.get("controller_preview_box_mode")
            or DEFAULT_CONTROLLER_PREVIEW_BOX_MODE
        ).strip().lower()
        if suggestion_preview not in CONTROLLER_PREVIEW_BOX_MODE_CHOICES:
            suggestion_preview = DEFAULT_CONTROLLER_PREVIEW_BOX_MODE
        self.controller_preview_box_mode_var = tk.StringVar(value=suggestion_preview)
        ttk.Combobox(
            master,
            values=CONTROLLER_PREVIEW_BOX_MODE_CHOICES,
            textvariable=self.controller_preview_box_mode_var,
            state="readonly",
        ).grid(row=6, column=1, sticky="w")

        ttk.Label(master, text="Offset X (px)").grid(row=7, column=0, sticky="w")
        self.offset_x_var = tk.StringVar(value=self._format_initial_offset(self._suggestion.get("offsetX")))
        ttk.Entry(master, textvariable=self.offset_x_var, width=40).grid(row=7, column=1, sticky="ew")

        ttk.Label(master, text="Offset Y (px)").grid(row=8, column=0, sticky="w")
        self.offset_y_var = tk.StringVar(value=self._format_initial_offset(self._suggestion.get("offsetY")))
        ttk.Entry(master, textvariable=self.offset_y_var, width=40).grid(row=8, column=1, sticky="ew")

        ttk.Label(master, text="Background color (hex or name)").grid(row=9, column=0, sticky="w")
        self.background_color_var = tk.StringVar(value=str(self._suggestion.get("backgroundColor") or ""))
        ttk.Entry(master, textvariable=self.background_color_var, width=40).grid(row=9, column=1, sticky="ew")

        ttk.Label(master, text="Border color (hex or name)").grid(row=10, column=0, sticky="w")
        self.background_border_color_var = tk.StringVar(value=str(self._suggestion.get("backgroundBorderColor") or ""))
        ttk.Entry(master, textvariable=self.background_border_color_var, width=40).grid(row=10, column=1, sticky="ew")

        ttk.Label(master, text="Background border (0–10 px)").grid(row=11, column=0, sticky="w")
        self.background_border_var = tk.StringVar(
            value=str(self._suggestion.get("backgroundBorderWidth", ""))
        )
        ttk.Spinbox(master, from_=0, to=10, textvariable=self.background_border_var, width=6).grid(
            row=11, column=1, sticky="w"
        )

        ttk.Label(master, text="Notes").grid(row=12, column=0, sticky="w")
        self.notes_var = tk.StringVar(value=str(self._suggestion.get("notes") or ""))
        ttk.Entry(master, textvariable=self.notes_var, width=40).grid(row=12, column=1, sticky="ew")
        return master

    def validate(self) -> bool:  # type: ignore[override]
        label = self.label_var.get().strip()
        if not label:
            messagebox.showerror("Validation error", "Grouping label is required.")
            return False
        try:
            prefixes = _parse_id_prefix_text(self.prefix_var.get())
        except ValueError as exc:
            messagebox.showerror("Validation error", str(exc))
            return False
        if not prefixes:
            messagebox.showerror("Validation error", "Enter at least one ID prefix.")
            return False
        self._validated_prefixes = prefixes
        try:
            (
                self._validated_background_color,
                self._validated_background_border_color,
                self._validated_border,
            ) = self._parse_background_inputs()
        except ValueError as exc:
            messagebox.showerror("Validation error", str(exc))
            return False
        return True

    @staticmethod
    def _format_initial_offset(value: Any) -> str:
        if isinstance(value, int):
            return str(value)
        if isinstance(value, float):
            if value.is_integer():
                return str(int(value))
            return f"{value:g}"
        if isinstance(value, str):
            return value.strip()
        return ""

    def result_data(self) -> Dict[str, object]:
        prefixes = getattr(self, "_validated_prefixes", _parse_id_prefix_text(self.prefix_var.get()))
        return {
            "label": self.label_var.get().strip(),
            "prefixes": prefixes,
            "anchor": self.anchor_var.get().strip(),
            "payload_justification": self.justification_var.get().strip(),
            "marker_label_position": self.marker_label_position_var.get().strip(),
            "controller_preview_box_mode": self.controller_preview_box_mode_var.get().strip(),
            "offset_x": self.offset_x_var.get().strip(),
            "offset_y": self.offset_y_var.get().strip(),
            "background_color": getattr(self, "_validated_background_color", None),
            "background_border_color": getattr(self, "_validated_background_border_color", None),
            "background_border_width": getattr(self, "_validated_border", None),
            "notes": self.notes_var.get().strip(),
        }

    def apply(self) -> None:  # type: ignore[override]
        self.result = self.result_data()

    def _parse_background_inputs(self) -> tuple[Optional[str], Optional[str], Optional[int]]:
        color_raw = self.background_color_var.get().strip()
        color_value: Optional[str]
        if not color_raw:
            color_value = None
        else:
            try:
                color_value = _normalise_background_color(color_raw)
            except PluginGroupingError as exc:
                raise ValueError(str(exc)) from exc
        border_color_raw = self.background_border_color_var.get().strip()
        border_color_value: Optional[str]
        if not border_color_raw:
            border_color_value = None
        else:
            try:
                border_color_value = _normalise_background_color(border_color_raw)
            except PluginGroupingError as exc:
                raise ValueError(str(exc)) from exc
        border_raw = self.background_border_var.get().strip()
        if border_raw == "":
            border_value: Optional[int] = None
        else:
            try:
                border_candidate = float(border_raw)
            except ValueError as exc:
                raise ValueError("backgroundBorderWidth must be a number between 0 and 10") from exc
            try:
                border_value = _normalise_border_width(border_candidate, "backgroundBorderWidth")
            except PluginGroupingError as exc:
                raise ValueError(str(exc)) from exc
        return color_value, border_color_value, border_value


class EditGroupingDialog(simpledialog.Dialog):
    """Dialog for editing an existing grouping entry."""

    def __init__(self, parent: tk.Tk, group_name: str, entry: Mapping[str, object]) -> None:
        self._group_name = group_name
        self._entry = entry
        label = entry.get("label", "")
        parsed_entries = parse_prefix_entries(entry.get("prefixEntries"))
        if not parsed_entries:
            parsed_entries = parse_prefix_entries(entry.get("prefixes"))
        self._prefix_entries: List[PrefixEntry] = list(parsed_entries)
        super().__init__(parent, title=f"Edit grouping '{label}'")

    def body(self, master: tk.Tk) -> tk.Widget:  # type: ignore[override]
        ttk.Label(master, text=f"Group: {self._group_name}").grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(master, text="Label").grid(row=1, column=0, sticky="w")
        self.label_var = tk.StringVar(value=str(self._entry.get("label") or ""))
        ttk.Entry(master, textvariable=self.label_var, width=40).grid(row=1, column=1, sticky="ew")

        ttk.Label(master, text="ID prefixes (manage list entries)").grid(row=2, column=0, sticky="w")
        prefix_frame = ttk.Frame(master)
        prefix_frame.grid(row=3, column=0, columnspan=2, sticky="nsew", pady=(0, 4))
        master.grid_rowconfigure(3, weight=1)
        prefix_frame.grid_columnconfigure(0, weight=1)

        list_frame = ttk.Frame(prefix_frame)
        list_frame.grid(row=0, column=0, columnspan=3, sticky="nsew")
        list_frame.grid_columnconfigure(0, weight=1)

        self.prefix_listbox = tk.Listbox(list_frame, height=5, exportselection=False)
        self.prefix_listbox.grid(row=0, column=0, sticky="nsew")
        list_scroll = ttk.Scrollbar(list_frame, orient="vertical", command=self.prefix_listbox.yview)
        list_scroll.grid(row=0, column=1, sticky="ns")
        self.prefix_listbox.configure(yscrollcommand=list_scroll.set)
        self.prefix_listbox.bind("<<ListboxSelect>>", lambda _e: self._on_prefix_selection_changed())

        button_frame = ttk.Frame(list_frame)
        button_frame.grid(row=0, column=2, sticky="nsw", padx=(6, 0))
        self.remove_prefix_button = ttk.Button(
            button_frame, text="Remove", command=self._handle_remove_prefix, state="disabled"
        )
        self.remove_prefix_button.pack(fill="x", pady=(0, 4))
        ttk.Label(button_frame, text="Match mode").pack(anchor="w", pady=(6, 0))
        self.selected_match_mode = tk.StringVar(value="")
        self.match_mode_combo = ttk.Combobox(
            button_frame,
            values=(MATCH_MODE_STARTSWITH, MATCH_MODE_EXACT),
            textvariable=self.selected_match_mode,
            state="disabled",
            width=12,
        )
        self.match_mode_combo.pack(fill="x", pady=(2, 0))
        self.match_mode_combo.bind("<<ComboboxSelected>>", self._handle_selected_mode_changed)

        add_frame = ttk.Frame(prefix_frame)
        add_frame.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(4, 0))
        add_frame.grid_columnconfigure(0, weight=1)
        ttk.Label(add_frame, text="Value").grid(row=0, column=0, sticky="w")
        ttk.Label(add_frame, text="Match mode").grid(row=0, column=1, sticky="w", padx=(6, 0))
        self.new_prefix_var = tk.StringVar()
        ttk.Entry(add_frame, textvariable=self.new_prefix_var).grid(row=1, column=0, sticky="ew")
        self.new_match_mode = tk.StringVar(value=MATCH_MODE_STARTSWITH)
        ttk.Combobox(
            add_frame,
            values=(MATCH_MODE_STARTSWITH, MATCH_MODE_EXACT),
            textvariable=self.new_match_mode,
            state="readonly",
            width=12,
        ).grid(row=1, column=1, sticky="w", padx=(6, 0))
        ttk.Button(add_frame, text="Add", command=self._handle_add_prefix).grid(row=1, column=2, padx=(6, 0))
        self._refresh_prefix_listbox()

        ttk.Label(master, text="Anchor").grid(row=4, column=0, sticky="w")
        anchor_choices = ("",) + ANCHOR_CHOICES
        current_anchor = str(self._entry.get("anchor") or "")
        self.anchor_var = tk.StringVar(value=current_anchor)
        ttk.Combobox(master, values=anchor_choices, textvariable=self.anchor_var, state="readonly").grid(
            row=4, column=1, sticky="w"
        )

        ttk.Label(master, text="Payload justification").grid(row=5, column=0, sticky="w")
        justification_value = str(
            self._entry.get("payloadJustification") or DEFAULT_PAYLOAD_JUSTIFICATION
        ).strip().lower()
        if justification_value not in PAYLOAD_JUSTIFICATION_CHOICES:
            justification_value = DEFAULT_PAYLOAD_JUSTIFICATION
        self.justification_var = tk.StringVar(value=justification_value)
        ttk.Combobox(
            master,
            values=PAYLOAD_JUSTIFICATION_CHOICES,
            textvariable=self.justification_var,
            state="readonly",
        ).grid(row=5, column=1, sticky="w")

        ttk.Label(master, text="Marker label position").grid(row=6, column=0, sticky="w")
        marker_label_position = str(
            self._entry.get("markerLabelPosition") or DEFAULT_MARKER_LABEL_POSITION
        ).strip().lower()
        if marker_label_position not in MARKER_LABEL_POSITION_CHOICES:
            marker_label_position = DEFAULT_MARKER_LABEL_POSITION
        self.marker_label_position_var = tk.StringVar(value=marker_label_position)
        ttk.Combobox(
            master,
            values=MARKER_LABEL_POSITION_CHOICES,
            textvariable=self.marker_label_position_var,
            state="readonly",
        ).grid(row=6, column=1, sticky="w")

        ttk.Label(master, text="Controller preview box").grid(row=7, column=0, sticky="w")
        preview_box_mode = str(
            self._entry.get("controllerPreviewBoxMode") or DEFAULT_CONTROLLER_PREVIEW_BOX_MODE
        ).strip().lower()
        if preview_box_mode not in CONTROLLER_PREVIEW_BOX_MODE_CHOICES:
            preview_box_mode = DEFAULT_CONTROLLER_PREVIEW_BOX_MODE
        self.controller_preview_box_mode_var = tk.StringVar(value=preview_box_mode)
        ttk.Combobox(
            master,
            values=CONTROLLER_PREVIEW_BOX_MODE_CHOICES,
            textvariable=self.controller_preview_box_mode_var,
            state="readonly",
        ).grid(row=7, column=1, sticky="w")

        ttk.Label(master, text="Offset X (px)").grid(row=8, column=0, sticky="w")
        self.offset_x_var = tk.StringVar(value=self._format_initial_offset(self._entry.get("offsetX")))
        ttk.Entry(master, textvariable=self.offset_x_var, width=40).grid(row=8, column=1, sticky="ew")

        ttk.Label(master, text="Offset Y (px)").grid(row=9, column=0, sticky="w")
        self.offset_y_var = tk.StringVar(value=self._format_initial_offset(self._entry.get("offsetY")))
        ttk.Entry(master, textvariable=self.offset_y_var, width=40).grid(row=9, column=1, sticky="ew")

        ttk.Label(master, text="Background color (hex or name)").grid(row=10, column=0, sticky="w")
        self.background_color_var = tk.StringVar(value=str(self._entry.get("backgroundColor") or ""))
        ttk.Entry(master, textvariable=self.background_color_var, width=40).grid(row=10, column=1, sticky="ew")

        ttk.Label(master, text="Border color (hex or name)").grid(row=11, column=0, sticky="w")
        self.background_border_color_var = tk.StringVar(value=str(self._entry.get("backgroundBorderColor") or ""))
        ttk.Entry(master, textvariable=self.background_border_color_var, width=40).grid(row=11, column=1, sticky="ew")

        ttk.Label(master, text="Background border (0–10 px)").grid(row=12, column=0, sticky="w")
        self.background_border_var = tk.StringVar(value=str(self._entry.get("backgroundBorderWidth") or ""))
        ttk.Spinbox(master, from_=0, to=10, textvariable=self.background_border_var, width=6).grid(
            row=12, column=1, sticky="w"
        )

        ttk.Label(master, text="Notes").grid(row=13, column=0, sticky="w")
        self.notes_var = tk.StringVar(value=str(self._entry.get("notes") or ""))
        ttk.Entry(master, textvariable=self.notes_var, width=40).grid(row=13, column=1, sticky="ew")
        return master

    def validate(self) -> bool:  # type: ignore[override]
        label = self.label_var.get().strip()
        if not label:
            messagebox.showerror("Validation error", "Grouping label is required.")
            return False
        if not self._prefix_entries:
            messagebox.showerror("Validation error", "Enter at least one ID prefix.")
            return False
        try:
            (
                self._validated_background_color,
                self._validated_background_border_color,
                self._validated_border,
            ) = self._parse_background_inputs()
        except ValueError as exc:
            messagebox.showerror("Validation error", str(exc))
            return False
        return True

    def result_data(self) -> Dict[str, object]:
        return {
            "original_label": self._entry.get("label"),
            "label": self.label_var.get().strip(),
            "prefixes": list(self._prefix_entries),
            "anchor": self.anchor_var.get().strip(),
            "payload_justification": self.justification_var.get().strip(),
            "marker_label_position": self.marker_label_position_var.get().strip(),
            "controller_preview_box_mode": self.controller_preview_box_mode_var.get().strip(),
            "offset_x": self.offset_x_var.get().strip(),
            "offset_y": self.offset_y_var.get().strip(),
            "background_color": getattr(self, "_validated_background_color", None),
            "background_border_color": getattr(self, "_validated_background_border_color", None),
            "background_border_width": getattr(self, "_validated_border", None),
            "notes": self.notes_var.get().strip(),
        }

    def _refresh_prefix_listbox(self) -> None:
        self.prefix_listbox.delete(0, tk.END)
        for entry in self._prefix_entries:
            self.prefix_listbox.insert(tk.END, entry.display_label())
        self._update_prefix_controls()

    def _update_prefix_controls(self) -> None:
        selection = self.prefix_listbox.curselection()
        has_selection = bool(selection)
        state = "normal" if has_selection else "disabled"
        self.remove_prefix_button.configure(state=state)
        self.match_mode_combo.configure(state=state if has_selection else "disabled")
        if has_selection:
            entry = self._prefix_entries[selection[0]]
            self.selected_match_mode.set(entry.match_mode)
        else:
            self.selected_match_mode.set("")

    def _on_prefix_selection_changed(self) -> None:
        self._update_prefix_controls()

    def _handle_selected_mode_changed(self, _event=None) -> None:
        selection = self.prefix_listbox.curselection()
        if not selection:
            return
        index = selection[0]
        if not (0 <= index < len(self._prefix_entries)):
            return
        mode = self.selected_match_mode.get().strip().lower()
        if mode not in (MATCH_MODE_STARTSWITH, MATCH_MODE_EXACT):
            return
        entry = self._prefix_entries[index]
        if entry.match_mode == mode:
            return
        try:
            updated = PrefixEntry(value=entry.value, match_mode=mode)
        except ValueError:
            return
        self._prefix_entries[index] = updated
        self._refresh_prefix_listbox()

    def _handle_add_prefix(self) -> None:
        value = self.new_prefix_var.get().strip()
        mode = self.new_match_mode.get().strip().lower()
        if not value:
            messagebox.showerror("Validation error", "Enter a prefix value before adding.")
            return
        if mode not in (MATCH_MODE_STARTSWITH, MATCH_MODE_EXACT):
            messagebox.showerror("Validation error", "Select a valid match mode.")
            return
        try:
            entry = PrefixEntry(value=value, match_mode=mode)
        except ValueError as exc:
            messagebox.showerror("Validation error", str(exc))
            return
        if any(existing.key == entry.key for existing in self._prefix_entries):
            messagebox.showinfo("Duplicate prefix", "That prefix already exists with the same match mode.")
            return
        self._prefix_entries.append(entry)
        self.new_prefix_var.set("")
        self._refresh_prefix_listbox()

    def _handle_remove_prefix(self) -> None:
        selection = self.prefix_listbox.curselection()
        if not selection:
            return
        index = selection[0]
        if 0 <= index < len(self._prefix_entries):
            del self._prefix_entries[index]
            self._refresh_prefix_listbox()

    def apply(self) -> None:  # type: ignore[override]
        self.result = self.result_data()

    @staticmethod
    def _format_initial_offset(value: Any) -> str:
        if isinstance(value, int):
            return str(value)
        if isinstance(value, float):
            if value.is_integer():
                return str(int(value))
            return f"{value:g}"
        if isinstance(value, str):
            return value.strip()
        return ""

    def _parse_background_inputs(self) -> tuple[Optional[str], Optional[str], Optional[int]]:
        color_raw = self.background_color_var.get().strip()
        color_value: Optional[str]
        if not color_raw:
            color_value = None
        else:
            try:
                color_value = _normalise_background_color(color_raw)
            except PluginGroupingError as exc:
                raise ValueError(str(exc)) from exc
        border_color_raw = self.background_border_color_var.get().strip()
        border_color_value: Optional[str]
        if not border_color_raw:
            border_color_value = None
        else:
            try:
                border_color_value = _normalise_background_color(border_color_raw)
            except PluginGroupingError as exc:
                raise ValueError(str(exc)) from exc
        border_raw = self.background_border_var.get().strip()
        if border_raw == "":
            border_value: Optional[int] = None
        else:
            try:
                border_candidate = float(border_raw)
            except ValueError as exc:
                raise ValueError("backgroundBorderWidth must be a number between 0 and 10") from exc
            try:
                border_value = _normalise_border_width(border_candidate, "backgroundBorderWidth")
            except PluginGroupingError as exc:
                raise ValueError(str(exc)) from exc
        return color_value, border_color_value, border_value


class AddPrefixDialog(simpledialog.Dialog):
    """Dialog that lets the user confirm or edit the prefix being added."""

    def __init__(
        self,
        parent: tk.Tk,
        *,
        group_name: str,
        grouping_label: str,
        default_prefix: str,
        payload_id: Optional[str] = None,
    ) -> None:
        self._group_name = group_name
        self._grouping_label = grouping_label
        self._default_prefix = default_prefix.strip()
        payload_text = payload_id.strip() if isinstance(payload_id, str) else ""
        self._payload_id = payload_text or self._default_prefix
        super().__init__(parent, title=f"Add prefix to '{grouping_label}'")

    def body(self, master: tk.Tk) -> tk.Widget:  # type: ignore[override]
        ttk.Label(master, text=f"Group: {self._group_name}").grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(master, text=f"ID Prefix group: {self._grouping_label}").grid(row=1, column=0, columnspan=2, sticky="w")
        ttk.Label(master, text="ID prefix to add").grid(row=2, column=0, sticky="w", pady=(8, 0))

        self.prefix_var = tk.StringVar(value=self._default_prefix)
        entry = ttk.Entry(master, textvariable=self.prefix_var, width=40)
        entry.grid(row=2, column=1, sticky="ew", pady=(8, 0))

        ttk.Label(master, text="Match mode").grid(row=3, column=0, sticky="w", pady=(8, 0))
        self.mode_var = tk.StringVar(value=MATCH_MODE_STARTSWITH)
        mode_combo = ttk.Combobox(
            master,
            values=(MATCH_MODE_STARTSWITH, MATCH_MODE_EXACT),
            textvariable=self.mode_var,
            state="readonly",
        )
        mode_combo.grid(row=3, column=1, sticky="w", pady=(8, 0))
        mode_combo.bind("<<ComboboxSelected>>", self._on_mode_changed)

        master.grid_columnconfigure(1, weight=1)
        self._on_mode_changed()
        return entry

    def validate(self) -> bool:  # type: ignore[override]
        value = self.prefix_var.get().strip()
        if not value:
            messagebox.showerror("Validation error", "Enter a prefix to add.")
            return False
        mode = self.mode_var.get().strip().lower()
        if mode not in (MATCH_MODE_STARTSWITH, MATCH_MODE_EXACT):
            messagebox.showerror("Validation error", "Select a valid match mode.")
            return False
        return True

    def result_data(self) -> PrefixEntry:
        return PrefixEntry(value=self.prefix_var.get().strip(), match_mode=self.mode_var.get().strip())

    def apply(self) -> None:  # type: ignore[override]
        self.result = self.result_data()

    def _on_mode_changed(self, _event=None) -> None:
        mode = self.mode_var.get().strip().lower()
        if mode == MATCH_MODE_EXACT and self._payload_id:
            self.prefix_var.set(self._payload_id)


class PluginGroupManagerApp:
    """Tkinter UI that ties the watcher/gather logic together."""

    def __init__(self, log_dir_override: Optional[Path] = None) -> None:
        self._matcher = OverrideMatcher(GROUPINGS_PATH)
        self._locator = LogLocator(ROOT_DIR, override_dir=log_dir_override)
        cache_path = ROOT_DIR / "payload_store" / "new-payloads.json"
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            cache_path.unlink()
        except FileNotFoundError:
            pass
        self._payload_store = NewPayloadStore(cache_path)
        self._group_store = GroupConfigStore(GROUPINGS_PATH)
        self._queue: "queue.Queue[Tuple[str, object]]" = queue.Queue()
        self._watcher: Optional[PayloadWatcher] = None
        self._gather_thread: Optional[LogGatherer] = None
        self._group_file_poll_ms = 1000
        self._closed = False

        self.root = tk.Tk()
        default_font = tkfont.nametofont("TkDefaultFont")
        self._group_title_font = default_font.copy()
        base_size = int(self._group_title_font.cget("size") or 10)
        increment = 2 if base_size >= 0 else -2
        self._group_title_font.configure(size=base_size + increment, weight="bold")
        self._grouping_label_font = default_font.copy()
        self._grouping_label_font.configure(weight="bold")
        self.root.title("Plugin Group Manager")
        self.root.geometry("1350x800")
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._style = ttk.Style(self.root)
        self._payload_window_bg = self._resolve_payload_window_background()
        self._configure_styles()

        self.watch_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="Idle.")
        self.payload_count_var = tk.StringVar()
        self._payload_meta: Dict[str, Tuple[str, Optional[str]]] = {}
        self._group_views: Dict[str, Dict[str, object]] = {}
        self._unmatched_by_group: Dict[str, List[str]] = {}
        self.selected_group_var = tk.StringVar()
        self.group_name_var = tk.StringVar(value="Select a group")
        self.group_match_var = tk.StringVar(value="-")
        self.group_notes_var = tk.StringVar(value="-")
        self.grouping_canvas: Optional[tk.Canvas] = None
        self.grouping_scrollbar: Optional[ttk.Scrollbar] = None
        self.grouping_entries_frame: Optional[ttk.Frame] = None
        self.grouping_entries_window: Optional[int] = None
        self._group_scroll_bound = False
        self._group_scroll_targets: List[tk.Widget] = []
        self._payload_context_menu: Optional[tk.Menu] = None
        self._payload_menu_dismiss_bind: Optional[str] = None
        self.replay_ttl_var = tk.StringVar(value=str(DEFAULT_REPLAY_TTL))
        self.crosshair_x_var = tk.StringVar(value="")
        self.crosshair_y_var = tk.StringVar(value="")
        self.replay_resolution_vars: Dict[Tuple[int, int], tk.BooleanVar] = {}
        self._active_mock_process: Optional[subprocess.Popen[Any]] = None

        self._build_ui()
        self._refresh_group_data()
        self._update_payload_count()
        self.root.after_idle(self._start_background_tasks)

    def _start_background_tasks(self) -> None:
        self.root.after(200, self._process_queue)
        self.root.after(self._group_file_poll_ms, self._poll_groupings_file)

    def _resolve_payload_window_background(self) -> str:
        """Mirror the payload inspector background so dropdown matches."""
        fallback = self.root.cget("background")
        try:
            probe = tk.Text(self.root)
        except tk.TclError:
            return fallback
        try:
            color = probe.cget("background") or fallback
        finally:
            probe.destroy()
        return color

    def _configure_styles(self) -> None:
        color = getattr(self, "_payload_window_bg", self.root.cget("background"))
        try:
            self._style.configure(
                GROUP_SELECTOR_STYLE,
                fieldbackground=color,
                background=color,
            )
            self._style.map(
                GROUP_SELECTOR_STYLE,
                fieldbackground=[("readonly", color)],
                background=[("readonly", color)],
            )
        except tk.TclError as exc:
            LOG.debug("Unable to configure group selector style: %s", exc)

    # UI -----------------------------------------------------------------
    def _build_ui(self) -> None:
        main = ttk.Frame(self.root, padding=12)
        main.pack(fill="both", expand=True)
        main.columnconfigure(0, weight=1)
        main.columnconfigure(1, weight=1)
        main.columnconfigure(2, weight=0)
        main.rowconfigure(0, weight=1)

        left_panel = ttk.Frame(main)
        left_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        left_panel.rowconfigure(1, weight=1)
        right_panel = ttk.Frame(main)
        right_panel.grid(row=0, column=1, sticky="nsew")
        right_panel.rowconfigure(2, weight=1)
        replay_section = self._create_label_frame(main, "Replay Settings")
        replay_section.grid(row=0, column=2, sticky="ns", padx=(8, 0))
        self._build_replay_panel(replay_section)

        overview_section = self._create_label_frame(left_panel, "Overview & Instructions")
        overview_section.pack(fill="x", expand=False, pady=(0, 12))
        overview_container = ttk.Frame(overview_section)
        overview_container.pack(fill="x", padx=8, pady=8)
        overview_text = (
            "Plugin Group Manager helps you define patterns to group payloads together for placement on the overlay "
            "while maintaining correct aspect ratios and font spacings."
        )
        ttk.Label(overview_container, text=overview_text, wraplength=LEFT_PANEL_WRAP, justify="left").pack(anchor="w")
        ttk.Label(overview_container, text="Instructions", font=self._grouping_label_font).pack(anchor="w", pady=(8, 2))
        steps = [
            "Step 1: Have the plugin in Dev mode (so payloads will be logged).",
            "Step 2: Watch for new payloads.",
            "Step 3: Trigger a payload in-game, or gather from logs after triggering.",
            "Step 4: If a payload is unmatched, create a new plugin group via the New Group button or by right-clicking the payload.",
            "Step 5: If a payload is ungrouped it already matches a plugin group; select it to highlight the group and add it to an ID Prefix group or right-click for quick actions.",
        ]
        for step in steps:
            ttk.Label(overview_container, text=step, wraplength=LEFT_PANEL_WRAP, justify="left").pack(anchor="w", pady=(2, 0))

        top_section = self._create_label_frame(left_panel, "Watcher / Gather")
        top_section.pack(fill="x", expand=False, pady=(0, 12))

        control_row = ttk.Frame(top_section)
        control_row.pack(fill="x", padx=8, pady=8)
        ttk.Checkbutton(
            control_row,
            text="Watch for new payloads",
            variable=self.watch_var,
            command=self._toggle_watcher,
        ).pack(side="left")
        ttk.Button(control_row, text="Gather from logs", command=self._start_gather).pack(side="left", padx=(12, 0))
        ttk.Label(top_section, textvariable=self.payload_count_var, anchor="w").pack(fill="x", padx=8, pady=(0, 4))

        ttk.Label(top_section, textvariable=self.status_var).pack(fill="x", padx=8)

        list_frame = ttk.Frame(left_panel)
        list_frame.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        columns = ("status", "payload")
        self.payload_list = ttk.Treeview(
            list_frame,
            columns=columns,
            show="headings",
            selectmode="browse",
            height=6,
        )
        self.payload_list.heading("status", text="Status")
        self.payload_list.heading("payload", text="Payload")
        self.payload_list.column("status", width=110, anchor="w", stretch=False)
        self.payload_list.column("payload", anchor="w")
        self.payload_list.pack(side="left", fill="both", expand=True)
        self.payload_list.bind("<<TreeviewSelect>>", self._on_payload_selection_changed)
        self.payload_list.bind("<Double-1>", self._inspect_selected_payload)
        self.payload_list.bind("<Button-3>", self._show_payload_context_menu)
        self.payload_list.bind("<Button-2>", self._show_payload_context_menu)
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.payload_list.yview)
        scrollbar.pack(side="right", fill="y")
        self.payload_list.configure(yscrollcommand=scrollbar.set)
        tips_frame = ttk.Frame(left_panel)
        tips_frame.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Label(tips_frame, text="Tips:", font=self._group_title_font).pack(anchor="w")
        tip_texts = [
            "Double-click a payload to inspect its JSON details.",
            "Right-click a payload to create plugin or ID prefix groups quickly.",
        ]
        for text in tip_texts:
            ttk.Label(tips_frame, text=f"• {text}", foreground="#5a5a5a", justify="left").pack(anchor="w", pady=(2, 0))

        selector_row = ttk.Frame(right_panel)
        selector_row.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Label(selector_row, text="Select plugin group:").grid(row=0, column=0, sticky="w")
        self.group_selector = ttk.Combobox(
            selector_row,
            textvariable=self.selected_group_var,
            state="readonly",
            width=30,
            style=GROUP_SELECTOR_STYLE,
        )
        self.group_selector.grid(row=0, column=1, sticky="w", padx=(8, 0))
        self.group_selector.bind("<<ComboboxSelected>>", lambda _: self._on_group_selected())
        ttk.Button(
            selector_row,
            text="New group",
            command=lambda: self._open_new_group_dialog(self._build_group_dialog_suggestion()),
        ).grid(row=0, column=2, sticky="e", padx=(8, 0))
        selector_row.columnconfigure(1, weight=1)

        info_section = self._create_label_frame(right_panel, "Plugin Group")
        info_section.pack(fill="x", padx=8, pady=(0, 8))
        info_grid = ttk.Frame(info_section)
        info_grid.pack(fill="x", padx=8, pady=8)
        info_grid.columnconfigure(1, weight=1)

        ttk.Label(info_grid, text="Group:").grid(row=0, column=0, sticky="w")
        ttk.Label(info_grid, textvariable=self.group_name_var).grid(row=0, column=1, sticky="w")
        ttk.Button(info_grid, text="Edit group", command=lambda: self._open_edit_group_dialog(self.selected_group_var.get())).grid(
            row=0, column=2, sticky="e"
        )
        ttk.Button(info_grid, text="Delete group", command=self._delete_selected_group).grid(row=0, column=3, sticky="e", padx=(8, 0))
        ttk.Label(info_grid, text="Match prefixes:").grid(row=1, column=0, sticky="nw", pady=(4, 0))
        ttk.Label(info_grid, textvariable=self.group_match_var, wraplength=640, justify="left").grid(
            row=1, column=1, columnspan=3, sticky="w", pady=(4, 0)
        )
        ttk.Label(info_grid, text="Notes:").grid(row=2, column=0, sticky="nw", pady=(4, 0))
        ttk.Label(info_grid, textvariable=self.group_notes_var, wraplength=640, justify="left").grid(
            row=2,
            column=1,
            columnspan=3,
            sticky="w",
            pady=(4, 0),
        )

        grouping_section = self._create_label_frame(right_panel, "ID Prefix Groups")
        grouping_section.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        grouping_action_row = ttk.Frame(grouping_section)
        grouping_action_row.pack(fill="x", padx=8, pady=(8, 0))
        ttk.Button(
            grouping_action_row,
            text="Add grouping",
            command=lambda: self._open_new_grouping_dialog(
                self.selected_group_var.get(), suggestion=self._build_grouping_dialog_suggestion(self.selected_group_var.get())
            ),
        ).pack(side="right")
        (
            entries_container,
            self.grouping_canvas,
            self.grouping_scrollbar,
            self.grouping_entries_frame,
            self.grouping_entries_window,
        ) = self._create_vertical_scroll_frame(grouping_section)
        entries_container.pack(fill="both", expand=True, padx=8, pady=8)
        self._group_scroll_targets = [entries_container]
        if self.grouping_canvas is not None:
            self._group_scroll_targets.append(self.grouping_canvas)
        if self.grouping_entries_frame is not None:
            self._group_scroll_targets.append(self.grouping_entries_frame)
        self._enable_group_scroll(None)

    def _build_replay_panel(self, parent: ttk.LabelFrame) -> None:
        container = ttk.Frame(parent)
        container.pack(fill="y", expand=False, padx=8, pady=8)
        ttk.Label(container, text="Payload TTL (seconds):").pack(anchor="w")
        ttk.Entry(container, textvariable=self.replay_ttl_var, width=6).pack(anchor="w", pady=(0, 8))
        ttk.Label(container, text="Crosshair position (% or px of window):").pack(anchor="w")
        ttk.Label(
            container,
            text="Enter % values like 50% or pixel values like 640px (no suffix = pixels).",
            wraplength=220,
            justify="left",
            foreground="#555555",
        ).pack(anchor="w", pady=(0, 4))
        crosshair_row = ttk.Frame(container)
        crosshair_row.pack(anchor="w", pady=(0, 8))
        ttk.Label(crosshair_row, text="X:").pack(side="left")
        ttk.Entry(crosshair_row, textvariable=self.crosshair_x_var, width=12).pack(side="left", padx=(2, 8))
        ttk.Label(crosshair_row, text="Y:").pack(side="left")
        ttk.Entry(crosshair_row, textvariable=self.crosshair_y_var, width=12).pack(side="left", padx=(2, 0))
        ttk.Label(container, text="Mock window sizes:").pack(anchor="w", pady=(4, 2))
        note = ttk.Label(
            container,
            text="Select the resolutions to test. The mock window is resized via wmctrl before each replay.",
            wraplength=220,
            justify="left",
            foreground="#555555",
        )
        note.pack(anchor="w", pady=(0, 6))
        action_row = ttk.Frame(container)
        action_row.pack(anchor="w", pady=(0, 8))
        ttk.Button(action_row, text="All", command=self._select_all_replay_resolutions).pack(side="left", padx=(0, 6))
        ttk.Button(action_row, text="None", command=self._clear_replay_resolutions).pack(side="left")
        for width, height in REPLAY_RESOLUTIONS:
            ratio = self._format_aspect_ratio(width, height)
            details = ratio
            if width == 1280 and height == 960:
                details = f"{ratio}, default"
            label = f"{width} x {height} ({details})"
            arrow = self._overflow_indicator(width, height)
            if arrow:
                label = f"{label} {arrow}"
            var = tk.BooleanVar(value=False)
            self.replay_resolution_vars[(width, height)] = var
            ttk.Checkbutton(container, text=label, variable=var).pack(anchor="w")

    def _create_label_frame(self, parent: tk.Widget, text: str) -> ttk.LabelFrame:
        label = ttk.Label(parent, text=text, font=self._group_title_font)
        frame = ttk.LabelFrame(parent, labelwidget=label)
        return frame

    def _create_vertical_scroll_frame(
        self, parent: tk.Widget
    ) -> Tuple[ttk.Frame, tk.Canvas, ttk.Scrollbar, ttk.Frame, int]:
        """Return a scrollable frame hosted inside a canvas with a vertical scrollbar."""
        container = ttk.Frame(parent)
        container.grid_columnconfigure(0, weight=1)
        container.grid_rowconfigure(0, weight=1)
        canvas = tk.Canvas(container, highlightthickness=0)
        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.grid(row=0, column=1, sticky="ns")
        frame = ttk.Frame(canvas)
        window_id = canvas.create_window((0, 0), window=frame, anchor="nw")
        frame.bind("<Configure>", lambda _: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind(
            "<Configure>",
            lambda event, target=canvas, window=window_id: target.itemconfigure(window, width=event.width),
        )
        return container, canvas, scrollbar, frame, window_id


    def _refresh_payload_list(self) -> None:
        if not hasattr(self, "payload_list"):
            return
        selected = self.payload_list.selection()
        selected_id = selected[0] if selected else None
        for item in self.payload_list.get_children():
            self.payload_list.delete(item)
        self._payload_meta = {}
        for record in self._payload_store.records():
            payload_id = record.payload_id
            status, target_group = self._determine_payload_status(record)
            self._payload_meta[payload_id] = (status, target_group)
            self.payload_list.insert("", "end", iid=payload_id, values=(status, record.label()))
        if selected_id and self.payload_list.exists(selected_id):
            self.payload_list.selection_set(selected_id)
            self.payload_list.focus(selected_id)
            self._on_payload_selection_changed()

    def _determine_payload_status(self, record: PayloadRecord) -> Tuple[str, Optional[str]]:
        group_name = (record.group or "").strip()
        if group_name:
            return "Ungrouped", group_name
        # Fall back to the matcher so we can re-evaluate the record against the current
        # ID prefix groups even if the cached payload metadata lacks a stored group.
        unmatched_plugin = self._matcher.unmatched_group_for(record.plugin, record.payload_id)
        if unmatched_plugin:
            return "Ungrouped", unmatched_plugin
        resolved = self._match_group_for_payload(record.payload_id)
        if resolved:
            return "Ungrouped", resolved
        return "Unmatched", None

    def _match_group_for_payload(self, payload_id: Optional[str]) -> Optional[str]:
        if not payload_id or not self._group_views:
            return None
        payload_cf = payload_id.casefold()
        for name, view in self._group_views.items():
            prefixes = [
                str(prefix).strip().casefold()
                for prefix in view.get("match_prefixes", [])
                if isinstance(prefix, str) and prefix.strip()
            ]
            if prefixes and any(payload_cf.startswith(prefix) for prefix in prefixes):
                return name
        return None

    def _current_payload_record(self) -> Optional[PayloadRecord]:
        if not hasattr(self, "payload_list"):
            return None
        selection = self.payload_list.selection()
        if not selection:
            return None
        payload_id = selection[0]
        return self._payload_store.get(payload_id)

    @staticmethod
    def _tokenise_payload_id(payload_id: str) -> List[str]:
        tokens = re.split(r"[-_.]+", payload_id)
        return [token for token in tokens if token]

    @staticmethod
    def _titleise_token(token: str) -> str:
        return token.replace("_", " ").replace("-", " ").replace(".", " ").title()

    @staticmethod
    def _extract_prefix(payload_id: str, segments: int) -> str:
        if segments <= 0:
            return payload_id
        count = 0
        for idx, char in enumerate(payload_id):
            if char in "-_.":
                count += 1
                if count == segments:
                    return payload_id[: idx + 1]
        return payload_id

    @staticmethod
    def _select_descriptive_tokens(tokens: List[str], max_tokens: int = 2) -> List[str]:
        if not tokens:
            return []
        filtered = [token for token in tokens if token.casefold() not in GENERIC_PAYLOAD_TOKENS]
        if not filtered:
            filtered = tokens
        return filtered[:max_tokens] if max_tokens > 0 else filtered

    def _build_group_dialog_suggestion(self) -> Optional[Dict[str, object]]:
        record = self._current_payload_record()
        if not record or not record.payload_id:
            return None
        tokens = self._tokenise_payload_id(record.payload_id)
        name_tokens = self._select_descriptive_tokens(tokens, max_tokens=2)
        if record.plugin:
            name = record.plugin
        else:
            name = " ".join(self._titleise_token(token) for token in name_tokens) or record.payload_id
        prefix = self._extract_prefix(record.payload_id, segments=1)
        suggestion: Dict[str, object] = {
            "name": name,
            "match_prefixes": [prefix.casefold()],
        }
        return suggestion

    def _build_grouping_dialog_suggestion(self, group_name: Optional[str]) -> Optional[Dict[str, object]]:
        if not group_name:
            return None
        record = self._current_payload_record()
        if not record or not record.payload_id:
            return None
        meta = self._payload_meta.get(record.payload_id)
        if not meta or meta[0] != "Ungrouped" or meta[1] != group_name:
            return None
        tokens = self._tokenise_payload_id(record.payload_id)
        label_tokens = self._select_descriptive_tokens(tokens, max_tokens=2)
        label = " ".join(self._titleise_token(token) for token in label_tokens) or record.payload_id
        prefix = self._extract_prefix(record.payload_id, segments=2)
        suggestion: Dict[str, object] = {
            "label": label,
            "prefixEntries": [PrefixEntry(value=prefix.casefold()).to_mapping()],
        }
        return suggestion

    def _on_payload_selection_changed(self, _event=None) -> None:
        if not hasattr(self, "payload_list"):
            return
        selection = self.payload_list.selection()
        if not selection:
            return
        payload_id = selection[0]
        status_info = self._payload_meta.get(payload_id)
        if not status_info:
            return
        status, target_group = status_info
        if status == "Ungrouped" and target_group and target_group in self._group_views:
            if self.selected_group_var.get() != target_group:
                self.selected_group_var.set(target_group)
                self._on_group_selected()

    def _dismiss_payload_context_menu(self, _event=None) -> None:
        menu = getattr(self, "_payload_context_menu", None)
        if menu is not None:
            try:
                menu.unpost()
            except tk.TclError:
                pass
            try:
                menu.destroy()
            except tk.TclError:
                pass
            self._payload_context_menu = None
        if self._payload_menu_dismiss_bind:
            try:
                self.root.unbind("<Button-1>", self._payload_menu_dismiss_bind)
            except tk.TclError:
                pass
            self._payload_menu_dismiss_bind = None

    def _queue_add_payload_to_existing_grouping(self, group_name: str, grouping_label: str) -> None:
        """Defer add-prefix flow until after the context menu closes."""
        LOG.debug(
            "Queueing add-to-prefix request: group=%s grouping=%s selection=%s",
            group_name,
            grouping_label,
            self.payload_list.selection(),
        )
        self._dismiss_payload_context_menu()
        self.root.after_idle(
            lambda g=group_name, label=grouping_label: self._add_payload_to_existing_grouping(g, label)
        )

    def _add_payload_to_existing_grouping(self, group_name: str, grouping_label: str) -> None:
        record = self._current_payload_record()
        if not record or not record.payload_id:
            LOG.debug("Add-to-prefix aborted: no selected payload.")
            messagebox.showinfo("Add to ID Prefix group", "Select a payload first.")
            return
        view = self._group_views.get(group_name)
        if not view:
            LOG.debug("Add-to-prefix aborted: group %s not in views.", group_name)
            messagebox.showerror("Add to ID Prefix group", f"Group '{group_name}' not found.")
            return
        group_entry = self._group_store.get_group(group_name)
        if not isinstance(group_entry, Mapping):
            LOG.debug("Add-to-prefix aborted: group entry missing for %s.", group_name)
            messagebox.showerror("Add to ID Prefix group", f"Group '{group_name}' data is unavailable.")
            return
        groups = group_entry.get("idPrefixGroups")
        if not isinstance(groups, Mapping) or grouping_label not in groups:
            LOG.debug("Add-to-prefix aborted: grouping %s missing in %s.", grouping_label, group_name)
            messagebox.showerror("Add to ID Prefix group", f"ID Prefix group '{grouping_label}' not found in {group_name}.")
            return
        target_spec = groups.get(grouping_label) or {}
        raw_prefixes = target_spec.get("idPrefixes") or target_spec.get("id_prefixes") or target_spec.get("prefixes") or []
        existing_prefixes: List[PrefixEntry] = parse_prefix_entries(raw_prefixes)
        LOG.debug(
            "Preparing prefix dialog: payload=%s group=%s grouping=%s existing=%s",
            record.payload_id,
            group_name,
            grouping_label,
            existing_prefixes,
        )
        prefix_raw = self._extract_prefix(record.payload_id, segments=2)
        default_prefix = prefix_raw.strip()
        if not default_prefix:
            LOG.debug("Add-to-prefix aborted: could not derive prefix for %s.", record.payload_id)
            messagebox.showerror("Add to ID Prefix group", "Could not determine a prefix from the selected payload ID.")
            return
        self._prompt_add_prefix_to_grouping(
            group_name=group_name,
            grouping_label=grouping_label,
            default_prefix=default_prefix,
            existing_prefixes=tuple(existing_prefixes),
            payload_id=record.payload_id,
        )

    def _show_payload_context_menu(self, event) -> None:
        if not hasattr(self, "payload_list"):
            return
        self._dismiss_payload_context_menu()
        row_id = self.payload_list.identify_row(event.y)
        if not row_id:
            LOG.debug("Context menu suppressed: no row at y=%s", event.y)
            return
        self.payload_list.selection_set(row_id)
        self.payload_list.focus(row_id)
        meta = self._payload_meta.get(row_id)
        if not meta:
            LOG.debug("Context menu suppressed: no metadata for row %s", row_id)
            return
        status, target_group = meta
        LOG.debug("Context menu request: payload=%s status=%s target_group=%s", row_id, status, target_group)
        menu = tk.Menu(self.root, tearoff=False)
        if status == "Unmatched":
            menu.add_command(
                label="Create new group",
                command=lambda: self._open_new_group_dialog_from_payload(),
            )
        elif status == "Ungrouped" and target_group:
            label = f"Create new ID Prefix Group in {target_group}"
            menu.add_command(
                label=label,
                command=lambda group=target_group: self._open_new_grouping_dialog_from_payload(group),
            )
            grouping_entries = [
                entry
                for entry in self._group_views.get(target_group, {}).get("groupings", [])
                if isinstance(entry, Mapping) and entry.get("label")
            ]
            if grouping_entries:
                menu.add_separator()
                for entry in grouping_entries:
                    entry_label = str(entry.get("label"))
                    LOG.debug("Adding context entry for grouping '%s' in %s", entry_label, target_group)
                    menu.add_command(
                        label=f"Add to ID Prefix group {entry_label}",
                        command=lambda group=target_group, glabel=entry_label: self._queue_add_payload_to_existing_grouping(group, glabel),
                    )
        if menu.index("end") is None:
            LOG.debug("Context menu aborted: no menu entries for payload=%s", row_id)
            return
        LOG.debug("Posting context menu for payload=%s with %s entries", row_id, menu.index("end") + 1)
        self._payload_context_menu = menu
        menu.bind("<Unmap>", lambda _evt: self._dismiss_payload_context_menu())
        try:
            self._payload_menu_dismiss_bind = self.root.bind(
                "<Button-1>", lambda _evt: self._dismiss_payload_context_menu(), add="+"
            )
        except tk.TclError:
            self._payload_menu_dismiss_bind = None

        def _menu_click_handler(evt, menu_ref=menu):
            self._on_payload_context_menu_click(evt, menu_ref)
            return "break"

        menu.bind("<ButtonRelease-1>", _menu_click_handler)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _prompt_add_prefix_to_grouping(
        self,
        *,
        group_name: str,
        grouping_label: str,
        default_prefix: str,
        existing_prefixes: Tuple[PrefixEntry, ...],
        payload_id: Optional[str],
    ) -> None:
        try:
            dialog = AddPrefixDialog(
                self.root,
                group_name=group_name,
                grouping_label=grouping_label,
                default_prefix=default_prefix,
                payload_id=payload_id,
            )
            LOG.debug(
                "Displayed AddPrefixDialog for payload prefix: group=%s grouping=%s default=%s",
                group_name,
                grouping_label,
                default_prefix,
            )
        except tk.TclError as exc:
            messagebox.showerror("Add to ID Prefix group", f"Unable to show prefix dialog: {exc}")
            LOG.exception("Failed to open AddPrefixDialog for %s/%s", group_name, grouping_label)
            return
        prefix_entry = getattr(dialog, "result", None)
        if prefix_entry is None:
            LOG.debug("Add-to-prefix cancelled via dialog for %s/%s", group_name, grouping_label)
            self.status_var.set(f"Add to ID Prefix group '{grouping_label}' cancelled.")
            return
        if any(p.key == prefix_entry.key for p in existing_prefixes):
            LOG.debug(
                "Add-to-prefix skipped: '%s' already exists in %s/%s",
                prefix_entry.value,
                group_name,
                grouping_label,
            )
            self.status_var.set(
                f"ID Prefix group '{grouping_label}' already includes '{prefix_entry.value}' with that match mode."
            )
            return
        updated_prefixes = list(existing_prefixes) + [prefix_entry]
        try:
            self._group_store.update_grouping(group_name, grouping_label, prefixes=updated_prefixes)
        except Exception as exc:
            LOG.exception("Failed to update grouping %s/%s with prefix '%s'", group_name, grouping_label, prefix_entry)
            messagebox.showerror("Add to ID Prefix group", f"Failed to update '{grouping_label}': {exc}")
            return
        LOG.debug(
            "Add-to-prefix succeeded: group=%s grouping=%s prefix=%s updated_prefixes=%s",
            group_name,
            grouping_label,
            prefix_entry,
            updated_prefixes,
        )
        self.status_var.set(f"Added '{prefix_entry.value}' to ID Prefix group '{grouping_label}'.")
        self._refresh_group_data(target_group=group_name)
        self._purge_matched()

    def _on_payload_context_menu_click(self, event, menu: tk.Menu) -> None:
        """Handle left-click release within the payload context menu."""
        if menu != getattr(self, "_payload_context_menu", None):
            LOG.debug("Menu click ignored: context menu no longer active.")
            return
        try:
            index = menu.index(f"@{event.x},{event.y}")
        except tk.TclError:
            LOG.debug("Menu click ignored: invalid coordinates (%s,%s).", event.x, event.y)
            return
        if index is None:
            LOG.debug("Menu click ignored: no entry at (%s,%s).", event.x, event.y)
            return
        menu.activate(index)
        label = menu.entrycget(index, "label")
        LOG.debug("Menu click invoking entry %s (%s)", index, label)
        try:
            menu.invoke(index)
        except tk.TclError as exc:
            LOG.debug("Menu invoke failed for index %s: %s", index, exc)

    def _open_new_grouping_dialog_from_payload(self, group_name: str) -> None:
        self._dismiss_payload_context_menu()
        if group_name not in self._group_views:
            LOG.debug("New grouping dialog aborted: %s not in current views.", group_name)
            return
        if self.selected_group_var.get() != group_name:
            self.selected_group_var.set(group_name)
            self._on_group_selected()
        suggestion = self._build_grouping_dialog_suggestion(group_name)
        LOG.debug("Opening NewGroupingDialog from payload for group %s with suggestion %s", group_name, suggestion)
        self._open_new_grouping_dialog(group_name, suggestion=suggestion)

    def _refresh_group_data(self, target_group: Optional[str] = None) -> None:
        views = self._group_store.iter_group_views()
        self._unmatched_by_group = self._collect_unmatched_payloads(views)
        self._group_views = {view["name"]: view for view in views}
        names = sorted(self._group_views.keys(), key=str.casefold)
        self.group_selector.configure(values=names)
        if not names:
            self.selected_group_var.set("")
            self._render_selected_group(None)
            self._refresh_payload_list()
            return
        current = target_group or self.selected_group_var.get()
        if current not in names:
            current = names[0]
        self.selected_group_var.set(current)
        self._render_selected_group(current)
        self._refresh_payload_list()

    def _render_selected_group(self, group_name: Optional[str]) -> None:
        self._clear_grouping_entries()
        if not group_name or group_name not in self._group_views:
            self.group_name_var.set("Select a group")
            self.group_match_var.set("-")
            self.group_notes_var.set("-")
            return
        view = self._group_views[group_name]
        match_text = ", ".join(view.get("match_prefixes", [])) or "- none -"
        notes_text = view.get("notes") or "- none -"
        self.group_name_var.set(group_name)
        self.group_match_var.set(match_text)
        self.group_notes_var.set(notes_text)

        entries: List[Dict[str, object]] = list(view.get("groupings", []))
        self._render_grouping_entries(group_name, entries)
        self._reset_grouping_scroll()

    def _clear_grouping_entries(self) -> None:
        if not self.grouping_entries_frame:
            return
        for child in self.grouping_entries_frame.winfo_children():
            child.destroy()

    def _render_grouping_entries(self, group_name: str, entries: List[Dict[str, object]]) -> None:
        if not self.grouping_entries_frame:
            return
        if not entries:
            ttk.Label(self.grouping_entries_frame, text="No groupings defined.", padding=(8, 2)).pack(anchor="w")
            return
        for index, entry in enumerate(entries):
            # extra padding makes each grouping easier to scan
            entry_frame = ttk.Frame(self.grouping_entries_frame, padding=(6, 4, 6, 6))
            entry_frame.pack(fill="x", padx=6, pady=4)
            entry_frame.grid_columnconfigure(0, weight=0, minsize=LEFT_COLUMN_WIDTH)
            entry_frame.grid_columnconfigure(1, weight=1)
            label_text = entry.get("label") or "- unnamed -"
            ttk.Label(entry_frame, text=label_text, font=self._grouping_label_font).grid(row=0, column=0, columnspan=3, sticky="w")
            anchor_value = entry.get("anchor") or "- default -"
            justification_value = entry.get("payloadJustification") or DEFAULT_PAYLOAD_JUSTIFICATION
            if isinstance(justification_value, str):
                justification_value = justification_value.strip().lower() or DEFAULT_PAYLOAD_JUSTIFICATION
            else:
                justification_value = DEFAULT_PAYLOAD_JUSTIFICATION
            if justification_value not in PAYLOAD_JUSTIFICATION_CHOICES:
                justification_value = DEFAULT_PAYLOAD_JUSTIFICATION
            marker_label_value = entry.get("markerLabelPosition") or DEFAULT_MARKER_LABEL_POSITION
            if isinstance(marker_label_value, str):
                marker_label_value = marker_label_value.strip().lower() or DEFAULT_MARKER_LABEL_POSITION
            else:
                marker_label_value = DEFAULT_MARKER_LABEL_POSITION
            if marker_label_value not in MARKER_LABEL_POSITION_CHOICES:
                marker_label_value = DEFAULT_MARKER_LABEL_POSITION
            preview_box_value = entry.get("controllerPreviewBoxMode") or DEFAULT_CONTROLLER_PREVIEW_BOX_MODE
            if isinstance(preview_box_value, str):
                preview_box_value = preview_box_value.strip().lower() or DEFAULT_CONTROLLER_PREVIEW_BOX_MODE
            else:
                preview_box_value = DEFAULT_CONTROLLER_PREVIEW_BOX_MODE
            if preview_box_value not in CONTROLLER_PREVIEW_BOX_MODE_CHOICES:
                preview_box_value = DEFAULT_CONTROLLER_PREVIEW_BOX_MODE
            notes_text = entry.get("notes") or "- none -"
            left_cell = ttk.Frame(entry_frame, width=LEFT_COLUMN_WIDTH)
            left_cell.grid(row=1, column=0, sticky="nw", pady=(2, 0))
            left_cell.grid_propagate(False)
            ttk.Label(left_cell, text=f"Anchor: {anchor_value}").pack(anchor="w")
            ttk.Label(left_cell, text=f"Justification: {justification_value}").pack(anchor="w", pady=(2, 0))
            ttk.Label(left_cell, text=f"Marker label: {marker_label_value}").pack(anchor="w", pady=(2, 0))
            ttk.Label(left_cell, text=f"Controller preview: {preview_box_value}").pack(anchor="w", pady=(2, 0))
            offset_label = (
                f"Offset: x={self._format_offset_value(entry.get('offsetX'))}, "
                f"y={self._format_offset_value(entry.get('offsetY'))}"
            )
            ttk.Label(left_cell, text=offset_label).pack(anchor="w", pady=(2, 0))
            notes_label = ttk.Label(left_cell, text=f"Notes: {notes_text}", wraplength=LEFT_COLUMN_WIDTH, justify="left")
            notes_label.pack(anchor="w", pady=(2, 0))

            prefix_entries = parse_prefix_entries(entry.get("prefixEntries"))
            if not prefix_entries:
                prefix_entries = parse_prefix_entries(entry.get("prefixes"))
            display_prefixes = [p.display_label() for p in prefix_entries]
            prefix_block = "\n".join(display_prefixes) if display_prefixes else "- none -"
            prefix_frame = ttk.Frame(entry_frame)
            prefix_frame.grid(row=1, column=1, sticky="nw", padx=(20, 0))
            ttk.Label(prefix_frame, text="Prefixes", font=("TkDefaultFont", 9, "underline")).pack(anchor="w")
            tk.Label(prefix_frame, text=prefix_block, justify="left", anchor="w", wraplength=520).pack(anchor="w", pady=(2, 0))

            button_frame = ttk.Frame(entry_frame)
            button_frame.grid(row=1, column=2, rowspan=2, padx=(18, 0), pady=(0, 4), sticky="n")
            ttk.Button(
                button_frame,
                text="Edit",
                command=lambda group=group_name, entry_data=entry: self._open_edit_grouping_dialog(group, entry_data),
            ).pack(fill="x")
            ttk.Button(
                button_frame,
                text="Delete",
                command=lambda group=group_name, entry_label=entry.get("label"): self._delete_grouping(group, entry_label),
            ).pack(fill="x", pady=(4, 0))
            log_path = self._log_path_for_group_label(entry.get("label"))
            if log_path:
                ttk.Button(
                    button_frame,
                    text="Play",
                    command=lambda path=log_path: self._play_group_log(path),
                ).pack(fill="x", pady=(4, 0))
            if index < len(entries) - 1:
                ttk.Separator(self.grouping_entries_frame, orient="horizontal").pack(fill="x", padx=4, pady=(0, 4))

    def _reset_grouping_scroll(self) -> None:
        if self.grouping_canvas is None:
            return
        self.grouping_canvas.yview_moveto(0.0)

    @staticmethod
    def _format_offset_value(value: Optional[object]) -> str:
        if isinstance(value, int):
            return str(value)
        if isinstance(value, float):
            if value.is_integer():
                return str(int(value))
            return f"{value:g}"
        return "0"

    @staticmethod
    def _format_aspect_ratio(width: int, height: int) -> str:
        try:
            divisor = math.gcd(int(width), int(height))
        except (ValueError, TypeError):
            return "?"
        if divisor <= 0:
            return "?"
        return f"{width // divisor}:{height // divisor}"

    @staticmethod
    def _overflow_indicator(width: int, height: int) -> str:
        try:
            ratio = float(width) / float(height)
        except (TypeError, ValueError, ZeroDivisionError):
            return ""
        if math.isclose(ratio, BASE_ASPECT_RATIO, rel_tol=1e-3, abs_tol=1e-3):
            return ""
        return "↓" if ratio > BASE_ASPECT_RATIO else "→"

    def _selected_replay_resolutions(self) -> List[Tuple[int, int]]:
        selections: List[Tuple[int, int]] = []
        for width, height in REPLAY_RESOLUTIONS:
            var = self.replay_resolution_vars.get((width, height))
            if var is not None and var.get():
                selections.append((width, height))
        return selections

    def _select_all_replay_resolutions(self) -> None:
        for var in self.replay_resolution_vars.values():
            var.set(True)

    def _clear_replay_resolutions(self) -> None:
        for var in self.replay_resolution_vars.values():
            var.set(False)

    def _resolve_replay_ttl(self) -> int:
        raw_value = (self.replay_ttl_var.get() or "").strip()
        if not raw_value:
            return DEFAULT_REPLAY_TTL
        try:
            numeric = float(raw_value)
        except ValueError:
            raise RuntimeError("Replay TTL must be a positive number.")
        if numeric <= 0:
            raise RuntimeError("Replay TTL must be a positive number.")
        ttl = int(round(numeric))
        return max(1, ttl)

    @staticmethod
    def _resolve_crosshair_percentage(value: str, axis: str) -> Optional[float]:
        raw_value = (value or "").strip()
        if not raw_value:
            return None
        multiplier = 1.0
        mode: Optional[str] = None
        base = BASE_WIDTH if axis.upper() == "X" else BASE_HEIGHT
        if raw_value.lower().endswith("px"):
            raw_value = raw_value[:-2].strip()
            multiplier = 100.0 / base
            mode = "px"
        elif raw_value.endswith("%"):
            raw_value = raw_value[:-1].strip()
            mode = "%"
        else:
            # Unlabelled inputs are interpreted as pixels.
            multiplier = 100.0 / base
            mode = "px"
        try:
            numeric = float(raw_value)
        except ValueError:
            raise RuntimeError(
                f"Crosshair {axis} must be a percent with '%' (e.g. 50%) or a pixel value (e.g. 640 or 640px) relative to a 1280x960 window."
            )
        numeric *= multiplier
        if mode == "%":
            if numeric < 0.0 or numeric > 100.0:
                raise RuntimeError(f"Crosshair {axis} value must be between 0 and 100 (received {numeric:g}).")
        if numeric < 0.0 or numeric > 100.0:
            raise RuntimeError(f"Crosshair {axis} value must be between 0 and 100 (received {numeric:g}).")
        return numeric

    def _sleep_with_stop_check(self, seconds: float) -> None:
        time.sleep(max(0.0, seconds))

    def _launch_mock_window(
        self,
        width: int,
        height: int,
        *,
        crosshair_x: Optional[float] = None,
        crosshair_y: Optional[float] = None,
    ) -> subprocess.Popen[Any]:
        if not MOCK_WINDOW_PATH.exists():
            raise RuntimeError(f"Mock window script not found at {MOCK_WINDOW_PATH}.")
        env = dict(os.environ)
        env["MOCK_ELITE_WIDTH"] = str(width)
        env["MOCK_ELITE_HEIGHT"] = str(height)
        command = [
            sys.executable,
            str(MOCK_WINDOW_PATH),
            "--title",
            MOCK_WINDOW_TITLE,
            "--size",
            f"{width}x{height}",
        ]
        if crosshair_x is not None:
            command.extend(["--crosshair-x", f"{crosshair_x:g}"])
        if crosshair_y is not None:
            command.extend(["--crosshair-y", f"{crosshair_y:g}"])
        try:
            process = subprocess.Popen(command, cwd=ROOT_DIR, env=env)
            self._active_mock_process = process
            return process
        except OSError as exc:
            raise RuntimeError(f"Failed to launch mock window: {exc}") from exc

    def _terminate_mock_window(self, process: Optional[subprocess.Popen[Any]]) -> None:
        if process is None:
            return
        if process.poll() is not None:
            if process is self._active_mock_process:
                self._active_mock_process = None
            return
        try:
            process.terminate()
        except Exception:
            pass
        try:
            process.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
                try:
                    process.kill()
                    process.wait(timeout=1.0)
                except Exception:
                    pass
        if process is self._active_mock_process:
            self._active_mock_process = None

    @staticmethod
    def _log_path_for_group_label(label_value: Optional[object]) -> Optional[Path]:
        if not isinstance(label_value, str):
            return None
        slug = label_value.strip().lower().replace(" ", "_")
        if not slug:
            return None
        candidate = PAYLOAD_STORE_DIR / f"{slug}.log"
        if candidate.exists():
            return candidate
        return None

    def _play_group_log(self, log_path: Path) -> None:
        title = "Replay payloads"
        try:
            ttl_value = self._resolve_replay_ttl()
            crosshair_x = self._resolve_crosshair_percentage(self.crosshair_x_var.get(), "X")
            crosshair_y = self._resolve_crosshair_percentage(self.crosshair_y_var.get(), "Y")
            port = self._load_overlay_port()
            self._wait_for_overlay_ready(port)
            messages = self._load_payloads_from_log(log_path)
        except RuntimeError as exc:
            self._report_playback_error(title, str(exc))
            return
        if not messages:
            messagebox.showinfo(title, f"No playable payloads were found in {log_path.name}.")
            return
        resolutions = self._selected_replay_resolutions()
        if not resolutions:
            resolutions = [(1280, 960)]
        total_resolutions = len(resolutions)
        for idx, resolution in enumerate(resolutions, start=1):
            label = f"{resolution[0]}x{resolution[1]}"
            self.status_var.set(f"Replaying {log_path.name} at {label} ({idx}/{total_resolutions})…")
            self.root.update_idletasks()
            mock_process = None
            try:
                width, height = resolution
                mock_process = self._launch_mock_window(width, height, crosshair_x=crosshair_x, crosshair_y=crosshair_y)
                self._sleep_with_stop_check(REPLAY_WINDOW_WAIT_SECONDS)
                total = len(messages)
                for seq, payload in enumerate(messages, start=1):
                    payload_copy = json.loads(json.dumps(payload))
                    payload_body = payload_copy.get("payload")
                    if isinstance(payload_body, dict):
                        payload_body["ttl"] = ttl_value
                    meta = payload_copy.setdefault("meta", {})
                    if isinstance(meta, dict):
                        meta.setdefault("sequence", seq)
                        meta.setdefault("count", total)
                        if resolution is not None:
                            meta["resolution"] = label
                    response = self._send_payload_to_client(port, payload_copy)
                    if response.get("status") != "ok":
                        error_msg = response.get("error") or response
                        self._report_playback_error(title, f"Overlay client reported an error for payload {seq}: {error_msg}")
                        return
                self._sleep_with_stop_check(ttl_value + 2.0)
            finally:
                self._terminate_mock_window(mock_process)
        success_msg = f"Sent {len(messages)} payload(s) from {log_path.name}."
        self.status_var.set(success_msg)

    @staticmethod
    def _report_playback_error(title: str, message: str) -> None:
        print(f"[plugin-group-manager] {title}: {message}", file=sys.stderr)
        messagebox.showerror(title, message)

    def _load_overlay_port(self) -> int:
        try:
            port_data = json.loads(PORT_PATH.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise RuntimeError(f"port.json was not found at {PORT_PATH}") from exc
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Failed to parse port.json: {exc}") from exc
        port = port_data.get("port")
        if not isinstance(port, int) or port <= 0:
            raise RuntimeError(f"port.json did not contain a valid port number: {port}")
        return port

    def _wait_for_overlay_ready(self, port: int, timeout: float = 30.0) -> None:
        deadline = time.monotonic() + timeout
        attempt = 0
        while True:
            attempt += 1
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=2.0):
                    return
            except OSError as exc:
                if time.monotonic() >= deadline:
                    raise RuntimeError(
                        f"Timed out waiting for the overlay broadcaster on port {port}: {exc}"
                    ) from exc
                time.sleep(0.5)

    def _load_payloads_from_log(self, log_path: Path) -> List[Dict[str, Any]]:
        if not log_path.exists():
            raise RuntimeError(f"Log file not found: {log_path}")
        messages: List[Dict[str, Any]] = []
        try:
            with log_path.open("r", encoding="utf-8") as handle:
                for line_no, line in enumerate(handle, start=1):
                    payload = self._extract_payload_from_log_line(line, line_no, log_path)
                    if payload is None:
                        continue
                    messages.append(payload)
        except OSError as exc:
            raise RuntimeError(f"Failed to read {log_path}: {exc}") from exc
        return messages

    @staticmethod
    def _extract_payload_from_log_line(raw_line: str, line_no: int, log_path: Path) -> Optional[Dict[str, Any]]:
        record = PluginGroupManagerApp._extract_json_segment(raw_line)
        if record is None:
            return None
        payload_obj = record.get("raw")
        if not isinstance(payload_obj, dict):
            payload_obj = record.get("payload")
        if not isinstance(payload_obj, dict):
            payload_obj = record
        if not isinstance(payload_obj, dict):
            return None
        payload = dict(payload_obj)
        payload_type = payload.get("type")
        if isinstance(payload_type, str):
            payload_type_cf = payload_type.casefold()
            if payload_type_cf == "legacy_clear":
                return None
        if str(payload.get("event") or "").strip().lower() == "legacyoverlay":
            payload.setdefault("event", "LegacyOverlay")
            payload_type = str(payload.get("type") or "message").lower()
            if payload_type == "message":
                text_value = str(payload.get("text") or "").strip()
                if not text_value:
                    return None
        ttl_value = payload.get("ttl")
        if isinstance(ttl_value, (int, float)) and ttl_value <= 0:
            return None
        event = payload.get("event") or record.get("event")
        if not isinstance(event, str) or not event:
            return None
        payload["event"] = event
        return {
            "cli": "legacy_overlay",
            "payload": payload,
            "meta": {
                "source": "plugin_group_manager",
                "logfile": str(log_path),
                "line": line_no,
            },
        }

    @staticmethod
    def _extract_json_segment(line: str) -> Optional[Dict[str, Any]]:
        start = line.find("{")
        if start == -1:
            return None
        segment = line[start:]
        try:
            return json.loads(segment)
        except json.JSONDecodeError:
            return None

    @staticmethod
    def _send_payload_to_client(port: int, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        message = json.dumps(payload, ensure_ascii=False)
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=5.0) as sock:
                sock.settimeout(5.0)
                writer = sock.makefile("w", encoding="utf-8", newline="\n")
                reader = sock.makefile("r", encoding="utf-8")
                writer.write(message)
                writer.write("\n")
                writer.flush()
                for _ in range(10):
                    response_line = reader.readline()
                    if not response_line:
                        raise RuntimeError("Connection closed before acknowledgement was received.")
                    try:
                        response = json.loads(response_line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(response, Mapping) and "status" in response:
                        return dict(response)
                raise RuntimeError("Did not receive an acknowledgement from the overlay client.")
        except OSError as exc:
            raise RuntimeError(
                f"Failed to send payload to the overlay client on port {port}: {exc}. "
                "Ensure the Modern Overlay window is running."
            ) from exc

    def _on_group_selected(self) -> None:
        name = self.selected_group_var.get()
        self._render_selected_group(name if name else None)

    def _collect_unmatched_payloads(self, views: Sequence[Mapping[str, object]]) -> Dict[str, List[str]]:
        unmatched: Dict[str, List[str]] = {view["name"]: [] for view in views}
        if not views:
            return unmatched
        records = self._payload_store.records()
        if not records:
            return unmatched

        view_match_data: List[Tuple[str, List[str], List[PrefixEntry]]] = []
        for view in views:
            match_prefixes = [
                prefix.casefold()
                for prefix in view.get("match_prefixes", [])
                if isinstance(prefix, str) and prefix.strip()
            ]
            grouping_prefixes: List[PrefixEntry] = []
            for entry in view.get("groupings", []):
                raw_entries = entry.get("prefixEntries") or entry.get("prefixes") or []
                grouping_prefixes.extend(parse_prefix_entries(raw_entries))
            view_match_data.append((view["name"], match_prefixes, grouping_prefixes))

        for record in records:
            payload_id = record.payload_id
            if not payload_id:
                continue
            if record.group and record.group in unmatched:
                unmatched[record.group].append(payload_id)
                continue
            payload_cf = payload_id.casefold()
            for name, match_prefixes, grouping_prefixes in view_match_data:
                if not match_prefixes:
                    continue
                if not any(payload_cf.startswith(prefix) for prefix in match_prefixes):
                    continue
                if grouping_prefixes and any(prefix.matches(payload_id) for prefix in grouping_prefixes):
                    continue
                unmatched[name].append(payload_id)
        return unmatched

    # Actions -------------------------------------------------------------
    def _toggle_watcher(self) -> None:
        if self.watch_var.get():
            if not self._ensure_payload_logging_enabled():
                self.watch_var.set(False)
                return
            self._start_watcher()
        else:
            self._stop_watcher()

    def _ensure_payload_logging_enabled(self) -> bool:
        enabled = False
        try:
            settings_data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        except FileNotFoundError:
            settings_data = {}
        except (OSError, json.JSONDecodeError):
            settings_data = {}
        if isinstance(settings_data, Mapping):
            flag = settings_data.get("log_payloads")
            if isinstance(flag, bool):
                enabled = flag
            elif flag is not None:
                enabled = bool(flag)
        if not enabled:
            try:
                data = json.loads(DEBUG_CONFIG_PATH.read_text(encoding="utf-8"))
            except FileNotFoundError:
                data = {}
            except (OSError, json.JSONDecodeError):
                data = {}
            if isinstance(data, Mapping):
                payload_logging = data.get("payload_logging")
                if isinstance(payload_logging, Mapping):
                    flag = payload_logging.get("overlay_payload_log_enabled")
                    if isinstance(flag, bool):
                        enabled = flag
                    elif flag is not None:
                        enabled = bool(flag)
        if not enabled:
            messagebox.showerror(
                "Watcher unavailable",
                "Enable payload logging from the Modern Overlay preferences before starting the watcher.",
            )
            return False
        return True

    def _start_watcher(self) -> None:
        if self._watcher and self._watcher.is_alive():
            return
        self.status_var.set("Starting watcher...")
        self._watcher = PayloadWatcher(self._locator, self._matcher, self._payload_store, self._queue)
        self._watcher.start()

    def _stop_watcher(self) -> None:
        if self._watcher:
            self._watcher.stop()
            self._watcher = None
        self.status_var.set("Watcher disabled.")

    def _start_gather(self) -> None:
        if self._gather_thread and self._gather_thread.is_alive():
            messagebox.showinfo("Gather running", "A gather operation is already in progress.")
            return
        self.status_var.set("Gathering payload IDs from logs...")
        self._gather_thread = LogGatherer(self._locator, self._matcher, self._payload_store, self._queue)
        self._gather_thread.start()

    def _purge_matched(self, emit_status: bool = True) -> int:
        self._matcher.refresh()
        removed = self._payload_store.remove_matched(self._matcher)
        if removed:
            self._refresh_payload_list()
        self._update_payload_count()
        if emit_status:
            message = f"Removed {removed} payload(s) that now match configured groupings."
            self.status_var.set(message)
        return removed

    def _enable_group_scroll(self, _event) -> None:
        if self._group_scroll_bound:
            return
        self.root.bind_all("<MouseWheel>", self._on_mouse_wheel, add="+")
        self.root.bind_all("<Button-4>", self._on_mouse_wheel, add="+")
        self.root.bind_all("<Button-5>", self._on_mouse_wheel, add="+")
        self._group_scroll_bound = True

    def _disable_group_scroll(self, _event) -> None:
        if not self._group_scroll_bound:
            return
        self.root.unbind_all("<MouseWheel>")
        self.root.unbind_all("<Button-4>")
        self.root.unbind_all("<Button-5>")
        self._group_scroll_bound = False

    def _on_mouse_wheel(self, event) -> None:
        if not self.grouping_canvas or not self._is_pointer_over_grouping():
            return
        event_num = getattr(event, "num", None)
        if event_num == 4:
            delta = -1
        elif event_num == 5:
            delta = 1
        else:
            wheel_delta = getattr(event, "delta", 0)
            if wheel_delta == 0:
                return
            delta = -1 if wheel_delta > 0 else 1
        self.grouping_canvas.yview_scroll(delta, "units")

    def _is_pointer_over_grouping(self) -> bool:
        if not self._group_scroll_targets:
            return False
        try:
            pointer_widget = self.root.winfo_containing(self.root.winfo_pointerx(), self.root.winfo_pointery())
        except (tk.TclError, KeyError):
            return False
        if pointer_widget is None:
            return False
        for target in self._group_scroll_targets:
            if target is None:
                continue
            if self._widget_is_descendant(pointer_widget, target):
                return True
        return False

    @staticmethod
    def _widget_is_descendant(widget: tk.Widget, ancestor: tk.Widget) -> bool:
        current: Optional[tk.Widget] = widget
        while current is not None:
            if current == ancestor:
                return True
            current = getattr(current, "master", None)
        return False

    def _inspect_selected_payload(self, event) -> None:
        selection = self.payload_list.selection()
        if not selection:
            return
        payload_id = selection[0]
        record = self._payload_store.get(payload_id)
        if record is None or record.payload is None:
            messagebox.showinfo("Inspect payload", "Payload contents are no longer available.")
            return
        try:
            payload_json = json.dumps(record.payload, indent=2, ensure_ascii=False)
        except (TypeError, ValueError):
            payload_json = str(record.payload)

        window = tk.Toplevel(self.root)
        window.title(f"Payload: {payload_id}")
        window.geometry("800x500")

        text_frame = ttk.Frame(window)
        text_frame.pack(fill="both", expand=True)

        text_widget = tk.Text(text_frame, wrap="none", font=("Courier", 10))
        text_widget.insert("1.0", payload_json)
        text_widget.configure(state="disabled")

        scroll_y = ttk.Scrollbar(text_frame, orient="vertical", command=text_widget.yview)
        scroll_x = ttk.Scrollbar(text_frame, orient="horizontal", command=text_widget.xview)
        text_widget.configure(yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set)

        text_widget.grid(row=0, column=0, sticky="nsew")
        scroll_y.grid(row=0, column=1, sticky="ns")
        scroll_x.grid(row=1, column=0, sticky="ew")
        text_frame.rowconfigure(0, weight=1)
        text_frame.columnconfigure(0, weight=1)

    def _open_new_group_dialog(self, suggestion: Optional[Mapping[str, object]] = None) -> None:
        dialog = NewGroupDialog(self.root, title="Create new group", suggestion=suggestion)
        if dialog.result is None:
            return
        data = dialog.result
        try:
            self._group_store.add_group(
                name=data["name"],
                notes=data["notes"],
                match_prefixes=data["match_prefixes"],
            )
        except ValueError as exc:
            messagebox.showerror("Failed to add group", str(exc))
            return
        except OSError as exc:
            messagebox.showerror("Failed to add group", f"Could not write overlay_groupings.json: {exc}")
            return
        self._refresh_group_data(target_group=data["name"])
        self.status_var.set(f"Added group '{data['name']}'.")
        self._purge_matched()

    def _open_new_group_dialog_from_payload(self) -> None:
        """Close the context menu and open the new-group dialog."""
        self._dismiss_payload_context_menu()
        suggestion = self._build_group_dialog_suggestion()
        self._open_new_group_dialog(suggestion)

    def _open_edit_group_dialog(self, group_name: str) -> None:
        if not group_name:
            messagebox.showerror("Edit group", "Select a plugin group first.")
            return
        entry = self._group_store.get_group(group_name)
        if entry is None:
            messagebox.showerror("Edit group", f"Group '{group_name}' no longer exists.")
            return
        dialog = EditGroupDialog(self.root, group_name, entry)
        if dialog.result is None:
            return
        data = dialog.result
        try:
            self._group_store.update_group(
                original_name=group_name,
                new_name=data["name"],
                match_prefixes=data["match_prefixes"],
                notes=data["notes"],
            )
        except ValueError as exc:
            messagebox.showerror("Failed to edit group", str(exc))
            return
        except OSError as exc:
            messagebox.showerror("Failed to edit group", f"Could not write overlay_groupings.json: {exc}")
            return
        self._refresh_group_data(target_group=data["name"])
        self.status_var.set(f"Updated group '{data['name']}'.")
        self._purge_matched()

    def _open_new_grouping_dialog(self, group_name: str, suggestion: Optional[Mapping[str, object]] = None) -> None:
        if not group_name:
            messagebox.showerror("Add grouping", "Select a plugin group first.")
            return
        dialog = NewGroupingDialog(self.root, group_name, suggestion=suggestion)
        if dialog.result is None:
            return
        data = dialog.result
        try:
            self._group_store.add_grouping(
                group_name=group_name,
                label=data["label"],
                prefixes=data["prefixes"],
                anchor=data["anchor"],
                notes=data["notes"],
                offset_x=data.get("offset_x"),
                offset_y=data.get("offset_y"),
                payload_justification=data.get("payload_justification"),
                marker_label_position=data.get("marker_label_position"),
                controller_preview_box_mode=data.get("controller_preview_box_mode"),
                background_color=data.get("background_color"),
                background_border_color=data.get("background_border_color"),
                background_border_width=data.get("background_border_width"),
            )
        except ValueError as exc:
            messagebox.showerror("Failed to add grouping", str(exc))
            return
        except OSError as exc:
            messagebox.showerror("Failed to add grouping", f"Could not write overlay_groupings.json: {exc}")
            return
        self._refresh_group_data()
        self.status_var.set(f"Added grouping '{data['label']}' to {group_name}.")
        self._purge_matched()

    def _open_edit_grouping_dialog(self, group_name: str, entry: Mapping[str, object]) -> None:
        dialog = EditGroupingDialog(self.root, group_name, entry)
        if dialog.result is None:
            return
        data = dialog.result
        original_label = data.get("original_label") or entry.get("label")
        if not isinstance(original_label, str) or not original_label:
            messagebox.showerror("Failed to edit grouping", "Could not determine the selected grouping label.")
            return
        try:
            self._group_store.update_grouping(
                group_name=group_name,
                label=original_label,
                new_label=data.get("label"),
                prefixes=data.get("prefixes"),
                anchor=data.get("anchor"),
                notes=data.get("notes"),
                offset_x=data.get("offset_x"),
                offset_y=data.get("offset_y"),
                payload_justification=data.get("payload_justification"),
                marker_label_position=data.get("marker_label_position"),
                controller_preview_box_mode=data.get("controller_preview_box_mode"),
                background_color=data.get("background_color"),
                background_border_color=data.get("background_border_color"),
                background_border_width=data.get("background_border_width"),
            )
        except ValueError as exc:
            messagebox.showerror("Failed to edit grouping", str(exc))
            return
        except OSError as exc:
            messagebox.showerror("Failed to edit grouping", f"Could not write overlay_groupings.json: {exc}")
            return
        self._refresh_group_data()
        self.status_var.set(f"Updated grouping '{data.get('label')}' in {group_name}.")
        self._purge_matched()

    def _delete_grouping(self, group_name: str, label: str) -> None:
        if not messagebox.askyesno("Delete grouping", f"Delete grouping '{label}' from {group_name}?"):
            return
        try:
            self._group_store.delete_grouping(group_name, label)
        except OSError as exc:
            messagebox.showerror("Failed to delete grouping", f"Could not update overlay_groupings.json: {exc}")
            return
        self._refresh_group_data()
        self.status_var.set(f"Deleted grouping '{label}' from {group_name}.")
        self._purge_matched()

    def _delete_group(self, group_name: str) -> None:
        if not messagebox.askyesno("Delete group", f"Delete group '{group_name}' and all of its groupings?"):
            return
        try:
            self._group_store.delete_group(group_name)
        except OSError as exc:
            messagebox.showerror("Failed to delete group", f"Could not update overlay_groupings.json: {exc}")
            return
        self._refresh_group_data()
        self.status_var.set(f"Deleted group '{group_name}'.")
        self._purge_matched()

    def _delete_selected_group(self) -> None:
        group_name = self.selected_group_var.get()
        if not group_name:
            return
        self._delete_group(group_name)

    def _update_payload_count(self) -> None:
        count = len(self._payload_store)
        self.payload_count_var.set(f"New payloads: {count}")

    # Queue processing ----------------------------------------------------
    def _process_queue(self) -> None:
        if self._closed:
            return
        try:
            while True:
                message_type, payload = self._queue.get_nowait()
                if message_type == "status":
                    self.status_var.set(str(payload))
                elif message_type == "error":
                    self.status_var.set(str(payload))
                    messagebox.showerror("Plugin Group Manager", str(payload))
                elif message_type == "payload_added":
                    self._refresh_payload_list()
                    self._update_payload_count()
                elif message_type == "gather_complete":
                    info = payload if isinstance(payload, Mapping) else {}
                    added = info.get("added", 0)
                    files = info.get("files", 0)
                    self._refresh_payload_list()
                    self._update_payload_count()
                    self.status_var.set(f"Gather complete: added {added} new payload(s) from {files} log file(s).")
        except queue.Empty:
            pass
        if not self._closed:
            self.root.after(200, self._process_queue)

    def _poll_groupings_file(self) -> None:
        if self._closed:
            return
        try:
            changed = self._group_store.refresh_if_changed()
        except Exception as exc:
            LOG.debug("Failed to refresh overlay_groupings.json: %s", exc)
            changed = False
        if changed:
            removed = self._purge_matched(emit_status=False)
            self._refresh_group_data()
            message = "overlay_groupings.json changed on disk; reloaded."
            if removed:
                message += f" Removed {removed} payload(s) that now match configured groupings."
            self.status_var.set(message)
        if not self._closed:
            self.root.after(self._group_file_poll_ms, self._poll_groupings_file)

    def _on_close(self) -> None:
        self._closed = True
        self._stop_watcher()
        self._disable_group_scroll(None)
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    parser = argparse.ArgumentParser(description="Interactive Plugin Group Manager for Modern Overlay.")
    parser.add_argument(
        "--log-dir",
        help=(
            "Directory that contains overlay payload logs (or a specific overlay-payloads.log path). "
            "Defaults to the standard EDMC logs search path."
        ),
    )
    parser.add_argument(
        "--trace-context-menu",
        action="store_true",
        help=(
            "Write verbose context-menu debugging output to "
            f"{TRACE_LOG_PATH.name} beside plugin_group_manager.py."
        ),
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    if args.trace_context_menu:
        TRACE_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(TRACE_LOG_PATH, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        LOG.addHandler(handler)
        LOG.setLevel(logging.DEBUG)
        LOG.propagate = False
        LOG.debug("Context menu tracing enabled. Log file: %s", TRACE_LOG_PATH)
    log_dir_override = Path(args.log_dir).expanduser() if args.log_dir else None
    app = PluginGroupManagerApp(log_dir_override=log_dir_override)
    app.run()


if __name__ == "__main__":
    main()
