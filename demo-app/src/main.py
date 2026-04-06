"""Main entry point for demo app."""
from pywire import PyWire
from pathlib import Path

# Get the pages directory
pages_dir = Path(__file__).parent / "pages"

# Create app instance
app = PyWire(
    pages_dir = str(pages_dir),
    path_based_routing=False,
    static_dir="static",
    debug=True
)
