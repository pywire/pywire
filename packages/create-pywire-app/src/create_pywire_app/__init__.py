from importlib.metadata import version, PackageNotFoundError

from create_pywire_app import _compat as _compat  # noqa: F401  (runs version floor checks)

try:
    __version__ = version("create-pywire-app")
except PackageNotFoundError:
    __version__ = "unknown"
