"""Server factory for uvicorn."""

from pathlib import Path
from typing import Any, Optional

from pywire.runtime.app import PyWire


def create_app(pages_dir: Optional[Path] = None, reload: bool = False) -> Any:
    """Create ASGI app - used by uvicorn."""
    if pages_dir is None:
        # Default pages directory
        pages_dir = Path("pages")

        # Try to find pages directory
        if not pages_dir.exists():
            # Try src/pages
            pages_dir = Path("src/pages")

    app = PyWire(str(pages_dir))
    # Store references to handlers in state for dev server access
    app.app.state.ws_handler = app.ws_handler
    app.app.state.http_handler = app.http_handler
    app.app.state.pywire_app = app
    return app.app
