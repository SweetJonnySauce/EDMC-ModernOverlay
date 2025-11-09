#!/usr/bin/env python3
"""Interactive Plugin Group Manager for Modern Overlay."""

from __future__ import annotations

import argparse
import json
import logging
import os
import queue
import re
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
GROUP_SELECTOR_STYLE = "ModernOverlayGroupSelect.TCombobox"


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
        groups: Dict[str, Dict[str, object]] = {}
        if isinstance(grouping, Mapping):
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
                for item in prefixes:
                    if isinstance(item, str) and item:
                        groups[item] = {"id_prefixes": [item]}
        entry["grouping"] = {"groups": groups}
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
            grouping_block: Dict[str, object] = {"groups": {}}
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
            cleaned_match = [token.strip() for token in (match_prefixes or []) if isinstance(token, str) and token.strip()]
            if not cleaned_match and initial_grouping:
                cleaned_match = [token.strip() for token in initial_grouping.get("id_prefixes", []) if isinstance(token, str) and token.strip()]
            if cleaned_match:
                entry["__match__"] = {"id_prefixes": cleaned_match}
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
                cleaned_matches = [token.strip() for token in match_prefixes if isinstance(token, str) and token.strip()]
                if cleaned_matches:
                    entry["__match__"] = {"id_prefixes": cleaned_matches}
                else:
                    entry.pop("__match__", None)

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

class NewGroupDialog(simpledialog.Dialog):
    """Dialog for creating a brand new plugin group."""

    def body(self, master: tk.Tk) -> tk.Widget:  # type: ignore[override]
        ttk.Label(master, text="Group name").grid(row=0, column=0, sticky="w")
        self.name_var = tk.StringVar()
        ttk.Entry(master, textvariable=self.name_var, width=40).grid(row=0, column=1, sticky="ew")

        master.grid_columnconfigure(1, weight=1)
        ttk.Label(master, text="Match prefixes (comma separated)").grid(row=1, column=0, sticky="w")
        self.match_prefix_var = tk.StringVar()
        ttk.Entry(master, textvariable=self.match_prefix_var, width=40).grid(row=1, column=1, sticky="ew")

        ttk.Label(master, text="Notes (optional)").grid(row=2, column=0, sticky="nw")
        self.notes_text = tk.Text(master, width=40, height=4, font=tkfont.nametofont("TkDefaultFont"))
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
        match_section = self._entry.get("__match__")
        if isinstance(match_section, Mapping):
            values = match_section.get("id_prefixes")
            if isinstance(values, Iterable):
                for token in values:
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

    def __init__(self, log_dir_override: Optional[Path] = None) -> None:
        self._matcher = OverrideMatcher(GROUPINGS_PATH)
        self._locator = LogLocator(ROOT_DIR, override_dir=log_dir_override)
        cache_path = self._locator.log_dir / "new-payloads.json"
        self._payload_store = NewPayloadStore(cache_path)
        self._group_store = GroupConfigStore(GROUPINGS_PATH)
        self._queue: "queue.Queue[Tuple[str, object]]" = queue.Queue()
        self._watcher: Optional[PayloadWatcher] = None
        self._gather_thread: Optional[LogGatherer] = None

        self.root = tk.Tk()
        default_font = tkfont.nametofont("TkDefaultFont")
        self._group_title_font = default_font.copy()
        base_size = int(self._group_title_font.cget("size") or 10)
        increment = 2 if base_size >= 0 else -2
        self._group_title_font.configure(size=base_size + increment, weight="bold")
        self.root.title("Plugin Group Manager")
        self.root.geometry("1100x800")
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

        self._build_ui()
        self._refresh_group_data()
        self._update_payload_count()
        self.root.after(200, self._process_queue)

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
        main.rowconfigure(0, weight=1)

        left_panel = ttk.Frame(main)
        left_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        left_panel.rowconfigure(1, weight=1)
        right_panel = ttk.Frame(main)
        right_panel.grid(row=0, column=1, sticky="nsew")
        right_panel.rowconfigure(2, weight=1)

        top_section = ttk.LabelFrame(left_panel, text="Watcher / Gather")
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
            height=8,
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
        ttk.Label(
            left_panel,
            text="Tip: double-click a payload to inspect its JSON details.",
            foreground="#5a5a5a",
        ).pack(
            fill="x",
            padx=8,
            pady=(0, 8),
        )

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
        ttk.Button(selector_row, text="New group", command=self._open_new_group_dialog).grid(row=0, column=2, sticky="e", padx=(8, 0))
        selector_row.columnconfigure(1, weight=1)

        info_section = ttk.LabelFrame(right_panel, text="Plugin Group")
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
        ttk.Label(info_grid, textvariable=self.group_match_var, wraplength=500, justify="left").grid(
            row=1, column=1, columnspan=3, sticky="w", pady=(4, 0)
        )
        ttk.Label(info_grid, text="Notes:").grid(row=2, column=0, sticky="nw", pady=(4, 0))
        ttk.Label(info_grid, textvariable=self.group_notes_var, wraplength=500, justify="left").grid(
            row=2,
            column=1,
            columnspan=3,
            sticky="w",
            pady=(4, 0),
        )

        grouping_section = ttk.LabelFrame(right_panel, text="ID Prefix Groups")
        grouping_section.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        grouping_action_row = ttk.Frame(grouping_section)
        grouping_action_row.pack(fill="x", padx=8, pady=(8, 0))
        ttk.Button(
            grouping_action_row,
            text="Add grouping",
            command=lambda: self._open_new_grouping_dialog(self.selected_group_var.get()),
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

    def _show_payload_context_menu(self, event) -> None:
        if not hasattr(self, "payload_list"):
            return
        row_id = self.payload_list.identify_row(event.y)
        if not row_id:
            return
        self.payload_list.selection_set(row_id)
        self.payload_list.focus(row_id)
        meta = self._payload_meta.get(row_id)
        if not meta:
            return
        status, target_group = meta
        menu = tk.Menu(self.root, tearoff=False)
        if status == "Unmatched":
            menu.add_command(label="Create new group", command=self._open_new_group_dialog)
        elif status == "Ungrouped" and target_group:
            label = f"Create new ID Prefix Group in {target_group}"
            menu.add_command(
                label=label,
                command=lambda group=target_group: self._open_new_grouping_dialog_from_payload(group),
            )
        if menu.index("end") is None:
            return
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _open_new_grouping_dialog_from_payload(self, group_name: str) -> None:
        if group_name not in self._group_views:
            return
        if self.selected_group_var.get() != group_name:
            self.selected_group_var.set(group_name)
            self._on_group_selected()
        self._open_new_grouping_dialog(group_name)

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
        unmatched = self._unmatched_by_group.get(group_name, [])
        if unmatched:
            entries = [{"label": "ungrouped", "prefixes": unmatched, "anchor": None, "notes": ""}] + entries
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
            entry_frame.grid_columnconfigure(1, weight=1)
            label = entry.get("label", "")
            ttk.Label(entry_frame, text=f"Label: {label}").grid(row=0, column=0, sticky="w", pady=(0, 4))
            prefixes = ", ".join(entry.get("prefixes", [])) if entry.get("prefixes") else "- none -"
            ttk.Label(entry_frame, text=f"Prefixes: {prefixes}", wraplength=350, justify="left").grid(
                row=1,
                column=0,
                sticky="w",
                pady=(0, 4),
            )
            anchor_value = entry.get("anchor") or "- default -"
            ttk.Label(entry_frame, text=f"Anchor: {anchor_value}").grid(row=0, column=1, sticky="w", padx=(12, 0), pady=(0, 4))
            notes_text = entry.get("notes") or "- none -"
            ttk.Label(entry_frame, text=f"Notes: {notes_text}", wraplength=350, justify="left").grid(
                row=1,
                column=1,
                sticky="w",
                padx=(12, 0),
                pady=(0, 4),
            )
            if label == "ungrouped":
                if index < len(entries) - 1:
                    ttk.Separator(self.grouping_entries_frame, orient="horizontal").pack(fill="x", padx=4, pady=(0, 4))
                continue
            button_frame = ttk.Frame(entry_frame)
            button_frame.grid(row=0, column=2, rowspan=2, padx=(18, 0), pady=(0, 4), sticky="n")
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
            if index < len(entries) - 1:
                ttk.Separator(self.grouping_entries_frame, orient="horizontal").pack(fill="x", padx=4, pady=(0, 4))

    def _reset_grouping_scroll(self) -> None:
        if self.grouping_canvas is None:
            return
        self.grouping_canvas.yview_moveto(0.0)

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
        pointer_widget = self.root.winfo_containing(self.root.winfo_pointerx(), self.root.winfo_pointery())
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

    def _open_new_group_dialog(self) -> None:
        dialog = NewGroupDialog(self.root, title="Create new group")
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

    def _open_new_grouping_dialog(self, group_name: str) -> None:
        if not group_name:
            messagebox.showerror("Add grouping", "Select a plugin group first.")
            return
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
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    log_dir_override = Path(args.log_dir).expanduser() if args.log_dir else None
    app = PluginGroupManagerApp(log_dir_override=log_dir_override)
    app.run()


if __name__ == "__main__":
    main()
