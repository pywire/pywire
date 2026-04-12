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
from pywire.core.stores import writable, readable, store_derived
from pywire.core.props import props
from pywire.core.expose import expose
from pywire.core.event_handler import EventHandler
from pywire.core.refs import ref, Ref
from pywire.core.dispatch import dispatch
from pywire.core.wire import WireDict
from pywire.runtime.importer import install_import_hook

install_import_hook()

__all__ = [
    "PyWire",
    "BasePage",
    "wire",
    "WireDict",
    "derived",
    "effect",
    "props",
    "expose",
    "EventHandler",
    "CircularDependencyError",
    "ReactivityError",
    "ref",
    "Ref",
    "dispatch",
    "writable",
    "readable",
    "store_derived",
]
