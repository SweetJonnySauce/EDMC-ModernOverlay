"""Package marker to make EDMC load ModernOverlay before dependent plugins."""

# Re-export the legacy compatibility facade so `from EDMCOverlay import edmcoverlay`
# succeeds as soon as this package is on sys.path.
from .EDMCOverlay import edmcoverlay  # noqa: F401
from .version import __version__  # noqa: F401

__all__ = ["edmcoverlay", "__version__"]
