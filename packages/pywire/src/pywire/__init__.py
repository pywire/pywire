from importlib.metadata import version, PackageNotFoundError
from typing import Optional, TYPE_CHECKING

try:
    __version__ = version("pywire")
except PackageNotFoundError:
    __version__ = "unknown"

if TYPE_CHECKING:
    from pywire.runtime.app import PyWire as _PyWireType

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
from pywire.core.refs import (
    ref,
    Ref,
    MediaElement,
    DialogElement,
    CanvasElement,
)
from pywire.core.dispatch import dispatch
from pywire.core.wire import WireDict
from pywire.core.snippet import Snippet, Child, Children
from pywire.runtime.importer import install_import_hook

install_import_hook()

# Ambient reference to the first-constructed PyWire instance in this process.
# Set by PyWire.__init__ (first-wins). Pages can import this at script top
# level to access shared app state (app.state.X) without a circular import
# on main.py. Subsequent PyWire constructions (test fixtures, mounted
# sub-apps) do not overwrite this — each such instance is reachable via
# request.app on its own requests.
app: Optional["_PyWireType"] = None

__all__ = [
    "app",
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
    "MediaElement",
    "DialogElement",
    "CanvasElement",
    "writable",
    "readable",
    "store_derived",
    "Snippet",
    "Child",
    "Children",
]
