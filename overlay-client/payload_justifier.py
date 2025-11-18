"""Utilities for aligning payloads within an idPrefix group."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Sequence, Tuple

_JUSTIFIABLE = {"center", "right"}


@dataclass(frozen=True)
class JustificationRequest:
    """Minimal information required to compute a justification offset."""

    identifier: Any
    key: Tuple[str, Optional[str]]
    suffix: Optional[str]
    justification: str
    width: float
    baseline_width: Optional[float] = None


def calculate_offsets(requests: Sequence[JustificationRequest]) -> Dict[Any, float]:
    """Return horizontal offsets for justifying payloads within each group."""

    groups: Dict[Tuple[str, Optional[str]], list[Tuple[JustificationRequest, float]]] = {}
    for request in requests:
        if request.suffix is None:
            continue
        if request.justification not in _JUSTIFIABLE:
            continue
        width = max(0.0, float(request.width))
        groups.setdefault(request.key, []).append((request, width))

    offsets: Dict[Any, float] = {}
    for entries in groups.values():
        if not entries:
            continue
        baseline: Optional[float] = None
        for request, width in entries:
            if request.baseline_width and request.baseline_width > 0.0:
                baseline = max(baseline or 0.0, request.baseline_width)
        if baseline is None:
            baseline = max(width for _, width in entries)
        baseline = max(0.0, float(baseline))
        if baseline <= 0.0:
            continue
        for request, width in entries:
            delta = baseline - width
            if delta <= 0.0:
                continue
            if request.justification == "center":
                delta *= 0.5
            offsets[request.identifier] = delta

    return offsets
