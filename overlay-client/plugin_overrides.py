"""Plugin-specific override support for Modern Overlay payload rendering."""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Tuple


JsonDict = Dict[str, Any]


@dataclass
class _PluginConfig:
    name: str
    match_id_prefixes: Tuple[str, ...]
    overrides: List[Tuple[str, JsonDict]]


class PluginOverrideManager:
    """Load and apply plugin-specific rendering overrides."""

    def __init__(self, config_path: Path, logger) -> None:
        self._path = config_path
        self._logger = logger
        self._mtime: Optional[float] = None
        self._plugins: Dict[str, _PluginConfig] = {}
        self._x_scale_cache: Dict[str, float] = {}
        self._load_config()

    # ------------------------------------------------------------------
    # Public API

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
        if not message_id:
            return

        override = self._select_override(config, message_id)
        if override is None:
            return

        self._apply_override(plugin_name, override, payload)

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

            match_prefixes: Tuple[str, ...] = ()
            match_section = plugin_payload.get("__match__")
            if isinstance(match_section, Mapping):
                prefixes = match_section.get("id_prefixes")
                if isinstance(prefixes, Iterable):
                    cleaned: List[str] = []
                    for value in prefixes:
                        if isinstance(value, str) and value:
                            cleaned.append(value)
                    match_prefixes = tuple(cleaned)

            overrides: List[Tuple[str, JsonDict]] = []
            for key, spec in plugin_payload.items():
                if not isinstance(spec, Mapping) or key.startswith("__"):
                    continue
                overrides.append((str(key), dict(spec)))

            plugins[plugin_name] = _PluginConfig(
                name=plugin_name,
                match_id_prefixes=match_prefixes,
                overrides=overrides,
            )

        self._plugins = plugins
        self._x_scale_cache.clear()
        try:
            self._mtime = self._path.stat().st_mtime
        except FileNotFoundError:
            self._mtime = None
        self._logger.debug(
            "Loaded %d plugin override configuration(s) from %s.",
            len(self._plugins),
            self._path,
        )

    def _determine_plugin_name(self, payload: Mapping[str, Any]) -> Optional[str]:
        for key in ("plugin", "plugin_name", "source_plugin"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                return value

        meta = payload.get("meta")
        if isinstance(meta, Mapping):
            for key in ("plugin", "plugin_name", "source_plugin"):
                value = meta.get(key)
                if isinstance(value, str) and value:
                    return value

        raw = payload.get("raw")
        if isinstance(raw, Mapping):
            for key in ("plugin", "plugin_name", "source_plugin"):
                value = raw.get(key)
                if isinstance(value, str) and value:
                    return value

        item_id = str(payload.get("id") or "")
        if not item_id:
            return None

        for name, config in self._plugins.items():
            if not config.match_id_prefixes:
                continue
            if any(item_id.startswith(prefix) for prefix in config.match_id_prefixes):
                return name

        return None

    def _select_override(self, config: _PluginConfig, message_id: str) -> Optional[JsonDict]:
        for pattern, spec in config.overrides:
            if fnmatchcase(message_id, pattern):
                return spec
        return None

    def _apply_override(self, plugin: str, override: Mapping[str, Any], payload: MutableMapping[str, Any]) -> None:
        shape_type = str(payload.get("type") or "").lower()
        if shape_type != "shape":
            return
        shape = str(payload.get("shape") or "").lower()
        if shape not in {"vect", "rect"}:
            return
        if int(payload.get("ttl", 0)) == 0:
            return

        if "x_scale" in override:
            scale = self._resolve_x_scale(plugin, override["x_scale"], payload)
            if scale is not None and not math.isclose(scale, 1.0, rel_tol=1e-3):
                if shape == "vect":
                    self._scale_vector(payload, scale)
                elif shape == "rect":
                    self._scale_rect(payload, scale)

        # Additional overrides (gutters, font tweaks, etc.) can be added here.

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
        cache_key = plugin

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

        xs: List[float] = []
        for point in vector:
            if isinstance(point, Mapping) and isinstance(point.get("x"), (int, float)):
                xs.append(float(point["x"]))
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
        if isinstance(raw, MutableMapping) and isinstance(raw.get("vector"), list):
            self._scale_vector(raw, scale)  # type: ignore[arg-type]

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
