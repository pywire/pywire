from pywire import PyWire

app = PyWire(
    pages_dir="./pages",
    debug=True,
    ws_ping_interval=5,     # Ping every 5s so keep-alive is verifiable quickly
    ws_ping_timeout=3,
    reconnect_max_attempts=5,
    reconnect_overlay=True,
    session_ttl=30,         # Short TTL to test session expiry toast
)
