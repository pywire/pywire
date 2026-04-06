
import sys
import os
from pathlib import Path
from unittest.mock import MagicMock

# Mock problematic modules that require compiled extensions
sys.modules["pywire.runtime.loader"] = MagicMock()
sys.modules["pywire.runtime.webtransport_handler"] = MagicMock()

from pywire.runtime.app import PyWire

class TestPyWire(PyWire):
    def _load_pages(self) -> None:
        print("Mocked _load_pages")

    def __init__(self, *args, **kwargs):
        # Prevent router init from failing if it imports things?
        # Router is imported at module level in app.py.
        super().__init__(*args, **kwargs)

# We expect pages to be sibling to this file
# This relative path "pages" should resolve to current_dir / "pages"
app = TestPyWire(pages_dir="pages", static_dir="static")

print(f"Pages Dir: {app.pages_dir}")
if app.static_dir:
    print(f"Static Dir: {app.static_dir}")
else:
    print(f"Static Dir: None")
