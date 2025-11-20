"""Utilities for parsing and serialising ID prefix entries with match modes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

MATCH_MODE_STARTSWITH = "startswith"
MATCH_MODE_EXACT = "exact"
VALID_MATCH_MODES = {MATCH_MODE_STARTSWITH, MATCH_MODE_EXACT}


def _normalise_match_mode(value: Optional[str]) -> str:
    token = (value or MATCH_MODE_STARTSWITH).strip().lower() if isinstance(value, str) else MATCH_MODE_STARTSWITH
    if token not in VALID_MATCH_MODES:
        return MATCH_MODE_STARTSWITH
    return token


@dataclass(frozen=True)
class PrefixEntry:
    """Represents a single ID prefix and its match behaviour."""

    value: str
    match_mode: str = MATCH_MODE_STARTSWITH

    def __post_init__(self) -> None:
        cleaned_value = str(self.value or "").strip()
        if not cleaned_value:
            raise ValueError("PrefixEntry requires a non-empty value.")
        object.__setattr__(self, "value", cleaned_value.casefold())
        object.__setattr__(self, "match_mode", _normalise_match_mode(self.match_mode))

    @property
    def value_cf(self) -> str:
        return self.value.casefold()

    @property
    def key(self) -> Tuple[str, str]:
        return (self.value_cf, self.match_mode)

    def matches(self, identifier: str) -> bool:
        candidate = identifier.casefold()
        if self.match_mode == MATCH_MODE_EXACT:
            return candidate == self.value_cf
        return candidate.startswith(self.value_cf)

    def to_json(self) -> Union[str, Dict[str, str]]:
        if self.match_mode == MATCH_MODE_STARTSWITH:
            return self.value
        return {"value": self.value, "matchMode": self.match_mode}

    def to_mapping(self) -> Dict[str, str]:
        return {"value": self.value, "matchMode": self.match_mode}

    def display_label(self) -> str:
        if self.match_mode == MATCH_MODE_EXACT:
            return f"{self.value} (exact)"
        return self.value


def _iter_raw_entries(raw_value: Any) -> Iterable[Any]:
    if raw_value is None:
        return []
    if isinstance(raw_value, (str, int, float, Mapping, PrefixEntry)):
        return [raw_value]
    if isinstance(raw_value, Iterable) and not isinstance(raw_value, (bytes, bytearray)):
        return raw_value
    return []


def parse_prefix_entry(raw: Any) -> Optional[PrefixEntry]:
    if raw is None:
        return None
    if isinstance(raw, PrefixEntry):
        return raw
    if isinstance(raw, Mapping):
        raw_value = raw.get("value", raw.get("prefix"))
        if isinstance(raw_value, (str, int, float)):
            value_text = str(raw_value).strip()
        else:
            return None
        if not value_text:
            return None
        raw_mode = raw.get("matchMode", raw.get("match_mode"))
        return PrefixEntry(value=value_text, match_mode=_normalise_match_mode(raw_mode if isinstance(raw_mode, str) else None))
    if isinstance(raw, (int, float)):
        value_text = str(raw).strip()
        if not value_text:
            return None
        return PrefixEntry(value=value_text)
    if isinstance(raw, str):
        value_text = raw.strip()
        if not value_text:
            return None
        return PrefixEntry(value=value_text)
    return None


def parse_prefix_entries(raw_value: Any) -> List[PrefixEntry]:
    entries: List[PrefixEntry] = []
    seen: set[Tuple[str, str]] = set()
    for item in _iter_raw_entries(raw_value):
        entry = parse_prefix_entry(item)
        if entry is None:
            continue
        if entry.key in seen:
            continue
        entries.append(entry)
        seen.add(entry.key)
    return entries


def serialise_prefix_entries(entries: Sequence[PrefixEntry]) -> List[Union[str, Dict[str, str]]]:
    return [entry.to_json() for entry in entries]
