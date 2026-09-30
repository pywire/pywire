"""Taskboard: a FastAPI + pywire app.

Layout (one direction of imports, top to bottom):

    settings   configuration from the environment
    db         engine and sessions
    models     SQLAlchemy tables
    schemas    Pydantic models shared by the JSON API and the page forms
    services   every read and write, with authorization; no HTTP, no pages
    live       fan-out of changes to open pages and raw WebSockets
    identity   who is asking: principals, bearer tokens
    api        FastAPI routes (JSON + WebSocket) on top of services

Pages in ``src/pages`` call ``services`` directly, exactly like ``api`` does.
Neither calls the other over HTTP.
"""
