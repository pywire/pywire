"""
ASGI HTTP/3 + WebTransport server using aioquic directly.

This module bypasses Hypercorn to use aioquic's native WebTransport support,
which requires explicit enable_webtransport=True in H3Connection initialization.
"""

import asyncio
from typing import Any, Callable, Optional

from aioquic.asyncio import QuicConnectionProtocol, serve  # type: ignore
from aioquic.h3.connection import H3_ALPN, H3Connection  # type: ignore
from aioquic.h3.events import (  # type: ignore
    H3Event,
    HeadersReceived,
)
from aioquic.quic.configuration import QuicConfiguration  # type: ignore
from aioquic.quic.events import ProtocolNegotiated, QuicEvent  # type: ignore


class ASGIProtocol(QuicConnectionProtocol):
    """
    QUIC/HTTP3 protocol handler that routes to ASGI application.

    Handles WebTransport by creating H3Connection with enable_webtransport=True.
    """

    def __init__(self, quic: Any, *args: Any, app_factory: Callable, **kwargs: Any) -> None:
        super().__init__(quic, *args, **kwargs)
        self._http: Optional[H3Connection] = None
        self._app_factory = app_factory
        self._app: Optional[Callable] = None

    def quic_event_received(self, event: QuicEvent) -> None:
        """Handle QUIC events, including protocol negotiation."""
        if isinstance(event, ProtocolNegotiated):
            if event.alpn_protocol in H3_ALPN:
                # CRITICAL: Enable WebTransport support
                self._http = H3Connection(self._quic, enable_webtransport=True)
                print("PyWire: HTTP/3 connection established with WebTransport enabled", flush=True)

        # Pass events to HTTP/3 layer
        if self._http is not None:
            for http_event in self._http.handle_event(event):
                self.http_event_received(http_event)

    def http_event_received(self, event: H3Event) -> None:
        """Route HTTP/3 events to ASGI application."""
        if isinstance(event, HeadersReceived):
            # Parse ASGI scope from headers
            scope = self._build_scope(event)
            print(
                f"PyWire: Received {scope['type']} request to {scope.get('path', '/')}", flush=True
            )

            # Create ASGI handler
            if self._app is None:
                self._app = self._app_factory()

            # Dispatch to ASGI app
            asyncio.ensure_future(self._handle_asgi(scope, event))

    def _build_scope(self, event: HeadersReceived) -> dict:
        """Build ASGI scope dictionary from HTTP/3 headers."""
        headers = []
        method = ""
        path = "/"
        protocol = None

        for header, value in event.headers:
            if header == b":method":
                method = value.decode()
            elif header == b":path":
                path = value.decode()
            elif header == b":protocol":
                protocol = value.decode()
            elif header and not header.startswith(b":"):
                headers.append((header, value))

        # Determine scope type
        if method == "CONNECT" and protocol == "webtransport":
            scope_type = "webtransport"
        else:
            scope_type = "http"

        return {
            "type": scope_type,
            "asgi": {"version": "3.0"},
            "http_version": "3",
            "method": method,
            "path": path,
            "headers": headers,
            "server": ("localhost", 3000),
        }

    async def _handle_asgi(self, scope: dict, event: HeadersReceived) -> None:
        """Handle ASGI application invocation."""
        stream_id = event.stream_id

        # Create receive/send callables
        async def receive() -> dict:
            # For WebTransport: wait for connect message
            if scope["type"] == "webtransport":
                return {"type": "webtransport.connect"}
            return {"type": "http.request"}

        async def send(message: dict) -> None:
            msg_type = message["type"]
            print(f"PyWire: Sending {msg_type} on stream {stream_id}", flush=True)

            if msg_type == "webtransport.accept":
                # Send 200 OK for WebTransport
                if self._http:
                    self._http.send_headers(
                        stream_id=stream_id,
                        headers=[
                            (b":status", b"200"),
                            (b"sec-webtransport-http3-draft", b"draft02"),
                        ],
                    )
                print(f"PyWire: WebTransport connection accepted on stream {stream_id}", flush=True)
            elif msg_type == "http.response.start":
                status = message.get("status", 200)
                response_headers = message.get("headers", [])
                if self._http:
                    self._http.send_headers(
                        stream_id=stream_id,
                        headers=[(b":status", str(status).encode())] + response_headers,
                    )
            elif msg_type == "http.response.body":
                data = message.get("body", b"")
                if self._http:
                    self._http.send_data(
                        stream_id=stream_id,
                        data=data,
                        end_stream=not message.get("more_body", False),
                    )

            self.transmit()

        # Dispatch to ASGI app
        if self._app:
            await self._app(scope, receive, send)


async def run_aioquic_server(
    app_factory: Callable,
    host: str,
    port: int,
    certfile: str,
    keyfile: str,
) -> None:
    """
    Run HTTP/3 + WebTransport server using aioquic directly.

    Args:
        app_factory: Callable that returns ASGI application
        host: Host to bind to
        port: Port to bind to
        certfile: Path to SSL certificate
        keyfile: Path to SSL private key
    """
    # Configure QUIC
    configuration = QuicConfiguration(
        alpn_protocols=H3_ALPN,
        is_client=False,
        max_datagram_frame_size=65536,
    )
    configuration.load_cert_chain(certfile, keyfile)

    # Create protocol factory
    # Create protocol factory
    def create_protocol(*args: Any, **kwargs: Any) -> ASGIProtocol:
        if "app_factory" in kwargs:
            del kwargs["app_factory"]
        return ASGIProtocol(*args, app_factory=app_factory, **kwargs)

    # Start server
    print(f"PyWire: Starting aioquic HTTP/3 server on {host}:{port}", flush=True)
    await serve(
        host,
        port,
        configuration=configuration,
        create_protocol=create_protocol,  # type: ignore
    )
