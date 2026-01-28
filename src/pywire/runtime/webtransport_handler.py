"""WebTransport handler using ASGI standard.

Handles 'webtransport' scope type from Hypercorn.
"""

import json
from typing import Any, Dict, Set

from pywire.runtime.page import BasePage


class WebTransportHandler:
    """Handles WebTransport connections."""

    def __init__(self, app: Any) -> None:
        self.app = app
        # Store active sessions/connections
        # For WebTransport, the 'scope' is the connection identifier
        self.active_connections: Set[Any] = set()

        # Map connection -> current page instance
        self.connection_pages: Dict[Any, BasePage] = {}

    async def handle(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        """Handle ASGI webtransport scope."""
        print("DEBUG: WebTransport handler started")
        # Active streams buffer: stream_id -> bytes
        streams: Dict[int, bytearray] = {}

        # 1. Wait for connection request
        try:
            message = await receive()
            print(f"DEBUG: WebTransport received initial message: {message['type']}")
            if message["type"] != "webtransport.connect":
                print(f"DEBUG: Unexpected message type: {message['type']}")
                return
        except Exception as e:
            print(f"DEBUG: Error receiving connect message: {e}")
            return

        # 2. Accept connection
        await send({"type": "webtransport.accept"})
        print("DEBUG: WebTransport connection accepted")

        # Register connection (using the receive channel as ID or scope object)
        # Since scope is mutable dictionary, we use its id() or just the object if stable
        connection_id = id(scope)
        self.active_connections.add(connection_id)

        try:
            while True:
                message = await receive()
                msg_type = message["type"]
                # print(f"DEBUG: Received WT message: {msg_type}")

                if msg_type == "webtransport.stream.connect":
                    # New bidirectional stream opened by client
                    stream_id = message["stream_id"]
                    streams[stream_id] = bytearray()
                    # print(f"DEBUG: Stream {stream_id} connected")

                elif msg_type == "webtransport.stream.receive":
                    stream_id = message["stream_id"]
                    data = message.get("data", b"")

                    if stream_id not in streams:
                        # Stream might have been accepted implicitly or we missed connect
                        streams[stream_id] = bytearray()

                    streams[stream_id].extend(data)

                    # Check if stream is finished (some impls use 'more_body', others 'fin')
                    # Hypercorn uses 'more_body' (True if more coming)
                    more_body = message.get("more_body", False)

                    if not more_body:
                        # Full message received
                        payload = streams[stream_id]
                        del streams[stream_id]  # Clear buffer

                        # Process message
                        try:
                            json_data = json.loads(payload.decode("utf-8"))
                            await self._handle_message(json_data, scope, send, stream_id)
                        except Exception as e:
                            print(f"WebTransport message error: {e}")

                elif msg_type == "webtransport.disconnect":
                    break

        except Exception as e:
            print(f"WebTransport handler error: {e}")
        finally:
            self.active_connections.discard(connection_id)
            if connection_id in self.connection_pages:
                del self.connection_pages[connection_id]

    async def _handle_message(
        self, data: dict[str, Any], scope: dict[str, Any], send: Any, stream_id: int
    ) -> None:
        """Handle decoded JSON message."""
        msg_type = data.get("type")
        connection_id = id(scope)

        if msg_type == "event":
            # Handle event
            if connection_id in self.connection_pages:
                page = self.connection_pages[connection_id]
                handler_name = data.get("handler")
                event_data = data.get("data", {})

                try:
                    if handler_name and isinstance(handler_name, str):
                        # Execute handler
                        response = await page.handle_event(handler_name, event_data)
                    else:
                        raise ValueError("Invalid handler name")

                    # If response is HTML, send update
                    if hasattr(response, "body"):
                        html = bytes(response.body).decode("utf-8")
                        response_data = {"type": "update", "html": html}
                        await self._send_response(send, stream_id, response_data)

                except Exception as e:
                    # Send error response (no print - response is sufficient)
                    await self._send_response(send, stream_id, {"type": "error", "error": str(e)})

        elif msg_type == "init":
            # Initialize page for this connection (similar to WS)
            # Parse path and instantiate page
            path = data.get("path", "/")
            match = self.app.router.match(path)
            if match:
                page_class, params, variant_name = match
                # Mock request object? Or extract from scope
                # We need a Request-like object for Page init
                from starlette.requests import Request

                request = Request(scope)
                query = dict(request.query_params)

                # Build path info dict
                path_info = {}
                if hasattr(page_class, "__routes__"):
                    for name in page_class.__routes__.keys():
                        path_info[name] = name == variant_name
                elif hasattr(page_class, "__route__"):
                    path_info["main"] = True

                # Build URL helper
                from pywire.runtime.router import URLHelper

                url_helper = None
                if hasattr(page_class, "__routes__"):
                    url_helper = URLHelper(page_class.__routes__)

                page = page_class(request, params, query, path=path_info, url=url_helper)
                if hasattr(self.app, "get_user"):
                    page.user = self.app.get_user(request)

                self.connection_pages[connection_id] = page

    async def _send_response(self, send: Any, stream_id: int, data: dict[str, Any]) -> None:
        """Send response back on the same stream."""
        payload = json.dumps(data).encode("utf-8")
        await send(
            {
                "type": "webtransport.stream.send",
                "stream_id": stream_id,
                "data": payload,
                "finish": True,  # Close the stream after sending
            }
        )

    async def broadcast_reload(self) -> None:
        """Broadcast reload to all active WebTransport connections."""
        # For broadcast, we must initiate a NEW stream for each connection
        # But we don't have reference to 'send' callable for each connection here!
        # The 'send' is only available inside the 'handle' loop.

        # This is a problem with the simple loop approach.
        # We need a way to inject messages into the handle loops.
        pass

        # Solution: Use an asyncio.Queue for each connection, and have the handle loop
        # wait for EITHER 'receive()' OR 'queue.get()'.
