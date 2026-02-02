try:
    from ._version import __version__
except ImportError:
    from importlib.metadata import version, PackageNotFoundError

    try:
        __version__ = version("pywire")
    except PackageNotFoundError:
        __version__ = "unknown"

from .runtime.app import PyWire as PyWire
from .core.wire import wire as wire
