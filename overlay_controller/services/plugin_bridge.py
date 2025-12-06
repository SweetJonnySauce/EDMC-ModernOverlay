from __future__ import annotations

import json
import socket
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Callable, Optional

JsonDict = dict[str, Any]
ConnectFn = Callable[[tuple[str, int], float], object]
LogFn = Callable[[str], None]


def _noop_log(message: str) -> None:
    return None


class PluginBridge:
    """Thin helper for controller-to-plugin CLI messaging and related signals."""

    def __init__(
        self,
        *,
        root: Path,
        port_path: Optional[Path] = None,
        settings_path: Optional[Path] = None,
        connect: Optional[ConnectFn] = None,
        logger: Optional[LogFn] = None,
        time_source: Callable[[], float] = time.time,
    ) -> None:
        self._root = root
        self._port_path = port_path or (root / "port.json")
        self._settings_path = settings_path or (root / "overlay_settings.json")
        self._connect = connect or socket.create_connection
        self._log = logger or _noop_log
        self._time = time_source
        self._force_render_override = ForceRenderOverrideManager(
            settings_path=self._settings_path,
            port_path=self._port_path,
            connect=self._connect,
            logger=self._log,
            time_source=self._time,
        )
        self._last_active_group: tuple[str, str, str] | None = None
        self._last_override_reload_nonce: Optional[str] = None

    @property
    def force_render_override(self) -> "ForceRenderOverrideManager":
        return self._force_render_override

    def read_port(self) -> Optional[int]:
        try:
            data = json.loads(self._port_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return None
        port = data.get("port")
        if not isinstance(port, int) or port <= 0:
            return None
        return port

    def send_cli(self, payload: JsonDict) -> bool:
        port = self.read_port()
        if port is None:
            return False
        try:
            with self._connect(("127.0.0.1", port), timeout=1.5) as sock:
                writer = sock.makefile("w", encoding="utf-8", newline="\n")
                writer.write(json.dumps(payload, ensure_ascii=False))
                writer.write("\n")
                writer.flush()
            return True
        except Exception:
            return False

    def send_heartbeat(self) -> bool:
        return self.send_cli({"cli": "controller_heartbeat"})

    def send_active_group(
        self,
        plugin: Optional[str],
        label: Optional[str],
        *,
        anchor: Optional[str] = None,
        edit_nonce: str = "",
    ) -> bool:
        plugin_name = (plugin or "").strip()
        group_label = (label or "").strip()
        anchor_token = (anchor or "").strip().lower()
        key = (plugin_name, group_label, anchor_token)
        if key == self._last_active_group:
            return False
        payload = {
            "cli": "controller_active_group",
            "plugin": plugin_name,
            "label": group_label,
            "anchor": anchor_token,
            "edit_nonce": edit_nonce,
        }
        sent = self.send_cli(payload)
        if sent:
            self._last_active_group = key
        return sent

    def reset_active_group_cache(self) -> None:
        self._last_active_group = None

    def emit_override_reload(
        self,
        *,
        nonce: str,
        edit_nonce: str = "",
        timestamp: Optional[float] = None,
        dedupe: bool = True,
    ) -> bool:
        if dedupe and nonce and nonce == self._last_override_reload_nonce:
            return False
        payload = {
            "cli": "controller_override_reload",
            "nonce": nonce,
            "edit_nonce": edit_nonce,
            "timestamp": self._time() if timestamp is None else timestamp,
        }
        sent = self.send_cli(payload)
        if sent:
            self._last_override_reload_nonce = nonce
        return sent


class ForceRenderOverrideManager:
    """Manages temporary force-render overrides while the controller is open."""

    def __init__(
        self,
        *,
        settings_path: Path,
        port_path: Path,
        connect: Optional[ConnectFn] = None,
        logger: Optional[LogFn] = None,
        time_source: Callable[[], float] = time.monotonic,
    ) -> None:
        self._settings_path = settings_path
        self._port_path = port_path
        self._connect = connect or socket.create_connection
        self._logger = logger or _noop_log
        self._time = time_source
        self._active = False
        self._previous_force: Optional[bool] = None
        self._previous_allow: Optional[bool] = None

    def activate(self) -> None:
        if self._active:
            return
        current_force, current_allow = self._read_force_settings()
        self._previous_force = current_force
        self._previous_allow = current_allow
        response = self._send_override({"cli": "force_render_override", "allow": True, "force_render": True})
        if response is not None:
            previous_force = response.get("previous_force_render")
            if isinstance(previous_force, bool):
                self._previous_force = previous_force
            previous_allow = response.get("previous_allow")
            if isinstance(previous_allow, bool):
                self._previous_allow = previous_allow
        else:
            if self._previous_force is None:
                self._previous_force = False
            if self._previous_allow is None:
                self._previous_allow = False
            self._update_settings_file(force=True, allow=True)
        self._active = True

    def deactivate(self) -> None:
        if not self._active:
            return
        restore_force = self._previous_force if self._previous_force is not None else False
        restore_allow = self._previous_allow if self._previous_allow is not None else False
        response = self._send_override(
            {
                "cli": "force_render_override",
                "allow": restore_allow,
                "force_render": restore_force,
            }
        )
        if response is None:
            self._safe_log(
                "Overlay CLI unavailable while restoring force-render override; writing settings file directly."
            )
        self._update_settings_file(force=restore_force, allow=restore_allow)
        self._active = False
        self._previous_force = None
        self._previous_allow = None

    def _send_override(self, payload: JsonDict) -> Optional[JsonDict]:
        port = self._load_port()
        if port is None:
            return None
        message = json.dumps(payload, ensure_ascii=False)
        try:
            with self._connect(("127.0.0.1", port), timeout=2.0) as sock:
                try:
                    sock.settimeout(2.0)
                except Exception:
                    pass
                writer = sock.makefile("w", encoding="utf-8", newline="\n")
                reader = sock.makefile("r", encoding="utf-8")
                writer.write(message)
                writer.write("\n")
                writer.flush()
                deadline = self._time() + 2.0
                while self._time() < deadline:
                    line = reader.readline()
                    if not line:
                        break
                    try:
                        response = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(response, dict):
                        status = response.get("status")
                        if status == "ok":
                            return response
                        if status == "error":
                            error_msg = response.get("error")
                            if error_msg:
                                self._safe_log(f"Overlay client rejected force-render override: {error_msg}")
                            return None
        except OSError:
            return None
        except Exception:
            traceback.print_exc(file=sys.stderr)
            return None
        return None

    def _load_port(self) -> Optional[int]:
        try:
            data = json.loads(self._port_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return None
        port = data.get("port")
        if not isinstance(port, int) or port <= 0:
            return None
        return port

    def _read_force_settings(self) -> tuple[bool, bool]:
        try:
            raw = json.loads(self._settings_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return False, False
        return bool(raw.get("force_render", False)), bool(raw.get("allow_force_render_release", False))

    def _update_settings_file(self, *, force: bool, allow: bool) -> None:
        try:
            raw = json.loads(self._settings_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            raw = {}
        raw["force_render"] = bool(force)
        raw["allow_force_render_release"] = bool(allow)
        try:
            text = json.dumps(raw, indent=2) + "\n"
            self._settings_path.write_text(text, encoding="utf-8")
        except OSError:
            pass

    def _safe_log(self, message: str) -> None:
        try:
            self._logger(message)
        except Exception:
            print(f"[overlay-controller] {message}", file=sys.stderr)
