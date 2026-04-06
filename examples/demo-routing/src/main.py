from pathlib import Path
from pywire import PyWire

# Get the pages directory
pages_dir = Path(__file__).parent / "pages"

# Create application instance
app = PyWire(
    pages_dir=str(pages_dir),
    enable_pjax=True
)
