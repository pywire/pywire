from pywire import PyWire

# Stateless mode signs the client-held page state with PYWIRE_SECRET_KEY
# (at least 32 bytes). Anyone with the key can forge snapshots, so it comes
# from the environment and is never committed.
app = PyWire(pages_dir="src/pages", stateless=True)
