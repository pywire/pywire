from pywire.runtime.app import PyWire

app = PyWire(
    "./pages",
    stateless=True,
    secret_key="test-secret-key-at-least-32-bytes",
    debug=True,
)
