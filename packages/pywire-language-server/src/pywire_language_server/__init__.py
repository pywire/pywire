try:
    from ._version import __version__
except ImportError:
    from importlib.metadata import version, PackageNotFoundError

    try:
        __version__ = version("pywire-language-server")
    except PackageNotFoundError:
        __version__ = "unknown"
