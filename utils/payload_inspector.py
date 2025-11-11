#!/usr/bin/env python3
"""Modern Overlay payload tail/inspect utility."""

from __future__ import annotations

import argparse
import json
import logging
import os
import queue
import sys
import threading
import tkinter as tk
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from tkinter import ttk
from typing import Any, Dict, Mapping, Optional, Tuple


ROOT_DIR = Path(__file__).resolve().parents[1]
OVERLAY_CLIENT_DIR = ROOT_DIR / "overlay-client"
if str(OVERLAY_CLIENT_DIR) not in sys.path:
    sys.path.insert(0, str(OVERLAY_CLIENT_DIR))

try:
    from plugin_overrides import PluginOverrideManager
except Exception as exc:  # pragma: no cover - required at runtime
    raise SystemExit(f"Failed to import plugin_overrides: {exc}")


LOG = logging.getLogger("payload-inspector")
LOG.addHandler(logging.NullHandler())

GROUPINGS_PATH = ROOT_DIR / "overlay_groupings.json"
PAYLOAD_LOG_DIR_NAME = "EDMC-ModernOverlay"
PAYLOAD_LOG_BASENAMES = ("overlay-payloads.log", "overlay_payloads.log")
MAX_ROWS = 500


@dataclass
class ParsedPayload:
    """Structured data extracted from a single payload log line."""

    timestamp: str
    plugin: Optional[str]
    payload_id: str
    payload: Mapping[str, Any]


class GroupResolver:
    """Thread-safe helper that exposes PluginOverrideManager grouping metadata."""

    def __init__(self, config_path: Path) -> None:
        self._logger = logging.getLogger("payload-inspector.override")
        self._logger.addHandler(logging.NullHandler())
        self._manager = PluginOverrideManager(config_path, self._logger)
        self._lock = threading.Lock()

    def resolve(self, plugin: Optional[str], payload_id: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
        with self._lock:
            key = self._manager.grouping_key_for(plugin, payload_id)
        if not key:
            return None, None
        return key


class LogLocator:
    """Replicate plugin log discovery so rotations & overrides behave identically to runtime."""

    def __init__(self, plugin_root: Path, override_dir: Optional[Path] = None) -> None:
        self._plugin_root = plugin_root
        self._override_dir = override_dir
        self._log_dir = self._resolve()

    @property
    def log_dir(self) -> Path:
        return self._log_dir

    def _resolve(self) -> Path:
        if self._override_dir is not None:
            target = self._override_dir.expanduser()
            if target.suffix:
                target = target.parent
            target.mkdir(parents=True, exist_ok=True)
            return target

        candidates = []
        parents = self._plugin_root.parents
        if len(parents) >= 2:
            candidates.append(parents[1] / "logs")
        if len(parents) >= 1:
            candidates.append(parents[0] / "logs")
        candidates.append(Path.cwd() / "logs")
        for base in candidates:
            path = base / PAYLOAD_LOG_DIR_NAME
            try:
                path.mkdir(parents=True, exist_ok=True)
                return path
            except OSError:
                continue
        fallback = self._plugin_root / "logs" / PAYLOAD_LOG_DIR_NAME
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback

    def primary_log_file(self) -> Optional[Path]:
        for name in PAYLOAD_LOG_BASENAMES:
            candidate = self._log_dir / name
            if candidate.exists():
                return candidate
        rotated = self.all_log_files()
        return rotated[0] if rotated else None

    def all_log_files(self) -> Tuple[Path, ...]:
        files: Dict[str, Path] = {}
        for base in PAYLOAD_LOG_BASENAMES:
            for candidate in self._log_dir.glob(f"{base}*"):
                if candidate.is_file():
                    files[str(candidate)] = candidate
        return tuple(sorted(files.values()))


class PayloadParser:
    """Extract payload metadata (timestamp, plugin, JSON body) from raw log lines."""

    def __init__(self) -> None:
        import re

        self._pattern = re.compile(
            r"Overlay payload(?: \[[^\]]+\])?(?: plugin=(?P<plugin>[^:]+))?: (?P<body>\{.*\})"
        )

    def parse(self, line: str) -> Optional[ParsedPayload]:
        if "Overlay payload" not in line or "Overlay legacy_raw" in line:
            return None
        match = self._pattern.search(line)
        if not match:
            return None
        body = match.group("body")
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            LOG.debug("Skipping unparsable payload JSON: %s", body)
            return None
        payload_id = self._extract_payload_id(payload)
        if not payload_id:
            return None
        timestamp = self._extract_timestamp(line)
        plugin = (match.group("plugin") or "").strip() or None
        return ParsedPayload(timestamp=timestamp, plugin=plugin, payload_id=payload_id, payload=payload)

    @staticmethod
    def _extract_timestamp(line: str) -> str:
        prefix = line.split("[", 1)[0].strip()
        return prefix or "unknown"

    @staticmethod
    def _extract_payload_id(payload: Mapping[str, Any]) -> Optional[str]:
        for key in ("id",):
            value = payload.get(key)
            if isinstance(value, str) and value:
                return value
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


class PayloadTailer(threading.Thread):
    """Tail overlay-payloads.log, handling pause/resume and log rotations."""

    def __init__(
        self,
        locator: LogLocator,
        resolver: GroupResolver,
        outbox: "queue.Queue[Tuple[str, object]]",
        *,
        history_limit: int = 0,
    ) -> None:
        super().__init__(daemon=True)
        self._locator = locator
        self._resolver = resolver
        self._queue = outbox
        self._parser = PayloadParser()
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._history_limit = max(0, history_limit)

    def stop(self) -> None:
        self._stop_event.set()

    def set_paused(self, paused: bool) -> None:
        if paused:
            self._pause_event.set()
        else:
            self._pause_event.clear()

    def run(self) -> None:
        while not self._stop_event.is_set():
            log_path = self._locator.primary_log_file()
            if log_path is None:
                self._queue.put(("log_path", None))
                self._queue.put(("status", "Waiting for overlay-payloads.log..."))
                if self._stop_event.wait(2.0):
                    break
                continue
            try:
                with log_path.open("r", encoding="utf-8") as stream:
                    self._queue.put(("status", f"Tailing {log_path.name}"))
                    self._queue.put(("log_path", str(log_path)))
                    history_count = self._emit_history(stream)
                    if history_count:
                        self._queue.put(("history_complete", history_count))
                    stream.seek(0, os.SEEK_END)
                    current_inode = self._inode(log_path)
                    while not self._stop_event.is_set():
                        if self._pause_event.is_set():
                            if self._stop_event.wait(0.2):
                                break
                            continue
                        line = stream.readline()
                        if line:
                            self._emit_record(line, history=False)
                            continue
                        if self._stop_event.wait(0.5):
                            break
                        try:
                            stat = log_path.stat()
                        except FileNotFoundError:
                            self._queue.put(("status", "Log rotated, reopening..."))
                            break
                        if stat.st_ino != current_inode or stat.st_size < stream.tell():
                            self._queue.put(("status", "Log rotated, reopening..."))
                            break
            except OSError as exc:
                self._queue.put(("error", f"Failed to open {log_path}: {exc}"))
                self._queue.put(("log_path", None))
                if self._stop_event.wait(2.0):
                    break

    @staticmethod
    def _inode(path: Path) -> int:
        try:
            return path.stat().st_ino
        except OSError:
            return -1

    def _emit_history(self, stream) -> int:
        if not self._history_limit:
            return 0
        stream.seek(0)
        buffer = deque(maxlen=self._history_limit)
        for line in stream:
            buffer.append(line)
            if self._stop_event.is_set():
                return 0
        count = 0
        for line in buffer:
            if self._stop_event.is_set():
                break
            if self._emit_record(line, history=True):
                count += 1
        return count

    def _emit_record(self, line: str, history: bool) -> bool:
        record = self._parser.parse(line)
        if not record:
            return False
        plugin_group, prefix_group = self._resolver.resolve(record.plugin, record.payload_id)
        payload_json = json.dumps(record.payload, indent=2, ensure_ascii=False)
        entry: Dict[str, object] = {
            "timestamp": record.timestamp,
            "plugin": record.plugin or "",
            "plugin_group": plugin_group,
            "group_label": prefix_group,
            "payload_id": record.payload_id,
            "payload_json": payload_json,
        }
        self._queue.put(("payload_history" if history else "payload", entry))
        return True


class PayloadInspectorApp:
    """Tk application presenting payload summaries on the left and JSON details on the right."""

    def __init__(self, log_dir_override: Optional[Path] = None) -> None:
        self.root = tk.Tk()
        self.root.title("Modern Overlay Payload Inspector")
        self.root.geometry("1100x600")

        self._queue: "queue.Queue[Tuple[str, object]]" = queue.Queue()
        self._row_counter = 0
        self._row_order: list[str] = []
        self._payload_store: Dict[str, Dict[str, object]] = {}
        self._paused = False

        self._locator = LogLocator(ROOT_DIR, override_dir=log_dir_override)
        self._resolver = GroupResolver(GROUPINGS_PATH)
        self._tailer = PayloadTailer(self._locator, self._resolver, self._queue, history_limit=MAX_ROWS)
        self._tailer.start()

        self._build_widgets()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(200, self._drain_queue)

    def _build_widgets(self) -> None:
        toolbar = ttk.Frame(self.root)
        toolbar.pack(side="top", fill="x")

        self.pause_button = ttk.Button(toolbar, text="Pause", command=self._toggle_pause)
        self.pause_button.pack(side="left", padx=5, pady=5)

        self.log_path_var = tk.StringVar()
        self._update_log_label(None)
        ttk.Label(toolbar, textvariable=self.log_path_var).pack(side="left", padx=5)

        self.status_var = tk.StringVar(value="Starting tailer...")
        ttk.Label(toolbar, textvariable=self.status_var).pack(side="left", padx=5)

        main_frame = ttk.Frame(self.root)
        main_frame.pack(fill="both", expand=True)

        left_frame = ttk.Frame(main_frame)
        left_frame.pack(side="left", fill="both", expand=True)

        columns = ("timestamp", "plugin", "plugin_group", "group_label", "payload")
        self.tree = ttk.Treeview(
            left_frame,
            columns=columns,
            show="headings",
            height=20,
        )
        headings = {
            "timestamp": "Timestamp",
            "plugin": "Plugin",
            "plugin_group": "Plugin Group",
            "group_label": "ID Prefix Group",
            "payload": "Payload ID",
        }
        for column in columns:
            self.tree.heading(column, text=headings[column])
            width = 160 if column == "timestamp" else 140
            if column == "payload":
                width = 220
            self.tree.column(column, width=width, anchor="w")
        self.tree.pack(side="left", fill="both", expand=True)

        scroll_y = ttk.Scrollbar(left_frame, orient="vertical", command=self.tree.yview)
        scroll_y.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=scroll_y.set)
        self.tree.bind("<<TreeviewSelect>>", self._on_selection_changed)

        right_frame = ttk.Frame(main_frame)
        right_frame.pack(side="left", fill="both", expand=True, padx=(8, 0))

        ttk.Label(right_frame, text="Payload details").pack(anchor="w")

        text_container = ttk.Frame(right_frame)
        text_container.pack(fill="both", expand=True)

        self.detail_text = tk.Text(text_container, wrap="none", font=("Courier", 10))
        self.detail_text.pack(side="left", fill="both", expand=True)
        self.detail_text.configure(state="disabled")

        detail_scroll_y = ttk.Scrollbar(text_container, orient="vertical", command=self.detail_text.yview)
        detail_scroll_y.pack(side="right", fill="y")
        self.detail_text.configure(yscrollcommand=detail_scroll_y.set)

    def _toggle_pause(self) -> None:
        self._paused = not self._paused
        self._tailer.set_paused(self._paused)
        self.pause_button.config(text="Resume" if self._paused else "Pause")
        self.status_var.set("Paused" if self._paused else "Resumed - catching up...")

    def _drain_queue(self) -> None:
        try:
            while True:
                message_type, payload = self._queue.get_nowait()
                if message_type == "payload":
                    self._add_row(payload)
                elif message_type == "payload_history":
                    self._add_row(payload, autoscroll=False)
                elif message_type == "status":
                    self.status_var.set(str(payload))
                elif message_type == "error":
                    self.status_var.set(f"Error: {payload}")
                elif message_type == "log_path":
                    self._update_log_label(payload if isinstance(payload, str) else None)
                elif message_type == "history_complete":
                    self._scroll_to_end()
        except queue.Empty:
            pass
        finally:
            self.root.after(200, self._drain_queue)

    def _add_row(self, payload: Mapping[str, object], autoscroll: bool = True) -> None:
        row_id = f"row-{self._row_counter}"
        self._row_counter += 1
        values = (
            payload.get("timestamp", ""),
            payload.get("plugin", ""),
            payload.get("plugin_group") or "",
            payload.get("group_label") or "",
            payload.get("payload_id", ""),
        )
        self.tree.insert("", "end", iid=row_id, values=values)
        self._payload_store[row_id] = dict(payload)
        self._row_order.append(row_id)
        if autoscroll and not self._paused:
            self.tree.see(row_id)
        if len(self._row_order) > MAX_ROWS:
            expired = self._row_order.pop(0)
            self.tree.delete(expired)
            self._payload_store.pop(expired, None)

    def _on_selection_changed(self, _event=None) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        row_id = selection[0]
        payload = self._payload_store.get(row_id)
        if not payload:
            return
        details = payload.get("payload_json", "")
        if not isinstance(details, str):
            details = json.dumps(payload, indent=2, ensure_ascii=False)
        self.detail_text.configure(state="normal")
        self.detail_text.delete("1.0", tk.END)
        self.detail_text.insert("1.0", details)
        self.detail_text.configure(state="disabled")

    def _on_close(self) -> None:
        self._tailer.stop()
        self.root.after(200, self.root.destroy)

    def run(self) -> None:
        self.root.mainloop()

    def _update_log_label(self, path: Optional[str]) -> None:
        if path:
            display = path
        else:
            display = f"searching under {self._locator.log_dir}"
        self.log_path_var.set(f"Log file: {display}")

    def _scroll_to_end(self) -> None:
        if hasattr(self, "tree"):
            children = self.tree.get_children()
            if children:
                self.tree.see(children[-1])


def main() -> None:
    parser = argparse.ArgumentParser(description="Tail overlay payloads with grouping metadata.")
    parser.add_argument(
        "--log-dir",
        help="Directory that contains overlay payload logs (or a direct overlay-payloads.log path).",
    )
    args = parser.parse_args()
    log_dir_override = Path(args.log_dir).expanduser() if args.log_dir else None

    logging.basicConfig(level=logging.INFO)
    app = PayloadInspectorApp(log_dir_override=log_dir_override)
    app.run()


if __name__ == "__main__":
    main()
