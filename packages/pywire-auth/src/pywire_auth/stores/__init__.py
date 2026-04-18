"""Auth store adapters."""

from pywire_auth.stores.memory import MemoryAuthStore

__all__ = ["MemoryAuthStore"]

# SQLAlchemyAuthStore is optional — only importable when the
# pywire-auth[sqlalchemy] extra is installed. Surface a lazy re-export so
# `from pywire_auth import SQLAlchemyAuthStore` works without forcing
# sqlalchemy into every app's venv.
try:
    from pywire_auth.stores.sqlalchemy import SQLAlchemyAuthStore  # noqa: F401

    __all__.append("SQLAlchemyAuthStore")
except ImportError:
    pass
