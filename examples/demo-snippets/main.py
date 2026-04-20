import os
from pathlib import Path
from pywire import PyWire

base_dir = Path(__file__).parent
interactive = os.environ.get("PYWIRE_INTERACTIVE", "1") != "0"

app = PyWire(
    debug=True,
    pages_dir=base_dir / "pages",
    interactive_server_mode=interactive,
)
