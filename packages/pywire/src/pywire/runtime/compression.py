"""Gzip for text responses (HTML, CSS, JS, JSON, SVG, msgpack updates).

Starlette's ``GZipMiddleware`` compresses every content type, which wastes CPU
on images, fonts and archives that are already compressed. This middleware
only compresses types that shrink, passes everything else through, and leaves
responses that already carry a ``Content-Encoding`` alone.
"""

from __future__ import annotations

import zlib
from typing import Any

from starlette.datastructures import Headers, MutableHeaders

_COMPRESSIBLE_TYPES = frozenset(
    {
        "application/javascript",
        "application/json",
        "application/xml",
        "application/x-msgpack",
        "application/wasm",
        "image/svg+xml",
    }
)


def is_compressible(content_type: str) -> bool:
    media_type = content_type.split(";", 1)[0].strip().lower()
    if media_type == "text/event-stream":
        return False
    return (
        media_type.startswith("text/")
        or media_type in _COMPRESSIBLE_TYPES
        or media_type.endswith(("+json", "+xml"))
    )


def gzip_bytes(data: bytes, level: int = 6) -> bytes:
    compressor = zlib.compressobj(level, zlib.DEFLATED, 31)
    return compressor.compress(data) + compressor.flush()


class CompressionMiddleware:
    def __init__(self, app: Any, minimum_size: int = 500, level: int = 6) -> None:
        self.app = app
        self.minimum_size = minimum_size
        self.level = level

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        headers = Headers(raw=scope.get("headers", []))
        if scope["type"] != "http" or "gzip" not in headers.get("accept-encoding", ""):
            await self.app(scope, receive, send)
            return

        start: Any = None
        passthrough = False
        compressor: Any = None  # created with the first compressed chunk

        async def send_compressed(message: Any) -> None:
            nonlocal start, passthrough, compressor
            kind = message["type"]
            if kind == "http.response.start":
                headers = Headers(raw=message["headers"])
                if "content-encoding" in headers or not is_compressible(
                    headers.get("content-type", "")
                ):
                    passthrough = True
                    await send(message)
                else:
                    start = message  # held until the first body chunk
                return
            if passthrough or kind != "http.response.body":
                if start is not None:
                    await send(start)
                    start = None
                await send(message)
                return

            body = message.get("body", b"")
            more_body = message.get("more_body", False)
            if start is not None:
                headers = MutableHeaders(raw=start["headers"])
                headers.add_vary_header("Accept-Encoding")
                if not more_body and len(body) < self.minimum_size:
                    await send(start)
                    start = None
                    await send(message)
                    passthrough = True
                    return
                headers["Content-Encoding"] = "gzip"
                if "content-length" in headers:
                    del headers["Content-Length"]
            if compressor is None:
                compressor = zlib.compressobj(self.level, zlib.DEFLATED, 31)
            data = compressor.compress(body) + compressor.flush(
                zlib.Z_SYNC_FLUSH if more_body else zlib.Z_FINISH
            )
            if start is not None:
                if not more_body:
                    MutableHeaders(raw=start["headers"])["Content-Length"] = str(
                        len(data)
                    )
                await send(start)
                start = None
            await send(
                {"type": "http.response.body", "body": data, "more_body": more_body}
            )

        await self.app(scope, receive, send_compressed)
