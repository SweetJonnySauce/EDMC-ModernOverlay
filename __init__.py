"""Package marker to make EDMC load ModernOverlay before dependent plugins."""

# Re-export the legacy compatibility facade so `from EDMCOverlay import edmcoverlay`
# succeeds as soon as this package is on sys.path. When this module is executed
# outside a package context (e.g. running tests from a checkout), fall back to
# absolute imports.
try:
    from .EDMCOverlay import edmcoverlay  # type: ignore  # noqa: F401
    from .version import __version__  # type: ignore  # noqa: F401
except ImportError:  # pragma: no cover - fallback for direct execution
    from EDMCOverlay import edmcoverlay  # type: ignore  # noqa: F401
    from version import __version__  # type: ignore  # noqa: F401

__all__ = ["edmcoverlay", "__version__"]
