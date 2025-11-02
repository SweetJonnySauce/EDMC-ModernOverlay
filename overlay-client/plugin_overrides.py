"""Plugin-specific override support for Modern Overlay payload rendering."""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Tuple

from debug_config import DebugConfig


JsonDict = Dict[str, Any]


@dataclass
class _GroupSpec:
    label: Optional[str]
    prefixes: Tuple[str, ...]
    defaults: Optional[JsonDict]
    preserve_fill_aspect_enabled: Optional[bool] = None
    preserve_fill_aspect_anchor: Optional[str] = None


@dataclass
class _PluginConfig:
    name: str
    canonical_name: str
    match_id_prefixes: Tuple[str, ...]
    overrides: List[Tuple[str, JsonDict]]
    plugin_defaults: Optional[JsonDict]
    group_mode: Optional[str]
    group_specs: Tuple[_GroupSpec, ...]


class PluginOverrideManager:
    """Load and apply plugin-specific rendering overrides."""

    def __init__(self, config_path: Path, logger, debug_config: Optional[DebugConfig] = None) -> None:
        self._path = config_path
        self._logger = logger
        self._mtime: Optional[float] = None
        self._plugins: Dict[str, _PluginConfig] = {}
        self._x_scale_cache: Dict[str, float] = {}
        self._debug_config = debug_config or DebugConfig()
        self._diagnostic_spans: Dict[Tuple[str, str], Tuple[float, float, float]] = {}
        self._load_config()

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
        try:
            stat = self._path.stat()
        except FileNotFoundError:
            if self._mtime is not None:
                self._logger.info("Plugin override file %s no longer present; disabling overrides.", self._path)
            self._mtime = None
            self._plugins.clear()
            self._x_scale_cache.clear()
            return

        if self._mtime is not None and stat.st_mtime <= self._mtime:
            return

        self._load_config()

    def _load_config(self) -> None:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            self._plugins.clear()
            self._x_scale_cache.clear()
            self._mtime = None
            self._logger.debug("Plugin override file %s not found; continuing without overrides.", self._path)
            return
        except json.JSONDecodeError as exc:
            self._logger.warning("Failed to parse plugin override file %s: %s", self._path, exc)
            return

        if not isinstance(raw, Mapping):
            self._logger.warning("Plugin override file %s must contain a JSON object at the top level.", self._path)
            return

        plugins: Dict[str, _PluginConfig] = {}
        for plugin_name, plugin_payload in raw.items():
            if not isinstance(plugin_name, str) or not isinstance(plugin_payload, Mapping):
                continue
            canonical_name = self._canonical_plugin_name(plugin_name)
            if canonical_name is None:
                continue

            match_prefixes: Tuple[str, ...] = ()
            match_section = plugin_payload.get("__match__")
            if isinstance(match_section, Mapping):
                prefixes = match_section.get("id_prefixes")
                if isinstance(prefixes, Iterable):
                    cleaned: List[str] = []
                    for value in prefixes:
                        if isinstance(value, str) and value:
                            cleaned.append(value.casefold())
                    match_prefixes = tuple(cleaned)

            grouping_mode: Optional[str] = None
            grouping_specs: List[_GroupSpec] = []
            grouping_section = plugin_payload.get("grouping")
            if isinstance(grouping_section, Mapping):
                mode_raw = grouping_section.get("mode")
                if isinstance(mode_raw, str):
                    mode_token = mode_raw.strip().lower()
                    if mode_token in {"plugin", "id_prefix"}:
                        grouping_mode = mode_token
                def _parse_preserve(source: Mapping[str, Any]) -> Tuple[Optional[bool], Optional[str]]:
                    block = source.get("preserve_fill_aspect")
                    enabled_val: Optional[bool] = None
                    anchor_val: Optional[str] = None
                    if isinstance(block, Mapping):
                        enabled_field = block.get("enabled")
                        if isinstance(enabled_field, bool):
                            enabled_val = enabled_field
                        anchor_field = block.get("anchor")
                        if isinstance(anchor_field, str):
                            anchor_token = anchor_field.strip().lower()
                            if anchor_token in {"first", "centroid"}:
                                anchor_val = anchor_token
                    return enabled_val, anchor_val
                if grouping_mode == "id_prefix":
                    def _capture_defaults(source: Mapping[str, Any]) -> Optional[JsonDict]:
                        defaults: JsonDict = {}
                        for key in ("transform", "x_scale", "x_shift"):
                            if key not in source:
                                continue
                            value = source[key]
                            if value is None:
                                continue
                            defaults[key] = dict(value) if isinstance(value, Mapping) else value
                        return defaults or None

                    groups_spec = grouping_section.get("groups")
                    if isinstance(groups_spec, Mapping):
                        for label, group_value in groups_spec.items():
                            if not isinstance(group_value, Mapping):
                                continue
                            prefixes_field = group_value.get("id_prefixes")
                            prefixes_list: List[str] = []
                            if isinstance(prefixes_field, str) and prefixes_field:
                                prefixes_list = [prefixes_field]
                            elif isinstance(prefixes_field, Iterable):
                                for entry in prefixes_field:
                                    if isinstance(entry, str) and entry:
                                        prefixes_list.append(entry)
                            if not prefixes_list:
                                single_prefix = group_value.get("prefix")
                                if isinstance(single_prefix, str) and single_prefix:
                                    prefixes_list = [single_prefix]
                            cleaned_prefixes = tuple(prefix.casefold() for prefix in prefixes_list if prefix)
                            if not cleaned_prefixes:
                                continue
                            group_label = str(label).strip() if isinstance(label, str) and label else None
                            defaults = _capture_defaults(group_value)
                            preserve_enabled, preserve_anchor = _parse_preserve(group_value)
                            grouping_specs.append(
                                _GroupSpec(
                                    label=group_label,
                                    prefixes=cleaned_prefixes,
                                    defaults=defaults,
                                    preserve_fill_aspect_enabled=preserve_enabled,
                                    preserve_fill_aspect_anchor=preserve_anchor,
                                )
                            )

                    prefixes_spec = grouping_section.get("prefixes")
                    if isinstance(prefixes_spec, Mapping):
                        for label, prefix_value in prefixes_spec.items():
                            prefixes: List[str] = []
                            defaults: Optional[JsonDict] = None
                            label_value: Optional[str] = None
                            if isinstance(prefix_value, str):
                                prefixes = [prefix_value]
                                label_value = str(label) if isinstance(label, str) and label else prefix_value
                            elif isinstance(prefix_value, Mapping):
                                raw_prefix = prefix_value.get("prefix")
                                if isinstance(raw_prefix, str) and raw_prefix:
                                    prefixes = [raw_prefix]
                                label_value = str(label) if isinstance(label, str) and label else (raw_prefix or None)
                                defaults = _capture_defaults(prefix_value)
                                preserve_enabled, preserve_anchor = _parse_preserve(prefix_value)
                            cleaned_prefixes = tuple(prefix.casefold() for prefix in prefixes if prefix)
                            if not cleaned_prefixes:
                                continue
                            grouping_specs.append(
                                _GroupSpec(
                                    label=label_value,
                                    prefixes=cleaned_prefixes,
                                    defaults=defaults,
                                    preserve_fill_aspect_enabled=preserve_enabled,
                                    preserve_fill_aspect_anchor=preserve_anchor,
                                )
                            )
                    elif isinstance(prefixes_spec, Iterable):
                        for entry in prefixes_spec:
                            if isinstance(entry, str) and entry:
                                grouping_specs.append(
                                    _GroupSpec(
                                        label=entry,
                                        prefixes=(entry.casefold(),),
                                        defaults=None,
                                    )
                                )

            overrides: List[Tuple[str, JsonDict]] = []
            plugin_defaults: JsonDict = {}
            for key, spec in plugin_payload.items():
                if key == "notes":
                    continue
                if key == "grouping":
                    continue
                if key == "transform" and isinstance(spec, Mapping):
                    plugin_defaults["transform"] = dict(spec)
                    continue
                if key == "x_scale" and spec is not None:
                    plugin_defaults["x_scale"] = spec
                    continue
                if key == "x_shift" and spec is not None:
                    plugin_defaults["x_shift"] = spec
                    continue
                if not isinstance(spec, Mapping) or key.startswith("__"):
                    continue
                overrides.append((str(key), dict(spec)))

            plugins[canonical_name] = _PluginConfig(
                name=plugin_name,
                canonical_name=canonical_name,
                match_id_prefixes=match_prefixes,
                overrides=overrides,
                plugin_defaults=plugin_defaults or None,
                group_mode=grouping_mode,
                group_specs=tuple(grouping_specs),
            )

        self._plugins = plugins
        self._x_scale_cache.clear()
        self._diagnostic_spans.clear()
        try:
            self._mtime = self._path.stat().st_mtime
        except FileNotFoundError:
            self._mtime = None
        self._logger.debug(
            "Loaded %d plugin override configuration(s) from %s.",
            len(self._plugins),
            self._path,
        )

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
        if config.group_mode != "id_prefix" or not config.group_specs:
            return None
        if not message_id:
            return None
        message_id_cf = message_id.casefold()
        for spec in config.group_specs:
            if any(message_id_cf.startswith(prefix) for prefix in spec.prefixes):
                label_value = spec.label or (spec.prefixes[0] if spec.prefixes else "")
                if spec.defaults:
                    return label_value, dict(spec.defaults)
                break
        return None

    def grouping_key_for(self, plugin: Optional[str], payload_id: Optional[str]) -> Optional[Tuple[str, Optional[str]]]:
        self._reload_if_needed()
        canonical = self._canonical_plugin_name(plugin)
        if canonical is None:
            return None
        config = self._plugins.get(canonical)
        if config is None or not config.group_mode:
            return None
        mode = config.group_mode
        if mode == "plugin":
            return config.name, None
        if mode == "id_prefix" and isinstance(payload_id, str) and payload_id:
            payload_cf = payload_id.casefold()
            for spec in config.group_specs:
                if any(payload_cf.startswith(prefix) for prefix in spec.prefixes):
                    label_value = spec.label or (spec.prefixes[0] if spec.prefixes else None)
                    return config.name, label_value
            return config.name, None
        return None

    def group_is_configured(self, plugin: Optional[str], suffix: Optional[str]) -> bool:
        self._reload_if_needed()
        canonical = self._canonical_plugin_name(plugin)
        if canonical is None:
            return False
        config = self._plugins.get(canonical)
        if config is None or not config.group_mode:
            return False
        if config.group_mode == "plugin":
            return suffix is None
        if config.group_mode == "id_prefix":
            if suffix is None:
                return False
            for spec in config.group_specs:
                label_value = spec.label or (spec.prefixes[0] if spec.prefixes else None)
                if label_value == suffix:
                    return True
            return False
        return False

    def group_preserve_fill_aspect(self, plugin: Optional[str], suffix: Optional[str]) -> Tuple[bool, str]:
        """Return whether fill-aspect preservation is enabled and which anchor to use."""

        self._reload_if_needed()
        canonical = self._canonical_plugin_name(plugin)
        if canonical is None:
            return True, "first"
        config = self._plugins.get(canonical)
        if config is None or not config.group_mode:
            return True, "first"
        if config.group_mode == "plugin":
            return True, "first"
        if config.group_mode == "id_prefix":
            if suffix is None:
                return True, "first"
            for spec in config.group_specs:
                label_value = spec.label or (spec.prefixes[0] if spec.prefixes else None)
                if label_value == suffix:
                    enabled = True if spec.preserve_fill_aspect_enabled is None else bool(spec.preserve_fill_aspect_enabled)
                    anchor = spec.preserve_fill_aspect_anchor or "first"
                    return enabled, anchor
            return True, "first"
        return True, "first"

    def group_mode_for(self, plugin: Optional[str]) -> Optional[str]:
        self._reload_if_needed()
        canonical = self._canonical_plugin_name(plugin)
        if canonical is None:
            return None
        config = self._plugins.get(canonical)
        if config is not None and config.group_mode:
            return config.group_mode
        # Handle callers that pass display names directly.
        for cfg in self._plugins.values():
            if cfg.name == plugin and cfg.group_mode:
                return cfg.group_mode
        return None

    def _should_trace(self, plugin: str, message_id: str) -> bool:
        cfg = self._debug_config
        if not cfg.trace_enabled:
            return False
        plugin_key = self._canonical_plugin_name(plugin)
        if cfg.trace_plugin:
            trace_key = self._canonical_plugin_name(cfg.trace_plugin)
            if trace_key is None:
                return False
            if trace_key != plugin_key:
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
        if shape_type == "message":
            self._apply_message_override(
                plugin,
                pattern,
                override,
                payload,
                trace=trace,
                message_id=message_id,
            )
            return
        if shape_type != "shape":
            return
        shape = str(payload.get("shape") or "").lower()
        if shape not in {"vect", "rect"}:
            return
        if int(payload.get("ttl", 0)) == 0:
            return

        transform_spec = override.get("transform")
        if isinstance(transform_spec, Mapping):
            if trace:
                self._log_trace(plugin, message_id, f"{pattern}:before_transform", payload)
            try:
                self._apply_transform(plugin, message_id, pattern, transform_spec, payload, trace=trace)
            except Exception:  # pragma: no cover - defensive
                self._logger.exception("Failed applying transform override for plugin %s", plugin)
            if trace:
                self._log_trace(plugin, message_id, f"{pattern}:after_transform", payload)

        scale: Optional[float] = None
        if "x_scale" in override:
            scale = self._resolve_x_scale(plugin, override["x_scale"], payload)
            if scale is not None and not math.isclose(scale, 1.0, rel_tol=1e-3):
                if shape == "vect":
                    self._scale_vector(payload, scale)
                elif shape == "rect":
                    self._scale_rect(payload, scale)
                if trace:
                    self._log_trace(plugin, message_id, f"{pattern}:after_scale", payload)

        if "x_shift" in override:
            shift = self._resolve_x_shift(plugin, override["x_shift"], payload, scale or 1.0)
            if shift is not None and not math.isclose(shift, 0.0, rel_tol=1e-3):
                if shape == "vect":
                    self._translate_vector(payload, shift)
                elif shape == "rect":
                    self._translate_rect(payload, shift)
                if trace:
                    self._log_trace(plugin, message_id, f"{pattern}:after_shift", payload)

        # Additional overrides (gutters, font tweaks, etc.) can be added here.

    def _apply_message_override(
        self,
        plugin: str,
        pattern: str,
        override: Mapping[str, Any],
        payload: MutableMapping[str, Any],
        *,
        trace: bool = False,
        message_id: str = "",
    ) -> None:
        transform_spec = override.get("transform")
        if not isinstance(transform_spec, Mapping):
            return

        scale_spec = transform_spec.get("scale")
        offset_spec = transform_spec.get("offset")

        scale_x = 1.0
        scale_y = 1.0
        offset_x = 0.0
        offset_y = 0.0
        pivot: Tuple[float, float] = (0.0, 0.0)

        if isinstance(scale_spec, Mapping):
            scale_x = self._coerce_float(scale_spec.get("x"), 1.0)
            scale_y = self._coerce_float(scale_spec.get("y"), 1.0)
            pivot_override = self._parse_point(scale_spec.get("pivot"))
            if pivot_override is not None:
                pivot = pivot_override
        elif isinstance(scale_spec, (int, float)):
            scale_x = float(scale_spec)
            scale_y = float(scale_spec)

        try:
            raw_x = float(payload.get("x", 0.0))
            raw_y = float(payload.get("y", 0.0))
        except (TypeError, ValueError):
            return
        raw_payload = payload.get("raw")

        if isinstance(offset_spec, Mapping):
            offset_x = self._coerce_float(offset_spec.get("x"), 0.0)
            offset_y = self._coerce_float(offset_spec.get("y"), 0.0)

        transform_meta = {
            "pivot": {"x": pivot[0], "y": pivot[1]},
            "scale": {"x": scale_x, "y": scale_y},
            "offset": {"x": offset_x, "y": offset_y},
            "pattern": pattern,
            "plugin": plugin,
            "original": {"x": raw_x, "y": raw_y},
        }
        if trace:
            self._logger.debug(
                "trace plugin=%s id=%s stage=%s deferred_transform=%s",
                plugin,
                message_id,
                f"{pattern}:message_transform",
                transform_meta,
            )
        payload.setdefault("__mo_transform__", {}).update(transform_meta)
        if isinstance(raw_payload, MutableMapping):
            raw_payload.setdefault("__mo_transform__", {}).update(transform_meta)

    def _parse_point(self, spec: Any) -> Optional[Tuple[float, float]]:
        if isinstance(spec, Mapping):
            try:
                return float(spec.get("x", 0.0)), float(spec.get("y", 0.0))
            except (TypeError, ValueError):
                return None
        return None

    def _resolve_x_scale(self, plugin: str, spec: Any, payload: Mapping[str, Any]) -> Optional[float]:
        if isinstance(spec, (int, float)):
            value = float(spec)
            return value if value > 0 else None

        if isinstance(spec, Mapping):
            mode = spec.get("mode")
        elif isinstance(spec, str):
            mode = spec
        else:
            mode = None

        if not isinstance(mode, str):
            return None

        mode = mode.lower().strip()
        cache_key = self._canonical_plugin_name(plugin) or plugin

        if mode == "derive_ratio_from_height":
            ratio = self._derive_ratio(payload)
            if ratio is None:
                return None
            self._x_scale_cache[cache_key] = ratio
            return ratio

        if mode == "use_cached_ratio":
            cached = self._x_scale_cache.get(cache_key)
            if cached is not None:
                return cached
            ratio = self._derive_ratio(payload)
            if ratio is None:
                return None
            self._x_scale_cache[cache_key] = ratio
            return ratio

        return None
    
    def _apply_transform(
        self,
        plugin: str,
        message_id: str,
        pattern: str,
        spec: Mapping[str, Any],
        payload: MutableMapping[str, Any],
        *,
        trace: bool = False,
    ) -> None:
        shape = str(payload.get("shape") or "").lower()
        if shape not in {"vect", "rect"}:
            return

        scale_spec = spec.get("scale")
        offset_spec = spec.get("offset")

        pivot_override: Optional[Tuple[float, float]] = None
        pivot_label: Optional[str] = None
        if not isinstance(scale_spec, Mapping):
            scale_x = 1.0
            scale_y = 1.0
            bounds_spec = None
        else:
            scale_x = self._coerce_float(scale_spec.get("x"), 1.0)
            scale_y = self._coerce_float(scale_spec.get("y"), 1.0)
            pivot_spec = scale_spec.get("pivot", scale_spec.get("point"))
            if isinstance(pivot_spec, Mapping):
                try:
                    pivot_override = (
                        float(pivot_spec.get("x", 0.0)),
                        float(pivot_spec.get("y", 0.0)),
                    )
                except (TypeError, ValueError):
                    pivot_override = None
            elif isinstance(pivot_spec, str):
                token = pivot_spec.strip()
                if token:
                    pivot_label = token
            bounds_spec = scale_spec.get("source_bounds")

        offset_x = 0.0
        offset_y = 0.0
        if isinstance(offset_spec, Mapping):
            offset_x = self._coerce_float(offset_spec.get("x"), 0.0)
            offset_y = self._coerce_float(offset_spec.get("y"), 0.0)

        points = self._extract_points_from_payload(payload)
        bounds = self._compute_bounds(points, bounds_spec)
        if bounds is None and pivot_override is None:
            return

        if pivot_override is not None:
            pivot = pivot_override
        elif pivot_label and bounds is not None:
            pivot = self._resolve_pivot(bounds, pivot_label)
        elif bounds is not None:
            pivot = self._resolve_pivot(bounds, "NW")
        else:
            pivot = (0.0, 0.0)

        scale_tuple = (scale_x, scale_y)
        offset_tuple = (offset_x, offset_y)

        original_meta: Dict[str, Any] = {}
        shape = str(payload.get("shape") or "").lower()
        if shape == "rect":
            try:
                original_meta = {
                    "x": float(payload.get("x", 0.0)),
                    "y": float(payload.get("y", 0.0)),
                    "w": float(payload.get("w", 0.0)),
                    "h": float(payload.get("h", 0.0)),
                }
            except (TypeError, ValueError):
                original_meta = {}
        elif shape == "vect":
            vector = payload.get("vector")
            if isinstance(vector, Iterable):
                points_list = [pt for pt in vector if isinstance(pt, Mapping)]
                if points_list:
                    original_meta["points"] = len(points_list)

        if bounds is not None:
            min_x, max_x, min_y, max_y = bounds
            original_meta.setdefault(
                "bounds",
                {"min_x": min_x, "max_x": max_x, "min_y": min_y, "max_y": max_y},
            )

        if trace:
            self._logger.debug(
                "trace plugin=%s id=%s stage=%s pivot=(%.2f,%.2f) scale=(%.3f,%.3f) offset=(%.3f,%.3f)",
                plugin,
                message_id,
                f"{pattern}:transform_params",
                pivot[0],
                pivot[1],
                scale_tuple[0],
                scale_tuple[1],
                offset_tuple[0],
                offset_tuple[1],
            )

        transform_meta = {
            "pivot": {"x": pivot[0], "y": pivot[1]},
            "scale": {"x": scale_tuple[0], "y": scale_tuple[1]},
            "offset": {"x": offset_tuple[0], "y": offset_tuple[1]},
            "pattern": pattern,
            "plugin": plugin,
        }
        if original_meta:
            transform_meta["original"] = original_meta
        if trace:
            self._logger.debug(
                "trace plugin=%s id=%s stage=%s deferred_transform=%s",
                plugin,
                message_id,
                f"{pattern}:transform_params",
                transform_meta,
            )
        payload.setdefault("__mo_transform__", {}).update(transform_meta)
        raw_payload = payload.get("raw")
        if isinstance(raw_payload, MutableMapping):
            raw_payload.setdefault("__mo_transform__", {}).update(transform_meta)

    def _coerce_float(self, value: Any, default: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _extract_points_from_payload(self, payload: Mapping[str, Any]) -> List[Tuple[float, float]]:
        shape = str(payload.get("shape") or "").lower()
        points: List[Tuple[float, float]] = []

        if shape == "vect":
            vector = payload.get("vector")
            if isinstance(vector, Iterable):
                for point in vector:
                    if not isinstance(point, Mapping):
                        continue
                    try:
                        x_val = float(point.get("x", 0.0))
                        y_val = float(point.get("y", 0.0))
                    except (TypeError, ValueError):
                        continue
                    points.append((x_val, y_val))

        elif shape == "rect":
            try:
                x_val = float(payload.get("x", 0.0))
                y_val = float(payload.get("y", 0.0))
                w_val = float(payload.get("w", 0.0))
                h_val = float(payload.get("h", 0.0))
            except (TypeError, ValueError):
                return points
            points.extend(
                [
                    (x_val, y_val),
                    (x_val + w_val, y_val),
                    (x_val, y_val + h_val),
                    (x_val + w_val, y_val + h_val),
                ]
            )

        return points

    def _compute_bounds(
        self,
        points: Sequence[Tuple[float, float]],
        bounds_spec: Any,
    ) -> Optional[Tuple[float, float, float, float]]:
        if points:
            xs = [pt[0] for pt in points]
            ys = [pt[1] for pt in points]
            return min(xs), max(xs), min(ys), max(ys)

        if isinstance(bounds_spec, Mapping):
            min_spec = bounds_spec.get("min")
            max_spec = bounds_spec.get("max")
            if isinstance(min_spec, Mapping) and isinstance(max_spec, Mapping):
                try:
                    min_x = float(min_spec.get("x", 0.0))
                    min_y = float(min_spec.get("y", 0.0))
                    max_x = float(max_spec.get("x", 0.0))
                    max_y = float(max_spec.get("y", 0.0))
                except (TypeError, ValueError):
                    return None
                return min_x, max_x, min_y, max_y

        return None

    def _resolve_pivot(self, bounds: Tuple[float, float, float, float], anchor: str) -> Tuple[float, float]:
        min_x, max_x, min_y, max_y = bounds
        anchor_upper = anchor.upper()
        if anchor_upper == "NE":
            return max_x, min_y
        if anchor_upper == "SW":
            return min_x, max_y
        if anchor_upper == "SE":
            return max_x, max_y
        if anchor_upper == "CENTER":
            return (min_x + max_x) / 2.0, (min_y + max_y) / 2.0
        if anchor_upper == "ORIGIN":
            return 0.0, 0.0
        return min_x, min_y


    def _resolve_x_shift(
        self,
        plugin: str,
        spec: Any,
        payload: Mapping[str, Any],
        applied_scale: float,
    ) -> Optional[float]:
        if isinstance(spec, (int, float)):
            return float(spec)

        if isinstance(spec, Mapping):
            mode = spec.get("mode")
            if isinstance(mode, str) and mode.lower() == "align_center":
                target = spec.get("target")
                if target is None:
                    return None
                try:
                    target_center = float(target)
                except (TypeError, ValueError):
                    return None
                current_center = self._current_center(payload)
                if current_center is None:
                    return None
                return target_center - current_center
        return None

    def _current_center(self, payload: Mapping[str, Any]) -> Optional[float]:
        shape = str(payload.get("shape") or "").lower()
        if shape == "vect":
            points = payload.get("vector")
            if not isinstance(points, list):
                return None
            xs = [float(point.get("x", 0)) for point in points if isinstance(point, Mapping) and isinstance(point.get("x"), (int, float))]
            if not xs:
                return None
            return (min(xs) + max(xs)) / 2.0
        if shape == "rect":
            try:
                x_val = float(payload.get("x", 0))
                width = float(payload.get("w", 0))
            except (TypeError, ValueError):
                return None
            return x_val + width / 2.0
        return None

    def _derive_ratio(self, payload: Mapping[str, Any]) -> Optional[float]:
        shape = str(payload.get("shape") or "").lower()
        if shape == "vect":
            points = payload.get("vector")
            if not isinstance(points, list):
                return None
            xs: List[float] = []
            ys: List[float] = []
            for point in points:
                if not isinstance(point, Mapping):
                    continue
                try:
                    xs.append(float(point.get("x", 0)))
                    ys.append(float(point.get("y", 0)))
                except (TypeError, ValueError):
                    continue
            if len(xs) < 2 or len(ys) < 2:
                return None
            span_x = max(xs) - min(xs)
            span_y = max(ys) - min(ys)
            if span_x <= 0 or span_y <= 0:
                return None
            return span_y / span_x

        if shape == "rect":
            try:
                width = float(payload.get("w", 0))
                height = float(payload.get("h", 0))
            except (TypeError, ValueError):
                return None
            if width <= 0 or height <= 0:
                return None
            return height / width

        return None

    def _scale_vector(self, payload: MutableMapping[str, Any], scale: float) -> None:
        vector = payload.get("vector")
        if not isinstance(vector, list):
            return

        xs = [float(point.get("x", 0)) for point in vector if isinstance(point, Mapping) and isinstance(point.get("x"), (int, float))]
        if not xs:
            return
        center_x = (min(xs) + max(xs)) / 2.0
        for point in vector:
            if not isinstance(point, MutableMapping):
                continue
            try:
                x_val = float(point.get("x", 0))
            except (TypeError, ValueError):
                continue
            offset = x_val - center_x
            point["x"] = int(round(center_x + offset * scale))

        raw = payload.get("raw")
        if isinstance(raw, MutableMapping):
            raw_vector = raw.get("vector")
            if isinstance(raw_vector, list):
                raw_xs = [float(point.get("x", 0)) for point in raw_vector if isinstance(point, Mapping) and isinstance(point.get("x"), (int, float))]
                if raw_xs:
                    raw_center = (min(raw_xs) + max(raw_xs)) / 2.0
                    for point in raw_vector:
                        if not isinstance(point, MutableMapping):
                            continue
                        try:
                            raw_x = float(point.get("x", 0))
                        except (TypeError, ValueError):
                            continue
                        offset = raw_x - raw_center
                        point["x"] = int(round(raw_center + offset * scale))

    def _scale_rect(self, payload: MutableMapping[str, Any], scale: float) -> None:
        try:
            x_val = float(payload.get("x", 0))
            width = float(payload.get("w", 0))
        except (TypeError, ValueError):
            return
        if width <= 0:
            return
        center = x_val + width / 2.0
        new_width = max(1, int(round(width * scale)))
        new_x = int(round(center - new_width / 2.0))
        payload["w"] = new_width
        payload["x"] = new_x

        raw = payload.get("raw")
        if isinstance(raw, MutableMapping):
            try:
                raw_width = float(raw.get("w", width))
                raw_x = float(raw.get("x", x_val))
            except (TypeError, ValueError):
                raw_width = width
                raw_x = x_val
            center_raw = raw_x + raw_width / 2.0
            new_raw_width = max(1, int(round(raw_width * scale)))
            new_raw_x = int(round(center_raw - new_raw_width / 2.0))
            raw["w"] = new_raw_width
            raw["x"] = new_raw_x

    def _translate_vector(self, payload: MutableMapping[str, Any], delta: float) -> None:
        vector = payload.get("vector")
        if not isinstance(vector, list):
            return
        for point in vector:
            if not isinstance(point, MutableMapping):
                continue
            try:
                x_val = float(point.get("x", 0))
            except (TypeError, ValueError):
                continue
            point["x"] = int(round(x_val + delta))

        raw = payload.get("raw")
        if isinstance(raw, MutableMapping):
            raw_vector = raw.get("vector")
            if isinstance(raw_vector, list):
                for point in raw_vector:
                    if not isinstance(point, MutableMapping):
                        continue
                    try:
                        x_val = float(point.get("x", 0))
                    except (TypeError, ValueError):
                        continue
                    point["x"] = int(round(x_val + delta))

    def _translate_rect(self, payload: MutableMapping[str, Any], delta: float) -> None:
        try:
            x_val = float(payload.get("x", 0))
        except (TypeError, ValueError):
            return
        payload["x"] = int(round(x_val + delta))

        raw = payload.get("raw")
        if isinstance(raw, MutableMapping):
            try:
                raw_x = float(raw.get("x", x_val))
            except (TypeError, ValueError):
                return
            raw["x"] = int(round(raw_x + delta))
