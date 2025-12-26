from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Optional

from overlay_plugin.groupings_diff import diff_groupings, is_empty_diff


class EditController:
    """Manages persistence, debounces, cache reload guards, and signal emission."""

    def __init__(self, app, *, logger=None) -> None:
        self.app = app
        self._log = logger or (lambda *args, **kwargs: None)

    @staticmethod
    def _round_offsets(payload: dict[str, object]) -> dict[str, object]:
        """Return a copy with offsets rounded to 3 decimals to avoid float noise."""

        result: dict[str, object] = {}
        for plugin_name, plugin_entry in payload.items():
            if not isinstance(plugin_entry, dict):
                result[plugin_name] = plugin_entry
                continue
            plugin_copy: dict[str, object] = dict(plugin_entry)
            groups = plugin_entry.get("idPrefixGroups")
            if isinstance(groups, dict):
                groups_copy: dict[str, object] = {}
                for label, group_entry in groups.items():
                    if not isinstance(group_entry, dict):
                        groups_copy[label] = group_entry
                        continue
                    group_copy: dict[str, object] = dict(group_entry)
                    for key in ("offsetX", "offsetY"):
                        value = group_copy.get(key)
                        if isinstance(value, (int, float)):
                            group_copy[key] = round(float(value), 3)
                    groups_copy[label] = group_copy
                plugin_copy["idPrefixGroups"] = groups_copy
            result[plugin_name] = plugin_copy
        return result

    # Persistence helpers -------------------------------------------------
    def persist_offsets(self, selection: tuple[str, str], offset_x: float, offset_y: float, debounce_ms: int | None) -> None:
        app = self.app
        plugin_name, label = selection
        app._edit_nonce = f"{time.time():.6f}-{os.getpid()}"
        state = app.__dict__.get("_group_state")
        if state is not None:
            try:
                state.persist_offsets(
                    plugin_name,
                    label,
                    offset_x,
                    offset_y,
                    edit_nonce=app._edit_nonce,
                    write=False,
                    invalidate_cache=True,
                )
                app._groupings_data = getattr(state, "_groupings_data", app._groupings_data)
                app._groupings_cache = getattr(state, "_groupings_cache", app._groupings_cache)
            except Exception:
                app._set_config_offsets(plugin_name, label, offset_x, offset_y)
        else:
            app._set_config_offsets(plugin_name, label, offset_x, offset_y)
        app._last_edit_ts = time.time()
        timers = getattr(app, "_mode_timers", None)
        if timers is not None:
            try:
                timers.record_edit()
            except Exception:
                pass
        if state is None:
            app._invalidate_group_cache_entry(plugin_name, label)
        delay = app._offset_write_debounce_ms if debounce_ms is None else debounce_ms
        self.schedule_groupings_config_write(delay)
        snapshot = app._group_snapshots.get(selection)
        if snapshot is not None:
            snapshot.offset_x = offset_x
            snapshot.offset_y = offset_y
            snapshot.has_transform = False
            snapshot.transform_bounds = snapshot.base_bounds
            snapshot.transform_anchor_token = snapshot.anchor_token
            snapshot.transform_anchor = snapshot.base_anchor
            app._group_snapshots[selection] = snapshot
        self._log(
            "Target updated for %s/%s: offset_x=%.1f offset_y=%.1f debounce_ms=%s",
            plugin_name,
            label,
            offset_x,
            offset_y,
            debounce_ms,
        )

    def persist_justification(self, plugin_name: str, label: str, justification: str) -> None:
        app = self.app
        state = app.__dict__.get("_group_state")
        if state is not None:
            try:
                state.persist_justification(
                    plugin_name, label, justification, edit_nonce=app._edit_nonce, write=False, invalidate_cache=True
                )
                app._groupings_data = getattr(state, "_groupings_data", app._groupings_data)
                app._groupings_cache = getattr(state, "_groupings_cache", app._groupings_cache)
            except Exception:
                pass
        self.schedule_groupings_config_write()
        if state is None:
            app._invalidate_group_cache_entry(plugin_name, label)
        app._last_edit_ts = time.time()
        app._offset_live_edit_until = max(getattr(app, "_offset_live_edit_until", 0.0) or 0.0, app._last_edit_ts + 5.0)
        timers = getattr(app, "_mode_timers", None)
        if timers is not None:
            try:
                timers.start_live_edit_window(5.0)
                timers.record_edit()
            except Exception:
                pass
        app._edit_nonce = f"{time.time():.6f}-{os.getpid()}"

    def persist_background(
        self,
        selection: tuple[str, str],
        color: Optional[str],
        border_color: Optional[str],
        border_width: Optional[int],
    ) -> None:
        app = self.app
        plugin_name, label = selection
        state = app.__dict__.get("_group_state")
        if state is not None:
            try:
                state.persist_background(
                    plugin_name,
                    label,
                    color,
                    border_color,
                    border_width,
                    edit_nonce=app._edit_nonce,
                    write=False,
                    invalidate_cache=True,
                )
                app._groupings_data = getattr(state, "_groupings_data", app._groupings_data)
                app._groupings_cache = getattr(state, "_groupings_cache", app._groupings_cache)
            except Exception:
                pass
        self.schedule_groupings_config_write()
        if state is None:
            app._invalidate_group_cache_entry(plugin_name, label)
        app._last_edit_ts = time.time()
        snapshot = app._group_snapshots.get(selection)
        if snapshot is not None:
            snapshot.background_color = color if color else None
            snapshot.background_border_color = border_color if border_color else None
            snapshot.background_border_width = int(border_width or 0) if border_width is not None else 0
            app._group_snapshots[selection] = snapshot
        timers = getattr(app, "_mode_timers", None)
        if timers is not None:
            try:
                timers.record_edit()
            except Exception:
                pass
        app._edit_nonce = f"{time.time():.6f}-{os.getpid()}"

    # Debounce/scheduling -------------------------------------------------
    def schedule_debounce(self, key: str, callback: callable, delay_ms: int | None = None) -> None:
        app = self.app
        timers = getattr(app, "_mode_timers", None)
        if timers is not None:
            handle = timers.schedule_debounce(key, callback, delay_ms=delay_ms)
            app._debounce_handles[key] = handle
            return
        existing = app._debounce_handles.get(key)
        if existing is not None:
            try:
                app.after_cancel(existing)
            except Exception:
                pass
        delay = app._write_debounce_ms if delay_ms is None else delay_ms
        handle = app.after(delay, callback)
        app._debounce_handles[key] = handle

    def schedule_groupings_config_write(self, delay_ms: int | None = None) -> None:
        self.schedule_debounce("config_write", self._flush_groupings_config, delay_ms)

    def schedule_groupings_cache_write(self, delay_ms: int | None = None) -> None:
        app = self.app
        timers = getattr(app, "_mode_timers", None)
        if timers is not None:
            timers.cancel_debounce("cache_write")
        else:
            existing = app._debounce_handles.pop("cache_write", None)
            if existing is not None:
                try:
                    app.after_cancel(existing)
                except Exception:
                    pass

    def _flush_groupings_config(self) -> None:
        app = self.app
        app._debounce_handles["config_write"] = None
        app._last_edit_ts = time.time()
        timers = getattr(app, "_mode_timers", None)
        if timers is not None:
            try:
                timers.record_edit()
            except Exception:
                pass
        app._user_overrides_nonce = app._edit_nonce
        self._write_groupings_config()
        self._emit_override_reload_signal()

    # Signals/cache helpers ----------------------------------------------
    def _write_groupings_config(self) -> None:
        app = self.app
        state = app.__dict__.get("_group_state")
        if state is None:
            user_path = getattr(app, "_groupings_user_path", None) or getattr(app, "_groupings_path", None)
            if user_path is None:
                return

            shipped_path = getattr(app, "_groupings_shipped_path", None)
            if shipped_path is None:
                root = Path(__file__).resolve().parents[2]
                shipped_path = root / "overlay_groupings.json"
                app._groupings_shipped_path = shipped_path

            try:
                shipped_raw = json.loads(shipped_path.read_text(encoding="utf-8"))
            except Exception:
                shipped_raw = {}

            merged_view = getattr(app, "_groupings_data", None)
            if not isinstance(merged_view, dict):
                merged_view = {}
            else:
                merged_view = self._round_offsets(merged_view)

            try:
                diff = diff_groupings(shipped_raw, merged_view)
            except Exception:
                return

            if is_empty_diff(diff):
                if user_path.exists():
                    try:
                        user_path.write_text("{}\n", encoding="utf-8")
                        self._log("Cleared user groupings file; no overrides to persist.")
                    except Exception:
                        pass
                else:
                    self._log("Skip writing user groupings: no diff to persist.")
                return

            try:
                payload = dict(diff) if isinstance(diff, dict) else {}
                payload["_edit_nonce"] = getattr(app, "_user_overrides_nonce", "")
                text = json.dumps(payload, indent=2) + "\n"
                tmp_path = user_path.with_suffix(user_path.suffix + ".tmp")
                tmp_path.write_text(text, encoding="utf-8")
                tmp_path.replace(user_path)
                merged_payload = dict(merged_view)
                merged_payload["_edit_nonce"] = getattr(app, "_user_overrides_nonce", "")
                app._send_plugin_cli(
                    {"cli": "controller_overrides_payload", "overrides": merged_payload, "nonce": merged_payload["_edit_nonce"]}
                )
            except Exception:
                return
            return
        try:
            state._write_groupings_config(edit_nonce=getattr(app, "_user_overrides_nonce", ""))
            merged_payload = getattr(state, "_groupings_data", {})
            if isinstance(merged_payload, dict):
                merged_payload = dict(merged_payload)
                merged_payload["_edit_nonce"] = getattr(app, "_user_overrides_nonce", "")
                app._send_plugin_cli(
                    {"cli": "controller_overrides_payload", "overrides": merged_payload, "nonce": merged_payload["_edit_nonce"]}
                )
        except Exception:
            return

    @classmethod
    def legacy_write_groupings_config(cls, app) -> None:
        """Legacy/test entry point forwarding to instance writer."""

        cls(app, logger=lambda *_args, **_kwargs: None)._write_groupings_config()

    def _emit_override_reload_signal(self) -> None:
        app = self.app
        now = time.monotonic()
        last = getattr(app, "_last_override_reload_ts", 0.0)
        if last and now - last < 0.25:
            return
        nonce = f"{int(time.time() * 1000)}-{os.getpid()}"
        app._last_override_reload_ts = now
        app._last_override_reload_nonce = nonce
        payload = {
            "cli": "controller_override_reload",
            "nonce": nonce,
            "edit_nonce": getattr(app, "_user_overrides_nonce", ""),
            "timestamp": time.time(),
        }
        bridge = getattr(app, "_plugin_bridge", None)
        sent = False
        if bridge is not None:
            try:
                sent = bool(
                    bridge.emit_override_reload(nonce=nonce, edit_nonce=payload["edit_nonce"], timestamp=payload["timestamp"])
                )
            except Exception:
                sent = False
        if not sent:
            app._send_plugin_cli(payload)
        self._log("Controller override reload signal sent (nonce=%s)", nonce)
