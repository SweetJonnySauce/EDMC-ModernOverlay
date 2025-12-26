"""Public helper API for interacting with EDMC Modern Overlay."""
from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
import time
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Callable, Dict, Mapping, MutableMapping, Optional, Sequence, Tuple, Union, cast

from prefix_entries import PrefixEntry, parse_prefix_entries, serialise_prefix_entries

_LOGGER = logging.getLogger("EDMC.ModernOverlay.API")
_MAX_MESSAGE_BYTES = 16_384
_ANCHOR_CHOICES = {"nw", "ne", "sw", "se", "center", "top", "bottom", "left", "right"}
_JUSTIFICATION_CHOICES = {"left", "center", "right"}
_MARKER_LABEL_POSITIONS = {"below", "above", "centered"}
_CONTROLLER_PREVIEW_BOX_MODES = {"last", "max"}
_HEX_DIGITS = set("0123456789ABCDEFabcdef")

_publisher: Optional[Callable[[Mapping[str, Any]], bool]] = None
_grouping_store: Optional["_PluginGroupingStore"] = None
_publisher_warn_at: float = 0.0
_publisher_warn_suppressed: int = 0
_PUBLISHER_WARN_INTERVAL = 30.0  # seconds


class PluginGroupingError(ValueError):
    """Raised when callers provide invalid plugin grouping data."""


def register_publisher(publisher: Callable[[Mapping[str, Any]], bool]) -> None:
    """Register a callable that delivers overlay payloads.

    The EDMC Modern Overlay plugin calls this during startup so other plugins can
    publish messages without depending on transport details.
    """

    global _publisher
    _publisher = publisher


def unregister_publisher() -> None:
    """Clear the registered publisher (called when the plugin stops)."""

    global _publisher
    _publisher = None


def register_grouping_store(path: Union[str, Path]) -> None:
    """Expose the overlay grouping JSON so other plugins can edit it."""

    resolved = Path(path)
    if resolved.name == "overlay_groupings.user.json":
        raise PluginGroupingError("register_grouping_store must target the shipped overlay_groupings.json, not the user file")
    if resolved.name != "overlay_groupings.json":
        _log_warning("register_grouping_store expected overlay_groupings.json, got %s", resolved.name)

    global _grouping_store
    _grouping_store = _PluginGroupingStore(resolved)


def unregister_grouping_store() -> None:
    """Forget the overlay grouping JSON path (used when shutting down)."""

    global _grouping_store
    _grouping_store = None


def send_overlay_message(message: Mapping[str, Any]) -> bool:
    """Publish a payload to the Modern Overlay broadcaster.

    Parameters
    ----------
    message:
        Mapping containing JSON-serialisable values. Must include an ``event``
        field. A ``timestamp`` is added automatically when omitted.

    Returns
    -------
    bool
        ``True`` if the message was handed to the broadcaster, ``False``
        otherwise.
    """

    publisher = _publisher
    if publisher is None:
        # Avoid log spam when other plugins send messages before the overlay is ready.
        global _publisher_warn_at, _publisher_warn_suppressed
        now = time.monotonic()
        if now - _publisher_warn_at >= _PUBLISHER_WARN_INTERVAL:
            suppressed = _publisher_warn_suppressed
            _publisher_warn_at = now
            _publisher_warn_suppressed = 0
            if suppressed:
                _log_warning(
                    "Overlay publisher unavailable (plugin not running?) [%d more messages suppressed]",
                    suppressed,
                )
            else:
                _log_warning("Overlay publisher unavailable (plugin not running?)")
        else:
            _publisher_warn_suppressed += 1
        return False

    payload = _normalise_message(message)
    if payload is None:
        return False

    try:
        serialised = json.dumps(payload, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        _log_warning(f"Overlay message is not JSON serialisable: {exc}")
        return False

    payload_size = len(serialised.encode("utf-8"))
    if payload_size > _MAX_MESSAGE_BYTES:
        _log_warning(
            "Overlay message exceeds size limit (%d > %d bytes)",
            payload_size,
            _MAX_MESSAGE_BYTES,
        )
        return False

    try:
        return bool(publisher(payload))
    except Exception as exc:  # pragma: no cover - defensive guard
        _log_warning(f"Overlay publisher raised error: {exc}")
        return False


def define_plugin_group(
    *,
    plugin_group: str,
    matching_prefixes: Optional[Sequence[str]] = None,
    id_prefix_group: Optional[str] = None,
    id_prefixes: Optional[Sequence[Union[str, Mapping[str, Any]]]] = None,
    id_prefix_group_anchor: Optional[str] = None,
    id_prefix_offset_x: Optional[Union[int, float]] = None,
    id_prefix_offset_y: Optional[Union[int, float]] = None,
    payload_justification: Optional[str] = None,
    marker_label_position: Optional[str] = None,
    controller_preview_box_mode: Optional[str] = None,
    background_color: Optional[str] = None,
    background_border_color: Optional[str] = None,
    background_border_width: Optional[Union[int, float]] = None,
) -> bool:
    """Create or replace grouping metadata for a plugin.

    Returns ``True`` when the JSON file was updated. Raises
    :class:`PluginGroupingError` when validation fails or when the overlay
    plugin is not running.
    """

    if not plugin_group:
        raise PluginGroupingError("pluginGroup is required")

    store = _grouping_store
    if store is None:
        raise PluginGroupingError("Modern Overlay plugin is unavailable; cannot define plugin groups")

    plugin_label = _normalise_label(plugin_group, "pluginGroup")
    if (
        matching_prefixes is None
        and id_prefix_group is None
        and id_prefixes is None
        and id_prefix_group_anchor is None
        and id_prefix_offset_x is None
        and id_prefix_offset_y is None
        and payload_justification is None
        and marker_label_position is None
        and controller_preview_box_mode is None
        and background_color is None
        and background_border_color is None
        and background_border_width is None
    ):
        raise PluginGroupingError(
            "Provide matchingPrefixes, idPrefixGroup, idPrefixes, idPrefixGroupAnchor, "
            "markerLabelPosition, controllerPreviewBoxMode, offsets, payloadJustification, or background fields"
        )

    match_list = _normalise_prefixes(matching_prefixes, "matchingPrefixes") if matching_prefixes is not None else None
    id_group_label = _normalise_label(id_prefix_group, "idPrefixGroup") if id_prefix_group is not None else None
    id_prefix_entries = _normalise_id_prefix_entries(id_prefixes) if id_prefixes is not None else None
    if id_prefix_entries is not None and id_group_label is None:
        raise PluginGroupingError("idPrefixGroup is required when specifying idPrefixes")
    anchor_token = _normalise_anchor(id_prefix_group_anchor) if id_prefix_group_anchor is not None else None
    if anchor_token is not None and id_group_label is None:
        raise PluginGroupingError("idPrefixGroup is required when specifying idPrefixGroupAnchor")
    offset_x = _normalise_offset(id_prefix_offset_x, "idPrefixGroup offsetX") if id_prefix_offset_x is not None else None
    offset_y = _normalise_offset(id_prefix_offset_y, "idPrefixGroup offsetY") if id_prefix_offset_y is not None else None
    if id_group_label is None and (offset_x is not None or offset_y is not None):
        raise PluginGroupingError("idPrefixGroup is required when specifying offsets")
    justification_token = (
        _normalise_justification(payload_justification) if payload_justification is not None else None
    )
    if justification_token is not None and id_group_label is None:
        raise PluginGroupingError("idPrefixGroup is required when specifying payloadJustification")
    marker_label_position_token = (
        _normalise_marker_label_position(marker_label_position) if marker_label_position is not None else None
    )
    if marker_label_position_token is not None and id_group_label is None:
        raise PluginGroupingError("idPrefixGroup is required when specifying markerLabelPosition")
    controller_preview_box_mode_token = (
        _normalise_controller_preview_box_mode(controller_preview_box_mode)
        if controller_preview_box_mode is not None
        else None
    )
    if controller_preview_box_mode_token is not None and id_group_label is None:
        raise PluginGroupingError("idPrefixGroup is required when specifying controllerPreviewBoxMode")
    background_color_token = _normalise_background_color(background_color) if background_color is not None else None
    background_border_color_token = (
        _normalise_background_color(background_border_color) if background_border_color is not None else None
    )
    background_border_width_token = (
        _normalise_border_width(background_border_width, "backgroundBorderWidth")
        if background_border_width is not None
        else None
    )
    if (
        background_color_token is not None
        or background_border_color_token is not None
        or background_border_width_token is not None
    ) and id_group_label is None:
        raise PluginGroupingError(
            "idPrefixGroup is required when specifying backgroundColor, backgroundBorderColor, or backgroundBorderWidth"
        )

    update = _GroupingUpdate(
        plugin_group=plugin_label,
        matching_prefixes=match_list,
        id_prefix_group=id_group_label,
        id_prefixes=id_prefix_entries,
        id_prefix_group_anchor=anchor_token,
        offset_x=offset_x,
        offset_y=offset_y,
        payload_justification=justification_token,
        marker_label_position=marker_label_position_token,
        controller_preview_box_mode=controller_preview_box_mode_token,
        background_color=background_color_token,
        background_border_color=background_border_color_token,
        background_border_width=background_border_width_token,
    )
    return store.apply(update)


def _normalise_message(message: Mapping[str, Any]) -> Optional[MutableMapping[str, Any]]:
    if not isinstance(message, Mapping):
        _log_warning("Overlay message must be a mapping/dict")
        return None
    if not message:
        _log_warning("Overlay message is empty")
        return None

    payload: MutableMapping[str, Any] = dict(message)
    event = payload.get("event")
    if not isinstance(event, str) or not event:
        _log_warning("Overlay message requires a non-empty 'event' string")
        return None

    if "timestamp" not in payload:
        payload["timestamp"] = datetime.now(timezone.utc).isoformat()

    return payload


def _normalise_label(value: Optional[str], field: str) -> str:
    if not isinstance(value, str):
        raise PluginGroupingError(f"{field} must be a string")
    token = value.strip()
    if not token:
        raise PluginGroupingError(f"{field} must be a non-empty string")
    return token


def _normalise_prefixes(values: Optional[Sequence[str]], field: str) -> Tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, str):
        iterable = [values]
    else:
        iterable = list(values)
    cleaned: list[str] = []
    seen = set()
    for entry in iterable:
        if not isinstance(entry, str):
            raise PluginGroupingError(f"{field} entries must be strings")
        token = entry.strip()
        if not token:
            continue
        lowered = token.lower()
        if lowered not in seen:
            cleaned.append(lowered)
            seen.add(lowered)
    if not cleaned:
        raise PluginGroupingError(f"{field} must contain at least one non-empty string")
    return tuple(cleaned)


def _normalise_id_prefix_entries(values: Optional[Sequence[Union[str, Mapping[str, Any]]]]) -> Tuple[PrefixEntry, ...]:
    if values is None:
        return ()
    entries = parse_prefix_entries(values)
    if not entries:
        raise PluginGroupingError("idPrefixes must contain at least one non-empty value")
    return tuple(entries)


def _normalise_anchor(value: Optional[str]) -> str:
    if not isinstance(value, str):
        raise PluginGroupingError("idPrefixGroupAnchor must be a string")
    token = value.strip().lower()
    if not token:
        raise PluginGroupingError("idPrefixGroupAnchor must be non-empty")
    if token not in _ANCHOR_CHOICES:
        raise PluginGroupingError(
            "idPrefixGroupAnchor must be one of: " + ", ".join(sorted(_ANCHOR_CHOICES))
        )
    return token


def _normalise_justification(value: Optional[str]) -> str:
    if not isinstance(value, str):
        raise PluginGroupingError("payloadJustification must be a string")
    token = value.strip().lower()
    if not token:
        raise PluginGroupingError("payloadJustification must be non-empty")
    if token not in _JUSTIFICATION_CHOICES:
        raise PluginGroupingError(
            "payloadJustification must be one of: " + ", ".join(sorted(_JUSTIFICATION_CHOICES))
        )
    return token


def _normalise_marker_label_position(value: Optional[str]) -> str:
    if not isinstance(value, str):
        raise PluginGroupingError("markerLabelPosition must be a string")
    token = value.strip().lower()
    if not token:
        raise PluginGroupingError("markerLabelPosition must be non-empty")
    if token not in _MARKER_LABEL_POSITIONS:
        raise PluginGroupingError(
            "markerLabelPosition must be one of: " + ", ".join(sorted(_MARKER_LABEL_POSITIONS))
        )
    return token


def _normalise_controller_preview_box_mode(value: Optional[str]) -> str:
    if not isinstance(value, str):
        raise PluginGroupingError("controllerPreviewBoxMode must be a string")
    token = value.strip().lower()
    if not token:
        raise PluginGroupingError("controllerPreviewBoxMode must be non-empty")
    if token not in _CONTROLLER_PREVIEW_BOX_MODES:
        raise PluginGroupingError(
            "controllerPreviewBoxMode must be one of: " + ", ".join(sorted(_CONTROLLER_PREVIEW_BOX_MODES))
        )
    return token


def _normalise_offset(value: Union[int, float], field: str) -> float:
    if not isinstance(value, (int, float)):
        raise PluginGroupingError(f"{field} must be a number")
    numeric = float(value)
    if not math.isfinite(numeric):
        raise PluginGroupingError(f"{field} must be a finite number")
    return numeric


def _normalise_background_color(value: Optional[str]) -> str:
    if not isinstance(value, str):
        raise PluginGroupingError("backgroundColor must be a string")
    token = value.strip()
    if not token:
        raise PluginGroupingError("backgroundColor must be non-empty")
    if token.startswith("#") or (
        len(token) in (6, 8) and all(ch in _HEX_DIGITS for ch in token)
    ):
        if not token.startswith("#"):
            token = "#" + token
        token = token.upper()
        if len(token) not in (7, 9):
            raise PluginGroupingError("backgroundColor must be #RRGGBB or #AARRGGBB")
        if not all(ch in _HEX_DIGITS for ch in token[1:]):
            raise PluginGroupingError("backgroundColor must use hex digits")
        return token
    if not token[0].isalpha():
        raise PluginGroupingError("backgroundColor must be #RRGGBB, #AARRGGBB, or a named color")
    if not all(ch.isalnum() or ch == "_" for ch in token):
        raise PluginGroupingError("backgroundColor must be #RRGGBB, #AARRGGBB, or a named color")
    return token


def _normalise_border_width(value: Union[int, float], field: str) -> int:
    if not isinstance(value, (int, float)):
        raise PluginGroupingError(f"{field} must be a number")
    numeric = int(value)
    if numeric < 0 or numeric > 10:
        raise PluginGroupingError(f"{field} must be between 0 and 10")
    return numeric


def _matches_contains_prefix(matches: Sequence[Any], prefix: str) -> bool:
    candidate = prefix.strip().lower()
    if not candidate:
        return True
    for entry in matches:
        if isinstance(entry, str) and entry.strip().lower() == candidate:
            return True
    return False


def _prefix_is_captured(prefix: str, matches: Sequence[Any]) -> bool:
    candidate = prefix.strip().lower()
    if not candidate:
        return True
    for entry in matches:
        if not isinstance(entry, str):
            continue
        token = entry.strip().lower()
        if token and candidate.startswith(token):
            return True
    return False


def _log_warning(message: str, *args: Any) -> None:
    _emit(logging.WARNING, message, *args)


def _emit(level: int, message: str, *args: Any) -> None:
    try:
        from config import config as edmc_config  # type: ignore

        logger_obj = getattr(edmc_config, "logger", None)
        if logger_obj:
            logger_obj.log(level, f"[EDMCModernOverlay] {message % args if args else message}")
            return
    except Exception:
        pass
    if args:
        _LOGGER.log(level, message, *args)
    else:
        _LOGGER.log(level, message)


@dataclass(frozen=True)
class _GroupingUpdate:
    plugin_group: str
    matching_prefixes: Optional[Tuple[str, ...]]
    id_prefix_group: Optional[str]
    id_prefixes: Optional[Tuple[PrefixEntry, ...]]
    id_prefix_group_anchor: Optional[str]
    offset_x: Optional[float]
    offset_y: Optional[float]
    payload_justification: Optional[str]
    marker_label_position: Optional[str]
    controller_preview_box_mode: Optional[str]
    background_color: Optional[str]
    background_border_color: Optional[str]
    background_border_width: Optional[int]


class _PluginGroupingStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = RLock()

    def apply(self, update: _GroupingUpdate) -> bool:
        with self._lock:
            data = self._load()
            plugin_block = data.get(update.plugin_group)
            attach_plugin_block = False
            if not isinstance(plugin_block, dict):
                plugin_block = {}
                attach_plugin_block = True
            plugin_block = cast(Dict[str, Any], plugin_block)
            mutated = False

            if update.matching_prefixes is not None:
                new_matches = list(update.matching_prefixes)
                if plugin_block.get("matchingPrefixes") != new_matches:
                    plugin_block["matchingPrefixes"] = new_matches
                    mutated = True

            if update.id_prefix_group is not None:
                groups = plugin_block.get("idPrefixGroups")
                groups_missing = not isinstance(groups, dict)
                if groups_missing:
                    groups = {}
                groups = cast(Dict[str, Any], groups)
                group_entry = groups.get(update.id_prefix_group)
                group_missing = not isinstance(group_entry, dict)
                if group_missing and update.id_prefixes is None:
                    raise PluginGroupingError(
                        f"idPrefixes must be provided when creating idPrefixGroup '{update.id_prefix_group}'"
                    )
                if group_missing:
                    group_entry = {}
                group_entry = cast(Dict[str, Any], group_entry)

                if update.id_prefixes is not None:
                    prefix_entries = list(update.id_prefixes)
                    serialised_prefixes = serialise_prefix_entries(prefix_entries)
                    if group_entry.get("idPrefixes") != serialised_prefixes:
                        group_entry["idPrefixes"] = serialised_prefixes
                        mutated = True
                    new_value_keys = {entry.value_cf for entry in prefix_entries}
                    # Remove these prefixes from every other group so they stay unique within this plugin.
                    for other_label, other_entry in list(groups.items()):
                        if other_label == update.id_prefix_group:
                            continue
                        if not isinstance(other_entry, dict):
                            continue
                        other_prefixes_raw = other_entry.get("idPrefixes")
                        other_prefixes = parse_prefix_entries(other_prefixes_raw)
                        if not other_prefixes:
                            continue
                        original = list(other_prefixes)
                        filtered = [entry for entry in original if entry.value_cf not in new_value_keys]
                        if len(filtered) == len(original):
                            continue
                        if filtered:
                            other_entry["idPrefixes"] = serialise_prefix_entries(filtered)
                        else:
                            other_entry.pop("idPrefixes", None)
                        groups[other_label] = other_entry
                        mutated = True
                    matches = plugin_block.get("matchingPrefixes")
                    if not isinstance(matches, list):
                        matches = []
                        plugin_block["matchingPrefixes"] = matches
                        mutated = True
                    for entry in prefix_entries:
                        value = entry.value.casefold()
                        if _prefix_is_captured(value, matches):
                            continue
                        if not _matches_contains_prefix(matches, value):
                            matches.append(value)
                            mutated = True

                if update.id_prefix_group_anchor is not None:
                    if group_entry.get("idPrefixGroupAnchor") != update.id_prefix_group_anchor:
                        group_entry["idPrefixGroupAnchor"] = update.id_prefix_group_anchor
                        mutated = True
                if update.payload_justification is not None:
                    if group_entry.get("payloadJustification") != update.payload_justification:
                        group_entry["payloadJustification"] = update.payload_justification
                        mutated = True
                if update.marker_label_position is not None:
                    if group_entry.get("markerLabelPosition") != update.marker_label_position:
                        group_entry["markerLabelPosition"] = update.marker_label_position
                        mutated = True
                if update.controller_preview_box_mode is not None:
                    if group_entry.get("controllerPreviewBoxMode") != update.controller_preview_box_mode:
                        group_entry["controllerPreviewBoxMode"] = update.controller_preview_box_mode
                        mutated = True
                if update.offset_x is not None:
                    if group_entry.get("offsetX") != update.offset_x:
                        group_entry["offsetX"] = update.offset_x
                        mutated = True
                if update.offset_y is not None:
                    if group_entry.get("offsetY") != update.offset_y:
                        group_entry["offsetY"] = update.offset_y
                        mutated = True
                if update.background_color is not None:
                    if group_entry.get("backgroundColor") != update.background_color:
                        group_entry["backgroundColor"] = update.background_color
                        mutated = True
                if update.background_border_color is not None:
                    if group_entry.get("backgroundBorderColor") != update.background_border_color:
                        group_entry["backgroundBorderColor"] = update.background_border_color
                        mutated = True
                if update.background_border_width is not None:
                    if group_entry.get("backgroundBorderWidth") != update.background_border_width:
                        group_entry["backgroundBorderWidth"] = update.background_border_width
                        mutated = True

                if group_missing or groups_missing:
                    mutated = True
                groups[update.id_prefix_group] = group_entry
                plugin_block["idPrefixGroups"] = groups
            else:
                if (
                    update.id_prefixes is not None
                    or update.id_prefix_group_anchor is not None
                    or update.offset_x is not None
                    or update.offset_y is not None
                    or update.marker_label_position is not None
                    or update.controller_preview_box_mode is not None
                    or update.background_color is not None
                    or update.background_border_color is not None
                    or update.background_border_width is not None
                ):
                    raise PluginGroupingError(
                        "idPrefixGroup is required when specifying idPrefixes, idPrefixGroupAnchor, "
                        "markerLabelPosition, controllerPreviewBoxMode, offsets, or background fields"
                    )

        if mutated:
            if attach_plugin_block:
                data[update.plugin_group] = plugin_block
            self._write(data)
        return mutated

    def _load(self) -> Dict[str, Any]:
        try:
            raw_text = self._path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return {}
        except OSError as exc:  # pragma: no cover - filesystem issues
            raise PluginGroupingError(f"Unable to read {self._path}: {exc}") from exc
        if not raw_text.strip():
            return {}
        try:
            data = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise PluginGroupingError(f"overlay_groupings.json is not valid JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise PluginGroupingError("overlay_groupings.json must contain a JSON object at the root")
        return dict(data)

    def _write(self, data: Mapping[str, Any]) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            serialised = json.dumps(data, indent=2, ensure_ascii=False)
            self._path.write_text(serialised + "\n", encoding="utf-8")
        except OSError as exc:  # pragma: no cover - filesystem issues
            raise PluginGroupingError(f"Unable to write {self._path}: {exc}") from exc
