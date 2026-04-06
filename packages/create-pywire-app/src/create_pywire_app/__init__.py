from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("create-pywire-app")
except PackageNotFoundError:
    __version__ = "unknown"
