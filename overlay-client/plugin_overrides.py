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
class _PluginConfig:
    name: str
    canonical_name: str
    match_id_prefixes: Tuple[str, ...]
    overrides: List[Tuple[str, JsonDict]]
    plugin_defaults: Optional[JsonDict]


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

            overrides: List[Tuple[str, JsonDict]] = []
            plugin_defaults: JsonDict = {}
            for key, spec in plugin_payload.items():
                if key == "notes":
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
            else:
                anchor_spec = scale_spec.get("scale_anchor_point", scale_spec.get("point"))
                anchor_point = self._parse_point(anchor_spec)
                if anchor_point is not None:
                    pivot = anchor_point
        elif isinstance(scale_spec, (int, float)):
            scale_x = float(scale_spec)
            scale_y = float(scale_spec)

        if isinstance(offset_spec, Mapping):
            offset_x = self._coerce_float(offset_spec.get("x"), 0.0)
            offset_y = self._coerce_float(offset_spec.get("y"), 0.0)

        if math.isclose(scale_x, 1.0, rel_tol=1e-9) and math.isclose(scale_y, 1.0, rel_tol=1e-9) and math.isclose(offset_x, 0.0, rel_tol=1e-9) and math.isclose(offset_y, 0.0, rel_tol=1e-9):
            return

        try:
            raw_x = float(payload.get("x", 0.0))
            raw_y = float(payload.get("y", 0.0))
        except (TypeError, ValueError):
            return

        new_x, new_y = self._transform_point((raw_x, raw_y), pivot, (scale_x, scale_y), (offset_x, offset_y))
        rounded_x = self._round_coordinate(new_x)
        rounded_y = self._round_coordinate(new_y)
        if trace:
            self._logger.debug(
                "trace plugin=%s id=%s stage=%s coords=(%.2f,%.2f)->(%.2f,%.2f)",
                plugin,
                message_id,
                f"{pattern}:message_transform",
                raw_x,
                raw_y,
                new_x,
                new_y,
            )

        payload["x"] = rounded_x
        payload["y"] = rounded_y
        raw_payload = payload.get("raw")
        if isinstance(raw_payload, MutableMapping):
            raw_payload["x"] = rounded_x
            raw_payload["y"] = rounded_y

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

        pivot_override = None
        if not isinstance(scale_spec, Mapping):
            scale_x = 1.0
            scale_y = 1.0
            scale_anchor = "NW"
            bounds_spec = None
        else:
            scale_x = self._coerce_float(scale_spec.get("x"), 1.0)
            scale_y = self._coerce_float(scale_spec.get("y"), 1.0)
            point_spec = scale_spec.get("scale_anchor_point", scale_spec.get("point", "NW"))
            if isinstance(point_spec, Mapping):
                try:
                    pivot_override = (
                        float(point_spec.get("x", 0.0)),
                        float(point_spec.get("y", 0.0)),
                    )
                except (TypeError, ValueError):
                    pivot_override = None
                scale_anchor = "NW"
            else:
                scale_anchor = str(point_spec or "NW")
            bounds_spec = scale_spec.get("source_bounds")

        offset_x = 0.0
        offset_y = 0.0
        if isinstance(offset_spec, Mapping):
            offset_x = self._coerce_float(offset_spec.get("x"), 0.0)
            offset_y = self._coerce_float(offset_spec.get("y"), 0.0)

        if math.isclose(scale_x, 1.0, rel_tol=1e-9) and math.isclose(scale_y, 1.0, rel_tol=1e-9) and math.isclose(offset_x, 0.0, rel_tol=1e-9) and math.isclose(offset_y, 0.0, rel_tol=1e-9):
            return

        if isinstance(scale_spec, Mapping):
            pivot_candidate = scale_spec.get("pivot")
            if isinstance(pivot_candidate, Mapping):
                try:
                    pivot_override = (
                        float(pivot_candidate.get("x", 0.0)),
                        float(pivot_candidate.get("y", 0.0)),
                    )
                except (TypeError, ValueError):
                    pass

        points = self._extract_points_from_payload(payload)
        bounds = self._compute_bounds(points, bounds_spec)
        if bounds is None and pivot_override is None:
            return

        if pivot_override is not None:
            pivot = pivot_override
        else:
            pivot = self._resolve_pivot(bounds, scale_anchor)

        scale_tuple = (scale_x, scale_y)
        offset_tuple = (offset_x, offset_y)

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
        payload.setdefault("__mo_transform__", {}).update(transform_meta)
        raw_payload = payload.get("raw")
        if isinstance(raw_payload, MutableMapping):
            raw_payload.setdefault("__mo_transform__", {}).update(transform_meta)

        if shape == "vect":
            self._transform_vector_payload(payload, pivot, scale_tuple, offset_tuple)
        elif shape == "rect":
            self._transform_rect_payload(payload, pivot, scale_tuple, offset_tuple)

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

    def _transform_vector_payload(
        self,
        payload: MutableMapping[str, Any],
        pivot: Tuple[float, float],
        scale: Tuple[float, float],
        offset: Tuple[float, float],
    ) -> None:
        vector = payload.get("vector")
        if isinstance(vector, list):
            for point in vector:
                if not isinstance(point, MutableMapping):
                    continue
                try:
                    x_val = float(point.get("x", 0.0))
                    y_val = float(point.get("y", 0.0))
                except (TypeError, ValueError):
                    continue
                new_x, new_y = self._transform_point((x_val, y_val), pivot, scale, offset)
                point["x"] = self._round_coordinate(new_x)
                point["y"] = self._round_coordinate(new_y)

        raw = payload.get("raw")
        if isinstance(raw, MutableMapping):
            raw_vector = raw.get("vector")
            if isinstance(raw_vector, list):
                for point in raw_vector:
                    if not isinstance(point, MutableMapping):
                        continue
                    try:
                        x_val = float(point.get("x", 0.0))
                        y_val = float(point.get("y", 0.0))
                    except (TypeError, ValueError):
                        continue
                    new_x, new_y = self._transform_point((x_val, y_val), pivot, scale, offset)
                    point["x"] = self._round_coordinate(new_x)
                    point["y"] = self._round_coordinate(new_y)

    def _transform_rect_payload(
        self,
        payload: MutableMapping[str, Any],
        pivot: Tuple[float, float],
        scale: Tuple[float, float],
        offset: Tuple[float, float],
    ) -> None:
        try:
            x_val = float(payload.get("x", 0.0))
            y_val = float(payload.get("y", 0.0))
            w_val = float(payload.get("w", 0.0))
            h_val = float(payload.get("h", 0.0))
        except (TypeError, ValueError):
            return

        corners = [
            (x_val, y_val),
            (x_val + w_val, y_val),
            (x_val, y_val + h_val),
            (x_val + w_val, y_val + h_val),
        ]
        transformed = [self._transform_point(corner, pivot, scale, offset) for corner in corners]
        xs = [pt[0] for pt in transformed]
        ys = [pt[1] for pt in transformed]

        min_x = min(xs)
        max_x = max(xs)
        min_y = min(ys)
        max_y = max(ys)

        payload["x"] = self._round_coordinate(min_x)
        payload["y"] = self._round_coordinate(min_y)
        payload["w"] = max(1, self._round_coordinate(max_x - min_x))
        payload["h"] = max(1, self._round_coordinate(max_y - min_y))

        raw = payload.get("raw")
        if isinstance(raw, MutableMapping):
            try:
                raw_x = float(raw.get("x", x_val))
                raw_y = float(raw.get("y", y_val))
                raw_w = float(raw.get("w", w_val))
                raw_h = float(raw.get("h", h_val))
            except (TypeError, ValueError):
                raw_x = x_val
                raw_y = y_val
                raw_w = w_val
                raw_h = h_val

            raw_corners = [
                (raw_x, raw_y),
                (raw_x + raw_w, raw_y),
                (raw_x, raw_y + raw_h),
                (raw_x + raw_w, raw_y + raw_h),
            ]
            raw_transformed = [self._transform_point(corner, pivot, scale, offset) for corner in raw_corners]
            raw_xs = [pt[0] for pt in raw_transformed]
            raw_ys = [pt[1] for pt in raw_transformed]

            raw_min_x = min(raw_xs)
            raw_max_x = max(raw_xs)
            raw_min_y = min(raw_ys)
            raw_max_y = max(raw_ys)

            raw["x"] = self._round_coordinate(raw_min_x)
            raw["y"] = self._round_coordinate(raw_min_y)
            raw["w"] = max(1, self._round_coordinate(raw_max_x - raw_min_x))
            raw["h"] = max(1, self._round_coordinate(raw_max_y - raw_min_y))

    def _transform_point(
        self,
        point: Tuple[float, float],
        pivot: Tuple[float, float],
        scale: Tuple[float, float],
        offset: Tuple[float, float],
    ) -> Tuple[float, float]:
        pivot_x, pivot_y = pivot
        scale_x, scale_y = scale
        offset_x, offset_y = offset
        scaled_x = pivot_x + (point[0] - pivot_x) * scale_x
        scaled_y = pivot_y + (point[1] - pivot_y) * scale_y
        return scaled_x + offset_x, scaled_y + offset_y

    def _round_coordinate(self, value: float) -> int:
        if math.isnan(value) or math.isinf(value):
            return 0
        return int(round(value))

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
