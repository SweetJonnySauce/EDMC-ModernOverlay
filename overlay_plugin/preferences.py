"""Preferences management and Tk UI for the Modern Overlay plugin."""
from __future__ import annotations

import json
import logging
import math
import webbrowser
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional, Sequence, Tuple

try:
    from config import config as EDMC_CONFIG  # type: ignore
except Exception:  # pragma: no cover - running outside EDMC
    EDMC_CONFIG = None


PREFERENCES_FILE = "overlay_settings.json"
STATUS_BASE_MARGIN = 20
LEGACY_STATUS_SLOT_MARGIN = 17
STATUS_GUTTER_MAX = 500
STATUS_GUTTER_DEFAULT = 50
ROW_PAD = (6, 0)
LATEST_RELEASE_URL = "https://github.com/SweetJonnySauce/EDMC-ModernOverlay/releases/latest"
OVERLAY_ID_PREFIX = "EDMCModernOverlay-"
CONFIG_PREFIX = "edmc_modern_overlay."
CONFIG_STATE_VERSION = 1
CONFIG_VERSION_KEY = f"{CONFIG_PREFIX}state_version"
CLIENT_LOG_RETENTION_MIN = 1
CLIENT_LOG_RETENTION_MAX = 20
DEFAULT_CLIENT_LOG_RETENTION = 5
PHYSICAL_CLAMP_SCALE_MIN = 0.5
PHYSICAL_CLAMP_SCALE_MAX = 3.0

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class TroubleshootingPanelState:
    diagnostics_enabled: bool = False
    capture_enabled: bool = False
    log_retention_override: Optional[int] = None
    exclude_plugins: Tuple[str, ...] = ()


def _config_available() -> bool:
    return EDMC_CONFIG is not None and hasattr(EDMC_CONFIG, "get") and hasattr(EDMC_CONFIG, "set")


def _config_key(name: str) -> str:
    return f"{CONFIG_PREFIX}{name}"


def _config_get_raw(key: str, default: Any) -> Any:
    if not _config_available():
        return default
    getter = getattr(EDMC_CONFIG, "get", None)
    if callable(getter):
        try:
            value = getter(key)
        except TypeError:
            try:
                value = getter(key, default)
            except Exception:
                value = default
    else:
        value = getattr(EDMC_CONFIG, key, default)
    return default if value is None else value


def _config_set_raw(key: str, value: Any) -> None:
    if not _config_available():
        return
    setter = getattr(EDMC_CONFIG, "set", None)
    if callable(setter):
        try:
            setter(key, value)
            return
        except (TypeError, ValueError):
            try:
                setter(key, str(value))
                return
            except Exception:
                pass
        except Exception:
            pass
    try:
        setattr(EDMC_CONFIG, key, value)
    except Exception:
        LOGGER.debug("Failed to persist %s into EDMC config", key)


def _coerce_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        token = value.strip().lower()
        if token in {"1", "true", "yes", "on"}:
            return True
        if token in {"0", "false", "no", "off"}:
            return False
    return default


def _coerce_int(value: Any, default: int, *, minimum: Optional[int] = None, maximum: Optional[int] = None) -> int:
    try:
        numeric = int(value)
    except (TypeError, ValueError):
        numeric = default
    if minimum is not None:
        numeric = max(minimum, numeric)
    if maximum is not None:
        numeric = min(maximum, numeric)
    return numeric


def _coerce_float(value: Any, default: float, *, minimum: Optional[float] = None, maximum: Optional[float] = None) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        numeric = default
    if minimum is not None:
        numeric = max(minimum, numeric)
    if maximum is not None:
        numeric = min(maximum, numeric)
    return numeric


def _coerce_str(
    value: Any,
    default: str,
    *,
    allowed: Optional[set[str]] = None,
    transform: Callable[[str], str] | None = None,
) -> str:
    if value is None:
        return default
    try:
        text = str(value)
    except Exception:
        return default
    text = text.strip()
    if transform:
        text = transform(text)
    if allowed and text not in allowed:
        return default
    return text or default


def _format_physical_clamp_overrides(overrides: Mapping[str, float]) -> str:
    """Convert the override map into a stable, user-friendly string."""
    if not overrides:
        return ""
    tokens: list[str] = []
    for name in sorted(overrides.keys()):
        try:
            tokens.append(f"{name}={float(overrides[name]):g}")
        except Exception:
            continue
    return ", ".join(tokens)


def _attach_tooltip(widget, text: str, *, nb_module=None, delay_ms: int = 500) -> None:
    if not text:
        return
    if nb_module is not None:
        tooltip_factory = (
            getattr(nb_module, "ToolTip", None)
            or getattr(nb_module, "Tooltip", None)
            or getattr(nb_module, "CreateToolTip", None)
        )
        if tooltip_factory:
            try:
                tooltip_factory(widget, text)
                return
            except Exception:
                LOGGER.debug("Failed to attach notebook tooltip helper", exc_info=True)
    try:
        import tkinter as tk
    except Exception:
        return

    tip_window = None
    after_id = None

    def hide_tip() -> None:
        nonlocal tip_window, after_id
        if after_id is not None:
            try:
                widget.after_cancel(after_id)
            except Exception:
                pass
            after_id = None
        if tip_window is not None:
            try:
                tip_window.destroy()
            except Exception:
                pass
            tip_window = None

    def show_tip() -> None:
        nonlocal tip_window
        if tip_window is not None:
            return
        try:
            x = widget.winfo_rootx() + 16
            y = widget.winfo_rooty() + widget.winfo_height() + 8
        except Exception:
            return
        tip_window = tk.Toplevel(widget)
        tip_window.wm_overrideredirect(True)
        try:
            tip_window.attributes("-topmost", True)
        except Exception:
            pass
        label = tk.Label(
            tip_window,
            text=text,
            background="#ffffe0",
            relief="solid",
            borderwidth=1,
            justify="left",
        )
        label.pack(ipadx=6, ipady=3)
        tip_window.wm_geometry(f"+{x}+{y}")

    def schedule_tip(_event=None) -> None:
        nonlocal after_id
        hide_tip()
        after_id = widget.after(delay_ms, show_tip)

    widget.bind("<Enter>", schedule_tip, add="+")
    widget.bind("<Leave>", lambda _event: hide_tip(), add="+")
    widget.bind("<ButtonPress>", lambda _event: hide_tip(), add="+")


def _coerce_physical_clamp_overrides(
    value: Any,
    default: Optional[Mapping[str, float]],
    *,
    allow_empty: bool = False,
    errors: Optional[list[str]] = None,
) -> Dict[str, float]:
    """Parse per-monitor clamp overrides from mappings or strings.

    Accepts a mapping (preferred) or a comma-separated string of name=scale entries.
    Scales are clamped to a safe range to avoid destructive values.
    """

    def _record(message: str) -> None:
        if errors is not None:
            errors.append(message)

    def _normalise_map(raw_map: Mapping[str, Any]) -> Dict[str, float]:
        overrides: Dict[str, float] = {}
        for raw_name, raw_scale in raw_map.items():
            try:
                name = str(raw_name).strip()
            except Exception:
                _record(f"Skipping override with invalid screen name {raw_name!r}")
                continue
            if not name:
                _record("Skipping override with empty screen name")
                continue
            try:
                scale = float(raw_scale)
            except (TypeError, ValueError):
                _record(f"Skipping override for {name}: invalid scale {raw_scale!r}")
                continue
            if not math.isfinite(scale) or scale <= 0:
                _record(f"Skipping override for {name}: non-finite or non-positive scale {raw_scale!r}")
                continue
            clamped = max(PHYSICAL_CLAMP_SCALE_MIN, min(PHYSICAL_CLAMP_SCALE_MAX, scale))
            if not math.isclose(clamped, scale):
                _record(f"Clamped override for {name} to {clamped:g}")
            overrides[name] = clamped
        return overrides

    def _parse_string(text: str) -> Dict[str, Any]:
        try:
            parsed_json = json.loads(text)
        except Exception:
            parsed_json = None
        if isinstance(parsed_json, Mapping):
            return dict(parsed_json)
        raw_map: Dict[str, Any] = {}
        for token in text.split(","):
            if not token:
                continue
            if "=" not in token:
                if token.strip():
                    _record(f"Skipping override '{token.strip()}': expected name=scale")
                continue
            name, _, raw_scale = token.partition("=")
            raw_map[name] = raw_scale
        return raw_map

    base_default: Dict[str, float] = dict(default or {})
    if value is None:
        return base_default
    if isinstance(value, Mapping):
        overrides = _normalise_map(value)
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return {} if allow_empty else base_default
        overrides = _normalise_map(_parse_string(text))
    else:
        return base_default

    if overrides:
        return overrides
    return {} if allow_empty else base_default


def _normalise_launch_command(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return "!ovr"
    if not text.startswith("!"):
        text = "!" + text
    return text


@dataclass
class Preferences:
    """Simple JSON-backed preferences store."""

    plugin_dir: Path
    dev_mode: bool = False
    overlay_opacity: float = 0.0
    global_payload_opacity: int = 100
    show_connection_status: bool = False
    debug_overlay_corner: str = "NW"
    client_log_retention: int = DEFAULT_CLIENT_LOG_RETENTION
    gridlines_enabled: bool = False
    gridline_spacing: int = 120
    force_render: bool = False
    force_xwayland: bool = False
    physical_clamp_enabled: bool = False
    physical_clamp_overrides: Dict[str, float] = field(default_factory=dict)
    show_debug_overlay: bool = False
    min_font_point: float = 6.0
    max_font_point: float = 24.0
    legacy_font_step: int = 2
    title_bar_enabled: bool = False
    title_bar_height: int = 0
    cycle_payload_ids: bool = False
    copy_payload_id_on_cycle: bool = False
    scale_mode: str = "fit"
    nudge_overflow_payloads: bool = False
    payload_nudge_gutter: int = 30
    status_message_gutter: int = STATUS_GUTTER_DEFAULT
    log_payloads: bool = False
    payload_log_delay_seconds: float = 0.5
    controller_launch_command: str = "!ovr"

    def __post_init__(self) -> None:
        self.plugin_dir = Path(self.plugin_dir)
        self._path = self.plugin_dir / PREFERENCES_FILE
        self._config_enabled = _config_available()
        if self._config_enabled:
            self._maybe_import_legacy_json()
            self._load_from_config()
            # Merge in the shadow JSON in case EDMC config missed a recent update.
            # This keeps restarts consistent even if config persistence failed mid-session.
            self._load_from_json(silent=True)
            try:
                self._persist_to_config()
            except Exception:
                LOGGER.debug("Failed to persist preferences into EDMC config after shadow merge.", exc_info=True)
            self._ensure_state_version_mark()
        else:
            self._load_from_json()
        try:
            self._write_shadow_file()
        except Exception:
            LOGGER.debug("Unable to write initial overlay_settings.json shadow file.", exc_info=True)

    # Persistence ---------------------------------------------------------

    def _load_from_json(self, *, silent: bool = False) -> None:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except json.JSONDecodeError:
            if not silent:
                LOGGER.debug("overlay_settings.json is not valid JSON; ignoring contents.")
            return
        self._apply_raw_data(data)

    def _maybe_import_legacy_json(self) -> None:
        current_version = _coerce_int(_config_get_raw(CONFIG_VERSION_KEY, 0), 0)
        if current_version >= CONFIG_STATE_VERSION:
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            _config_set_raw(CONFIG_VERSION_KEY, CONFIG_STATE_VERSION)
            return
        self._apply_raw_data(data)
        self._persist_to_config()

    def _load_from_config(self) -> None:
        LOGGER.debug(
            "Loading prefs from EDMC config (controller_launch_command=%s default=%s)",
            _config_get_raw(_config_key("controller_launch_command"), self.controller_launch_command),
            self.controller_launch_command,
        )
        payload: Dict[str, Any] = {
            "overlay_opacity": _config_get_raw(_config_key("overlay_opacity"), self.overlay_opacity),
            "global_payload_opacity": _config_get_raw(
                _config_key("global_payload_opacity"),
                self.global_payload_opacity,
            ),
            "show_connection_status": _config_get_raw(_config_key("show_connection_status"), self.show_connection_status),
            "debug_overlay_corner": _config_get_raw(_config_key("debug_overlay_corner"), self.debug_overlay_corner),
            "client_log_retention": _config_get_raw(_config_key("client_log_retention"), self.client_log_retention),
            "gridlines_enabled": _config_get_raw(_config_key("gridlines_enabled"), self.gridlines_enabled),
            "gridline_spacing": _config_get_raw(_config_key("gridline_spacing"), self.gridline_spacing),
            "force_render": _config_get_raw(_config_key("force_render"), self.force_render),
            "force_xwayland": _config_get_raw(_config_key("force_xwayland"), self.force_xwayland),
            "physical_clamp_enabled": _config_get_raw(
                _config_key("physical_clamp_enabled"),
                self.physical_clamp_enabled,
            ),
            "physical_clamp_overrides": _config_get_raw(
                _config_key("physical_clamp_overrides"),
                self.physical_clamp_overrides,
            ),
            "show_debug_overlay": _config_get_raw(_config_key("show_debug_overlay"), self.show_debug_overlay),
            "min_font_point": _config_get_raw(_config_key("min_font_point"), self.min_font_point),
            "max_font_point": _config_get_raw(_config_key("max_font_point"), self.max_font_point),
            "legacy_font_step": _config_get_raw(_config_key("legacy_font_step"), self.legacy_font_step),
            "title_bar_enabled": _config_get_raw(_config_key("title_bar_enabled"), self.title_bar_enabled),
            "title_bar_height": _config_get_raw(_config_key("title_bar_height"), self.title_bar_height),
            "cycle_payload_ids": _config_get_raw(_config_key("cycle_payload_ids"), self.cycle_payload_ids),
            "copy_payload_id_on_cycle": _config_get_raw(
                _config_key("copy_payload_id_on_cycle"),
                self.copy_payload_id_on_cycle,
            ),
            "scale_mode": _config_get_raw(_config_key("scale_mode"), self.scale_mode),
            "nudge_overflow_payloads": _config_get_raw(
                _config_key("nudge_overflow_payloads"),
                self.nudge_overflow_payloads,
            ),
            "payload_nudge_gutter": _config_get_raw(_config_key("payload_nudge_gutter"), self.payload_nudge_gutter),
            "status_message_gutter": _config_get_raw(
                _config_key("status_message_gutter"),
                self.status_message_gutter,
            ),
            "log_payloads": _config_get_raw(_config_key("log_payloads"), self.log_payloads),
            "payload_log_delay_seconds": _config_get_raw(
                _config_key("payload_log_delay_seconds"),
                self.payload_log_delay_seconds,
            ),
            "controller_launch_command": _config_get_raw(
                _config_key("controller_launch_command"),
                self.controller_launch_command,
            ),
        }
        self._apply_raw_data(payload)

    def _apply_raw_data(self, data: Mapping[str, Any]) -> None:
        self.overlay_opacity = _coerce_float(data.get("overlay_opacity"), self.overlay_opacity, minimum=0.0, maximum=1.0)
        self.global_payload_opacity = _coerce_int(
            data.get("global_payload_opacity"),
            self.global_payload_opacity,
            minimum=0,
            maximum=100,
        )
        self.show_connection_status = _coerce_bool(data.get("show_connection_status"), self.show_connection_status)
        self.debug_overlay_corner = _coerce_str(
            data.get("debug_overlay_corner"),
            self.debug_overlay_corner,
            allowed={"NW", "NE", "SW", "SE"},
            transform=str.upper,
        )
        self.client_log_retention = _coerce_int(
            data.get("client_log_retention"),
            self.client_log_retention,
            minimum=1,
        )
        self.gridlines_enabled = _coerce_bool(data.get("gridlines_enabled"), self.gridlines_enabled)
        self.gridline_spacing = _coerce_int(data.get("gridline_spacing"), self.gridline_spacing, minimum=10)
        self.force_render = _coerce_bool(data.get("force_render"), self.force_render)
        self.force_xwayland = _coerce_bool(data.get("force_xwayland"), self.force_xwayland)
        self.physical_clamp_enabled = _coerce_bool(
            data.get("physical_clamp_enabled"),
            self.physical_clamp_enabled,
        )
        self.physical_clamp_overrides = _coerce_physical_clamp_overrides(
            data.get("physical_clamp_overrides"),
            self.physical_clamp_overrides,
            allow_empty=True,
        )
        self.show_debug_overlay = _coerce_bool(data.get("show_debug_overlay"), self.show_debug_overlay)
        self.min_font_point = _coerce_float(data.get("min_font_point"), self.min_font_point, minimum=1.0, maximum=48.0)
        self.max_font_point = _coerce_float(
            data.get("max_font_point"), self.max_font_point, minimum=self.min_font_point, maximum=72.0
        )
        self.legacy_font_step = _coerce_int(
            data.get("legacy_font_step"),
            self.legacy_font_step,
            minimum=0,
            maximum=10,
        )
        self.title_bar_enabled = _coerce_bool(data.get("title_bar_enabled"), self.title_bar_enabled)
        self.title_bar_height = _coerce_int(data.get("title_bar_height"), self.title_bar_height, minimum=0)
        self.cycle_payload_ids = _coerce_bool(data.get("cycle_payload_ids"), self.cycle_payload_ids)
        self.copy_payload_id_on_cycle = _coerce_bool(data.get("copy_payload_id_on_cycle"), self.copy_payload_id_on_cycle)
        self.scale_mode = _coerce_str(
            data.get("scale_mode"),
            self.scale_mode,
            allowed={"fit", "fill"},
            transform=str.lower,
        )
        self.nudge_overflow_payloads = _coerce_bool(data.get("nudge_overflow_payloads"), self.nudge_overflow_payloads)
        self.payload_nudge_gutter = _coerce_int(
            data.get("payload_nudge_gutter"),
            self.payload_nudge_gutter,
            minimum=0,
            maximum=500,
        )
        status_default = data.get("status_message_gutter", self.status_message_gutter)
        status_gutter = _coerce_int(status_default, self.status_message_gutter, minimum=0, maximum=STATUS_GUTTER_MAX)
        if "status_message_gutter" not in data:
            legacy_slots = int(bool(data.get("show_ed_bandwidth"))) + int(bool(data.get("show_ed_fps")))
            status_gutter = max(status_gutter, LEGACY_STATUS_SLOT_MARGIN * legacy_slots)
        self.status_message_gutter = status_gutter
        self.log_payloads = _coerce_bool(data.get("log_payloads"), self.log_payloads)
        self.payload_log_delay_seconds = _coerce_float(
            data.get("payload_log_delay_seconds"),
            self.payload_log_delay_seconds,
            minimum=0.0,
        )
        launch_value = data.get("controller_launch_command")
        if launch_value is None:
            launch_value = data.get("launch_command")
        self.controller_launch_command = _coerce_str(
            launch_value,
            self.controller_launch_command,
            transform=_normalise_launch_command,
        )

    def save(self) -> None:
        if self._config_enabled:
            self._persist_to_config()
        self._write_shadow_file()

    def _shadow_payload(self) -> Dict[str, Any]:
        return {
            "overlay_opacity": float(self.overlay_opacity),
            "global_payload_opacity": int(self.global_payload_opacity),
            "show_connection_status": bool(self.show_connection_status),
            "debug_overlay_corner": str(self.debug_overlay_corner or "NW"),
            "client_log_retention": int(self.client_log_retention),
            "gridlines_enabled": bool(self.gridlines_enabled),
            "gridline_spacing": int(self.gridline_spacing),
            "force_render": bool(self.force_render),
            "force_xwayland": bool(self.force_xwayland),
            "physical_clamp_enabled": bool(self.physical_clamp_enabled),
            "physical_clamp_overrides": dict(self.physical_clamp_overrides or {}),
            "show_debug_overlay": bool(self.show_debug_overlay),
            "min_font_point": float(self.min_font_point),
            "max_font_point": float(self.max_font_point),
            "legacy_font_step": int(self.legacy_font_step),
            "status_bottom_margin": int(self.status_bottom_margin()),
            "title_bar_enabled": bool(self.title_bar_enabled),
            "title_bar_height": int(self.title_bar_height),
            "cycle_payload_ids": bool(self.cycle_payload_ids),
            "copy_payload_id_on_cycle": bool(self.copy_payload_id_on_cycle),
            "scale_mode": str(self.scale_mode or "fit"),
            "nudge_overflow_payloads": bool(self.nudge_overflow_payloads),
            "payload_nudge_gutter": int(self.payload_nudge_gutter),
            "status_message_gutter": int(self.status_message_gutter),
            "log_payloads": bool(self.log_payloads),
            "payload_log_delay_seconds": float(self.payload_log_delay_seconds),
            "controller_launch_command": str(self.controller_launch_command or "!ovr"),
        }

    def _write_shadow_file(self) -> None:
        payload = self._shadow_payload()
        self._path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _persist_to_config(self) -> None:
        if not self._config_enabled:
            return
        _config_set_raw(_config_key("overlay_opacity"), float(self.overlay_opacity))
        _config_set_raw(_config_key("global_payload_opacity"), int(self.global_payload_opacity))
        _config_set_raw(_config_key("show_connection_status"), bool(self.show_connection_status))
        _config_set_raw(_config_key("debug_overlay_corner"), str(self.debug_overlay_corner or "NW"))
        _config_set_raw(_config_key("client_log_retention"), int(self.client_log_retention))
        _config_set_raw(_config_key("gridlines_enabled"), bool(self.gridlines_enabled))
        _config_set_raw(_config_key("gridline_spacing"), int(self.gridline_spacing))
        _config_set_raw(_config_key("force_render"), bool(self.force_render))
        _config_set_raw(_config_key("force_xwayland"), bool(self.force_xwayland))
        _config_set_raw(_config_key("physical_clamp_enabled"), bool(self.physical_clamp_enabled))
        try:
            overrides_payload = json.dumps(self.physical_clamp_overrides)
        except Exception:
            overrides_payload = "{}"
        _config_set_raw(_config_key("physical_clamp_overrides"), overrides_payload)
        _config_set_raw(_config_key("show_debug_overlay"), bool(self.show_debug_overlay))
        _config_set_raw(_config_key("min_font_point"), float(self.min_font_point))
        _config_set_raw(_config_key("max_font_point"), float(self.max_font_point))
        _config_set_raw(_config_key("legacy_font_step"), int(self.legacy_font_step))
        _config_set_raw(_config_key("title_bar_enabled"), bool(self.title_bar_enabled))
        _config_set_raw(_config_key("title_bar_height"), int(self.title_bar_height))
        _config_set_raw(_config_key("cycle_payload_ids"), bool(self.cycle_payload_ids))
        _config_set_raw(_config_key("copy_payload_id_on_cycle"), bool(self.copy_payload_id_on_cycle))
        _config_set_raw(_config_key("scale_mode"), str(self.scale_mode or "fit"))
        _config_set_raw(_config_key("nudge_overflow_payloads"), bool(self.nudge_overflow_payloads))
        _config_set_raw(_config_key("payload_nudge_gutter"), int(self.payload_nudge_gutter))
        _config_set_raw(_config_key("status_message_gutter"), int(self.status_message_gutter))
        _config_set_raw(_config_key("log_payloads"), bool(self.log_payloads))
        _config_set_raw(_config_key("payload_log_delay_seconds"), float(self.payload_log_delay_seconds))
        _config_set_raw(_config_key("controller_launch_command"), str(self.controller_launch_command or "!ovr"))
        _config_set_raw(CONFIG_VERSION_KEY, CONFIG_STATE_VERSION)

    def _ensure_state_version_mark(self) -> None:
        if not self._config_enabled:
            return
        current_version = _coerce_int(_config_get_raw(CONFIG_VERSION_KEY, 0), 0)
        if current_version < CONFIG_STATE_VERSION:
            _config_set_raw(CONFIG_VERSION_KEY, CONFIG_STATE_VERSION)

    def status_bottom_margin(self) -> int:
        return STATUS_BASE_MARGIN + int(max(0, self.status_message_gutter))


class PreferencesPanel:
    """Builds a Tkinter frame that edits Modern Overlay preferences."""

    def __init__(
        self,
        parent,
        preferences: Preferences,
        send_test_callback: Optional[Callable[[str, Optional[int], Optional[int]], None]] = None,
        set_opacity_callback: Optional[Callable[[float], None]] = None,
        set_status_callback: Optional[Callable[[bool], None]] = None,
        set_status_gutter_callback: Optional[Callable[[int], None]] = None,
        set_debug_overlay_corner_callback: Optional[Callable[[str], None]] = None,
        set_gridlines_enabled_callback: Optional[Callable[[bool], None]] = None,
        set_gridline_spacing_callback: Optional[Callable[[int], None]] = None,
        set_payload_nudge_callback: Optional[Callable[[bool], None]] = None,
        set_payload_gutter_callback: Optional[Callable[[int], None]] = None,
        set_force_render_callback: Optional[Callable[[bool], None]] = None,
        set_title_bar_config_callback: Optional[Callable[[bool, int], None]] = None,
        set_debug_overlay_callback: Optional[Callable[[bool], None]] = None,
        set_payload_logging_callback: Optional[Callable[[bool], None]] = None,
        set_font_min_callback: Optional[Callable[[float], None]] = None,
        set_font_max_callback: Optional[Callable[[float], None]] = None,
        set_font_step_callback: Optional[Callable[[int], None]] = None,
        preview_font_sizes_callback: Optional[Callable[[], None]] = None,
        set_cycle_payload_callback: Optional[Callable[[bool], None]] = None,
        set_cycle_payload_copy_callback: Optional[Callable[[bool], None]] = None,
        cycle_payload_prev_callback: Optional[Callable[[], None]] = None,
        cycle_payload_next_callback: Optional[Callable[[], None]] = None,
        restart_overlay_callback: Optional[Callable[[], None]] = None,
        set_launch_command_callback: Optional[Callable[[str], None]] = None,
        set_payload_opacity_callback: Optional[Callable[[int], None]] = None,
        reset_group_cache_callback: Optional[Callable[[], bool]] = None,
        dev_mode: bool = False,
        plugin_version: Optional[str] = None,
        version_update_available: bool = False,
        troubleshooting_state: Optional[TroubleshootingPanelState] = None,
        set_capture_override_callback: Optional[Callable[[bool], None]] = None,
        set_log_retention_override_callback: Optional[Callable[[Optional[int]], None]] = None,
        set_payload_exclusion_callback: Optional[Callable[[Sequence[str]], None]] = None,
        payload_logging_initial: Optional[bool] = None,
    ) -> None:
        import tkinter as tk
        from tkinter import ttk
        import tkinter.font as tkfont
        import myNotebook as nb

        self._preferences = preferences
        self._style = ttk.Style()
        (
            self._frame_style,
            self._spinbox_style,
            self._scale_style,
            self._labelframe_style,
        ) = self._init_theme_styles(nb)
        self._var_opacity = tk.DoubleVar(value=preferences.overlay_opacity)
        self._var_payload_opacity = tk.DoubleVar(value=float(preferences.global_payload_opacity))
        self._var_show_status = tk.BooleanVar(value=preferences.show_connection_status)
        self._var_status_gutter = tk.IntVar(value=max(0, int(preferences.status_message_gutter)))
        self._var_debug_overlay_corner = tk.StringVar(value=(preferences.debug_overlay_corner or "NW"))
        self._var_gridlines_enabled = tk.BooleanVar(value=preferences.gridlines_enabled)
        self._var_gridline_spacing = tk.IntVar(value=max(10, int(preferences.gridline_spacing)))
        self._var_payload_nudge = tk.BooleanVar(value=preferences.nudge_overflow_payloads)
        self._var_payload_gutter = tk.IntVar(value=max(0, int(preferences.payload_nudge_gutter)))
        self._var_force_render = tk.BooleanVar(value=preferences.force_render)
        self._var_physical_clamp = tk.BooleanVar(value=preferences.physical_clamp_enabled)
        self._var_physical_clamp_overrides = tk.StringVar(
            value=_format_physical_clamp_overrides(preferences.physical_clamp_overrides)
        )
        self._var_title_bar_enabled = tk.BooleanVar(value=preferences.title_bar_enabled)
        self._var_title_bar_height = tk.IntVar(value=int(preferences.title_bar_height))
        self._var_debug_overlay = tk.BooleanVar(value=preferences.show_debug_overlay)
        initial_logging = preferences.log_payloads if payload_logging_initial is None else bool(payload_logging_initial)
        self._var_payload_logging = tk.BooleanVar(value=initial_logging)
        self._var_min_font = tk.DoubleVar(value=float(preferences.min_font_point))
        self._var_max_font = tk.DoubleVar(value=float(preferences.max_font_point))
        self._var_legacy_font_step = tk.IntVar(value=int(preferences.legacy_font_step))
        self._var_cycle_payload = tk.BooleanVar(value=preferences.cycle_payload_ids)
        self._var_cycle_copy = tk.BooleanVar(value=preferences.copy_payload_id_on_cycle)
        self._var_launch_command = tk.StringVar(value=preferences.controller_launch_command)
        state = troubleshooting_state or TroubleshootingPanelState(
            diagnostics_enabled=False,
            capture_enabled=False,
            log_retention_override=None,
            exclude_plugins=(),
        )
        self._diagnostics_enabled = bool(state.diagnostics_enabled)
        self._var_capture_override = tk.BooleanVar(value=state.capture_enabled)
        retention_value = state.log_retention_override
        if retention_value is None:
            try:
                base_value = int(preferences.client_log_retention)
            except Exception:
                base_value = DEFAULT_CLIENT_LOG_RETENTION
            base_value = max(CLIENT_LOG_RETENTION_MIN, min(base_value, CLIENT_LOG_RETENTION_MAX))
            retention_value = base_value
        self._var_log_retention_override_active = tk.BooleanVar(value=state.log_retention_override is not None)
        self._var_log_retention_value = tk.IntVar(value=int(retention_value))
        self._var_payload_exclude = tk.StringVar(value=", ".join(state.exclude_plugins))
        self._font_bounds_apply_in_progress = False
        self._font_step_apply_in_progress = False
        self._launch_command_apply_in_progress = False
        self._payload_opacity_apply_in_progress = False

        self._send_test = send_test_callback
        self._set_opacity = set_opacity_callback
        self._set_status = set_status_callback
        self._set_status_gutter = set_status_gutter_callback
        self._set_debug_overlay_corner = set_debug_overlay_corner_callback
        self._set_gridlines_enabled = set_gridlines_enabled_callback
        self._set_gridline_spacing = set_gridline_spacing_callback
        self._set_payload_nudge = set_payload_nudge_callback
        self._set_payload_gutter = set_payload_gutter_callback
        self._set_force_render = set_force_render_callback
        self._set_title_bar_config = set_title_bar_config_callback
        self._set_debug_overlay = set_debug_overlay_callback
        self._set_payload_logging = set_payload_logging_callback
        self._set_font_min = set_font_min_callback
        self._set_font_max = set_font_max_callback
        self._set_font_step = set_font_step_callback
        self._preview_font_sizes = preview_font_sizes_callback
        self._set_cycle_payload = set_cycle_payload_callback
        self._set_cycle_payload_copy = set_cycle_payload_copy_callback
        self._cycle_prev_callback = cycle_payload_prev_callback
        self._cycle_next_callback = cycle_payload_next_callback
        self._restart_overlay = restart_overlay_callback
        self._set_launch_command = set_launch_command_callback
        self._set_payload_opacity = set_payload_opacity_callback
        self._reset_group_cache = reset_group_cache_callback
        self._set_capture_override = set_capture_override_callback
        self._set_log_retention_override = set_log_retention_override_callback
        self._set_payload_exclusions = set_payload_exclusion_callback

        self._legacy_client = None
        self._status_gutter_spin = None
        self._payload_gutter_spin = None
        self._title_bar_height_spin = None
        self._gridline_spacing_spin = None
        self._cycle_prev_btn = None
        self._cycle_next_btn = None
        self._cycle_copy_checkbox = None
        self._log_retention_spin = None
        self._payload_exclude_entry = None
        self._managed_fonts = []
        self._status_gutter_apply_in_progress = False
        self._var_status_gutter.trace_add("write", self._on_status_gutter_trace)
        self._plugin_version = (plugin_version or "").strip()
        self._version_update_available = bool(version_update_available)
        self._test_var = tk.StringVar()
        self._test_x_var = tk.StringVar()
        self._test_y_var = tk.StringVar()
        self._status_var = tk.StringVar(value="")
        self._payload_opacity_label = tk.StringVar(value=f"{int(preferences.global_payload_opacity)}%")
        self._dev_mode = bool(dev_mode)

        frame = nb.Frame(parent)

        self._var_min_font.trace_add("write", self._on_font_bounds_trace)
        self._var_max_font.trace_add("write", self._on_font_bounds_trace)
        self._var_legacy_font_step.trace_add("write", self._on_font_step_trace)
        header_frame = ttk.Frame(frame, style=self._frame_style)
        header_frame.grid(row=0, column=0, sticky="we")
        header_frame.columnconfigure(0, weight=1)
        header_frame.columnconfigure(1, weight=0)

        if self._plugin_version:
            version_column = ttk.Frame(header_frame, style=self._frame_style)
            version_column.grid(row=0, column=1, sticky="ne")
            version_label = nb.Label(
                version_column,
                text=f"Version {self._plugin_version}",
                cursor="hand2",
                foreground="#1a73e8",
            )
            try:
                link_font = tkfont.Font(root=parent, font=version_label.cget("font"))
                link_font.configure(underline=True)
                self._managed_fonts.append(link_font)
                version_label.configure(font=link_font)
            except Exception:
                pass
            version_label.grid(row=0, column=0, sticky="e")
            version_label.bind("<Button-1>", self._open_release_link)
            version_label.bind("<Return>", self._open_release_link)
            version_label.bind(
                "<Enter>", lambda _event, widget=version_label: widget.configure(foreground="#0b57d0")
            )
            version_label.bind(
                "<Leave>", lambda _event, widget=version_label: widget.configure(foreground="#1a73e8")
            )
            if self._version_update_available:
                warning_label = nb.Label(
                    version_column,
                    text="A newer version is available",
                    foreground="#c62828",
                )
                warning_label.grid(row=1, column=0, sticky="e", pady=(2, 0))

        user_section = ttk.Frame(frame, style=self._frame_style)
        user_section.grid(row=1, column=0, sticky="we")
        user_section.columnconfigure(0, weight=1)
        user_row = 0

        status_row = ttk.Frame(user_section, style=self._frame_style)
        status_checkbox = nb.Checkbutton(
            status_row,
            text="Show connection status message at bottom of overlay",
            variable=self._var_show_status,
            onvalue=True,
            offvalue=False,
            command=self._on_show_status_toggle,
        )
        status_checkbox.pack(side="left")
        gutter_label = nb.Label(status_row, text="Gutter (px):")
        gutter_label.pack(side="left", padx=(16, 4))
        status_gutter_spin = ttk.Spinbox(
            status_row,
            from_=0,
            to=STATUS_GUTTER_MAX,
            increment=5,
            width=5,
            textvariable=self._var_status_gutter,
            command=self._on_status_gutter_command,
            style=self._spinbox_style,
        )
        status_gutter_spin.pack(side="left")
        status_gutter_spin.bind("<FocusOut>", self._on_status_gutter_event)
        status_gutter_spin.bind("<Return>", self._on_status_gutter_event)
        self._status_gutter_spin = status_gutter_spin
        self._update_status_gutter_spin_state()

        status_row.grid(row=user_row, column=0, sticky="w", pady=ROW_PAD)
        user_row += 1

        force_row = ttk.Frame(user_section, style=self._frame_style)
        force_checkbox = nb.Checkbutton(
            force_row,
            text="Keep overlay visible when Elite Dangerous is not the foreground window",
            variable=self._var_force_render,
            onvalue=True,
            offvalue=False,
            command=self._on_force_render_toggle,
        )
        force_checkbox.pack(side="left")
        force_row.grid(row=user_row, column=0, sticky="w", pady=ROW_PAD)
        user_row += 1

        font_row = ttk.Frame(user_section, style=self._frame_style)
        font_label = nb.Label(font_row, text="Font scaling bounds (pt):")
        font_label.pack(side="left")
        min_spin = ttk.Spinbox(
            font_row,
            from_=1.0,
            to=72.0,
            increment=0.5,
            width=5,
            textvariable=self._var_min_font,
            command=self._on_font_bounds_command,
            style=self._spinbox_style,
        )
        min_spin.pack(side="left", padx=(6, 0))
        min_spin.bind("<FocusOut>", self._on_font_bounds_event)
        min_spin.bind("<Return>", self._on_font_bounds_event)
        nb.Label(font_row, text="–").pack(side="left", padx=(4, 4))
        max_spin = ttk.Spinbox(
            font_row,
            from_=1.0,
            to=72.0,
            increment=0.5,
            width=5,
            textvariable=self._var_max_font,
            command=self._on_font_bounds_command,
            style=self._spinbox_style,
        )
        max_spin.pack(side="left")
        max_spin.bind("<FocusOut>", self._on_font_bounds_event)
        max_spin.bind("<Return>", self._on_font_bounds_event)
        step_label = nb.Label(font_row, text="Font Step:")
        _attach_tooltip(
            step_label,
            'Font Step is the difference in font size between "Small", "Normal", "Large", and "Huge" font sizes.',
            nb_module=nb,
        )
        step_label.pack(side="left", padx=(12, 4))
        step_spin = ttk.Spinbox(
            font_row,
            from_=0,
            to=10,
            increment=1,
            width=3,
            textvariable=self._var_legacy_font_step,
            command=self._on_font_step_command,
            style=self._spinbox_style,
        )
        step_spin.pack(side="left")
        step_spin.bind("<FocusOut>", self._on_font_step_event)
        step_spin.bind("<Return>", self._on_font_step_event)
        preview_btn = nb.Button(font_row, text="Preview", command=self._on_font_preview)
        preview_btn.pack(side="left", padx=(8, 0))
        font_row.grid(row=user_row, column=0, sticky="w", pady=ROW_PAD)
        user_row += 1

        title_bar_row = ttk.Frame(user_section, style=self._frame_style)
        title_bar_checkbox = nb.Checkbutton(
            title_bar_row,
            text="Compensate for Elite Dangerous title bar",
            variable=self._var_title_bar_enabled,
            onvalue=True,
            offvalue=False,
            command=self._on_title_bar_toggle,
        )
        title_bar_checkbox.pack(side="left")
        title_bar_height_label = nb.Label(title_bar_row, text="Height (px):")
        title_bar_height_label.pack(side="left", padx=(12, 4))
        title_bar_height_spin = ttk.Spinbox(
            title_bar_row,
            from_=0,
            to=200,
            increment=1,
            width=4,
            textvariable=self._var_title_bar_height,
            command=self._on_title_bar_height_command,
            style=self._spinbox_style,
        )
        title_bar_height_spin.pack(side="left")
        title_bar_height_spin.bind("<FocusOut>", self._on_title_bar_height_event)
        title_bar_height_spin.bind("<Return>", self._on_title_bar_height_event)
        if not self._var_title_bar_enabled.get():
            title_bar_height_spin.state(["disabled"])
        self._title_bar_height_spin = title_bar_height_spin
        title_bar_row.grid(row=user_row, column=0, sticky="w", pady=ROW_PAD)
        user_row += 1

        nudge_row = ttk.Frame(user_section, style=self._frame_style)
        nudge_checkbox = nb.Checkbutton(
            nudge_row,
            text="Nudge overflowing payloads back into view",
            variable=self._var_payload_nudge,
            onvalue=True,
            offvalue=False,
            command=self._on_payload_nudge_toggle,
        )
        nudge_checkbox.pack(side="left")
        gutter_label = nb.Label(nudge_row, text="Gutter (px):")
        gutter_label.pack(side="left", padx=(12, 4))
        gutter_spin = ttk.Spinbox(
            nudge_row,
            from_=0,
            to=500,
            increment=5,
            width=6,
            textvariable=self._var_payload_gutter,
            command=self._on_payload_gutter_command,
            style=self._spinbox_style,
        )
        gutter_spin.pack(side="left")
        gutter_spin.bind("<FocusOut>", self._on_payload_gutter_event)
        gutter_spin.bind("<Return>", self._on_payload_gutter_event)
        self._payload_gutter_spin = gutter_spin
        self._update_payload_gutter_spin_state()
        nudge_row.grid(row=user_row, column=0, sticky="w", pady=ROW_PAD)
        user_row += 1

        launch_row = ttk.Frame(user_section, style=self._frame_style)
        nb.Label(launch_row, text="Chat command to launch controller:").pack(side="left")
        launch_entry = nb.EntryMenu(launch_row, width=10, textvariable=self._var_launch_command)
        launch_entry.pack(side="left", padx=(8, 0))
        launch_entry.bind("<FocusOut>", self._on_launch_command_event)
        launch_entry.bind("<Return>", self._on_launch_command_event)
        launch_row.grid(row=user_row, column=0, sticky="w", pady=ROW_PAD)
        user_row += 1

        payload_opacity_row = ttk.Frame(user_section, style=self._frame_style)
        payload_opacity_label = nb.Label(payload_opacity_row, text="Overlay payload opacity:")
        _attach_tooltip(
            payload_opacity_label,
            "Adjust the opacity of all payloads drawn on the game screen. "
            "If a payload is already semi-transparent this setting will adjust its opacity linearly.",
            nb_module=nb,
        )
        payload_opacity_label.pack(side="left")
        payload_opacity_scale = ttk.Scale(
            payload_opacity_row,
            variable=self._var_payload_opacity,
            from_=0,
            to=100,
            orient=tk.HORIZONTAL,
            length=200,
            command=self._on_payload_opacity_change,
            style=self._scale_style,
        )
        payload_opacity_scale.pack(side="left", padx=(8, 0))
        payload_opacity_value = nb.Label(payload_opacity_row, textvariable=self._payload_opacity_label)
        payload_opacity_value.pack(side="left", padx=(8, 0))
        payload_opacity_row.grid(row=user_row, column=0, sticky="w", pady=ROW_PAD)
        user_row += 1

        clamp_row = ttk.Frame(user_section, style=self._frame_style)
        clamp_checkbox = nb.Checkbutton(
            clamp_row,
            text="Clamp fractional desktop scaling (physical clamp)",
            variable=self._var_physical_clamp,
            onvalue=True,
            offvalue=False,
            command=self._on_physical_clamp_toggle,
        )
        clamp_checkbox.pack(side="left")
        clamp_row.grid(row=user_row, column=0, sticky="w", pady=ROW_PAD)
        user_row += 1

        clamp_override_row = ttk.Frame(user_section, style=self._frame_style)
        clamp_override_row.columnconfigure(1, weight=1)
        nb.Label(
            clamp_override_row,
            text="Per-monitor clamp overrides (name=scale, comma-separated):",
        ).grid(row=0, column=0, sticky="w")
        clamp_override_entry = nb.EntryMenu(
            clamp_override_row,
            width=40,
            textvariable=self._var_physical_clamp_overrides,
        )
        clamp_override_entry.grid(row=0, column=1, padx=(8, 0), sticky="we")
        clamp_override_entry.bind("<Return>", self._on_physical_clamp_overrides_event)
        clamp_override_entry.bind("<FocusOut>", self._on_physical_clamp_overrides_event)
        clamp_override_apply = nb.Button(
            clamp_override_row,
            text="Apply",
            command=self._on_physical_clamp_overrides_apply,
        )
        clamp_override_apply.grid(row=0, column=2, padx=(8, 0), sticky="e")
        helper_label = nb.Label(
            clamp_override_row,
            text="Example: DisplayPort-2=1.0, HDMI-0=1.25 (empty to clear)",
        )
        helper_label.grid(row=1, column=0, columnspan=3, sticky="w", pady=(ROW_PAD[0], 0))
        clamp_override_row.grid(row=user_row, column=0, sticky="we", pady=ROW_PAD)
        user_row += 1

        cache_row = ttk.Frame(user_section, style=self._frame_style)
        cache_label = nb.Label(cache_row, text="Overlay group cache:")
        cache_label.pack(side="left")
        reset_cache_btn = nb.Button(cache_row, text="Reset cached values", command=self._on_reset_group_cache)
        if self._reset_group_cache is None:
            reset_cache_btn.configure(state="disabled")
        reset_cache_btn.pack(side="left", padx=(8, 0))
        cache_row.grid(row=user_row, column=0, sticky="w", pady=ROW_PAD)
        user_row += 1

        if self._diagnostics_enabled:
            diagnostics_label = nb.Label(user_section, text="Diagnostics")
            try:
                diag_font = tkfont.Font(root=parent, font=diagnostics_label.cget("font"))
            except Exception:
                diag_font = None
            else:
                try:
                    diag_font.configure(weight="bold")
                    self._managed_fonts.append(diag_font)
                    diagnostics_label.configure(font=diag_font)
                except Exception:
                    pass
            diagnostics_frame = ttk.LabelFrame(
                user_section,
                labelwidget=diagnostics_label,
                padding=(8, 8),
                style=self._labelframe_style,
            )
            diagnostics_frame.grid(row=user_row, column=0, sticky="we", pady=ROW_PAD)
            diagnostics_frame.columnconfigure(0, weight=1)
            diag_row = 0

            debug_row = ttk.Frame(diagnostics_frame, style=self._frame_style)
            debug_checkbox = nb.Checkbutton(
                debug_row,
                text="Show debug overlay metrics (frame size, scaling)",
                variable=self._var_debug_overlay,
                onvalue=True,
                offvalue=False,
                command=self._on_debug_overlay_toggle,
            )
            debug_checkbox.pack(side="left")
            corner_label = nb.Label(debug_row, text="Corner:")
            corner_label.pack(side="left", padx=(12, 4))
            for label, value in (("NW", "NW"), ("NE", "NE"), ("SW", "SW"), ("SE", "SE")):
                rb = nb.Radiobutton(
                    debug_row,
                    text=label,
                    value=value,
                    variable=self._var_debug_overlay_corner,
                    command=self._on_debug_overlay_corner_change,
                )
                rb.pack(side="left", padx=(4, 0))
            debug_row.grid(row=diag_row, column=0, sticky="w", pady=ROW_PAD)
            diag_row += 1

            payload_logging_checkbox = nb.Checkbutton(
                diagnostics_frame,
                text="Log incoming payloads to overlay-payloads.log (required for Payload Inspector)",
                variable=self._var_payload_logging,
                onvalue=True,
                offvalue=False,
                command=self._on_payload_logging_toggle,
            )
            payload_logging_checkbox.grid(row=diag_row, column=0, sticky="w", pady=ROW_PAD)
            diag_row += 1

            capture_checkbox = nb.Checkbutton(
                diagnostics_frame,
                text="Capture overlay stdout/stderr in the EDMC log",
                variable=self._var_capture_override,
                onvalue=True,
                offvalue=False,
                command=self._on_capture_override_toggle,
            )
            if not (self._diagnostics_enabled and self._set_capture_override):
                capture_checkbox.state(["disabled"])
            capture_checkbox.grid(row=diag_row, column=0, sticky="w", pady=ROW_PAD)
            diag_row += 1

            retention_row = ttk.Frame(diagnostics_frame, style=self._frame_style)
            retention_row.grid(row=diag_row, column=0, sticky="w", pady=ROW_PAD)
            retention_checkbox = nb.Checkbutton(
                retention_row,
                text="Override overlay log retention (rotating log files)",
                variable=self._var_log_retention_override_active,
                onvalue=True,
                offvalue=False,
                command=self._on_log_retention_override_toggle,
            )
            retention_checkbox.pack(side="left")
            retention_spin = ttk.Spinbox(
                retention_row,
                from_=CLIENT_LOG_RETENTION_MIN,
                to=CLIENT_LOG_RETENTION_MAX,
                increment=1,
                width=3,
                textvariable=self._var_log_retention_value,
                command=self._on_log_retention_override_command,
                style=self._spinbox_style,
            )
            retention_spin.pack(side="left", padx=(12, 0))
            retention_spin.bind("<FocusOut>", self._on_log_retention_override_event)
            retention_spin.bind("<Return>", self._on_log_retention_override_event)
            self._log_retention_spin = retention_spin
            if not (self._diagnostics_enabled and self._set_log_retention_override):
                retention_checkbox.state(["disabled"])
            self._update_log_retention_spin_state()
            diag_row += 1

            exclude_row = ttk.Frame(diagnostics_frame, style=self._frame_style)
            exclude_row.grid(row=diag_row, column=0, sticky="we", pady=ROW_PAD)
            exclude_row.columnconfigure(0, weight=1)
            exclude_label = nb.Label(exclude_row, text="Skip payload logging for plugin IDs:")
            exclude_label.pack(side="left")
            exclude_entry = nb.EntryMenu(exclude_row, width=28, textvariable=self._var_payload_exclude)
            exclude_entry.pack(side="left", padx=(8, 0), fill="x", expand=True)
            exclude_entry.bind("<Return>", self._on_payload_exclude_event)
            self._payload_exclude_entry = exclude_entry
            exclude_button = nb.Button(exclude_row, text="Apply", command=self._on_payload_exclude_apply)
            exclude_button.pack(side="left", padx=(8, 0))
            if not (self._diagnostics_enabled and self._set_payload_exclusions):
                exclude_entry.configure(state="disabled")
                exclude_button.configure(state="disabled")
            user_row += 1

        next_row = 2
        if self._dev_mode:
            dev_label = nb.Label(frame, text="Developer Settings")
            try:
                dev_font = tkfont.Font(root=parent, font=dev_label.cget("font"))
            except Exception:
                dev_font = None
            else:
                try:
                    dev_font.configure(weight="bold")
                    self._managed_fonts.append(dev_font)
                    dev_label.configure(font=dev_font)
                except Exception:
                    pass
            dev_frame = ttk.LabelFrame(
                frame,
                labelwidget=dev_label,
                padding=(8, 8),
                style=self._labelframe_style,
            )
            dev_frame.grid(row=next_row, column=0, sticky="we", pady=ROW_PAD)
            dev_frame.columnconfigure(0, weight=1)
            dev_row = 0

            restart_row = ttk.Frame(dev_frame, style=self._frame_style)
            restart_btn = nb.Button(restart_row, text="Restart overlay client", command=self._on_restart_overlay)
            if self._restart_overlay is None:
                restart_btn.configure(state="disabled")
            restart_btn.pack(side="left")
            restart_row.grid(row=dev_row, column=0, sticky="w", pady=ROW_PAD)
            dev_row += 1

            opacity_label = nb.Label(
                dev_frame,
                text="Overlay background opacity (0.0 transparent – 1.0 opaque).",
            )
            opacity_label.grid(row=dev_row, column=0, sticky="w", pady=ROW_PAD)
            dev_row += 1

            opacity_row = ttk.Frame(dev_frame, style=self._frame_style)
            opacity_scale = ttk.Scale(
                opacity_row,
                variable=self._var_opacity,
                from_=0.0,
                to=1.0,
                orient=tk.HORIZONTAL,
                length=250,
                command=self._on_opacity_change,
                style=self._scale_style,
            )
            opacity_scale.pack(side="left", fill="x")
            opacity_row.grid(row=dev_row, column=0, sticky="we", pady=ROW_PAD)
            dev_row += 1

            grid_row = ttk.Frame(dev_frame, style=self._frame_style)
            grid_checkbox = nb.Checkbutton(
                grid_row,
                text="Show light gridlines over the overlay background",
                variable=self._var_gridlines_enabled,
                onvalue=True,
                offvalue=False,
                command=self._on_gridlines_toggle,
            )
            grid_checkbox.pack(side="left")
            grid_spacing_label = nb.Label(grid_row, text="Spacing (px):")
            grid_spacing_label.pack(side="left", padx=(12, 4))
            grid_spacing_spin = ttk.Spinbox(
                grid_row,
                from_=10,
                to=400,
                increment=10,
                width=5,
                textvariable=self._var_gridline_spacing,
                command=self._on_gridline_spacing_command,
                style=self._spinbox_style,
            )
            grid_spacing_spin.pack(side="left")
            grid_spacing_spin.bind("<FocusOut>", self._on_gridline_spacing_event)
            grid_spacing_spin.bind("<Return>", self._on_gridline_spacing_event)
            self._gridline_spacing_spin = grid_spacing_spin
            self._update_gridline_spacing_spin_state()
            grid_row.grid(row=dev_row, column=0, sticky="w", pady=ROW_PAD)
            dev_row += 1

            cycle_row = ttk.Frame(dev_frame, style=self._frame_style)
            cycle_checkbox = nb.Checkbutton(
                cycle_row,
                text="Cycle through Payload IDs",
                variable=self._var_cycle_payload,
                onvalue=True,
                offvalue=False,
                command=self._on_cycle_payload_toggle,
            )
            self._cycle_prev_btn = nb.Button(cycle_row, text="<", width=3, command=self._on_cycle_payload_prev)
            self._cycle_next_btn = nb.Button(cycle_row, text=">", width=3, command=self._on_cycle_payload_next)
            self._cycle_copy_checkbox = nb.Checkbutton(
                cycle_row,
                text="Copy current payload ID to clipboard",
                variable=self._var_cycle_copy,
                onvalue=True,
                offvalue=False,
                command=self._on_cycle_copy_toggle,
            )
            cycle_checkbox.pack(side="left")
            self._cycle_prev_btn.pack(side="left", padx=(8, 0))
            self._cycle_next_btn.pack(side="left", padx=(4, 0))
            self._cycle_copy_checkbox.pack(side="left", padx=(12, 0))
            cycle_row.grid(row=dev_row, column=0, sticky="w", pady=ROW_PAD)
            dev_row += 1

            test_row = ttk.Frame(dev_frame, style=self._frame_style)
            test_label = nb.Label(test_row, text="Send test message to overlay:")
            test_label.pack(side="left", padx=(0, 8))
            test_entry = nb.EntryMenu(test_row, textvariable=self._test_var, width=28)
            x_label = nb.Label(test_row, text="X:")
            x_entry = nb.EntryMenu(test_row, textvariable=self._test_x_var, width=6)
            y_label = nb.Label(test_row, text="Y:")
            y_entry = nb.EntryMenu(test_row, textvariable=self._test_y_var, width=6)
            send_button = nb.Button(test_row, text="Send", command=self._on_send_click)
            test_entry.pack(side="left", fill="x", expand=True)
            x_label.pack(side="left", padx=(8, 2))
            x_entry.pack(side="left")
            y_label.pack(side="left", padx=(8, 2))
            y_entry.pack(side="left")
            send_button.pack(side="left", padx=(8, 0))
            test_row.grid(row=dev_row, column=0, sticky="we", pady=ROW_PAD)
            test_row.columnconfigure(0, weight=1)
            dev_row += 1

            legacy_row = ttk.Frame(dev_frame, style=self._frame_style)
            legacy_label = nb.Label(legacy_row, text="Legacy edmcoverlay compatibility:")
            legacy_label.pack(side="left", padx=(0, 8))
            legacy_text_btn = nb.Button(legacy_row, text="Send legacy text", command=self._on_legacy_text)
            legacy_rect_btn = nb.Button(legacy_row, text="Send legacy rectangle", command=self._on_legacy_rect)
            legacy_emoji_btn = nb.Button(legacy_row, text="Send legacy emoji", command=self._on_legacy_emoji)
            legacy_text_btn.pack(side="left")
            legacy_rect_btn.pack(side="left", padx=(8, 0))
            legacy_emoji_btn.pack(side="left", padx=(8, 0))
            legacy_row.grid(row=dev_row, column=0, sticky="w", pady=ROW_PAD)
            dev_row += 1

            next_row += 1

        self._update_cycle_button_state()

        status_label = nb.Label(frame, textvariable=self._status_var, wraplength=400, justify="left")
        status_label.grid(row=next_row, column=0, sticky="w", pady=ROW_PAD)
        frame.columnconfigure(0, weight=1)

        self._frame = frame

    @property
    def frame(self):  # pragma: no cover - Tk integration
        return self._frame

    def apply(self) -> None:
        # Ensure any pending entry/spinbox values are written back before saving.
        self._apply_font_bounds(update_remote=False)
        self._apply_font_step(update_remote=False)
        self._apply_status_gutter(update_remote=False, force=True)
        self._apply_title_bar_height(update_remote=False)
        self._apply_payload_gutter()
        self._preferences.save()

    def _init_theme_styles(self, nb):
        try:
            bg = nb.PAGEBG
            fg = nb.PAGEFG
        except AttributeError:
            bg = fg = None
        frame_style = "OverlayPrefs.TFrame"
        labelframe_style = "OverlayPrefs.TLabelframe"
        labelframe_label_style = "OverlayPrefs.TLabelframe.Label"
        spin_style = "OverlayPrefs.TSpinbox"
        scale_style = "OverlayPrefs.Horizontal.TScale"
        self._style.configure(frame_style, background=bg)
        self._style.configure(labelframe_style, background=bg)
        self._style.configure(spin_style, arrowsize=12)
        if bg is not None and fg is not None:
            self._style.configure(labelframe_label_style, background=bg, foreground=fg)
            self._style.configure(spin_style, fieldbackground=bg, foreground=fg, background=bg)
            self._style.configure(scale_style, background=bg)
        return frame_style, spin_style, scale_style, labelframe_style

    def _on_opacity_change(self, value: str) -> None:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            numeric = 0.0
        numeric = max(0.0, min(1.0, numeric))
        self._var_opacity.set(numeric)
        self._preferences.overlay_opacity = numeric
        if self._set_opacity:
            try:
                self._set_opacity(numeric)
            except Exception as exc:
                self._status_var.set(f"Failed to update opacity: {exc}")
                return
        self._preferences.save()

    def _on_payload_opacity_change(self, value: str) -> None:
        self._apply_payload_opacity(value=value, update_remote=True)

    def _apply_payload_opacity(self, *, value: Optional[str] = None, update_remote: bool = True) -> int:
        if self._payload_opacity_apply_in_progress:
            return int(self._preferences.global_payload_opacity)
        self._payload_opacity_apply_in_progress = True
        try:
            if value is None:
                raw_value: object = self._var_payload_opacity.get()
            else:
                raw_value = value
            try:
                numeric = int(round(float(raw_value)))
            except (TypeError, ValueError):
                numeric = int(self._preferences.global_payload_opacity)
            numeric = max(0, min(100, numeric))
            if float(numeric) != float(self._var_payload_opacity.get()):
                self._var_payload_opacity.set(float(numeric))
            self._payload_opacity_label.set(f"{numeric}%")
            old_value = int(self._preferences.global_payload_opacity)
            if update_remote and self._set_payload_opacity and numeric != old_value:
                try:
                    self._set_payload_opacity(numeric)
                except Exception as exc:
                    self._status_var.set(f"Failed to update payload opacity: {exc}")
                    self._var_payload_opacity.set(float(old_value))
                    self._payload_opacity_label.set(f"{old_value}%")
                    self._preferences.global_payload_opacity = old_value
                    return old_value
            if numeric != old_value:
                self._preferences.global_payload_opacity = numeric
                self._preferences.save()
            return numeric
        finally:
            self._payload_opacity_apply_in_progress = False

    def _on_reset_group_cache(self) -> None:
        if not callable(self._reset_group_cache):
            self._status_var.set("Reset cached values is unavailable.")
            return
        try:
            success = self._reset_group_cache()
        except Exception as exc:
            LOGGER.debug("Reset cached values failed", exc_info=True)
            self._status_var.set(f"Failed to reset cached values: {exc}")
            return
        if success is False:
            self._status_var.set("Failed to reset cached values.")
            return
        self._status_var.set("Cached overlay values reset.")

    def _on_show_status_toggle(self) -> None:
        value = bool(self._var_show_status.get())
        self._preferences.show_connection_status = value
        self._update_status_gutter_spin_state()
        if self._set_status:
            try:
                self._set_status(value)
            except Exception as exc:
                self._status_var.set(f"Failed to update connection status: {exc}")
                return
        self._preferences.save()

    def _on_status_gutter_command(self) -> None:
        self._apply_status_gutter()

    def _on_status_gutter_event(self, _event) -> None:  # pragma: no cover - Tk event
        self._apply_status_gutter()

    def _on_status_gutter_trace(self, *_args) -> None:
        if self._status_gutter_apply_in_progress:
            return
        self._apply_status_gutter()

    def _on_launch_command_trace(self, *_args) -> None:
        if self._launch_command_apply_in_progress:
            return
        self._apply_launch_command()

    def _on_launch_command_event(self, _event=None) -> None:  # pragma: no cover - Tk event
        self._apply_launch_command()

    def _apply_launch_command(self) -> None:
        if self._launch_command_apply_in_progress:
            return
        self._launch_command_apply_in_progress = True
        raw_value = self._var_launch_command.get()
        normalised = _coerce_str(
            raw_value,
            self._preferences.controller_launch_command,
            transform=_normalise_launch_command,
        )
        LOGGER.info(
            "Overlay Controller launch command change requested (UI): raw=%r normalised=%s current=%s",
            raw_value,
            normalised,
            self._preferences.controller_launch_command,
        )
        if normalised != self._var_launch_command.get():
            self._var_launch_command.set(normalised)
        if normalised == self._preferences.controller_launch_command:
            self._launch_command_apply_in_progress = False
            return
        old_value = self._preferences.controller_launch_command
        self._preferences.controller_launch_command = normalised
        self._preferences.save()
        if callable(self._set_launch_command):
            try:
                self._set_launch_command(normalised)
            except Exception:
                LOGGER.debug("Failed to propagate launch command change", exc_info=True)
        self._status_var.set(f"Overlay launch command set to {normalised}")
        LOGGER.info("Overlay Controller launch command updated (UI): %s -> %s", old_value, normalised)
        self._launch_command_apply_in_progress = False

    def _open_release_link(self, _event=None) -> None:
        try:
            webbrowser.open_new(LATEST_RELEASE_URL)
        except Exception as exc:
            self._status_var.set(f"Failed to open release notes: {exc}")

    def _apply_status_gutter(self, update_remote: bool = True, force: bool = False) -> int:
        if self._status_gutter_apply_in_progress and not force:
            return self._preferences.status_message_gutter
        self._status_gutter_apply_in_progress = True
        try:
            try:
                gutter_raw = self._status_gutter_spin.get() if self._status_gutter_spin is not None else None
            except Exception:
                gutter_raw = None
            if gutter_raw is None:
                gutter = int(self._var_status_gutter.get())
            else:
                gutter = int(gutter_raw)
        except (TypeError, ValueError):
            gutter = self._preferences.status_message_gutter
        gutter = max(0, min(gutter, STATUS_GUTTER_MAX))
        if str(gutter) != str(self._var_status_gutter.get()):
            self._var_status_gutter.set(gutter)
        old_value = self._preferences.status_message_gutter
        if update_remote and self._set_status_gutter:
            try:
                self._set_status_gutter(gutter)
            except Exception as exc:
                self._status_var.set(f"Failed to update status gutter: {exc}")
                self._var_status_gutter.set(old_value)
                self._status_gutter_apply_in_progress = False
                return old_value
        elif gutter == old_value:
            self._status_gutter_apply_in_progress = False
            return gutter
        self._preferences.status_message_gutter = gutter
        self._preferences.save()
        self._status_gutter_apply_in_progress = False
        return gutter

    def _on_debug_overlay_corner_change(self) -> None:
        value = (self._var_debug_overlay_corner.get() or "NW").upper()
        if value not in {"NW", "NE", "SW", "SE"}:
            value = "NW"
        self._preferences.debug_overlay_corner = value
        if self._set_debug_overlay_corner:
            try:
                self._set_debug_overlay_corner(value)
            except Exception as exc:
                self._status_var.set(f"Failed to update debug overlay corner: {exc}")
                return
        self._preferences.save()

    def _on_payload_logging_toggle(self) -> None:
        value = bool(self._var_payload_logging.get())
        try:
            if self._set_payload_logging:
                self._set_payload_logging(value)
            else:
                self._preferences.log_payloads = value
                self._preferences.save()
        except Exception as exc:
            self._status_var.set(f"Failed to update payload logging: {exc}")
            self._var_payload_logging.set(not value)
            self._preferences.log_payloads = bool(self._var_payload_logging.get())
            return
        self._preferences.log_payloads = value
        self._preferences.save()

    def _on_capture_override_toggle(self) -> None:
        desired = bool(self._var_capture_override.get())
        if not (self._diagnostics_enabled and self._set_capture_override):
            self._var_capture_override.set(not desired)
            self._status_var.set("Set EDMC log level to DEBUG (or enable dev mode) to capture stdout/stderr.")
            return
        try:
            self._set_capture_override(desired)
        except Exception as exc:
            self._status_var.set(f"Failed to update stdout/stderr capture: {exc}")
            self._var_capture_override.set(not desired)
            return
        self._status_var.set(
            "Overlay stdout/stderr capture {}".format("enabled" if desired else "disabled")
        )

    def _update_status_gutter_spin_state(self) -> None:
        if self._status_gutter_spin is None:
            return
        if bool(self._var_show_status.get()):
            self._status_gutter_spin.state(["!disabled"])
        else:
            self._status_gutter_spin.state(["disabled"])

    def _update_payload_gutter_spin_state(self) -> None:
        if self._payload_gutter_spin is None:
            return
        if bool(self._var_payload_nudge.get()):
            self._payload_gutter_spin.state(["!disabled"])
        else:
            self._payload_gutter_spin.state(["disabled"])

    def _update_gridline_spacing_spin_state(self) -> None:
        if self._gridline_spacing_spin is None:
            return
        if bool(self._var_gridlines_enabled.get()):
            self._gridline_spacing_spin.state(["!disabled"])
        else:
            self._gridline_spacing_spin.state(["disabled"])

    def _update_log_retention_spin_state(self) -> None:
        if self._log_retention_spin is None:
            return
        enabled = (
            self._diagnostics_enabled
            and self._set_log_retention_override is not None
            and bool(self._var_log_retention_override_active.get())
        )
        if enabled:
            self._log_retention_spin.state(["!disabled"])
        else:
            self._log_retention_spin.state(["disabled"])

    def _on_log_retention_override_toggle(self) -> None:
        active = bool(self._var_log_retention_override_active.get())
        if not (self._diagnostics_enabled and self._set_log_retention_override):
            self._var_log_retention_override_active.set(False)
            self._status_var.set("Set EDMC logging to DEBUG to override overlay log retention.")
            self._update_log_retention_spin_state()
            return
        if not active:
            try:
                self._set_log_retention_override(None)
            except Exception as exc:
                self._status_var.set(f"Failed to clear log retention override: {exc}")
                self._var_log_retention_override_active.set(True)
            else:
                self._status_var.set("Overlay log retention override disabled.")
        else:
            if self._apply_log_retention_override(update_remote=True) is None:
                self._var_log_retention_override_active.set(False)
        self._update_log_retention_spin_state()

    def _on_log_retention_override_command(self) -> None:
        self._apply_log_retention_override()

    def _on_log_retention_override_event(self, _event) -> None:  # pragma: no cover - Tk event
        self._apply_log_retention_override()

    def _apply_log_retention_override(self, update_remote: bool = True) -> Optional[int]:
        try:
            value = int(self._var_log_retention_value.get())
        except Exception:
            try:
                value = int(self._preferences.client_log_retention)
            except Exception:
                value = DEFAULT_CLIENT_LOG_RETENTION
        value = max(CLIENT_LOG_RETENTION_MIN, min(value, CLIENT_LOG_RETENTION_MAX))
        self._var_log_retention_value.set(value)
        if not update_remote or self._set_log_retention_override is None:
            return value
        try:
            self._set_log_retention_override(value)
        except Exception as exc:
            self._status_var.set(f"Failed to update log retention override: {exc}")
            return None
        self._status_var.set(f"Overlay log retention override set to {value} files.")
        return value

    def _current_payload_excludes(self) -> Tuple[str, ...]:
        raw = (self._var_payload_exclude.get() or "").replace(",", " ")
        tokens: list[str] = []
        seen: set[str] = set()
        for token in raw.split():
            cleaned = token.strip().lower()
            if not cleaned or cleaned in seen:
                continue
            tokens.append(cleaned)
            seen.add(cleaned)
        return tuple(tokens)

    def _on_payload_exclude_apply(self) -> None:
        if not (self._diagnostics_enabled and self._set_payload_exclusions):
            self._status_var.set("Set EDMC logging to DEBUG to edit payload exclusions.")
            return
        try:
            self._set_payload_exclusions(self._current_payload_excludes())
        except Exception as exc:
            self._status_var.set(f"Failed to update payload exclusions: {exc}")
            return
        self._status_var.set("Payload logging exclusions updated.")

    def _on_payload_exclude_event(self, _event) -> str:  # pragma: no cover - Tk event
        self._on_payload_exclude_apply()
        return "break"

    def _update_cycle_button_state(self) -> None:
        state = "normal" if self._var_cycle_payload.get() else "disabled"
        for button in (self._cycle_prev_btn, self._cycle_next_btn, self._cycle_copy_checkbox):
            if button is not None:
                try:
                    button.configure(state=state)
                except Exception:
                    pass

    def _on_cycle_payload_toggle(self) -> None:
        value = bool(self._var_cycle_payload.get())
        try:
            if self._set_cycle_payload:
                self._set_cycle_payload(value)
            else:
                self._preferences.cycle_payload_ids = value
                self._preferences.save()
        except Exception as exc:
            self._status_var.set(f"Failed to update payload cycling: {exc}")
            self._var_cycle_payload.set(not value)
            self._preferences.cycle_payload_ids = bool(self._var_cycle_payload.get())
            self._update_cycle_button_state()
            return
        self._preferences.cycle_payload_ids = value
        self._update_cycle_button_state()

    def _on_cycle_copy_toggle(self) -> None:
        value = bool(self._var_cycle_copy.get())
        if not self._var_cycle_payload.get():  # Should not be reachable because checkbox disabled, but guard anyway.
            value = False
            self._var_cycle_copy.set(False)
        try:
            if self._set_cycle_payload_copy:
                self._set_cycle_payload_copy(value)
            else:
                self._preferences.copy_payload_id_on_cycle = value
                self._preferences.save()
        except Exception as exc:
            self._status_var.set(f"Failed to update copy-on-cycle setting: {exc}")
            self._var_cycle_copy.set(self._preferences.copy_payload_id_on_cycle)
            return
        self._preferences.copy_payload_id_on_cycle = value
        self._preferences.save()

    def _on_cycle_payload_prev(self) -> None:
        if not self._var_cycle_payload.get():
            return
        if self._cycle_prev_callback:
            try:
                self._cycle_prev_callback()
            except Exception as exc:
                self._status_var.set(f"Failed to cycle payload IDs: {exc}")

    def _on_cycle_payload_next(self) -> None:
        if not self._var_cycle_payload.get():
            return
        if self._cycle_next_callback:
            try:
                self._cycle_next_callback()
            except Exception as exc:
                self._status_var.set(f"Failed to cycle payload IDs: {exc}")

    def _on_restart_overlay(self) -> None:
        if self._restart_overlay is None:
            self._status_var.set("Overlay restart unavailable.")
            return
        try:
            self._restart_overlay()
        except Exception as exc:  # pragma: no cover - defensive UI handler
            self._status_var.set(f"Failed to restart overlay: {exc}")
            return
        self._status_var.set("Overlay restart requested.")

    def _on_force_render_toggle(self) -> None:
        value = bool(self._var_force_render.get())
        if self._set_force_render:
            try:
                self._set_force_render(value)
            except Exception as exc:
                self._status_var.set(f"Failed to update force-render option: {exc}")
                return
        else:
            self._preferences.force_render = value
            self._preferences.save()

    def _on_physical_clamp_toggle(self) -> None:
        self._preferences.physical_clamp_enabled = bool(self._var_physical_clamp.get())
        try:
            self._preferences.save()
        except Exception as exc:
            LOGGER.debug("Failed to persist physical clamp preference: %s", exc, exc_info=exc)

    def _on_physical_clamp_overrides_event(self, _event) -> None:  # pragma: no cover - Tk event
        self._on_physical_clamp_overrides_apply()

    def _on_physical_clamp_overrides_apply(self) -> None:
        errors: list[str] = []
        overrides = _coerce_physical_clamp_overrides(
            self._var_physical_clamp_overrides.get(),
            {},
            allow_empty=True,
            errors=errors,
        )
        self._preferences.physical_clamp_overrides = overrides
        try:
            self._preferences.save()
        except Exception as exc:
            LOGGER.debug("Failed to persist physical clamp overrides: %s", exc, exc_info=exc)
            self._status_var.set(f"Failed to save per-monitor clamp overrides: {exc}")
            return
        self._var_physical_clamp_overrides.set(_format_physical_clamp_overrides(overrides))
        if errors:
            self._status_var.set(f"Applied {len(overrides)} override(s); " + "; ".join(errors))
        else:
            self._status_var.set(f"Applied {len(overrides)} per-monitor override(s).")

    def _on_title_bar_toggle(self) -> None:
        enabled = bool(self._var_title_bar_enabled.get())
        height = self._apply_title_bar_height()
        self._preferences.title_bar_enabled = enabled
        if self._title_bar_height_spin is not None:
            if enabled:
                self._title_bar_height_spin.state(["!disabled"])
            else:
                self._title_bar_height_spin.state(["disabled"])
        if self._set_title_bar_config:
            try:
                self._set_title_bar_config(enabled, height)
            except Exception as exc:
                self._status_var.set(f"Failed to update title bar compensation: {exc}")
                return
        self._preferences.save()

    def _on_title_bar_height_command(self) -> None:
        self._apply_title_bar_height(update_remote=True)

    def _on_title_bar_height_event(self, _event) -> None:  # pragma: no cover - Tk event
        self._apply_title_bar_height(update_remote=True)

    def _apply_title_bar_height(self, update_remote: bool = False) -> int:
        try:
            value = int(self._var_title_bar_height.get())
        except Exception:
            value = self._preferences.title_bar_height
        value = max(0, value)
        self._var_title_bar_height.set(value)
        self._preferences.title_bar_height = value
        if update_remote and self._set_title_bar_config:
            try:
                self._set_title_bar_config(bool(self._var_title_bar_enabled.get()), value)
            except Exception as exc:
                self._status_var.set(f"Failed to update title bar height: {exc}")
                return value
        if update_remote:
            self._preferences.save()
        return value

    def _on_debug_overlay_toggle(self) -> None:
        value = bool(self._var_debug_overlay.get())
        self._preferences.show_debug_overlay = value
        if self._set_debug_overlay:
            try:
                self._set_debug_overlay(value)
            except Exception as exc:
                self._status_var.set(f"Failed to update debug overlay: {exc}")
                return
        self._preferences.save()

    def _on_gridlines_toggle(self) -> None:
        enabled = bool(self._var_gridlines_enabled.get())
        self._preferences.gridlines_enabled = enabled
        self._update_gridline_spacing_spin_state()
        if self._set_gridlines_enabled:
            try:
                self._set_gridlines_enabled(enabled)
            except Exception as exc:
                self._status_var.set(f"Failed to update gridlines: {exc}")
                return
        self._preferences.save()

    def _on_gridline_spacing_command(self) -> None:
        self._apply_gridline_spacing()

    def _on_gridline_spacing_event(self, _event) -> None:  # pragma: no cover - Tk event
        self._apply_gridline_spacing()

    def _apply_gridline_spacing(self) -> None:
        try:
            spacing = int(self._var_gridline_spacing.get())
        except (TypeError, ValueError):
            spacing = self._preferences.gridline_spacing
        spacing = max(10, spacing)
        self._var_gridline_spacing.set(spacing)
        self._preferences.gridline_spacing = spacing
        if self._set_gridline_spacing:
            try:
                self._set_gridline_spacing(spacing)
            except Exception as exc:
                self._status_var.set(f"Failed to update grid spacing: {exc}")
                return
        self._preferences.save()

    def _on_payload_nudge_toggle(self) -> None:
        enabled = bool(self._var_payload_nudge.get())
        self._preferences.nudge_overflow_payloads = enabled
        self._update_payload_gutter_spin_state()
        if self._set_payload_nudge:
            try:
                self._set_payload_nudge(enabled)
            except Exception as exc:
                self._status_var.set(f"Failed to update payload nudging: {exc}")
                self._var_payload_nudge.set(not enabled)
                self._preferences.nudge_overflow_payloads = bool(self._var_payload_nudge.get())
                self._update_payload_gutter_spin_state()
                return
        self._preferences.save()

    def _on_payload_gutter_command(self) -> None:
        self._apply_payload_gutter()

    def _on_payload_gutter_event(self, _event) -> None:  # pragma: no cover - Tk event
        self._apply_payload_gutter()

    def _apply_payload_gutter(self) -> None:
        try:
            gutter = int(self._var_payload_gutter.get())
        except (TypeError, ValueError):
            gutter = self._preferences.payload_nudge_gutter
        gutter = max(0, min(gutter, 500))
        self._var_payload_gutter.set(gutter)
        self._preferences.payload_nudge_gutter = gutter
        if self._set_payload_gutter:
            try:
                self._set_payload_gutter(gutter)
            except Exception as exc:
                self._status_var.set(f"Failed to update payload gutter: {exc}")
                return
        self._preferences.save()

        self._preferences.save()

    def _on_font_bounds_command(self) -> None:
        self._apply_font_bounds()

    def _on_font_bounds_event(self, _event) -> None:  # pragma: no cover - Tk event
        self._apply_font_bounds()

    def _on_font_bounds_trace(self, *_args) -> None:
        if self._font_bounds_apply_in_progress:
            return
        self._apply_font_bounds()

    def _on_font_step_command(self) -> None:
        self._apply_font_step()

    def _on_font_step_event(self, _event) -> None:  # pragma: no cover - Tk event
        self._apply_font_step()

    def _on_font_step_trace(self, *_args) -> None:
        if self._font_step_apply_in_progress:
            return
        self._apply_font_step()

    def _apply_font_bounds(self, update_remote: bool = True) -> None:
        if self._font_bounds_apply_in_progress:
            return
        self._font_bounds_apply_in_progress = True
        try:
            min_value = float(self._var_min_font.get())
        except (TypeError, ValueError):
            min_value = self._preferences.min_font_point
        try:
            max_value = float(self._var_max_font.get())
        except (TypeError, ValueError):
            max_value = self._preferences.max_font_point
        min_value = max(1.0, min(min_value, 48.0))
        max_value = max(min_value, min(max_value, 72.0))
        self._var_min_font.set(min_value)
        self._var_max_font.set(max_value)
        callback_failed = False
        if update_remote and self._set_font_min:
            try:
                self._set_font_min(min_value)
            except Exception as exc:
                self._status_var.set(f"Failed to update minimum font size: {exc}")
                callback_failed = True
        if update_remote and self._set_font_max:
            try:
                self._set_font_max(max_value)
            except Exception as exc:
                self._status_var.set(f"Failed to update maximum font size: {exc}")
                callback_failed = True
        if callback_failed:
            self._font_bounds_apply_in_progress = False
            return
        self._preferences.min_font_point = min_value
        self._preferences.max_font_point = max_value
        self._preferences.save()
        self._font_bounds_apply_in_progress = False

    def _apply_font_step(self, update_remote: bool = True) -> None:
        if self._font_step_apply_in_progress:
            return
        self._font_step_apply_in_progress = True
        try:
            step_value = int(self._var_legacy_font_step.get())
        except (TypeError, ValueError):
            step_value = int(self._preferences.legacy_font_step)
        step_value = max(0, min(step_value, 10))
        self._var_legacy_font_step.set(step_value)
        if update_remote and self._set_font_step:
            try:
                self._set_font_step(step_value)
            except Exception as exc:
                self._status_var.set(f"Failed to update font step: {exc}")
                self._font_step_apply_in_progress = False
                return
        self._preferences.legacy_font_step = step_value
        self._preferences.save()
        self._font_step_apply_in_progress = False

    def _on_font_preview(self) -> None:
        if not self._preview_font_sizes:
            self._status_var.set("Overlay not running; preview unavailable.")
            return
        try:
            self._preview_font_sizes()
        except Exception as exc:  # pragma: no cover - defensive UI handler
            self._status_var.set(f"Preview failed: {exc}")
            return
        self._status_var.set("Font size preview sent to overlay.")

    def _on_send_click(self) -> None:
        message = self._test_var.get().strip()
        if not message:
            self._status_var.set("Enter a test message first.")
            return
        if not self._send_test:
            self._status_var.set("Overlay not running; message not sent.")
            return
        x_raw = self._test_x_var.get().strip()
        y_raw = self._test_y_var.get().strip()
        x_val: Optional[int] = None
        y_val: Optional[int] = None
        if x_raw or y_raw:
            if not x_raw or not y_raw:
                self._status_var.set("Provide both X and Y coordinates or leave both blank.")
                return
            try:
                x_val = max(0, int(float(x_raw)))
            except (TypeError, ValueError):
                self._status_var.set("X coordinate must be a number.")
                return
            try:
                y_val = max(0, int(float(y_raw)))
            except (TypeError, ValueError):
                self._status_var.set("Y coordinate must be a number.")
                return
            self._test_x_var.set(str(x_val))
            self._test_y_var.set(str(y_val))
        try:
            if x_val is None or y_val is None:
                self._send_test(message, None, None)  # type: ignore[arg-type]
            else:
                self._send_test(message, x_val, y_val)
        except Exception as exc:  # pragma: no cover - defensive UI handler
            self._status_var.set(f"Failed to send message: {exc}")
            return
        if x_val is None or y_val is None:
            self._status_var.set("Test message sent to overlay.")
        else:
            self._status_var.set(f"Test message sent to overlay at ({x_val}, {y_val}).")

    def _legacy_overlay(self):
        if self._legacy_client is None:
            try:
                from EDMCOverlay import edmcoverlay
            except ImportError:
                self._status_var.set("Legacy API not available.")
                return None
            self._legacy_client = edmcoverlay.Overlay()
        return self._legacy_client

    def _on_legacy_text(self) -> None:
        overlay = self._legacy_overlay()
        if overlay is None:
            return
        message = self._test_var.get().strip() or "Hello from edmcoverlay"
        try:
            overlay.send_message(f"{OVERLAY_ID_PREFIX}test", message, "#80d0ff", 60, 120, ttl=5, size="large")
        except Exception as exc:
            self._status_var.set(f"Legacy text failed: {exc}")
            return
        self._status_var.set("Legacy text sent via edmcoverlay API.")

    def _on_legacy_emoji(self) -> None:
        overlay = self._legacy_overlay()
        if overlay is None:
            return
        try:
            overlay.send_message(
                f"{OVERLAY_ID_PREFIX}test-emoji",
                "\N{memo}",
                "#80d0ff",
                60,
                120,
                ttl=5,
                size="large",
            )
        except Exception as exc:
            self._status_var.set(f"Legacy emoji failed: {exc}")
            return
        self._status_var.set("Legacy emoji sent via edmcoverlay API.")

    def _on_legacy_rect(self) -> None:
        overlay = self._legacy_overlay()
        if overlay is None:
            return
        try:
            overlay.send_shape(
                f"{OVERLAY_ID_PREFIX}test-rect",
                "rect",
                "#80d0ff",
                "#20004080",
                40,
                80,
                400,
                120,
                ttl=5,
            )
        except Exception as exc:
            self._status_var.set(f"Legacy rectangle failed: {exc}")
            return
        self._status_var.set("Legacy rectangle sent via edmcoverlay API.")
