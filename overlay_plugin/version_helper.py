"""Helpers for checking the published Modern Overlay release version."""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Optional
from urllib.error import URLError, HTTPError
from urllib.request import Request, urlopen

LATEST_RELEASE_API = "https://api.github.com/repos/SweetJonnySauce/EDMC-ModernOverlay/releases/latest"
_USER_AGENT = "EDMC-ModernOverlay/version-check"
_TOKEN_SPLIT = re.compile(r"[.\-+_]")

try:  # Optional dependency; fall back to lightweight comparator when unavailable.
    from packaging.version import Version as _PkgVersion  # type: ignore
    from packaging.version import InvalidVersion as _PkgInvalidVersion  # type: ignore
except Exception:  # pragma: no cover - packaging not installed
    _PkgVersion = None  # type: ignore
    _PkgInvalidVersion = Exception  # type: ignore


@dataclass(frozen=True)
class VersionStatus:
    """Outcome of an upstream release check."""

    current_version: str
    latest_version: Optional[str]
    is_outdated: bool
    checked_at: float
    error: Optional[str] = None

    @property
    def update_available(self) -> bool:
        return self.is_outdated and self.latest_version is not None


def evaluate_version_status(current_version: str, timeout: float = 2.0) -> VersionStatus:
    """Fetch the latest GitHub release and compare against the running version."""

    checked_at = time.time()
    latest_version: Optional[str] = None
    error: Optional[str] = None
    try:
        latest_version = _fetch_latest_release_version(timeout=timeout)
    except Exception as exc:  # pragma: no cover - network/runtime failure
        error = str(exc)
    is_outdated = False
    if latest_version:
        is_outdated = _compare_versions(current_version, latest_version) < 0
    return VersionStatus(
        current_version=current_version,
        latest_version=latest_version,
        is_outdated=is_outdated,
        checked_at=checked_at,
        error=error,
    )


def _fetch_latest_release_version(timeout: float = 2.0) -> Optional[str]:
    request = Request(
        LATEST_RELEASE_API,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": _USER_AGENT,
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError(f"GitHub request failed: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Unable to parse GitHub response: {exc}") from exc
    latest = (payload.get("tag_name") or payload.get("name") or "").strip()
    return latest or None


def _compare_versions(current: str, latest: str) -> int:
    if _PkgVersion is not None:
        try:
            current_version = _PkgVersion(current)
            latest_version = _PkgVersion(latest)
            if current_version < latest_version:
                return -1
            if current_version > latest_version:
                return 1
            return 0
        except _PkgInvalidVersion:
            pass
    return _fallback_compare(current, latest)


def _fallback_compare(current: str, latest: str) -> int:
    current_tokens = _tokenize(current)
    latest_tokens = _tokenize(latest)
    length = min(len(current_tokens), len(latest_tokens))
    for index in range(length):
        cur = current_tokens[index]
        lat = latest_tokens[index]
        if cur == lat:
            continue
        # Numeric tokens outrank string tokens.
        if cur[0] != lat[0]:
            return 1 if cur[0] == "num" else -1
        if cur[1] < lat[1]:
            return -1
        return 1
    if len(current_tokens) == len(latest_tokens):
        return 0
    longer_tokens = current_tokens if len(current_tokens) > len(latest_tokens) else latest_tokens
    remainder = longer_tokens[length:]
    if not remainder:
        return 0
    # Additional numeric tokens imply a greater version, string tokens imply a pre-release.
    for token in remainder:
        if token[0] == "num":
            if token[1] == 0:
                continue
            return 1 if len(current_tokens) > len(latest_tokens) else -1
        return -1 if len(current_tokens) > len(latest_tokens) else 1
    return 0


def _tokenize(value: str) -> list[tuple[str, object]]:
    tokens = []
    for part in _TOKEN_SPLIT.split(value):
        if not part:
            continue
        if part.isdigit():
            tokens.append(("num", int(part)))
        else:
            tokens.append(("str", part.lower()))
    return tokens
