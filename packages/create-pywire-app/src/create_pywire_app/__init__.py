from importlib.metadata import PackageNotFoundError, version

# Imported for its side effect: runs the version floor checks.
from create_pywire_app import _compat as _compat

try:
    __version__ = version("create-pywire-app")
except PackageNotFoundError:
    __version__ = "unknown"
