"""Helpers for checking the published Modern Overlay release version."""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Optional

LATEST_RELEASE_API = "https://api.github.com/repos/SweetJonnySauce/EDMC-ModernOverlay/releases/latest"
_DEFAULT_USER_AGENT = "EDMCModernOverlay/version-check"
_TOKEN_SPLIT = re.compile(r"[.\-+_]")

try:  # Optional dependency; fall back to lightweight comparator when unavailable.
    from packaging.version import Version as _PkgVersion  # type: ignore
    from packaging.version import InvalidVersion as _PkgInvalidVersion  # type: ignore
except Exception:  # pragma: no cover - packaging not installed
    _PkgVersion = None  # type: ignore
    _PkgInvalidVersion = Exception  # type: ignore

try:  # Prefer EDMC's helper to inherit certifi/timeouts.
    from timeout_session import new_session as _edmc_new_session  # type: ignore
except Exception:  # pragma: no cover - fallback when unavailable
    _edmc_new_session = None  # type: ignore

try:
    from config import debug_senders as _edmc_debug_senders  # type: ignore
except Exception:  # pragma: no cover - running outside EDMC
    _edmc_debug_senders = None  # type: ignore

try:
    from config import user_agent as _edmc_user_agent  # type: ignore
except Exception:  # pragma: no cover - running outside EDMC
    _edmc_user_agent = None  # type: ignore

try:
    import requests
    from requests import Response
    from requests import exceptions as requests_exceptions
except Exception:  # pragma: no cover - requests not available
    requests = None  # type: ignore
    Response = None  # type: ignore
    requests_exceptions = None  # type: ignore


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
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": _build_user_agent(),
    }
    payload = _request_latest_release(headers=headers, timeout=timeout)
    latest = (payload.get("tag_name") or payload.get("name") or "").strip()
    return latest or None


def _request_latest_release(*, headers: dict[str, str], timeout: float) -> dict[str, object]:
    if requests is None:
        raise RuntimeError("requests library is unavailable; cannot check latest release")

    session_timeout = max(int(timeout), 1)
    session = _create_http_session(session_timeout)
    if session is None:
        raise RuntimeError("Failed to initialise HTTP session for release check")

    response: Optional[Response] = None
    try:
        response = session.get(LATEST_RELEASE_API, headers=headers, timeout=timeout)
        response.raise_for_status()
    except Exception as exc:
        # If requests raised a specific exception, transparently wrap it.
        if requests_exceptions and isinstance(exc, requests_exceptions.RequestException):
            raise RuntimeError(f"GitHub request failed: {exc}") from exc
        raise RuntimeError(f"Unable to fetch latest release: {exc}") from exc

    try:
        return response.json()
    except ValueError as exc:  # pragma: no cover - invalid JSON
        raise RuntimeError(f"Unable to parse GitHub response: {exc}") from exc
    finally:
        response.close()
        session.close()


def _create_http_session(timeout: int):
    if _edmc_new_session is not None:
        try:
            session = _edmc_new_session(timeout=timeout)
            session.headers.setdefault("User-Agent", _build_user_agent())
            _apply_debug_sender(session)
            return session
        except Exception:
            pass
    if requests is not None:
        session = requests.Session()
        session.headers.setdefault("User-Agent", _build_user_agent())
        _apply_debug_sender(session)
        return session
    return None


def _apply_debug_sender(session) -> None:
    """Redirect requests through EDMC's debug webserver when configured."""

    debug_target = None
    try:
        debug_target = _edmc_debug_senders() if callable(_edmc_debug_senders) else _edmc_debug_senders
    except Exception:
        debug_target = None
    if not debug_target:
        return
    try:
        if hasattr(session, "mount"):
            adapter = session.get_adapter("http://")
            session.mount("https://", adapter)
            session.mount("http://", adapter)
        session.proxies = {"http": debug_target, "https": debug_target}
    except Exception:
        pass


def _build_user_agent() -> str:
    base = _resolve_edmc_user_agent()
    if base:
        return f"{base} {_DEFAULT_USER_AGENT}"
    return _DEFAULT_USER_AGENT


def _resolve_edmc_user_agent() -> Optional[str]:
    if _edmc_user_agent is None:
        return None
    try:
        return _edmc_user_agent() if callable(_edmc_user_agent) else str(_edmc_user_agent)
    except Exception:
        return None


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
