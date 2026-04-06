from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("pywire-language-server")
except PackageNotFoundError:
    __version__ = "unknown"
