from pathlib import Path
from pywire import PyWire

base_dir = Path(__file__).parent
app = PyWire(debug=True, pages_dir=base_dir / "pages")