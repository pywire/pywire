import os

from pywire import PyWire

app = PyWire(
    pages_dir="src/pages",
    stateless=True,
    # HMAC key for the client-held state snapshots. Set PYWIRE_SECRET_KEY in
    # any real deployment — the fallback below is a dev-only convenience and
    # must never ship (anyone with the key can forge snapshots).
    secret_key=os.environ.get("PYWIRE_SECRET_KEY", "dev-only-insecure-fallback-key"),
    debug=True,
)
