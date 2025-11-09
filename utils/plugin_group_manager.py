#!/usr/bin/env python3
"""Interactive Plugin Group Manager for Modern Overlay."""

from __future__ import annotations

import json
import logging
import os
import queue
import re
import sys
import threading
import time
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import messagebox, simpledialog, ttk
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Tuple


ROOT_DIR = Path(__file__).resolve().parents[1]
OVERLAY_CLIENT_DIR = ROOT_DIR / "overlay-client"
if str(OVERLAY_CLIENT_DIR) not in sys.path:
    sys.path.insert(0, str(OVERLAY_CLIENT_DIR))

try:
    from plugin_overrides import PluginOverrideManager
except Exception as exc:  # pragma: no cover - manager required for runtime
    raise SystemExit(f"Failed to import plugin_overrides: {exc}")


LOG = logging.getLogger("plugin-group-manager")
LOG.addHandler(logging.NullHandler())

GROUPINGS_PATH = ROOT_DIR / "overlay_groupings.json"
DEBUG_CONFIG_PATH = ROOT_DIR / "debug.json"
PAYLOAD_LOG_DIR_NAME = "EDMC-ModernOverlay"
PAYLOAD_LOG_BASENAMES = ("overlay-payloads.log", "overlay_payloads.log")
ANCHOR_CHOICES = ("nw", "ne", "sw", "se", "center")


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
            plugin_label, suffix = key
            mode = self._manager.group_mode_for(plugin_label or plugin)
            if mode == "plugin":
                return True
            if mode == "id_prefix":
                return suffix is not None
            return False

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
            mode = self._manager.group_mode_for(plugin_label or plugin)
            if mode == "id_prefix" and suffix is None:
                return plugin_label
        return None


class LogLocator:
    """Resolves payload log directories/files, mirroring plugin runtime logic."""

    def __init__(self, plugin_root: Path) -> None:
        self._plugin_root = plugin_root.resolve()
        self._log_dir = self._resolve_log_dir()

    @property
    def log_dir(self) -> Path:
        return self._log_dir

    def _resolve_log_dir(self) -> Path:
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


class GroupConfigStore:
    """Helper around overlay_groupings.json mutations."""

    def __init__(self, path: Path) -> None:
        self._path = path
        # RLock avoids deadlocks when save() is called from other locked methods.
        self._lock = threading.RLock()
        self._data: Dict[str, MutableMapping[str, object]] = {}
        self._load()

    def _load(self) -> None:
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

    def _normalise_plugin_entry(self, entry: MutableMapping[str, object]) -> MutableMapping[str, object]:
        grouping = entry.get("grouping")
        if isinstance(grouping, Mapping):
            mode = grouping.get("mode")
            mode_token = mode if isinstance(mode, str) else "plugin"
            mode_token = mode_token.strip().lower()
            if mode_token not in {"plugin", "id_prefix"}:
                mode_token = "plugin"
            groups: Dict[str, Dict[str, object]] = {}
            raw_groups = grouping.get("groups")
            if isinstance(raw_groups, Mapping):
                for label, spec in raw_groups.items():
                    if not isinstance(spec, Mapping):
                        continue
                    key = str(label) if isinstance(label, str) else None
                    normalised = self._normalise_group_spec(dict(spec))
                    label_key = key or (normalised["id_prefixes"][0] if normalised["id_prefixes"] else None)
                    if label_key:
                        groups[label_key] = normalised
            prefixes = grouping.get("prefixes")
            if isinstance(prefixes, Mapping):
                for label, value in prefixes.items():
                    label_value = str(label) if isinstance(label, str) else None
                    if isinstance(value, str):
                        spec = {"id_prefixes": [value]}
                    elif isinstance(value, Mapping):
                        raw_prefix = value.get("prefix")
                        if not isinstance(raw_prefix, str):
                            continue
                        spec = dict(value)
                        spec["id_prefixes"] = [raw_prefix]
                    else:
                        continue
                    normalised = self._normalise_group_spec(spec)
                    key = label_value or (normalised["id_prefixes"][0] if normalised["id_prefixes"] else None)
                    if key:
                        groups[key] = normalised
            elif isinstance(prefixes, Iterable):
                for entry in prefixes:
                    if isinstance(entry, str) and entry:
                        groups[entry] = {"id_prefixes": [entry]}
            grouping_dict = {
                "mode": mode_token,
                "groups": groups,
            }
            entry["grouping"] = grouping_dict
        else:
            entry["grouping"] = {"mode": "plugin", "groups": {}}
        return entry

    @staticmethod
    def _normalise_group_spec(spec: MutableMapping[str, object]) -> Dict[str, object]:
        prefixes_field = spec.get("id_prefixes") or spec.get("prefixes")
        prefixes: List[str] = []
        if isinstance(prefixes_field, str):
            prefixes = [prefixes_field]
        elif isinstance(prefixes_field, Iterable):
            for token in prefixes_field:
                if isinstance(token, str) and token.strip():
                    prefixes.append(token.strip())
        if not prefixes:
            single = spec.get("prefix")
            if isinstance(single, str) and single.strip():
                prefixes = [single.strip()]
        spec = dict(spec)
        spec["id_prefixes"] = prefixes
        spec.pop("prefix", None)
        spec.pop("prefixes", None)
        anchor_value = spec.get("anchor")
        if isinstance(anchor_value, str):
            anchor_token = anchor_value.strip().lower()
            if anchor_token in ANCHOR_CHOICES:
                spec["anchor"] = anchor_token
            else:
                spec.pop("anchor", None)
        else:
            spec.pop("anchor", None)
        return spec

    def save(self) -> None:
        with self._lock:
            ordered = {name: self._data[name] for name in sorted(self._data.keys())}
            self._path.write_text(json.dumps(ordered, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

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
                grouping = entry.get("grouping", {})
                groups_block = grouping.get("groups", {})
                view_entries: List[Dict[str, object]] = []
                match_prefixes: List[str] = []

                def _append_prefix(token: object) -> None:
                    if isinstance(token, (str, int, float)):
                        cleaned = str(token).strip()
                        if cleaned and cleaned not in match_prefixes:
                            match_prefixes.append(cleaned)

                match_section = entry.get("__match__")
                if isinstance(match_section, Mapping):
                    match_values = match_section.get("id_prefixes")
                    if isinstance(match_values, str):
                        _append_prefix(match_values)
                    elif isinstance(match_values, Iterable):
                        for token in match_values:
                            _append_prefix(token)

                if isinstance(groups_block, Mapping):
                    for label in sorted(groups_block.keys(), key=str.casefold):
                        spec = groups_block[label]
                        if not isinstance(spec, Mapping):
                            continue
                        prefixes_value = spec.get("id_prefixes") or []
                        prefixes = [
                            str(item).strip()
                            for item in prefixes_value
                            if isinstance(item, (str, int, float)) and str(item).strip()
                        ]
                        anchor = spec.get("anchor") or ""
                        notes = spec.get("notes") or ""
                        view_entries.append(
                            {
                                "label": label,
                                "prefixes": list(prefixes),
                                "anchor": anchor,
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
                        "mode": grouping.get("mode", "plugin"),
                        "groupings": view_entries,
                        "match_prefixes": match_prefixes,
                    }
                )
        return views

    def add_group(
        self,
        name: str,
        notes: Optional[str],
        mode: str,
        initial_grouping: Optional[Dict[str, object]] = None,
    ) -> None:
        cleaned_name = name.strip()
        if not cleaned_name:
            raise ValueError("Group name is required.")
        mode_token = mode if mode in {"plugin", "id_prefix"} else "plugin"
        with self._lock:
            if cleaned_name in self._data:
                raise ValueError(f"Group '{cleaned_name}' already exists.")
            grouping_block: Dict[str, object] = {"mode": mode_token, "groups": {}}
            if initial_grouping:
                label = initial_grouping.get("label")
                if isinstance(label, str) and label:
                    anchor_value = initial_grouping.get("anchor")
                    anchor_token = anchor_value.strip().lower() if isinstance(anchor_value, str) else None
                    if anchor_token and anchor_token not in ANCHOR_CHOICES:
                        raise ValueError(f"Anchor must be one of {', '.join(ANCHOR_CHOICES)}.")
                    entry_spec: Dict[str, object] = {
                        "id_prefixes": list(initial_grouping.get("id_prefixes", [])),
                    }
                    if anchor_token:
                        entry_spec["anchor"] = anchor_token
                    notes_value = initial_grouping.get("notes")
                    if isinstance(notes_value, str) and notes_value.strip():
                        entry_spec["notes"] = notes_value.strip()
                    grouping_block["groups"][label] = entry_spec
            entry: Dict[str, object] = {"grouping": grouping_block}
            cleaned_notes = _normalise_notes(notes)
            if cleaned_notes:
                entry["notes"] = cleaned_notes
            self._data[cleaned_name] = entry
            self.save()

    def delete_group(self, name: str) -> None:
        with self._lock:
            if name in self._data:
                del self._data[name]
                self.save()

    def add_grouping(
        self,
        group_name: str,
        label: str,
        prefixes: Sequence[str],
        anchor: Optional[str],
        notes: Optional[str],
    ) -> None:
        if not prefixes:
            raise ValueError("At least one ID prefix is required.")
        cleaned_label = label.strip()
        if not cleaned_label:
            raise ValueError("Grouping label is required.")
        anchor_token = anchor.strip().lower() if isinstance(anchor, str) else None
        if anchor_token and anchor_token not in ANCHOR_CHOICES:
            raise ValueError(f"Anchor must be one of {', '.join(ANCHOR_CHOICES)}.")
        with self._lock:
            entry = self._data.get(group_name)
            if not entry:
                raise ValueError(f"Group '{group_name}' not found.")
            grouping = entry.get("grouping")
            if not isinstance(grouping, Mapping):
                raise ValueError(f"Group '{group_name}' has no grouping configuration.")
            if grouping.get("mode") != "id_prefix":
                raise ValueError(f"Group '{group_name}' must use id_prefix mode to add groupings.")
            groups = grouping.setdefault("groups", {})
            if not isinstance(groups, dict):
                grouping["groups"] = {}
                groups = grouping["groups"]
            if cleaned_label in groups:
                raise ValueError(f"Grouping '{cleaned_label}' already exists for '{group_name}'.")
            cleaned_notes = notes.strip() if isinstance(notes, str) else None
            groups[cleaned_label] = {
                "id_prefixes": list(prefixes),
            }
            if anchor_token:
                groups[cleaned_label]["anchor"] = anchor_token
            if cleaned_notes:
                groups[cleaned_label]["notes"] = cleaned_notes
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
    ) -> None:
        original_label = label.strip()
        if not original_label:
            raise ValueError("Existing grouping label is required.")
        replacement_label = new_label.strip() if isinstance(new_label, str) and new_label.strip() else original_label
        with self._lock:
            entry = self._data.get(group_name)
            if not entry:
                raise ValueError(f"Group '{group_name}' not found.")
            grouping = entry.get("grouping")
            if not isinstance(grouping, Mapping):
                raise ValueError(f"Group '{group_name}' has no grouping configuration.")
            if grouping.get("mode") != "id_prefix":
                raise ValueError(f"Group '{group_name}' must use id_prefix mode to edit groupings.")
            groups = grouping.get("groups")
            if not isinstance(groups, dict) or original_label not in groups:
                raise ValueError(f"Grouping '{original_label}' not found in '{group_name}'.")
            target_spec = groups[original_label]
            if not isinstance(target_spec, MutableMapping):
                target_spec = {}
                groups[original_label] = target_spec
            if prefixes is not None:
                cleaned_prefixes = [token.strip() for token in prefixes if isinstance(token, str) and token.strip()]
                if not cleaned_prefixes:
                    raise ValueError("At least one ID prefix is required.")
                target_spec["id_prefixes"] = cleaned_prefixes
            if anchor is not None:
                anchor_token = anchor.strip().lower()
                if anchor_token:
                    if anchor_token not in ANCHOR_CHOICES:
                        raise ValueError(f"Anchor must be one of {', '.join(ANCHOR_CHOICES)}.")
                    target_spec["anchor"] = anchor_token
                else:
                    target_spec.pop("anchor", None)
            if notes is not None:
                cleaned_notes = notes.strip()
                if cleaned_notes:
                    target_spec["notes"] = cleaned_notes
                else:
                    target_spec.pop("notes", None)
            if replacement_label != original_label:
                if replacement_label in groups and replacement_label != original_label:
                    raise ValueError(f"Grouping '{replacement_label}' already exists for '{group_name}'.")
                groups[replacement_label] = groups.pop(original_label)
            self.save()

    def delete_grouping(self, group_name: str, label: str) -> None:
        with self._lock:
            entry = self._data.get(group_name)
            if not entry:
                return
            grouping = entry.get("grouping")
            if not isinstance(grouping, Mapping):
                return
            groups = grouping.get("groups")
            if isinstance(groups, dict) and label in groups:
                del groups[label]
                self.save()

    def update_mode(self, group_name: str, mode: str) -> None:
        if mode not in {"plugin", "id_prefix"}:
            raise ValueError("Mode must be 'plugin' or 'id_prefix'.")
        with self._lock:
            entry = self._data.get(group_name)
            if not entry:
                raise ValueError(f"Group '{group_name}' not found.")
            grouping = entry.setdefault("grouping", {"mode": "plugin", "groups": {}})
            grouping["mode"] = mode
            grouping.setdefault("groups", {})
            self.save()


class NewGroupDialog(simpledialog.Dialog):
    """Dialog for creating a brand new plugin group."""

    def body(self, master: tk.Tk) -> tk.Widget:  # type: ignore[override]
        ttk.Label(master, text="Group name").grid(row=0, column=0, sticky="w")
        self.name_var = tk.StringVar()
        ttk.Entry(master, textvariable=self.name_var, width=40).grid(row=0, column=1, sticky="ew")

        ttk.Label(master, text="Mode").grid(row=1, column=0, sticky="w")
        self.mode_var = tk.StringVar(value="id_prefix")
        ttk.Combobox(master, values=("plugin", "id_prefix"), textvariable=self.mode_var, state="readonly").grid(
            row=1, column=1, sticky="w"
        )

        ttk.Label(master, text="Notes").grid(row=2, column=0, sticky="nw")
        self.notes_text = tk.Text(master, width=40, height=4)
        self.notes_text.grid(row=2, column=1, sticky="ew")

        ttk.Label(master, text="Initial grouping label (optional)").grid(row=3, column=0, sticky="w")
        self.group_label_var = tk.StringVar()
        ttk.Entry(master, textvariable=self.group_label_var, width=40).grid(row=3, column=1, sticky="ew")

        ttk.Label(master, text="ID prefixes (comma separated)").grid(row=4, column=0, sticky="w")
        self.prefix_var = tk.StringVar()
        ttk.Entry(master, textvariable=self.prefix_var, width=40).grid(row=4, column=1, sticky="ew")

        ttk.Label(master, text="Anchor").grid(row=5, column=0, sticky="w")
        self.anchor_var = tk.StringVar(value="nw")
        ttk.Combobox(master, values=ANCHOR_CHOICES, textvariable=self.anchor_var, state="readonly").grid(
            row=5, column=1, sticky="w"
        )

        self.initial_notes_var = tk.StringVar()
        ttk.Label(master, text="Grouping notes").grid(row=6, column=0, sticky="w")
        ttk.Entry(master, textvariable=self.initial_notes_var, width=40).grid(row=6, column=1, sticky="ew")
        return master

    def validate(self) -> bool:  # type: ignore[override]
        if not self.name_var.get().strip():
            messagebox.showerror("Validation error", "Group name is required.")
            return False
        mode = self.mode_var.get().strip().lower()
        if mode not in {"plugin", "id_prefix"}:
            messagebox.showerror("Validation error", "Mode must be plugin or id_prefix.")
            return False
        if mode == "id_prefix" and self.group_label_var.get().strip() and not _clean_prefixes(self.prefix_var.get()):
            messagebox.showerror("Validation error", "Enter at least one ID prefix for the initial grouping.")
            return False
        return True

    def result_data(self) -> Dict[str, object]:
        mode = self.mode_var.get().strip().lower()
        initial_grouping = None
        if mode == "id_prefix":
            label_value = self.group_label_var.get().strip()
            prefixes = _clean_prefixes(self.prefix_var.get())
            if label_value and prefixes:
                initial_grouping = {
                    "label": label_value,
                    "id_prefixes": prefixes,
                    "anchor": self.anchor_var.get().strip(),
                    "notes": self.initial_notes_var.get().strip(),
                }
        return {
            "name": self.name_var.get().strip(),
            "notes": self.notes_text.get("1.0", tk.END).strip(),
            "mode": mode,
            "initial_grouping": initial_grouping,
        }

    def apply(self) -> None:  # type: ignore[override]
        self.result = self.result_data()


class NewGroupingDialog(simpledialog.Dialog):
    """Dialog for adding a grouping to an existing plugin."""

    def __init__(self, parent: tk.Tk, group_name: str) -> None:
        self._group_name = group_name
        super().__init__(parent, title=f"Add grouping to {group_name}")

    def body(self, master: tk.Tk) -> tk.Widget:  # type: ignore[override]
        ttk.Label(master, text=f"Group: {self._group_name}").grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(master, text="Label").grid(row=1, column=0, sticky="w")
        self.label_var = tk.StringVar()
        ttk.Entry(master, textvariable=self.label_var, width=40).grid(row=1, column=1, sticky="ew")

        ttk.Label(master, text="ID prefixes (comma separated)").grid(row=2, column=0, sticky="w")
        self.prefix_var = tk.StringVar()
        ttk.Entry(master, textvariable=self.prefix_var, width=40).grid(row=2, column=1, sticky="ew")

        ttk.Label(master, text="Anchor").grid(row=3, column=0, sticky="w")
        self.anchor_var = tk.StringVar(value="nw")
        ttk.Combobox(master, values=ANCHOR_CHOICES, textvariable=self.anchor_var, state="readonly").grid(
            row=3, column=1, sticky="w"
        )

        ttk.Label(master, text="Notes").grid(row=4, column=0, sticky="w")
        self.notes_var = tk.StringVar()
        ttk.Entry(master, textvariable=self.notes_var, width=40).grid(row=4, column=1, sticky="ew")
        return master

    def validate(self) -> bool:  # type: ignore[override]
        label = self.label_var.get().strip()
        if not label:
            messagebox.showerror("Validation error", "Grouping label is required.")
            return False
        prefixes = _clean_prefixes(self.prefix_var.get())
        if not prefixes:
            messagebox.showerror("Validation error", "Enter at least one ID prefix.")
            return False
        return True

    def result_data(self) -> Dict[str, object]:
        return {
            "label": self.label_var.get().strip(),
            "prefixes": _clean_prefixes(self.prefix_var.get()),
            "anchor": self.anchor_var.get().strip(),
            "notes": self.notes_var.get().strip(),
        }

    def apply(self) -> None:  # type: ignore[override]
        self.result = self.result_data()


class EditGroupingDialog(simpledialog.Dialog):
    """Dialog for editing an existing grouping entry."""

    def __init__(self, parent: tk.Tk, group_name: str, entry: Mapping[str, object]) -> None:
        self._group_name = group_name
        self._entry = entry
        label = entry.get("label", "")
        super().__init__(parent, title=f"Edit grouping '{label}'")

    def body(self, master: tk.Tk) -> tk.Widget:  # type: ignore[override]
        ttk.Label(master, text=f"Group: {self._group_name}").grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(master, text="Label").grid(row=1, column=0, sticky="w")
        self.label_var = tk.StringVar(value=str(self._entry.get("label") or ""))
        ttk.Entry(master, textvariable=self.label_var, width=40).grid(row=1, column=1, sticky="ew")

        ttk.Label(master, text="ID prefixes (comma separated)").grid(row=2, column=0, sticky="w")
        prefixes = ", ".join(self._entry.get("prefixes", [])) if isinstance(self._entry.get("prefixes"), list) else ""
        self.prefix_var = tk.StringVar(value=prefixes)
        ttk.Entry(master, textvariable=self.prefix_var, width=40).grid(row=2, column=1, sticky="ew")

        ttk.Label(master, text="Anchor").grid(row=3, column=0, sticky="w")
        anchor_choices = ("",) + ANCHOR_CHOICES
        current_anchor = str(self._entry.get("anchor") or "")
        self.anchor_var = tk.StringVar(value=current_anchor)
        ttk.Combobox(master, values=anchor_choices, textvariable=self.anchor_var, state="readonly").grid(
            row=3, column=1, sticky="w"
        )

        ttk.Label(master, text="Notes").grid(row=4, column=0, sticky="w")
        self.notes_var = tk.StringVar(value=str(self._entry.get("notes") or ""))
        ttk.Entry(master, textvariable=self.notes_var, width=40).grid(row=4, column=1, sticky="ew")
        return master

    def validate(self) -> bool:  # type: ignore[override]
        label = self.label_var.get().strip()
        if not label:
            messagebox.showerror("Validation error", "Grouping label is required.")
            return False
        prefixes = _clean_prefixes(self.prefix_var.get())
        if not prefixes:
            messagebox.showerror("Validation error", "Enter at least one ID prefix.")
            return False
        return True

    def result_data(self) -> Dict[str, object]:
        return {
            "original_label": self._entry.get("label"),
            "label": self.label_var.get().strip(),
            "prefixes": _clean_prefixes(self.prefix_var.get()),
            "anchor": self.anchor_var.get().strip(),
            "notes": self.notes_var.get().strip(),
        }

    def apply(self) -> None:  # type: ignore[override]
        self.result = self.result_data()


class PluginGroupManagerApp:
    """Tkinter UI that ties the watcher/gather logic together."""

    def __init__(self) -> None:
        self._matcher = OverrideMatcher(GROUPINGS_PATH)
        self._locator = LogLocator(ROOT_DIR)
        cache_path = self._locator.log_dir / "new-payloads.json"
        self._payload_store = NewPayloadStore(cache_path)
        self._group_store = GroupConfigStore(GROUPINGS_PATH)
        self._queue: "queue.Queue[Tuple[str, object]]" = queue.Queue()
        self._watcher: Optional[PayloadWatcher] = None
        self._gather_thread: Optional[LogGatherer] = None

        self.root = tk.Tk()
        self.root.title("Plugin Group Manager")
        self.root.geometry("1100x800")
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self.watch_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="Idle.")
        self.payload_count_var = tk.StringVar()
        self._payload_index: List[str] = []
        self._group_scroll_bound = False

        self._build_ui()
        self._refresh_payload_list()
        self._refresh_group_view()
        self._update_payload_count()
        self.root.after(200, self._process_queue)

    # UI -----------------------------------------------------------------
    def _build_ui(self) -> None:
        main = ttk.Frame(self.root, padding=12)
        main.pack(fill="both", expand=True)

        top_section = ttk.LabelFrame(main, text="Watcher / Gather")
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
        ttk.Button(control_row, text="Re-check matches", command=self._purge_matched).pack(side="left", padx=(12, 0))
        ttk.Label(control_row, textvariable=self.payload_count_var).pack(side="right")

        ttk.Label(top_section, textvariable=self.status_var).pack(fill="x", padx=8)

        list_frame = ttk.Frame(top_section)
        list_frame.pack(fill="both", expand=True, padx=8, pady=8)
        self.payload_list = tk.Listbox(list_frame, height=8)
        self.payload_list.pack(side="left", fill="both", expand=True)
        self.payload_list.bind("<Double-1>", self._inspect_selected_payload)
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.payload_list.yview)
        scrollbar.pack(side="right", fill="y")
        self.payload_list.config(yscrollcommand=scrollbar.set)
        ttk.Label(top_section, text="Tip: double-click a payload to inspect its JSON details.", foreground="#5a5a5a").pack(
            fill="x",
            padx=8,
            pady=(0, 8),
        )

        bottom_section = ttk.LabelFrame(main, text="Grouping Management")
        bottom_section.pack(fill="both", expand=True)

        action_row = ttk.Frame(bottom_section)
        action_row.pack(fill="x", padx=8, pady=8)
        ttk.Button(action_row, text="New group", command=self._open_new_group_dialog).pack(side="left")

        group_scroll_frame = ttk.Frame(bottom_section)
        group_scroll_frame.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.group_canvas = tk.Canvas(group_scroll_frame, highlightthickness=0)
        self.group_canvas.pack(side="left", fill="both", expand=True)
        scrollbar_y = ttk.Scrollbar(group_scroll_frame, orient="vertical", command=self.group_canvas.yview)
        scrollbar_y.pack(side="right", fill="y")
        self.group_canvas.configure(yscrollcommand=scrollbar_y.set)
        self.group_frame = ttk.Frame(self.group_canvas)
        self.group_frame_window = self.group_canvas.create_window((0, 0), window=self.group_frame, anchor="nw")
        self.group_frame.bind("<Configure>", lambda _: self.group_canvas.configure(scrollregion=self.group_canvas.bbox("all")))
        self.group_canvas.bind("<Configure>", self._resize_group_canvas)
        group_scroll_frame.bind("<Enter>", self._enable_group_scroll)
        group_scroll_frame.bind("<Leave>", self._disable_group_scroll)


    def _refresh_payload_list(self) -> None:
        self.payload_list.delete(0, tk.END)
        self._payload_index = []
        for record in self._payload_store.records():
            self.payload_list.insert(tk.END, record.label())
            self._payload_index.append(record.payload_id)

    def _refresh_group_view(self) -> None:
        for child in self.group_frame.winfo_children():
            child.destroy()
        views = self._group_store.iter_group_views()
        unmatched_map = self._collect_unmatched_payloads(views)
        if not views:
            ttk.Label(self.group_frame, text="No groups configured yet.").pack(anchor="w")
            return
        for idx, view in enumerate(views):
            frame = ttk.LabelFrame(self.group_frame, text=view["name"])
            frame.pack(fill="x", expand=True, padx=4, pady=4)

            info_row = ttk.Frame(frame)
            info_row.pack(fill="x", padx=6, pady=(6, 2))
            ttk.Label(info_row, text=f"Mode:").grid(row=0, column=0, sticky="w")
            mode_var = tk.StringVar(value=view["mode"])
            mode_box = ttk.Combobox(info_row, values=("plugin", "id_prefix"), textvariable=mode_var, state="readonly", width=10)
            mode_box.grid(row=0, column=1, sticky="w", padx=(4, 12))
            mode_box.bind(
                "<<ComboboxSelected>>",
                lambda event, group=view["name"], var=mode_var: self._change_mode(group, var.get()),
            )
            prefix_text = ", ".join(view["match_prefixes"]) if view["match_prefixes"] else "- none -"
            ttk.Label(info_row, text="Matching prefixes:").grid(row=1, column=0, sticky="nw", pady=(4, 0))
            ttk.Label(info_row, text=prefix_text, wraplength=600, justify="left").grid(
                row=1,
                column=1,
                columnspan=2,
                sticky="w",
                pady=(4, 0),
            )
            ttk.Label(info_row, text="Notes:").grid(row=2, column=0, sticky="nw", pady=(4, 0))
            notes_value = view["notes"] or "- none -"
            ttk.Label(info_row, text=notes_value, wraplength=600, justify="left").grid(
                row=2,
                column=1,
                columnspan=2,
                sticky="w",
                pady=(4, 0),
            )
            unmatched_payloads = unmatched_map.get(view["name"], [])
            unmatched_text = ", ".join(unmatched_payloads) if unmatched_payloads else "- none -"
            ttk.Label(info_row, text="Unmatched payloads:").grid(row=3, column=0, sticky="nw", pady=(4, 0))
            ttk.Label(info_row, text=unmatched_text, wraplength=600, justify="left").grid(
                row=3,
                column=1,
                columnspan=2,
                sticky="w",
                pady=(4, 0),
            )

            button_row = ttk.Frame(frame)
            button_row.pack(fill="x", padx=6, pady=4)
            ttk.Button(
                button_row,
                text="Delete group",
                command=lambda group=view["name"]: self._delete_group(group),
            ).pack(side="right", padx=(8, 0))
            ttk.Button(
                button_row,
                text="Add grouping",
                command=lambda group=view["name"]: self._open_new_grouping_dialog(group),
            ).pack(side="right")

            grouping_entries = view["groupings"]
            if grouping_entries:
                for entry in grouping_entries:
                    entry_frame = ttk.Frame(frame)
                    entry_frame.pack(fill="x", padx=12, pady=2)
                    ttk.Label(entry_frame, text=f"Label: {entry['label']}").grid(row=0, column=0, sticky="w")
                    prefixes = ", ".join(entry["prefixes"]) if entry["prefixes"] else "- none -"
                    ttk.Label(entry_frame, text=f"Prefixes: {prefixes}").grid(row=1, column=0, sticky="w")
                    anchor = entry["anchor"] or "- default -"
                    ttk.Label(entry_frame, text=f"Anchor: {anchor}").grid(row=0, column=1, sticky="w", padx=(12, 0))
                    notes = entry["notes"] or "- none -"
                    ttk.Label(entry_frame, text=f"Notes: {notes}", wraplength=400, justify="left").grid(
                        row=1,
                        column=1,
                        sticky="w",
                        padx=(12, 0),
                    )
                    button_frame = ttk.Frame(entry_frame)
                    button_frame.grid(row=0, column=2, rowspan=2, padx=(12, 0), sticky="n")
                    ttk.Button(
                        button_frame,
                        text="Edit",
                        command=lambda group=view["name"], entry_data=entry: self._open_edit_grouping_dialog(group, entry_data),
                    ).pack(fill="x")
                    ttk.Button(
                        button_frame,
                        text="Delete",
                        command=lambda group=view["name"], label=entry["label"]: self._delete_grouping(group, label),
                    ).pack(fill="x", pady=(4, 0))
            else:
                ttk.Label(frame, text="No groupings defined.", padding=(8, 2)).pack(anchor="w")

    def _resize_group_canvas(self, event) -> None:
        if not hasattr(self, "group_frame_window"):
            return
        width = max(event.width - 4, 120)
        self.group_canvas.itemconfigure(self.group_frame_window, width=width)

    def _collect_unmatched_payloads(self, views: Sequence[Mapping[str, object]]) -> Dict[str, List[str]]:
        unmatched: Dict[str, List[str]] = {view["name"]: [] for view in views}
        if not views:
            return unmatched
        records = self._payload_store.records()
        if not records:
            return unmatched

        view_match_data: List[Tuple[str, List[str], List[str]]] = []
        for view in views:
            match_prefixes = [
                prefix.casefold()
                for prefix in view.get("match_prefixes", [])
                if isinstance(prefix, str) and prefix.strip()
            ]
            grouping_prefixes: List[str] = []
            for entry in view.get("groupings", []):
                prefixes = entry.get("prefixes") or []
                for prefix in prefixes:
                    if isinstance(prefix, str) and prefix.strip():
                        grouping_prefixes.append(prefix.casefold())
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
                if grouping_prefixes and any(payload_cf.startswith(prefix) for prefix in grouping_prefixes):
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
        try:
            data = json.loads(DEBUG_CONFIG_PATH.read_text(encoding="utf-8"))
        except FileNotFoundError:
            messagebox.showerror("Watcher unavailable", f"{DEBUG_CONFIG_PATH} not found.")
            return False
        except (OSError, json.JSONDecodeError) as exc:
            messagebox.showerror("Watcher unavailable", f"Failed to read {DEBUG_CONFIG_PATH}: {exc}")
            return False
        payload_logging = data.get("payload_logging")
        enabled = False
        if isinstance(payload_logging, Mapping):
            enabled = bool(payload_logging.get("overlay_payload_log_enabled"))
        if not enabled:
            messagebox.showerror(
                "Watcher unavailable",
                "Enable payload_logging.overlay_payload_log_enabled in debug.json to mirror payloads.",
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

    def _purge_matched(self) -> None:
        self._matcher.refresh()
        removed = self._payload_store.remove_matched(self._matcher)
        if removed:
            self._refresh_payload_list()
        self._update_payload_count()
        message = f"Removed {removed} payload(s) that now match configured groupings."
        self.status_var.set(message)

    def _enable_group_scroll(self, _event) -> None:
        if self._group_scroll_bound:
            return
        self.root.bind_all("<MouseWheel>", self._on_mouse_wheel)
        self.root.bind_all("<Button-4>", self._on_mouse_wheel)
        self.root.bind_all("<Button-5>", self._on_mouse_wheel)
        self._group_scroll_bound = True

    def _disable_group_scroll(self, _event) -> None:
        if not self._group_scroll_bound:
            return
        self.root.unbind_all("<MouseWheel>")
        self.root.unbind_all("<Button-4>")
        self.root.unbind_all("<Button-5>")
        self._group_scroll_bound = False

    def _on_mouse_wheel(self, event) -> None:
        if event.delta:
            self.group_canvas.yview_scroll(int(-event.delta / 120), "units")
        else:
            if event.num == 4:
                self.group_canvas.yview_scroll(-3, "units")
            elif event.num == 5:
                self.group_canvas.yview_scroll(3, "units")

    def _inspect_selected_payload(self, event) -> None:
        selection = self.payload_list.curselection()
        if not selection:
            return
        index = selection[0]
        if index >= len(self._payload_index):
            return
        payload_id = self._payload_index[index]
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

    def _open_new_group_dialog(self) -> None:
        dialog = NewGroupDialog(self.root, title="Create new group")
        if dialog.result is None:
            return
        data = dialog.result
        try:
            self._group_store.add_group(
                name=data["name"],
                notes=data["notes"],
                mode=data["mode"],
                initial_grouping=data["initial_grouping"],
            )
        except ValueError as exc:
            messagebox.showerror("Failed to add group", str(exc))
            return
        except OSError as exc:
            messagebox.showerror("Failed to add group", f"Could not write overlay_groupings.json: {exc}")
            return
        self._refresh_group_view()
        self.status_var.set(f"Added group '{data['name']}'.")
        self._purge_matched()

    def _open_new_grouping_dialog(self, group_name: str) -> None:
        dialog = NewGroupingDialog(self.root, group_name)
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
            )
        except ValueError as exc:
            messagebox.showerror("Failed to add grouping", str(exc))
            return
        except OSError as exc:
            messagebox.showerror("Failed to add grouping", f"Could not write overlay_groupings.json: {exc}")
            return
        self._refresh_group_view()
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
            )
        except ValueError as exc:
            messagebox.showerror("Failed to edit grouping", str(exc))
            return
        except OSError as exc:
            messagebox.showerror("Failed to edit grouping", f"Could not write overlay_groupings.json: {exc}")
            return
        self._refresh_group_view()
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
        self._refresh_group_view()
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
        self._refresh_group_view()
        self.status_var.set(f"Deleted group '{group_name}'.")
        self._purge_matched()

    def _change_mode(self, group_name: str, mode: str) -> None:
        try:
            self._group_store.update_mode(group_name, mode)
        except ValueError as exc:
            messagebox.showerror("Failed to update mode", str(exc))
            return
        self.status_var.set(f"Updated {group_name} mode to {mode}.")
        self._purge_matched()

    def _update_payload_count(self) -> None:
        count = len(self._payload_store)
        self.payload_count_var.set(f"New payloads: {count}")

    # Queue processing ----------------------------------------------------
    def _process_queue(self) -> None:
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
        self.root.after(200, self._process_queue)

    def _on_close(self) -> None:
        self._stop_watcher()
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    app = PluginGroupManagerApp()
    app.run()


if __name__ == "__main__":
    main()
