"""Main entry point for demo security app."""
from pywire import PyWire

app = PyWire(
    path_based_routing=True,
    debug=True,
)
