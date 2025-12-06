from __future__ import annotations

import sys
import traceback


def safe_getattr(obj, name: str, default=None):
    """Bypass Tk __getattr__ recursion when accessing private attrs."""
    try:
        return object.__getattribute__(obj, name)
    except AttributeError:
        return default


def log_exception(logger, context: str, exc: Exception) -> None:
    """Log an unexpected exception to the provided logger and stderr."""
    try:
        logger("%s: %s", context, exc)
    except Exception:
        pass
    traceback.print_exception(type(exc), exc, exc.__traceback__, file=sys.stderr)
