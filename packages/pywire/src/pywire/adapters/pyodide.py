"""Pyodide ASGI adapter for running PyWire in browser/WASM environments.

Provides a clean bridge between JavaScript/Pyodide and PyWire's ASGI interface.
Used by the docs tutorial, Cloudflare Python Workers, and Claude.ai/chatbot
Pyodide sandboxes.

This module is pure Python with no js/pyodide imports — caller code handles
the JS interop layer.
"""

from __future__ import annotations

import asyncio
import traceback
import uuid
from typing import Any, Dict, List, Optional, Tuple


class PyodideASGIAdapter:
    """Adapts a PyWire ASGI app for use in Pyodide/browser environments.

    Provides simple methods for HTTP requests and WebSocket connections
    without requiring knowledge of the ASGI protocol.
    """

    def __init__(self, app: Any) -> None:
        self.app = app
        self._ws_connections: Dict[str, asyncio.Queue] = {}

    async def fetch(
        self,
        method: str = "GET",
        path: str = "/",
        headers: Optional[Dict[str, str]] = None,
        body: bytes = b"",
        query_string: str = "",
    ) -> Tuple[int, List[Tuple[str, str]], str]:
        """Make an HTTP request to the ASGI app.

        Returns (status_code, response_headers, body_text).
        """
        if headers is None:
            headers = {}

        scope = {
            "type": "http",
            "http_version": "1.1",
            "method": method.upper(),
            "path": path,
            "root_path": "",
            "scheme": "http",
            "query_string": query_string.encode("utf-8") if query_string else b"",
            "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
            "server": ("localhost", 80),
            "client": ("client", 0),
        }

        receive_queue: asyncio.Queue = asyncio.Queue()
        receive_queue.put_nowait(
            {
                "type": "http.request",
                "body": body if isinstance(body, bytes) else body.encode("utf-8"),
                "more_body": False,
            }
        )

        status = 200
        response_headers: List[Tuple[str, str]] = []
        body_parts: List[bytes] = []

        async def receive():
            return await receive_queue.get()

        async def send(message: dict):
            nonlocal status, response_headers
            msg_type = message.get("type")
            if msg_type == "http.response.start":
                status = message.get("status", 200)
                raw_headers = message.get("headers", [])
                response_headers = [
                    (
                        k.decode("utf-8") if isinstance(k, bytes) else k,
                        v.decode("utf-8") if isinstance(v, bytes) else v,
                    )
                    for k, v in raw_headers
                ]
            elif msg_type == "http.response.body":
                body_parts.append(message.get("body", b""))

        try:
            await self.app(scope, receive, send)
        except Exception as exc:
            if not getattr(self.app, "debug", False):
                raise  # Don't leak tracebacks outside debug mode
            tb = traceback.format_exc()
            error_html = (
                "<!DOCTYPE html><html><head>"
                "<style>"
                "body{font-family:monospace;margin:0;padding:24px;background:#fff;color:#111}"
                "h2{color:#c00;margin:0 0 12px;font-size:1.1em}"
                "pre{background:#fff0f0;border:1px solid #fcc;padding:16px;"
                "border-radius:4px;overflow:auto;white-space:pre-wrap;word-break:break-word;"
                "font-size:0.85em;line-height:1.5}"
                "</style></head><body>"
                f"<h2>&#9888; {type(exc).__name__}: {exc}</h2>"
                f"<pre>{tb}</pre>"
                "</body></html>"
            )
            return 500, [("content-type", "text/html")], error_html

        full_body = b"".join(body_parts)
        try:
            body_text = full_body.decode("utf-8")
        except UnicodeDecodeError:
            body_text = full_body.hex()

        return status, response_headers, body_text

    async def ws_connect(
        self,
        path: str = "/_pywire/ws",
        headers: Optional[Dict[str, str]] = None,
    ) -> str:
        """Open a WebSocket connection to the ASGI app.

        Returns a connection_id for use with ws_send/ws_receive.
        """
        if headers is None:
            headers = {}

        connection_id = str(uuid.uuid4())
        receive_queue: asyncio.Queue = asyncio.Queue()
        self._ws_connections[connection_id] = receive_queue

        scope = {
            "type": "websocket",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "scheme": "ws",
            "path": path,
            "root_path": "",
            "query_string": b"",
            "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
            "server": ("localhost", 80),
            "client": ("client", 0),
        }

        send_queue: asyncio.Queue = asyncio.Queue()
        self._ws_connections[f"{connection_id}_send"] = send_queue

        async def receive():
            return await receive_queue.get()

        async def send(message: dict):
            await send_queue.put(message)

        # Queue the initial connect event
        receive_queue.put_nowait({"type": "websocket.connect"})

        # Start the ASGI app as a background task
        asyncio.create_task(self.app(scope, receive, send))

        # Wait for the accept message
        accept_msg = await send_queue.get()
        if accept_msg.get("type") != "websocket.accept":
            self._ws_connections.pop(connection_id, None)
            self._ws_connections.pop(f"{connection_id}_send", None)
            raise ConnectionError(
                f"WebSocket connection rejected: {accept_msg.get('type')}"
            )

        return connection_id

    async def ws_send(self, connection_id: str, data: bytes) -> None:
        """Send binary data over a WebSocket connection."""
        receive_queue = self._ws_connections.get(connection_id)
        if receive_queue is None:
            raise KeyError(f"No WebSocket connection: {connection_id}")
        receive_queue.put_nowait({"type": "websocket.receive", "bytes": data})

    async def ws_send_text(self, connection_id: str, text: str) -> None:
        """Send text data over a WebSocket connection."""
        receive_queue = self._ws_connections.get(connection_id)
        if receive_queue is None:
            raise KeyError(f"No WebSocket connection: {connection_id}")
        receive_queue.put_nowait({"type": "websocket.receive", "text": text})

    async def ws_receive(self, connection_id: str) -> dict:
        """Receive the next message from a WebSocket connection.

        Returns the raw ASGI message dict (type, bytes/text).
        """
        send_queue = self._ws_connections.get(f"{connection_id}_send")
        if send_queue is None:
            raise KeyError(f"No WebSocket connection: {connection_id}")
        return await send_queue.get()

    async def ws_close(self, connection_id: str) -> None:
        """Close a WebSocket connection."""
        receive_queue = self._ws_connections.get(connection_id)
        if receive_queue is not None:
            receive_queue.put_nowait(
                {
                    "type": "websocket.disconnect",
                    "code": 1000,
                }
            )
        self._ws_connections.pop(connection_id, None)
        self._ws_connections.pop(f"{connection_id}_send", None)
