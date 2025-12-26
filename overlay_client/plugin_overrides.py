"""Plugin-specific override support for Modern Overlay payload rendering."""
from __future__ import annotations

# ruff: noqa: E402

import json
import math
import time
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path
import sys
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Tuple

OVERLAY_ROOT = Path(__file__).resolve().parents[1]
if str(OVERLAY_ROOT) not in sys.path:
    sys.path.insert(0, str(OVERLAY_ROOT))

from prefix_entries import PrefixEntry, parse_prefix_entries

from overlay_client.debug_config import DebugConfig
from overlay_plugin.overlay_api import PluginGroupingError, _normalise_background_color, _normalise_border_width


JsonDict = Dict[str, Any]

_ANCHOR_OPTIONS = {"nw", "ne", "sw", "se", "center", "top", "bottom", "left", "right"}
_PAYLOAD_JUSTIFICATION_CHOICES = {"left", "center", "right"}
_DEFAULT_PAYLOAD_JUSTIFICATION = "left"
_MARKER_LABEL_POSITION_CHOICES = {"below", "above", "centered"}
_DEFAULT_MARKER_LABEL_POSITION = "below"
_CONTROLLER_PREVIEW_BOX_MODE_CHOICES = {"last", "max"}
_DEFAULT_CONTROLLER_PREVIEW_BOX_MODE = "last"


@dataclass
class _GroupSpec:
    label: Optional[str]
    prefixes: Tuple[PrefixEntry, ...]
    defaults: Optional[JsonDict]
    anchor: Optional[str] = None
    offset_x: float = 0.0
    offset_y: float = 0.0
    payload_justification: str = _DEFAULT_PAYLOAD_JUSTIFICATION
    marker_label_position: str = _DEFAULT_MARKER_LABEL_POSITION
    controller_preview_box_mode: str = _DEFAULT_CONTROLLER_PREVIEW_BOX_MODE
    background_color: Optional[str] = None
    background_border_color: Optional[str] = None
    background_border_width: Optional[int] = None


@dataclass
class _PluginConfig:
    name: str
    canonical_name: str
    match_id_prefixes: Tuple[str, ...]
    overrides: List[Tuple[str, JsonDict]]
    plugin_defaults: Optional[JsonDict]
    group_specs: Tuple[_GroupSpec, ...]


class PluginOverrideManager:
    """Load and apply plugin-specific rendering overrides."""

    def __init__(
        self,
        config_path: Path,
        logger,
        debug_config: Optional[DebugConfig] = None,
        groupings_loader: Optional[Any] = None,
    ) -> None:
        self._path = config_path
        self._logger = logger
        self._groupings_loader = groupings_loader
        self._mtime: Optional[float] = None
        self._plugins: Dict[str, _PluginConfig] = {}
        self._debug_config = debug_config or DebugConfig()
        self._diagnostic_spans: Dict[Tuple[str, str], Tuple[float, float, float]] = {}
        self._generation: int = 0
        self._loader_loaded = False
        self._controller_override_frozen: bool = False
        self._controller_active_nonce: str = ""
        self._controller_active_nonce_ts: float = 0.0
        self._loaded_override_nonce: str = ""
        self._last_reload_ts: float = 0.0
        self._load_config()

    def apply_override_payload(self, payload: Optional[Mapping[str, Any]], nonce: str) -> None:
        """Apply overrides directly from payload when nonce matches controller."""

        if payload is None or not isinstance(payload, Mapping):
            return
        incoming_nonce = str(nonce or "").strip()
        try:
            if incoming_nonce:
                self._controller_active_nonce = incoming_nonce
                self._controller_active_nonce_ts = time.time()
        except Exception:
            pass
        self._load_config_data(payload, mtime=time.time())

    # ------------------------------------------------------------------
    # Public API

    @staticmethod
    def _canonical_plugin_name(name: Optional[str]) -> Optional[str]:
        if not isinstance(name, str):
            return None
        token = name.strip()
        if not token:
            return None
        return token.casefold()

    def apply(self, payload: MutableMapping[str, Any]) -> None:
        """Apply overrides to the payload in-place when configured."""

        if not isinstance(payload, MutableMapping):
            return

        self._reload_if_needed()

        plugin_name = self._determine_plugin_name(payload)
        if plugin_name is None:
            return

        config = self._plugins.get(plugin_name)
        if config is None:
            return

        message_id = str(payload.get("id") or "")
        display_name = config.name

        if config.plugin_defaults:
            trace_defaults = self._should_trace(display_name, message_id)
            if trace_defaults:
                self._log_trace(display_name, message_id, "before_defaults", payload)
            self._apply_override(
                display_name,
                "defaults",
                config.plugin_defaults,
                payload,
                trace=trace_defaults,
                message_id=message_id,
            )
            if trace_defaults:
                self._log_trace(display_name, message_id, "after_defaults", payload)

        group_defaults = self._group_defaults_for(config, message_id)
        if group_defaults is not None:
            label, defaults = group_defaults
            trace_group = self._should_trace(display_name, message_id)
            if trace_group:
                self._log_trace(display_name, message_id, f"group:{label}:before", payload)
            self._apply_override(
                display_name,
                f"group:{label}",
                defaults,
                payload,
                trace=trace_group,
                message_id=message_id,
            )
            if trace_group:
                self._log_trace(display_name, message_id, f"group:{label}:after", payload)

        if not message_id:
            return

        selected = self._select_override(config, message_id)
        if selected is None:
            return

        pattern, override = selected
        if override is None:
            return

        if payload.get("shape") == "vect":
            points = payload.get("vector")
            if isinstance(points, list):
                xs = [float(pt.get("x", 0)) for pt in points if isinstance(pt, Mapping) and isinstance(pt.get("x"), (int, float))]
                if xs:
                    min_x = min(xs)
                    max_x = max(xs)
                    center_x = (min_x + max_x) / 2.0
                    key = (config.canonical_name, message_id.split("-")[0])
                    if key not in self._diagnostic_spans:
                        self._logger.info(
                            "override-diagnostic plugin=%s id=%s min_x=%.2f max_x=%.2f center=%.2f span=%.2f",
                            display_name,
                            message_id,
                            min_x,
                            max_x,
                            center_x,
                            max_x - min_x,
                        )
                        self._diagnostic_spans[key] = (min_x, max_x, center_x)

        trace_active = self._should_trace(display_name, message_id)
        if trace_active:
            self._log_trace(display_name, message_id, "before_override", payload)
        self._apply_override(
            display_name,
            pattern,
            override,
            payload,
            trace=trace_active,
            message_id=message_id,
        )
        if trace_active:
            self._log_trace(display_name, message_id, "after_override", payload)

    # ------------------------------------------------------------------
    # Internal helpers

    def _reload_if_needed(self) -> None:
        if self._groupings_loader is not None:
            try:
                if not self._loader_loaded:
                    self._groupings_loader.load()
                    self._loader_loaded = True
                    changed = True
                else:
                    changed = bool(self._groupings_loader.reload_if_changed())
            except Exception as exc:  # pragma: no cover - defensive guard
                self._logger.warning("Failed to reload overrides via loader: %s", exc)
                return
            if not changed and self._mtime is not None:
                return
            self._load_config_from_loader()
            return

        try:
            stat = self._path.stat()
        except FileNotFoundError:
            if self._mtime is not None:
                self._logger.info("Plugin override file %s no longer present; disabling overrides.", self._path)
            self._mtime = None
            self._plugins.clear()
            return

        if self._mtime is not None and stat.st_mtime <= self._mtime:
            return

        self._load_config()

    def _load_config(self) -> None:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            self._plugins.clear()
            self._mtime = None
            self._logger.debug("Plugin override file %s not found; continuing without overrides.", self._path)
            return
        except json.JSONDecodeError as exc:
            self._logger.warning("Failed to parse plugin override file %s: %s", self._path, exc)
            return

        self._load_config_data(raw, mtime=self._path.stat().st_mtime if self._path.exists() else None)

    def _load_config_from_loader(self) -> None:
        try:
            raw = self._groupings_loader.merged()
        except Exception as exc:
            self._logger.warning("Failed to load overrides from loader: %s", exc)
            return
        diag = self._groupings_loader.diagnostics() if self._groupings_loader else {}
        mtime = diag.get("last_reload_ts", None) if isinstance(diag, Mapping) else None
        self._load_config_data(raw, mtime=mtime)

    def _load_config_data(self, raw: Any, mtime: Optional[float]) -> None:
        if not isinstance(raw, Mapping):
            self._logger.warning("Plugin override config must contain a JSON object at the top level.")
            return
        controller_nonce = None
        try:
            controller_nonce = str(raw.get("_edit_nonce", "")).strip()
        except Exception:
            controller_nonce = None
        active_nonce = getattr(self, "_controller_active_nonce", "")
        if active_nonce:
            if not controller_nonce or controller_nonce != active_nonce:
                self._logger.debug("Override reload skipped: nonce mismatch (controller=%s file=%s)", active_nonce, controller_nonce or "<missing>")
                return

        plugins: Dict[str, _PluginConfig] = {}
        for plugin_name, plugin_payload in raw.items():
            if not isinstance(plugin_name, str) or not isinstance(plugin_payload, Mapping):
                continue
            canonical_name = self._canonical_plugin_name(plugin_name)
            if canonical_name is None:
                continue

            match_prefixes: List[str] = []

            def _extend_match_prefixes(raw: Any) -> None:
                if isinstance(raw, str):
                    candidates = [raw]
                elif isinstance(raw, Iterable):
                    candidates = [entry for entry in raw if isinstance(entry, str)]
                else:
                    candidates = []
                for value in candidates:
                    token = value.strip()
                    if not token:
                        continue
                    prefix = token.casefold()
                    if prefix not in match_prefixes:
                        match_prefixes.append(prefix)

            _extend_match_prefixes(plugin_payload.get("matchingPrefixes"))

            if not match_prefixes:
                match_section = plugin_payload.get("__match__")
                if isinstance(match_section, Mapping):
                    _extend_match_prefixes(match_section.get("id_prefixes"))

            grouping_specs: List[_GroupSpec] = []
            group_prefix_hints: List[str] = []

            def _clean_group_prefixes(raw_value: Any) -> Tuple[PrefixEntry, ...]:
                entries = parse_prefix_entries(raw_value)
                return tuple(entries)

            def _parse_anchor(source: Mapping[str, Any]) -> Optional[str]:
                anchor_field = source.get("idPrefixGroupAnchor") or source.get("anchor")
                if isinstance(anchor_field, str) and anchor_field.strip():
                    return anchor_field.strip()
                legacy_block = source.get("preserve_fill_aspect")
                if isinstance(legacy_block, Mapping):
                    legacy_anchor = legacy_block.get("anchor")
                    if isinstance(legacy_anchor, str) and legacy_anchor.strip():
                        return legacy_anchor.strip()
                return None

            def _parse_offset_value(value: Any) -> Optional[float]:
                if isinstance(value, (int, float)):
                    numeric = float(value)
                    if math.isfinite(numeric):
                        return numeric
                return None

            def _parse_offsets(source: Mapping[str, Any]) -> Tuple[float, float]:
                dx = _parse_offset_value(source.get("offsetX") or source.get("offset_x"))
                dy = _parse_offset_value(source.get("offsetY") or source.get("offset_y"))
                return (dx if dx is not None else 0.0, dy if dy is not None else 0.0)

            def _parse_payload_justification(source: Mapping[str, Any]) -> str:
                raw_value = source.get("payloadJustification") or source.get("payload_justification")
                if isinstance(raw_value, str):
                    token = raw_value.strip().lower()
                    if token in _PAYLOAD_JUSTIFICATION_CHOICES:
                        return token
                return _DEFAULT_PAYLOAD_JUSTIFICATION

            def _parse_marker_label_position(source: Mapping[str, Any]) -> str:
                raw_value = source.get("markerLabelPosition") or source.get("marker_label_position")
                if isinstance(raw_value, str):
                    token = raw_value.strip().lower()
                    if token in _MARKER_LABEL_POSITION_CHOICES:
                        return token
                return _DEFAULT_MARKER_LABEL_POSITION

            def _parse_controller_preview_box_mode(source: Mapping[str, Any]) -> str:
                raw_value = source.get("controllerPreviewBoxMode") or source.get("controller_preview_box_mode")
                if isinstance(raw_value, str):
                    token = raw_value.strip().lower()
                    if token in _CONTROLLER_PREVIEW_BOX_MODE_CHOICES:
                        return token
                return _DEFAULT_CONTROLLER_PREVIEW_BOX_MODE

            def _parse_background_fields(
                source: Mapping[str, Any],
            ) -> Tuple[Optional[str], Optional[str], Optional[int]]:
                color: Optional[str] = None
                border_color: Optional[str] = None
                border: Optional[int] = None
                if "backgroundColor" in source:
                    raw_color = source.get("backgroundColor")
                    if raw_color is None:
                        color = None
                    else:
                        try:
                            color = _normalise_background_color(raw_color)
                        except PluginGroupingError:
                            color = None
                if "backgroundBorderColor" in source:
                    raw_border_color = source.get("backgroundBorderColor")
                    if raw_border_color is None:
                        border_color = None
                    else:
                        try:
                            border_color = _normalise_background_color(raw_border_color)
                        except PluginGroupingError:
                            border_color = None
                if "backgroundBorderWidth" in source:
                    raw_border = source.get("backgroundBorderWidth")
                    if raw_border is None:
                        border = None
                    else:
                        try:
                            border = _normalise_border_width(raw_border, "backgroundBorderWidth")
                        except PluginGroupingError:
                            border = None
                return color, border_color, border

            def _append_group_spec(
                label: Optional[str],
                prefixes: Tuple[str, ...],
                anchor: Optional[str],
                offset_x: float,
                offset_y: float,
                payload_justification: str,
                marker_label_position: str,
                controller_preview_box_mode: str,
                background_color: Optional[str],
                background_border_color: Optional[str],
                background_border_width: Optional[int],
            ) -> None:
                if not prefixes:
                    return
                grouping_specs.append(
                    _GroupSpec(
                        label=label,
                        prefixes=prefixes,
                        defaults=None,
                        anchor=anchor,
                        offset_x=offset_x,
                        offset_y=offset_y,
                        payload_justification=payload_justification,
                        marker_label_position=marker_label_position,
                        controller_preview_box_mode=controller_preview_box_mode,
                        background_color=background_color,
                        background_border_color=background_border_color,
                        background_border_width=background_border_width,
                    )
                )
                for entry in prefixes:
                    value_cf = entry.value.casefold()
                    if value_cf not in group_prefix_hints:
                        group_prefix_hints.append(value_cf)

            id_prefix_groups = plugin_payload.get("idPrefixGroups")
            if isinstance(id_prefix_groups, Mapping):
                for label, group_value in id_prefix_groups.items():
                    if not isinstance(group_value, Mapping):
                        continue
                    cleaned_prefixes = _clean_group_prefixes(
                        group_value.get("idPrefixes") or group_value.get("id_prefixes")
                    )
                    anchor_token = _parse_anchor(group_value)
                    label_value = str(label).strip() if isinstance(label, str) and label else None
                    offset_x, offset_y = _parse_offsets(group_value)
                    justification_token = _parse_payload_justification(group_value)
                    marker_label_position = _parse_marker_label_position(group_value)
                    controller_preview_box_mode = _parse_controller_preview_box_mode(group_value)
                    background_color, background_border_color, background_border_width = _parse_background_fields(
                        group_value
                    )
                    _append_group_spec(
                        label_value,
                        cleaned_prefixes,
                        anchor_token,
                        offset_x,
                        offset_y,
                        justification_token,
                        marker_label_position,
                        controller_preview_box_mode,
                        background_color,
                        background_border_color,
                        background_border_width,
                    )

            grouping_section = plugin_payload.get("grouping")
            if isinstance(grouping_section, Mapping):
                groups_spec = grouping_section.get("groups")
                if isinstance(groups_spec, Mapping):
                    for label, group_value in groups_spec.items():
                        if not isinstance(group_value, Mapping):
                            continue
                        cleaned_prefixes = _clean_group_prefixes(group_value.get("id_prefixes"))
                        if not cleaned_prefixes:
                            cleaned_prefixes = _clean_group_prefixes(group_value.get("prefix"))
                        anchor_token = _parse_anchor(group_value)
                        label_value = str(label).strip() if isinstance(label, str) and label else None
                        offset_x, offset_y = _parse_offsets(group_value)
                        justification_token = _parse_payload_justification(group_value)
                        marker_label_position = _parse_marker_label_position(group_value)
                        controller_preview_box_mode = _parse_controller_preview_box_mode(group_value)
                        background_color, background_border_color, background_border_width = _parse_background_fields(
                            group_value
                        )
                        _append_group_spec(
                            label_value,
                            cleaned_prefixes,
                            anchor_token,
                            offset_x,
                            offset_y,
                            justification_token,
                            marker_label_position,
                            controller_preview_box_mode,
                            background_color,
                            background_border_color,
                            background_border_width,
                        )

                prefixes_spec = grouping_section.get("prefixes")
                if isinstance(prefixes_spec, Mapping):
                    for label, prefix_value in prefixes_spec.items():
                        prefixes: Tuple[str, ...] = ()
                        anchor_token: Optional[str] = None
                        label_value: Optional[str] = None
                        offset_x = 0.0
                        offset_y = 0.0
                        if isinstance(prefix_value, str):
                            prefixes = _clean_group_prefixes(prefix_value)
                            label_value = str(label).strip() if isinstance(label, str) and label else prefix_value
                            justification_token = _DEFAULT_PAYLOAD_JUSTIFICATION
                            marker_label_position = _DEFAULT_MARKER_LABEL_POSITION
                            controller_preview_box_mode = _DEFAULT_CONTROLLER_PREVIEW_BOX_MODE
                            background_color, background_border_color, background_border_width = _parse_background_fields(
                                {}
                            )
                        elif isinstance(prefix_value, Mapping):
                            prefixes = _clean_group_prefixes(prefix_value.get("prefix"))
                            label_value = str(label).strip() if isinstance(label, str) and label else None
                            anchor_token = _parse_anchor(prefix_value)
                            offset_x, offset_y = _parse_offsets(prefix_value)
                            justification_token = _parse_payload_justification(prefix_value)
                            marker_label_position = _parse_marker_label_position(prefix_value)
                            controller_preview_box_mode = _parse_controller_preview_box_mode(prefix_value)
                            background_color, background_border_color, background_border_width = _parse_background_fields(
                                prefix_value
                            )
                        else:
                            justification_token = _DEFAULT_PAYLOAD_JUSTIFICATION
                            marker_label_position = _DEFAULT_MARKER_LABEL_POSITION
                            controller_preview_box_mode = _DEFAULT_CONTROLLER_PREVIEW_BOX_MODE
                            background_color, background_border_color, background_border_width = _parse_background_fields(
                                {}
                            )
                        _append_group_spec(
                            label_value,
                            prefixes,
                            anchor_token,
                            offset_x,
                            offset_y,
                            justification_token,
                            marker_label_position,
                            controller_preview_box_mode,
                            background_color,
                            background_border_color,
                            background_border_width,
                        )
                elif isinstance(prefixes_spec, Iterable):
                    for entry in prefixes_spec:
                        if isinstance(entry, str) and entry:
                            cleaned_entry = entry.casefold()
                            background_color, background_border_color, background_border_width = _parse_background_fields(
                                {}
                            )
                            _append_group_spec(
                                entry,
                                (cleaned_entry,),
                                None,
                                0.0,
                                0.0,
                                _DEFAULT_PAYLOAD_JUSTIFICATION,
                                _DEFAULT_MARKER_LABEL_POSITION,
                                _DEFAULT_CONTROLLER_PREVIEW_BOX_MODE,
                                background_color,
                                background_border_color,
                                background_border_width,
                            )

            if group_prefix_hints:
                for prefix in group_prefix_hints:
                    if prefix not in match_prefixes:
                        match_prefixes.append(prefix)

            overrides: List[Tuple[str, JsonDict]] = []
            plugin_defaults: JsonDict = {}
            for key, spec in plugin_payload.items():
                if key == "notes":
                    continue
                if key == "grouping":
                    continue
                if key == "idPrefixGroups":
                    continue
                if key == "matchingPrefixes":
                    continue
                if not isinstance(spec, Mapping) or key.startswith("__"):
                    continue
                overrides.append((str(key), dict(spec)))

            plugins[canonical_name] = _PluginConfig(
                name=plugin_name,
                canonical_name=canonical_name,
                match_id_prefixes=tuple(match_prefixes),
                overrides=overrides,
                plugin_defaults=plugin_defaults or None,
                group_specs=tuple(grouping_specs),
            )

        self._plugins = plugins
        self._diagnostic_spans.clear()
        self._mtime = mtime if mtime is not None else (self._path.stat().st_mtime if self._path.exists() else None)
        if controller_nonce:
            self._loaded_override_nonce = controller_nonce
        elif active_nonce and not self._loaded_override_nonce:
            self._loaded_override_nonce = active_nonce
        reload_ts = time.time()
        if isinstance(mtime, (int, float)) and mtime > 0.0:
            reload_ts = float(mtime)
        self._last_reload_ts = reload_ts
        self._logger.debug(
            "Loaded %d plugin override configuration(s) from %s.",
            len(self._plugins),
            self._path,
        )
        self._generation += 1

    @property
    def generation(self) -> int:
        return self._generation

    def current_override_nonce(self) -> str:
        if self._controller_active_nonce:
            return self._controller_active_nonce
        if self._loaded_override_nonce:
            return self._loaded_override_nonce
        return ""

    def override_generation_timestamp(self) -> float:
        return float(self._last_reload_ts or 0.0)

    def force_reload(self) -> None:
        """Forcefully reload the override configuration from disk."""
        self._mtime = None
        self._load_config()

    def infer_plugin_name(self, payload: Mapping[str, Any]) -> Optional[str]:
        """Best-effort plugin lookup without mutating the payload."""

        if not isinstance(payload, Mapping):
            return None
        self._reload_if_needed()
        canonical = self._determine_plugin_name(payload)
        if canonical is None:
            return None
        config = self._plugins.get(canonical)
        return config.name if config else canonical

    def _config_for_payload_id(self, payload_id: str) -> Optional[_PluginConfig]:
        if not isinstance(payload_id, str) or not payload_id:
            return None
        payload_cf = payload_id.casefold()
        for config in self._plugins.values():
            if not config.match_id_prefixes:
                continue
            if any(payload_cf.startswith(prefix) for prefix in config.match_id_prefixes):
                return config
        return None

    def grouping_label_for_id(self, payload_id: str) -> Optional[str]:
        """Return the first matching grouping label for a payload id, if any."""

        config = self._config_for_payload_id(payload_id)
        if config is None:
            return None
        payload_cf = payload_id.casefold()
        for spec in config.group_specs:
            for entry in spec.prefixes:
                prefix = entry.value.casefold()
                if payload_cf.startswith(prefix):
                    return spec.label
        return None

    def _determine_plugin_name(self, payload: Mapping[str, Any]) -> Optional[str]:
        for key in ("plugin", "plugin_name", "source_plugin"):
            value = payload.get(key)
            canonical = self._canonical_plugin_name(value)
            if canonical:
                return canonical

        meta = payload.get("meta")
        if isinstance(meta, Mapping):
            for key in ("plugin", "plugin_name", "source_plugin"):
                canonical = self._canonical_plugin_name(meta.get(key))
                if canonical:
                    return canonical

        raw = payload.get("raw")
        if isinstance(raw, Mapping):
            for key in ("plugin", "plugin_name", "source_plugin"):
                canonical = self._canonical_plugin_name(raw.get(key))
                if canonical:
                    return canonical

        item_id = str(payload.get("id") or "")
        if not item_id:
            return None

        item_id_cf = item_id.casefold()

        for name, config in self._plugins.items():
            if not config.match_id_prefixes:
                continue
            if any(item_id_cf.startswith(prefix) for prefix in config.match_id_prefixes):
                return name

        return None

    def _select_override(self, config: _PluginConfig, message_id: str) -> Optional[Tuple[str, JsonDict]]:
        message_id_cf = message_id.casefold()
        for pattern, spec in config.overrides:
            if fnmatchcase(message_id, pattern):
                return pattern, spec
            if fnmatchcase(message_id_cf, pattern.casefold()):
                return pattern, spec
        return None

    def _group_defaults_for(self, config: _PluginConfig, message_id: str) -> Optional[Tuple[str, JsonDict]]:
        if not config.group_specs:
            return None
        if not message_id:
            return None
        spec = self._select_group_spec(config, message_id)
        if spec is None:
            return None
        label_value = spec.label or (spec.prefixes[0].value if spec.prefixes else "")
        if spec.defaults:
            return label_value, dict(spec.defaults)
        return None

    @staticmethod
    def _match_prefix_score(prefixes: Sequence[PrefixEntry], payload_cf: str) -> Optional[Tuple[int, int]]:
        best: Optional[Tuple[int, int]] = None
        for entry in prefixes:
            if entry.match_mode == "exact":
                if payload_cf != entry.value_cf:
                    continue
                score = (2, len(entry.value))
            else:
                if not payload_cf.startswith(entry.value_cf):
                    continue
                score = (1, len(entry.value))
            if best is None or score > best:
                best = score
        return best

    def _select_group_spec(self, config: _PluginConfig, payload_id: str) -> Optional[_GroupSpec]:
        if not config.group_specs or not payload_id:
            return None
        payload_cf = payload_id.casefold()
        best: Optional[Tuple[int, int, int]] = None
        selected: Optional[_GroupSpec] = None
        for order, spec in enumerate(config.group_specs):
            score = self._match_prefix_score(spec.prefixes, payload_cf)
            if score is None:
                continue
            candidate = (score[0], score[1], -order)
            if best is None or candidate > best:
                best = candidate
                selected = spec
        return selected

    def grouping_key_for(self, plugin: Optional[str], payload_id: Optional[str]) -> Optional[Tuple[str, Optional[str]]]:
        self._reload_if_needed()
        config: Optional[_PluginConfig] = None
        plugin_label: Optional[str] = None

        canonical = self._canonical_plugin_name(plugin)
        if canonical is not None:
            config = self._plugins.get(canonical)
            if config is not None:
                plugin_label = config.name

        if config is None and isinstance(payload_id, str) and payload_id:
            config = self._config_for_payload_id(payload_id)
            if config is not None:
                plugin_label = config.name

        if config is None or plugin_label is None or not config.group_specs:
            return None

        if not isinstance(payload_id, str) or not payload_id:
            return plugin_label, None

        spec = self._select_group_spec(config, payload_id)
        if spec is None:
            return plugin_label, None
        label_value = spec.label or (spec.prefixes[0].value if spec.prefixes else None)
        return plugin_label, label_value

    def group_is_configured(self, plugin: Optional[str], suffix: Optional[str]) -> bool:
        self._reload_if_needed()
        canonical = self._canonical_plugin_name(plugin)
        if canonical is None:
            return False
        config = self._plugins.get(canonical)
        if config is None or not config.group_specs:
            return False
        if suffix is None:
            return False
        for spec in config.group_specs:
            label_value = spec.label or (spec.prefixes[0].value if spec.prefixes else None)
            if label_value == suffix:
                return True
        return False

    def group_offsets(self, plugin: Optional[str], suffix: Optional[str]) -> Tuple[float, float]:
        self._reload_if_needed()
        canonical = self._canonical_plugin_name(plugin)
        if canonical is None:
            return 0.0, 0.0
        config = self._plugins.get(canonical)
        if config is None or not config.group_specs or suffix is None:
            return 0.0, 0.0
        for spec in config.group_specs:
            label_value = spec.label or (spec.prefixes[0].value if spec.prefixes else None)
            if label_value == suffix:
                return spec.offset_x, spec.offset_y
        return 0.0, 0.0

    def group_background(
        self, plugin: Optional[str], suffix: Optional[str]
    ) -> Tuple[Optional[str], Optional[str], Optional[int]]:
        self._reload_if_needed()
        canonical = self._canonical_plugin_name(plugin)
        if canonical is None or suffix is None:
            return None, None
        config = self._plugins.get(canonical)
        if config is None or not config.group_specs:
            return None, None
        for spec in config.group_specs:
            label_value = spec.label or (spec.prefixes[0].value if spec.prefixes else None)
            if label_value == suffix:
                border = spec.background_border_width
                if isinstance(border, bool):
                    border = int(bool(border))
                if isinstance(border, (int, float)):
                    try:
                        border_int = int(border)
                    except Exception:
                        border_int = None
                else:
                    border_int = None
                return spec.background_color, spec.background_border_color, border_int
        return None, None, None

    def group_payload_justification(self, plugin: Optional[str], suffix: Optional[str]) -> str:
        self._reload_if_needed()
        canonical = self._canonical_plugin_name(plugin)
        if canonical is None:
            return _DEFAULT_PAYLOAD_JUSTIFICATION
        config = self._plugins.get(canonical)
        if config is None or not config.group_specs or suffix is None:
            return _DEFAULT_PAYLOAD_JUSTIFICATION
        for spec in config.group_specs:
            label_value = spec.label or (spec.prefixes[0].value if spec.prefixes else None)
            if label_value == suffix:
                token = spec.payload_justification or _DEFAULT_PAYLOAD_JUSTIFICATION
                if token not in _PAYLOAD_JUSTIFICATION_CHOICES:
                    return _DEFAULT_PAYLOAD_JUSTIFICATION
                return token
        return _DEFAULT_PAYLOAD_JUSTIFICATION

    def group_marker_label_position(self, plugin: Optional[str], suffix: Optional[str]) -> str:
        self._reload_if_needed()
        canonical = self._canonical_plugin_name(plugin)
        if canonical is None:
            return _DEFAULT_MARKER_LABEL_POSITION
        config = self._plugins.get(canonical)
        if config is None or not config.group_specs or suffix is None:
            return _DEFAULT_MARKER_LABEL_POSITION
        for spec in config.group_specs:
            label_value = spec.label or (spec.prefixes[0].value if spec.prefixes else None)
            if label_value == suffix:
                token = spec.marker_label_position or _DEFAULT_MARKER_LABEL_POSITION
                if token not in _MARKER_LABEL_POSITION_CHOICES:
                    return _DEFAULT_MARKER_LABEL_POSITION
                return token
        return _DEFAULT_MARKER_LABEL_POSITION

    def group_controller_preview_box_mode(self, plugin: Optional[str], suffix: Optional[str]) -> str:
        self._reload_if_needed()
        canonical = self._canonical_plugin_name(plugin)
        if canonical is None:
            return _DEFAULT_CONTROLLER_PREVIEW_BOX_MODE
        config = self._plugins.get(canonical)
        if config is None or not config.group_specs or suffix is None:
            return _DEFAULT_CONTROLLER_PREVIEW_BOX_MODE
        for spec in config.group_specs:
            label_value = spec.label or (spec.prefixes[0].value if spec.prefixes else None)
            if label_value == suffix:
                token = spec.controller_preview_box_mode or _DEFAULT_CONTROLLER_PREVIEW_BOX_MODE
                if token not in _CONTROLLER_PREVIEW_BOX_MODE_CHOICES:
                    return _DEFAULT_CONTROLLER_PREVIEW_BOX_MODE
                return token
        return _DEFAULT_CONTROLLER_PREVIEW_BOX_MODE

    def group_preserve_fill_aspect(self, plugin: Optional[str], suffix: Optional[str]) -> Tuple[bool, str]:
        """Fill-mode preservation is always enabled; anchor selection is derived from overrides."""

        self._reload_if_needed()
        canonical = self._canonical_plugin_name(plugin)
        anchor_token: Optional[str] = None
        if canonical is not None:
            config = self._plugins.get(canonical)
            if config is not None and suffix is not None:
                for spec in config.group_specs:
                    label_value = spec.label or (spec.prefixes[0].value if spec.prefixes else None)
                    if label_value == suffix:
                        anchor_token = spec.anchor
                        break
        return True, self._normalise_anchor_token(anchor_token)

    @staticmethod
    def _normalise_anchor_token(anchor: Optional[str]) -> str:
        if not isinstance(anchor, str):
            return "nw"
        token = anchor.strip().lower()
        if not token:
            return "nw"
        if token == "first":
            token = "nw"
        elif token == "centroid":
            token = "center"
        if token not in _ANCHOR_OPTIONS:
            return "nw"
        return token

    def _should_trace(self, _plugin: str, message_id: str) -> bool:
        cfg = self._debug_config
        if not cfg.trace_enabled:
            return False
        if cfg.trace_payload_ids:
            if not message_id:
                return False
            return any(message_id.startswith(prefix) for prefix in cfg.trace_payload_ids)
        return True

    def _log_trace(self, plugin: str, message_id: str, stage: str, payload: Mapping[str, Any]) -> None:
        cfg = self._debug_config
        if not cfg.trace_enabled:
            return
        shape = str(payload.get("shape") or "").lower()
        if shape == "vect":
            vector = payload.get("vector")
            if not isinstance(vector, Sequence):
                return
            coords = []
            for point in vector:
                if isinstance(point, Mapping):
                    coords.append((point.get("x"), point.get("y")))
            self._logger.debug("trace plugin=%s id=%s stage=%s vector=%s", plugin, message_id, stage, coords)
        elif shape == "rect":
            try:
                x_val = payload.get("x")
                y_val = payload.get("y")
                w_val = payload.get("w")
                h_val = payload.get("h")
            except Exception:
                return
            self._logger.debug(
                "trace plugin=%s id=%s stage=%s rect=(x=%s,y=%s,w=%s,h=%s)",
                plugin,
                message_id,
                stage,
                x_val,
                y_val,
                w_val,
                h_val,
            )

    def _apply_override(
        self,
        plugin: str,
        pattern: str,
        override: Mapping[str, Any],
        payload: MutableMapping[str, Any],
        *,
        trace: bool = False,
        message_id: str = "",
    ) -> None:
        shape_type = str(payload.get("type") or "").lower()
        if shape_type not in {"message", "shape"}:
            return
        # Transform overrides have been retired; retain the method for future use.
