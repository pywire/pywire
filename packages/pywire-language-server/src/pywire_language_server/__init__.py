from importlib.metadata import version, PackageNotFoundError

from pywire_language_server import _compat as _compat  # noqa: F401  (runs version floor checks)

try:
    __version__ = version("pywire-language-server")
except PackageNotFoundError:
    __version__ = "unknown"
