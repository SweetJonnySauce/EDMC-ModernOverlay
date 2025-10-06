"""Compatibility facade so other plugins can `from EDMCOverlay import edmcoverlay`."""

from . import edmcoverlay  # re-export module for legacy imports

__all__ = ["edmcoverlay"]
