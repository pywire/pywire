try:
    from ._version import __version__
except ImportError:
    from importlib.metadata import version, PackageNotFoundError

    try:
        __version__ = version("pywire")
    except PackageNotFoundError:
        __version__ = "unknown"

from pywire.runtime.app import PyWire
from pywire.runtime.page import BasePage
from pywire.core.wire import wire
from pywire.core.signals import (
    derived,
    effect,
    CircularDependencyError,
    ReactivityError,
)
from pywire.core.props import props
from pywire.core.expose import expose
from pywire.runtime.importer import install_import_hook

install_import_hook()

__all__ = [
    "PyWire",
    "BasePage",
    "wire",
    "derived",
    "effect",
    "props",
    "expose",
    "CircularDependencyError",
    "ReactivityError",
]
