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
from tkinter import filedialog, ttk
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple


ROOT_DIR = Path(__file__).resolve().parents[1]
OVERLAY_CLIENT_DIR = ROOT_DIR / "overlay_client"
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

try:
    from overlay_client.plugin_overrides import PluginOverrideManager
except Exception as exc:  # pragma: no cover - required at runtime
    raise SystemExit(f"Failed to import overlay_client.plugin_overrides: {exc}")


LOG = logging.getLogger("payload-inspector")
LOG.addHandler(logging.NullHandler())

GROUPINGS_PATH = ROOT_DIR / "overlay_groupings.json"
PAYLOAD_LOG_DIR_NAME = "EDMCModernOverlay"
PAYLOAD_LOG_BASENAMES = ("overlay-payloads.log", "overlay_payloads.log")
MAX_ROWS = 500
CONFIG_DIR = Path.home() / ".config" / "edmc_modern_overlay"
CONFIG_FILE = CONFIG_DIR / "payload_inspector.json"


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
        self._plugin_root = plugin_root.resolve()
        self._override_dir: Optional[Path] = None
        self._override_file: Optional[Path] = None
        if override_dir is not None:
            target = override_dir.expanduser()
            if target.suffix:
                self._override_file = target
                self._override_dir = target.parent
            else:
                self._override_dir = target
        self._log_dir = self._resolve()

    @property
    def log_dir(self) -> Path:
        return self._log_dir

    def _resolve(self) -> Path:
        if self._override_dir is not None:
            target = self._override_dir
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
        if self._override_file:
            return self._override_file
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
        self._context_menu: Optional[tk.Menu] = None
        self._suppressed_plugins: set[str] = set()
        self._suppressed_plugin_groups: set[str] = set()
        self._suppressed_group_labels: set[str] = set()
        self._suppressed_payload_ids: set[str] = set()
        self._group_preview_payloads: Optional[str] = None

        self._user_config = self._load_user_config()
        custom_path = self._user_config.get("log_file")
        self._custom_log_file: Optional[Path] = Path(custom_path).expanduser() if custom_path else None
        self._cli_override = log_dir_override.expanduser() if log_dir_override else None
        self._resolver = GroupResolver(GROUPINGS_PATH)
        self._tailer: Optional[PayloadTailer] = None

        self._build_widgets()
        self._start_tailer()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(200, self._drain_queue)

    def _build_widgets(self) -> None:
        toolbar = ttk.Frame(self.root)
        toolbar.pack(side="top", fill="x")

        self.pause_button = ttk.Button(toolbar, text="Pause", command=self._toggle_pause)
        self.pause_button.pack(side="left", padx=5, pady=5)

        ttk.Button(toolbar, text="Clear suppression", command=self._clear_suppression).pack(side="left", padx=5, pady=5)

        self.status_var = tk.StringVar(value="Starting tailer...")
        ttk.Label(toolbar, textvariable=self.status_var).pack(side="left", padx=5)

        log_row = ttk.Frame(self.root)
        log_row.pack(side="top", fill="x", pady=(0, 4))
        ttk.Label(log_row, text="Log file:", font=("TkDefaultFont", 10, "bold")).pack(side="left", padx=(5, 0))
        self.log_path_var = tk.StringVar(value="resolving...")
        log_entry = ttk.Entry(log_row, textvariable=self.log_path_var, width=70)
        log_entry.configure(state="readonly")
        log_entry.pack(side="left", fill="x", expand=True, padx=5)
        ttk.Button(log_row, text="Choose...", command=self._choose_log_file).pack(side="right", padx=5)

        main_frame = ttk.Frame(self.root)
        main_frame.pack(fill="both", expand=True)

        left_frame = ttk.Frame(main_frame)
        left_frame.pack(side="left", fill="y", padx=(0, 6))
        ttk.Label(left_frame, text="Payload list", font=("TkDefaultFont", 10, "bold")).pack(anchor="w", padx=(5, 0), pady=(0, 4))

        columns = ("timestamp", "plugin", "plugin_group", "group_label", "payload")
        tree_container = ttk.Frame(left_frame)
        tree_container.pack(fill="both", expand=True, padx=(5, 0))
        self.tree = ttk.Treeview(tree_container, columns=columns, show="headings")
        headings = {
            "timestamp": "Timestamp",
            "plugin": "Plugin",
            "plugin_group": "Plugin Group",
            "group_label": "ID Prefix Group",
            "payload": "Payload ID",
        }
        for column in columns:
            self.tree.heading(column, text=headings[column])
            width = 140 if column == "timestamp" else 110
            if column == "plugin":
                width = 100
            if column == "plugin_group":
                width = 110
            if column == "group_label":
                width = 150
            if column == "payload":
                width = 180
            self.tree.column(column, width=width, anchor="w")
        self.tree.pack(side="left", fill="both", expand=True)

        scroll_y = ttk.Scrollbar(tree_container, orient="vertical", command=self.tree.yview)
        scroll_y.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=scroll_y.set)
        self.tree.bind("<<TreeviewSelect>>", self._on_selection_changed)
        # Right-click suppression menu (Button-2 for mac support)
        self.tree.bind("<Button-3>", self._show_context_menu)
        self.tree.bind("<Button-2>", self._show_context_menu)
        self.root.bind("<Button-1>", self._dismiss_context_menu, add="+")
        self.root.bind("<Button-2>", self._dismiss_context_menu, add="+")
        self.root.bind("<Button-3>", self._dismiss_context_menu, add="+")
        self.root.bind("<Escape>", self._dismiss_context_menu, add="+")

        tips_frame = ttk.Frame(left_frame)
        tips_frame.pack(fill="x", padx=(5, 0), pady=(6, 0))
        tips_row = ttk.Frame(tips_frame)
        tips_row.pack(fill="x")
        ttk.Label(tips_row, text="Tip:", font=("TkDefaultFont", 10, "bold")).pack(side="left")
        self.tip_var = tk.StringVar()
        ttk.Label(tips_row, textvariable=self.tip_var, justify="left").pack(side="left", fill="x", expand=True)
        self._tips = [
            "Enable \"Log incoming payloads\" in the Modern Overlay preferences to mirror payloads",
            "Right click on a payload to suppress it",
            "Use tests/send_overlay_from_log.py with the --log-file parameter to replay a captured payload for testing.",
            "Right click on a payload to draw the ID Prefix Group in the preview.",
        ]
        self._tip_index = -1
        self._rotate_tip()

        right_frame = ttk.Frame(main_frame)
        right_frame.pack(side="left", fill="both", expand=True, padx=(8, 0))

        preview_frame = ttk.Frame(right_frame)
        preview_frame.pack(fill="x", padx=(5, 0), pady=(0, 8))
        ttk.Label(preview_frame, text="Payload preview", font=("TkDefaultFont", 10, "bold")).pack(anchor="w")
        self.preview_canvas = tk.Canvas(preview_frame, width=400, height=250, background="#202020", highlightthickness=1)
        self.preview_canvas.pack(fill="x", expand=False, padx=(0, 5))

        details_header = ttk.Frame(right_frame)
        details_header.pack(fill="x", padx=(5, 5), pady=(4, 0))
        ttk.Label(details_header, text="Payload details", font=("TkDefaultFont", 10, "bold")).pack(side="left", anchor="w")
        ttk.Button(details_header, text="Copy", command=self._copy_payload_details).pack(side="right")

        text_container = ttk.Frame(right_frame)
        text_container.pack(fill="both", expand=True, padx=(5, 5))

        self.detail_text = tk.Text(text_container, wrap="none", font=("Courier", 10), width=40)
        self.detail_text.pack(side="left", fill="both", expand=True)
        self.detail_text.configure(state="disabled")

        detail_scroll_y = ttk.Scrollbar(text_container, orient="vertical", command=self.detail_text.yview)
        detail_scroll_y.pack(side="right", fill="y")
        self.detail_text.configure(yscrollcommand=detail_scroll_y.set)
        ttk.Frame(right_frame).pack(fill="x", padx=(5, 5), pady=(4, 0))


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
        if self._is_suppressed(payload):
            return
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
        self._group_preview_payloads = None
        self._draw_preview(payload)
        self._current_detail_text = details

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
        self.log_path_var.set(display)

    def _scroll_to_end(self) -> None:
        if hasattr(self, "tree"):
            children = self.tree.get_children()
            if children:
                self.tree.see(children[-1])
        self._draw_preview(None)

    def _show_context_menu(self, event) -> None:
        row_id = self.tree.identify_row(event.y)
        if not row_id:
            return
        self.tree.selection_set(row_id)
        payload = self._payload_store.get(row_id)
        if not payload:
            return
        if self._context_menu is not None:
            try:
                self._context_menu.destroy()
            except Exception:
                pass
        menu = tk.Menu(self.root, tearoff=0)
        plugin = (payload.get("plugin") or "").strip()
        plugin_group = (payload.get("plugin_group") or "").strip()
        group_label = (payload.get("group_label") or "").strip()
        payload_id = (payload.get("payload_id") or "").strip()

        def _add(label: str, handler: Callable[[], None]) -> None:
            menu.add_command(label=label, command=handler)

        added = False
        if plugin:
            _add(f"Suppress plugin '{plugin}'", lambda p=plugin: self._suppress("plugin", p))
            added = True
        if plugin_group:
            _add(f"Suppress plugin group '{plugin_group}'", lambda g=plugin_group: self._suppress("plugin_group", g))
            added = True
        if group_label:
            _add(
                f"Suppress ID prefix group '{group_label}'",
                lambda lbl=group_label: self._suppress("group_label", lbl),
            )
            added = True
        if payload_id:
            _add(f"Suppress payload id '{payload_id}'", lambda pid=payload_id: self._suppress("payload_id", pid))
            added = True
        if added:
            menu.add_separator()
        if group_label:
            menu.add_command(
                label=f"Draw ID prefix group '{group_label}'",
                command=lambda lbl=group_label: self._draw_group_preview(lbl),
            )
            menu.add_separator()
        menu.add_command(label="Clear suppression", command=self._clear_suppression)
        self._context_menu = menu
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _dismiss_context_menu(self, event=None) -> None:
        menu = self._context_menu
        if menu is None:
            return
        if event is not None:
            widget = getattr(event, "widget", None)
            if widget is menu:
                return
            if widget is self.tree and getattr(event, "num", None) in (2, 3):
                return
        try:
            menu.unpost()
        except Exception:
            pass
        try:
            menu.destroy()
        except Exception:
            pass
        self._context_menu = None

    def _suppress(self, kind: str, value: str) -> None:
        token = value.strip()
        if not token:
            return
        lowered = token.casefold()
        if kind == "plugin":
            if lowered in self._suppressed_plugins:
                return
            self._suppressed_plugins.add(lowered)

            def predicate(item: Mapping[str, Any]) -> bool:
                return (item.get("plugin") or "").strip().casefold() == lowered

            self.status_var.set(f"Suppressed plugin '{token}'.")
        elif kind == "plugin_group":
            if lowered in self._suppressed_plugin_groups:
                return
            self._suppressed_plugin_groups.add(lowered)

            def predicate(item: Mapping[str, Any]) -> bool:
                return (item.get("plugin_group") or "").strip().casefold() == lowered

            self.status_var.set(f"Suppressed plugin group '{token}'.")
        elif kind == "group_label":
            if lowered in self._suppressed_group_labels:
                return
            self._suppressed_group_labels.add(lowered)

            def predicate(item: Mapping[str, Any]) -> bool:
                return (item.get("group_label") or "").strip().casefold() == lowered

            self.status_var.set(f"Suppressed ID prefix group '{token}'.")
        elif kind == "payload_id":
            if token in self._suppressed_payload_ids:
                return
            self._suppressed_payload_ids.add(token)

            def predicate(item: Mapping[str, Any]) -> bool:
                return (item.get("payload_id") or "").strip() == token

            self.status_var.set(f"Suppressed payload id '{token}'.")
        else:
            return
        self._remove_rows(predicate)

    def _remove_rows(self, predicate: Callable[[Mapping[str, Any]], bool]) -> None:
        for row_id in list(self._row_order):
            payload = self._payload_store.get(row_id)
            if payload is None:
                continue
            try:
                if predicate(payload):
                    self.tree.delete(row_id)
                    self._payload_store.pop(row_id, None)
                    self._row_order.remove(row_id)
            except Exception:
                continue

    def _clear_suppression(self) -> None:
        if (
            not self._suppressed_plugins
            and not self._suppressed_plugin_groups
            and not self._suppressed_group_labels
            and not self._suppressed_payload_ids
        ):
            self.status_var.set("No suppression rules to clear.")
            return
        self._suppressed_plugins.clear()
        self._suppressed_plugin_groups.clear()
        self._suppressed_group_labels.clear()
        self._suppressed_payload_ids.clear()
        self.status_var.set("Suppression rules cleared.")

    def _is_suppressed(self, payload: Mapping[str, object]) -> bool:
        plugin = (payload.get("plugin") or "").strip()
        if plugin and plugin.casefold() in self._suppressed_plugins:
            return True
        plugin_group = (payload.get("plugin_group") or "").strip()
        if plugin_group and plugin_group.casefold() in self._suppressed_plugin_groups:
            return True
        group_label = (payload.get("group_label") or "").strip()
        if group_label and group_label.casefold() in self._suppressed_group_labels:
            return True
        payload_id = (payload.get("payload_id") or "").strip()
        if payload_id and payload_id in self._suppressed_payload_ids:
            return True
        return False

    @staticmethod
    def _is_valid_color(value: Any) -> bool:
        if not isinstance(value, str):
            return False
        token = value.strip()
        if not token:
            return False
        if token.startswith("#"):
            hex_part = token[1:]
            return len(hex_part) in {3, 4, 6, 8} and all(c in "0123456789abcdefABCDEF" for c in hex_part)
        lowered = token.lower()
        if lowered in {"none", "null"}:
            return False
        return True

    def _draw_preview(
        self,
        payload: Optional[Mapping[str, object]],
        *,
        group_payloads: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        canvas = getattr(self, "preview_canvas", None)
        if canvas is None:
            return
        canvas.delete("all")
        width = int(canvas.winfo_width() or canvas["width"])
        height = int(canvas.winfo_height() or canvas["height"])
        padding = 20
        inner_w = max(1, width - 2 * padding)
        inner_h = max(1, height - 2 * padding)
        canvas.create_rectangle(
            padding,
            padding,
            width - padding,
            height - padding,
            outline="#404040",
            dash=(3, 3),
        )
        payload_dicts: List[Dict[str, Any]] = []
        if group_payloads:
            payload_dicts.extend(group_payloads)
        elif payload is not None:
            payload_dicts.append(self._parse_payload_entry(payload))
        if not payload_dicts:
            canvas.create_text(width // 2, height // 2, text="(select a payload)", fill="#888888")
            return
        scale = self._compute_scale(inner_w, inner_h)
        ref_w, ref_h = 1280, 960
        offset_x = padding
        offset_y = padding

        last_text: Optional[str] = None
        for data in payload_dicts:
            text = self._render_payload(canvas, data, offset_x, offset_y, scale)
            if text:
                last_text = text

        if last_text and group_payloads is None:
            canvas.create_text(
                offset_x + (ref_w * scale) / 2.0,
                offset_y + ref_h * scale - 10,
                text=str(last_text),
                fill="#ffffff",
                anchor="s",
            )

    @staticmethod
    def _compute_scale(target_w: int, target_h: int) -> float:
        ref_w, ref_h = 1280.0, 960.0
        if target_w <= 0 or target_h <= 0:
            return 1.0
        return max(0.01, min(target_w / ref_w, target_h / ref_h))

    @staticmethod
    def _normalise_color(value: Any, *, default: str = "#80d0ff") -> str:
        if not isinstance(value, str):
            return default
        token = value.strip()
        if not token:
            return default
        if token.startswith("#"):
            hex_part = token[1:]
            if len(hex_part) == 8:
                hex_part = hex_part[2:]
            if len(hex_part) in {3, 4, 6}:
                return f"#{hex_part}"
            return default
        return token

    def _copy_payload_details(self) -> None:
        text = getattr(self, "_current_detail_text", None)
        if not isinstance(text, str) or not text.strip():
            self.status_var.set("No payload selected to copy.")
            return
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            self.status_var.set("Payload details copied to clipboard.")
        except Exception as exc:
            self.status_var.set(f"Failed to copy payload details: {exc}")

    def _choose_log_file(self) -> None:
        initial = self.log_path_var.get() or str(self._locator.primary_log_file() or self._locator.log_dir)
        initial_path = Path(initial)
        if initial_path.is_file() or initial_path.suffix:
            initial_dir = initial_path.parent
        else:
            initial_dir = initial_path
        file_path = filedialog.askopenfilename(
            parent=self.root,
            initialdir=str(initial_dir),
            title="Select overlay-payloads.log",
        )
        if not file_path:
            return
        self._custom_log_file = Path(file_path).expanduser()
        self._user_config["log_file"] = str(self._custom_log_file)
        self._save_user_config()
        self._start_tailer()
        self.status_var.set(f"Using log file: {file_path}")

    def _draw_group_preview(self, group_label: str) -> None:
        payloads: List[Dict[str, Any]] = []
        for entry in self._payload_store.values():
            label = (entry.get("group_label") or "").strip()
            if label == group_label:
                payloads.append(self._parse_payload_entry(entry))
        if not payloads:
            self.status_var.set(f"No payloads found for group '{group_label}'.")
            return
        self._group_preview_payloads = group_label
        self._draw_preview(None, group_payloads=payloads)
        self.status_var.set(f"Drew {len(payloads)} payload(s) for group '{group_label}'.")

    def _rotate_tip(self) -> None:
        if not hasattr(self, "_tips") or not self._tips:
            self.tip_var.set("")
            return
        self._tip_index = (self._tip_index + 1) % len(self._tips)
        self.tip_var.set(self._tips[self._tip_index])
        self.root.after(8000, self._rotate_tip)

    def _start_tailer(self) -> None:
        override = None
        if self._custom_log_file:
            override = self._custom_log_file
        elif self._cli_override:
            override = self._cli_override
        if getattr(self, "_tailer", None):
            self._tailer.stop()
            self._tailer.join(timeout=1)
        self._locator = LogLocator(ROOT_DIR, override_dir=override)
        self._tailer = PayloadTailer(self._locator, self._resolver, self._queue, history_limit=MAX_ROWS)
        self._tailer.start()
        display = str(self._locator.primary_log_file() or self._locator.log_dir)
        self._update_log_label(display)

    def _load_user_config(self) -> Dict[str, Any]:
        try:
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except json.JSONDecodeError:
            return {}

    def _save_user_config(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(self._user_config, indent=2), encoding="utf-8")
    @staticmethod
    def _draw_marker(canvas: tk.Canvas, marker: str, x: float, y: float, color: str, text: Optional[str]) -> None:
        size = 8
        if marker.lower() == "cross":
            canvas.create_line(x - size, y, x + size, y, fill=color, width=2)
            canvas.create_line(x, y - size, x, y + size, fill=color, width=2)
        elif marker.lower() == "dot":
            canvas.create_oval(x - size / 2, y - size / 2, x + size / 2, y + size / 2, fill=color, outline=color)
        else:
            canvas.create_rectangle(x - size / 2, y - size / 2, x + size / 2, y + size / 2, outline=color)
        if text:
            canvas.create_text(x + size + 4, y, text=str(text), anchor="w", fill="#ffffff")

    def _parse_payload_entry(self, payload_entry: Mapping[str, object]) -> Dict[str, Any]:
        try:
            return json.loads(payload_entry.get("payload_json", "{}"))
        except Exception:
            return {}

    def _render_payload(
        self,
        canvas: tk.Canvas,
        data: Mapping[str, Any],
        offset_x: float,
        offset_y: float,
        scale: float,
    ) -> Optional[str]:
        x = _coerce_number(data.get("x"))
        y = _coerce_number(data.get("y"))
        w = _coerce_number(data.get("w"))
        h = _coerce_number(data.get("h"))
        text = data.get("text")
        shape = str(data.get("shape") or data.get("type") or "").lower()
        raw_color = data.get("color") or "#80d0ff"
        color = self._normalise_color(raw_color)
        fill_value = data.get("fill")
        fill_color = self._normalise_color(fill_value, default="") if isinstance(fill_value, str) else ""
        points = data.get("vector") if isinstance(data.get("vector"), list) else None

        if shape == "vect" and points:
            scaled_points = []
            for point in points:
                px = _coerce_number((point or {}).get("x"))
                py = _coerce_number((point or {}).get("y"))
                sx = offset_x + px * scale
                sy = offset_y + py * scale
                marker = (point or {}).get("marker")
                if marker:
                    marker_color = self._normalise_color(point.get("color") or color)
                    self._draw_marker(canvas, marker, sx, sy, marker_color, point.get("text"))
                else:
                    scaled_points.extend([sx, sy])
            if len(scaled_points) >= 4:
                canvas.create_line(
                    *scaled_points,
                    fill=color,
                    width=2,
                    smooth=True,
                )
        elif shape == "rect" or shape == "message" or text:
            box_w = max(10, (w or 0) * scale)
            box_h = max(10, (h or 0) * scale)
            origin_x = offset_x + (x or 0) * scale
            origin_y = offset_y + (y or 0) * scale
            canvas.create_rectangle(
                origin_x,
                origin_y,
                origin_x + box_w,
                origin_y + box_h,
                outline=color if self._is_valid_color(color) else "#80d0ff",
                width=2,
                fill=fill_color if self._is_valid_color(fill_color) else "",
            )
        return text if isinstance(text, str) and text else None


def _coerce_number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


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
