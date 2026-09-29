import os

from pywire.runtime.app import PyWire

# Served at /demo, as if behind a proxy. The dev server receives both
# prefixed and unprefixed paths, like a proxy that doesn't strip.
app = PyWire(
    "./pages",
    base_path="/demo",
    stateless=os.environ.get("E2E_STATELESS") == "1",
    secret_key="test-secret-key-at-least-32-bytes",
)
