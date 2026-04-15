"""Main ASGI application."""

import logging
import os
import re
import traceback
import inspect
import hashlib
import json
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, cast

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, Response
from starlette.routing import Mount, Route, WebSocketRoute
from starlette.staticfiles import StaticFiles

from pywire import __version__
from pywire.runtime.error_page import ErrorPage
from pywire.runtime.http_transport import HTTPTransportHandler
from pywire.runtime.router import Router
from pywire.runtime.upload_manager import upload_manager
from pywire.runtime.websocket import WebSocketHandler

logger = logging.getLogger(__name__)


async def RequestContextMiddleware(scope, receive, send, app):
    if scope["type"] != "http":
        await app(scope, receive, send)
        return

    from pywire.shell import _request_ctx
    from starlette.requests import Request

    request = Request(scope, receive, send)
    token = _request_ctx.set(request)
    try:
        await app(scope, receive, send)
    finally:
        _request_ctx.reset(token)


class PyWire:
    """Main ASGI application and configuration."""

    def _get_caller_dir(self) -> Path:
        """Find the directory of the code that instantiated PyWire."""
        try:
            # Find first frame outside of pywire internals
            stack = inspect.stack()
            for frame_info in stack:
                filename = frame_info.filename
                if not filename or filename == "<string>":
                    continue

                # Skip internal pywire frames
                if "pywire/runtime" in filename or "pywire/compiler" in filename:
                    continue

                # Skip unit tests in pywire/tests to allow fallback to CWD
                # but DON'T skip repro apps or other scripts that don't look like tests
                base_name = Path(filename).name
                is_test_file = base_name.startswith("test_") or base_name.endswith(
                    "_test.py"
                )
                if "pywire/tests" in filename and is_test_file:
                    continue

                module = inspect.getmodule(frame_info.frame)
                if module:
                    name = getattr(module, "__name__", "")
                    if name and (
                        name.startswith("pywire.runtime")
                        or name.startswith("pywire.compiler")
                        or name == "pywire"
                    ):
                        continue

                # Skip common test runners
                if (
                    "pytest" in filename
                    or "unittest" in filename
                    or "_pytest" in filename
                    or "pluggy" in filename
                ):
                    continue

                return Path(filename).parent.resolve()
        except Exception:
            pass
        return Path.cwd().resolve()

    def _get_project_root(self, start_dir: Path) -> Path:
        """Find the project root by looking for markers like pyproject.toml or .venv."""
        current = start_dir
        while True:
            if (
                (current / "pyproject.toml").exists()
                or (current / "uv.lock").exists()
                or (current / ".venv").exists()
                or (current / ".git").exists()
            ):
                return current
            if current.parent == current:
                break
            current = current.parent
        # Fallback to caller_dir if no markers found (e.g. single script)
        return start_dir

    def __init__(
        self,
        pages_dir: Optional[str] = None,
        path_based_routing: bool = True,
        enable_pjax: bool = True,
        debug: bool = False,
        enable_webtransport: bool = False,
        static_dir: Optional[str] = None,
        static_route: Optional[str] = None,
        max_upload_size: int = 10 * 1024 * 1024,
        upload_token_ttl_seconds: int = 600,
        middleware: Optional[List] = None,
        session_store: Optional[Any] = None,
        session_ttl: Optional[int] = None,
        session_warn_size: int = 256 * 1024,  # 256 KB
        ws_ping_interval: int = 25,
        ws_ping_timeout: int = 10,
        reconnect_max_attempts: int = 10,
        reconnect_overlay: bool = True,
        interactive_server_mode: bool = True,
        fallthrough_404: bool = False,
    ) -> None:
        caller_dir = self._get_caller_dir()
        project_root = self._get_project_root(caller_dir)

        # NOTE: We do NOT use CWD or caller_dir for auto-discovery to avoid
        # security risks (e.g. serving ~/static if running from home dir).
        # We ONLY look relative to the detected project root.

        if pages_dir is None:
            # Auto-discovery
            # Priority: project_root/src/pages, then project_root/pages
            potential_paths = [
                project_root / "src" / "pages",
                project_root / "pages",
            ]

            discovered_pages = None
            for path in potential_paths:
                if path.exists() and path.is_dir():
                    discovered_pages = path.resolve()
                    break

            if discovered_pages:
                self.pages_dir = discovered_pages
            else:
                raise RuntimeError(
                    f"Could not find 'pages/' or 'src/pages/' directory relative to "
                    f"project root '{project_root}'. Please specify 'pages_dir' explicitly."
                )
        else:
            path = Path(pages_dir)
            if not path.is_absolute():
                # Explicit paths are relative to the project root
                self.pages_dir = (project_root / path).resolve()
            else:
                self.pages_dir = path.resolve()

        # User configured static directory
        if static_dir is None:
            # default static dir is adjacent to project root. Only serves if it exists.
            potential_static = project_root / "static"

            if potential_static.exists() and potential_static.is_dir():
                self.static_dir = potential_static.resolve()
            else:
                self.static_dir = None
        else:
            path = Path(static_dir)
            if not path.is_absolute():
                # Explicit paths are relative to the project root
                self.static_dir = (project_root / path).resolve()
            else:
                self.static_dir = path.resolve()

        if static_route is None:
            self.static_url_path = "/static"
        else:
            if not static_route.startswith("/"):
                static_route = "/" + static_route
            if static_route == "/":
                logger.warning(
                    "static_route='/' serves static files from the root path. "
                    "PyWire page routes will take priority over static file "
                    "routes, which may cause inconsistencies."
                )
            self.static_url_path = static_route

        # Add project root and src directory to sys.path to allow imports in .wire files
        import sys

        project_root_str = str(project_root.resolve())
        if project_root_str not in sys.path:
            sys.path.insert(0, project_root_str)

        src_dir = project_root / "src"
        if src_dir.exists() and src_dir.is_dir():
            src_dir_str = str(src_dir.resolve())
            if src_dir_str not in sys.path:
                sys.path.insert(0, src_dir_str)

        self.path_based_routing = path_based_routing
        self.enable_pjax = enable_pjax

        self.debug = debug

        # Internal framework logging — controlled separately from debug flag.
        # debug=True is for app-developer UX (error screens, source endpoints).
        # PYWIRE_LOG_LEVEL is for framework-developer diagnostics (wire tracking, etc.).
        pywire_logger = logging.getLogger("pywire")
        log_level = os.environ.get("PYWIRE_LOG_LEVEL", "").upper()
        if log_level and hasattr(logging, log_level):
            pywire_logger.setLevel(getattr(logging, log_level))
        else:
            pywire_logger.setLevel(logging.WARNING)

        self.enable_webtransport = enable_webtransport
        self.max_upload_size = max(1, int(max_upload_size))
        self.upload_token_ttl_seconds = max(30, int(upload_token_ttl_seconds))
        runtime_key = hashlib.sha256(str(self.pages_dir).encode("utf-8")).hexdigest()[
            :16
        ]
        self._runtime_dir = (
            Path(tempfile.gettempdir()) / "pywire_runtime" / runtime_key
        ).resolve()
        self._runtime_dir.mkdir(parents=True, exist_ok=True)
        self._upload_token_dir = self._runtime_dir / "upload_tokens"
        self._upload_token_dir.mkdir(parents=True, exist_ok=True)
        # Internal flag set by dev_server.py when running via 'pywire dev'
        self._is_dev_mode = False

        # Reconnection overlay config (passed to client via SPA metadata)
        self.reconnect_max_attempts = reconnect_max_attempts
        self.reconnect_overlay = reconnect_overlay

        # Reconnect template HTML/CSS — always populated (built-in default or
        # user's __reconnect__.wire override).  The server injects this as
        # <template id="_pywire_reconnect"> so the client has a single code path.
        self._reconnect_template_html: Optional[str] = None
        self._reconnect_template_style: Optional[str] = None
        self._load_default_reconnect_template()

        # Asset fingerprinting cache (prod without build: path -> content hash)
        self._asset_hash_cache: Dict[str, str] = {}
        # Asset manifest (prod with build: original path -> fingerprinted filename)
        self._asset_manifest: Optional[Dict[str, str]] = None
        # Track warned missing assets (prod: warn once per path)
        self._asset_warned_missing: Set[str] = set()

        self.router = Router()

        from pywire.runtime.loader import get_loader

        self.loader = get_loader()

        # Session store: auto-detect Redis from env, fall back to in-memory
        self.session_ttl = (
            session_ttl
            if session_ttl is not None
            else int(os.environ.get("SESSION_TTL", "1800"))
        )
        self.session_warn_size = session_warn_size
        if session_store is not None:
            self.session_store = session_store
        else:
            redis_url = os.environ.get("REDIS_URL") or os.environ.get("FLY_REDIS_URL")
            if redis_url:
                from pywire.runtime.redis_store import RedisSessionStore

                self.session_store = RedisSessionStore(redis_url)
                logger.info(
                    "Using Redis session store (auto-detected from environment)"
                )
            else:
                from pywire.runtime.session_store import MemorySessionStore

                self.session_store = MemorySessionStore()

        self.interactive_server_mode = interactive_server_mode
        self.fallthrough_404 = fallthrough_404
        self.ws_ping_interval = max(0, int(ws_ping_interval))
        self.ws_ping_timeout = max(1, int(ws_ping_timeout))

        # Transport handlers — only instantiate when interactive mode is on
        if self.interactive_server_mode:
            self.ws_handler = WebSocketHandler(self)
            self.http_handler = HTTPTransportHandler(self)

            from pywire.runtime.webtransport_handler import WebTransportHandler

            self.web_transport_handler = WebTransportHandler(self)
        else:
            self.ws_handler = None  # type: ignore[assignment]
            self.http_handler = None  # type: ignore[assignment]
            self.web_transport_handler = None  # type: ignore[assignment]

        # Backward-compatible token allowlist
        self.upload_tokens: Set[str] = set()
        # Token metadata: token -> (bound_session_id, issued_ts)
        self._upload_token_meta: Dict[str, Tuple[Optional[str], float]] = {}
        upload_manager.configure_storage(self._runtime_dir / "uploads")
        upload_manager.max_upload_size = self.max_upload_size

        # Compile and register all pages
        self._load_pages()

        # Prepare exception handlers
        exception_handlers: Dict[int, Any] = {}
        # Always register our handler to check for custom error pages
        exception_handlers[500] = self._handle_500

        # Build routes list
        routes: list[Route | WebSocketRoute | Mount] = [
            # Capabilities endpoint for transport negotiation
            Route("/_pywire/capabilities", self._handle_capabilities, methods=["GET"]),
            # Internal static files served via importlib.resources (works on all
            # platforms including Pyodide/CF Workers where filesystem ops fail)
            Route(
                "/_pywire/static/{path:path}",
                self._serve_internal_static,
                methods=["GET"],
            ),
        ]

        if self.interactive_server_mode:
            assert self.ws_handler is not None
            assert self.http_handler is not None
            # WebSocket transport
            routes.append(WebSocketRoute("/_pywire/ws", self.ws_handler.handle))
            # HTTP long-poll transport endpoints
            routes.append(
                Route(
                    "/_pywire/session",
                    self.http_handler.create_session,
                    methods=["POST"],
                )
            )
            routes.append(
                Route("/_pywire/poll", self.http_handler.poll, methods=["GET"])
            )
            routes.append(
                Route(
                    "/_pywire/event",
                    self.http_handler.handle_event,
                    methods=["POST"],
                )
            )

        # Upload endpoint (available in both modes — form file uploads)
        routes.append(Route("/_pywire/upload", self._handle_upload, methods=["POST"]))

        # Load asset manifest from build output (if pywire build was run)
        build_manifest_path = project_root / ".pywire" / "build" / "asset-manifest.json"
        build_static_dir = project_root / ".pywire" / "build" / "static"
        if build_manifest_path.exists():
            manifest = json.loads(build_manifest_path.read_text())
            self._asset_manifest = manifest
            logger.info("Loaded asset manifest with %d entries", len(manifest))

        # Mount User Static Files if configured
        if self.static_dir:
            if not self.static_dir.exists():
                logger.warning(
                    f"Configured static directory '{self.static_dir}' does not exist."
                )
            else:
                # If build produced fingerprinted static files, serve from
                # the build dir (contains both originals and fingerprinted copies).
                # Otherwise serve from the source static dir.
                if self._asset_manifest and build_static_dir.exists():
                    routes.append(
                        Mount(
                            self.static_url_path,
                            app=StaticFiles(directory=str(build_static_dir)),
                            name="static",
                        )
                    )
                else:
                    routes.append(
                        Mount(
                            self.static_url_path,
                            app=StaticFiles(directory=str(self.static_dir)),
                            name="static",
                        )
                    )

        # Debug endpoints (must be before catch-all)
        # ONLY enable these if BOTH debug=True AND we are in dev mode
        # This prevents source code exposure in 'pywire run' even if debug=True
        if self.debug:
            # We defer the check to the handler or register them but check flag inside?
            # Better to not register them at all if we know _is_dev_mode is False at init?
            # PROBLEM: _is_dev_mode is set AFTER init by dev_server.py.
            # So we register them, but gate them inside the handler, OR we allow dev_server
            # to re-init app? No, dev_server imports app.

            # Solution: Register them, but check self._is_dev_mode inside the handlers.
            # OR refactor so routes are dynamic? Starlette routes are fixed list usually.

            # Actually, let's keep them registered if debug=True, but
            # modify _handle_source/_handle_file to checking _is_dev_mode as well inside.
            routes.append(
                Route("/_pywire/source", self._handle_source, methods=["GET"])
            )
            routes.append(
                Route(
                    "/_pywire/file/{encoded:path}", self._handle_file, methods=["GET"]
                )
            )
            # Chrome DevTools automatic workspace folders (M-135+)
            routes.append(
                Route(
                    "/.well-known/appspecific/com.chrome.devtools.json",
                    self._handle_devtools_json,
                    methods=["GET"],
                )
            )

        # Default page handler (catch-all, must be last)
        routes.append(
            Route("/{path:path}", self._handle_request, methods=["GET", "POST"])
        )

        # Session store lifecycle via lifespan context manager
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def _lifespan(app: Any):
            # Startup
            connect = getattr(self.session_store, "connect", None)
            if callable(connect):
                await connect()
            yield
            # Shutdown
            close = getattr(self.session_store, "close", None)
            if callable(close):
                await close()

        # Create Starlette app with all transport routes
        self.app = Starlette(
            routes=routes,
            exception_handlers=exception_handlers,
            lifespan=_lifespan,
        )

        # Store configuration in app state for runtime access (e.g. by pages)
        self.app.state.enable_pjax = self.enable_pjax
        self.app.state.debug = self.debug
        self.app.state.pywire = self
        self.app.state.interactive_server_mode = self.interactive_server_mode

        # Add Middleware to set request context for shell API
        from starlette.middleware.base import BaseHTTPMiddleware

        class _RequestContextMiddleware(BaseHTTPMiddleware):
            async def dispatch(self, request: Request, call_next):
                from pywire.shell import _request_ctx

                token = _request_ctx.set(request)
                try:
                    return await call_next(request)
                finally:
                    _request_ctx.reset(token)

        self.app.add_middleware(cast(Any, _RequestContextMiddleware))

        # Apply user-provided middleware.
        # Starlette's add_middleware prepends (last added = outermost), so we
        # reverse the list so the first item in the user's list becomes outermost.
        if middleware:
            for mw in reversed(middleware):
                if isinstance(mw, tuple):
                    cls = mw[0]
                    options = mw[1] if len(mw) > 1 else {}
                    self.app.add_middleware(cls, **options)
                else:
                    self.app.add_middleware(mw)

        # In non-interactive mode, add session middleware for HTTP state
        if not self.interactive_server_mode:
            from pywire.runtime.session_middleware import SessionMiddleware

            self.app.add_middleware(
                SessionMiddleware,
                session_store=self.session_store,
                session_ttl=self.session_ttl,
            )

        # Internal dispatch target — set by as_asgi() when mounted in
        # a host framework (e.g. FastAPI). When None, internal requests
        # dispatch through self.app (the Starlette instance).
        self._root_app: Optional[Any] = None

    def _get_dispatch_target(self) -> Any:
        """Return the ASGI app for internal request dispatch."""
        return self._root_app or self.app

    def as_asgi(self, host: Any = None) -> "PyWire":
        """Return this app as an ASGI application for mounting.

        Pass the host application so that internal request dispatch
        (SPA navigation via WebSocket) goes through the host's full
        middleware stack::

            from fastapi import FastAPI
            from pywire import PyWire

            api = FastAPI()
            pywire = PyWire(pages_dir="./pages", fallthrough_404=True)

            api.mount("/", pywire.as_asgi(api))

        Without ``host``, internal dispatch only traverses PyWire's own
        middleware — suitable for standalone deployments.
        """
        if host is not None:
            self._root_app = host
        return self

    def add_middleware(self, middleware_class: Any, **kwargs: Any) -> None:
        """Add ASGI middleware to the application.

        Middleware wraps the ASGI app and is called for HTTP and WebSocket
        requests. WebTransport connections bypass middleware.
        """
        self.app.add_middleware(middleware_class, **kwargs)

    async def _serve_internal_static(self, request: Request) -> Response:
        """Serve PyWire's internal JS/CSS assets from package data.

        Uses importlib.resources to read from the installed pywire package,
        which works on all platforms (standard server, CF Workers, Pyodide).
        """
        import importlib.resources

        filename = request.path_params["path"]
        # Prevent directory traversal
        if "/" in filename or "\\" in filename or ".." in filename:
            return Response("Not Found", status_code=404)
        try:
            data = (
                importlib.resources.files("pywire.static")
                .joinpath(filename)
                .read_bytes()
            )
        except Exception:
            return Response("Not Found", status_code=404)

        content_types = {
            "js": "application/javascript",
            "css": "text/css",
            "map": "application/json",
        }
        ext = filename.rsplit(".", 1)[-1] if "." in filename else ""
        ct = content_types.get(ext, "application/octet-stream")
        return Response(
            data, media_type=ct, headers={"Cache-Control": "public, max-age=31536000"}
        )

    async def _handle_capabilities(self, request: Request) -> JSONResponse:
        """Return server transport capabilities for client negotiation."""
        if self.interactive_server_mode:
            transports = ["websocket", "http"]
        else:
            transports = ["http-only"]
        return JSONResponse(
            {
                "transports": transports,
                "interactive": self.interactive_server_mode,
                # WebTransport requires HTTP/3 - only available when running with Hypercorn
                "webtransport": False,
                "version": __version__,
            }
        )

    def _get_client_script_url(self) -> str:
        """Return the appropriate client bundle URL based on server mode.

        Returns dev bundle when running via 'pywire dev', core bundle otherwise.
        """
        if self._is_dev_mode:
            return f"/_pywire/static/pywire.dev.min.js?v={__version__}"
        return f"/_pywire/static/pywire.core.min.js?v={__version__}"

    async def _handle_upload(self, request: Request) -> JSONResponse:
        """Handle file uploads."""
        logger.debug(f"Handling upload request for {request.url}")
        try:
            # Check for upload token
            token = request.headers.get("X-Upload-Token")
            if not token:
                return JSONResponse(
                    {"error": "Invalid or expired upload token"}, status_code=403
                )
            self._cleanup_upload_tokens()
            token_binding = self._load_upload_token(token)
            if token_binding is None:
                if token in self.upload_tokens:
                    token_binding = (None, time.time())
                    self._store_upload_token(token, None, token_binding[1])
                else:
                    return JSONResponse(
                        {"error": "Invalid or expired upload token"}, status_code=403
                    )
            bound_session_id, issued_ts = token_binding
            if (time.time() - issued_ts) > self.upload_token_ttl_seconds:
                self._delete_upload_token(token)
                return JSONResponse({"error": "Upload token expired"}, status_code=403)

            session_id = request.headers.get("X-PyWire-Session")
            if bound_session_id is not None and session_id != bound_session_id:
                return JSONResponse(
                    {"error": "Upload token not valid for this session"},
                    status_code=403,
                )
            if bound_session_id is None and session_id:
                self._store_upload_token(token, session_id, issued_ts)

            # Fail-fast: Check Content-Length header
            content_length = request.headers.get("content-length")
            if content_length:
                try:
                    length = int(content_length)
                    if length > self.max_upload_size:
                        logger.warning(
                            "Upload rejected. Content-Length %s exceeds configured limit %s.",
                            length,
                            self.max_upload_size,
                        )
                        return JSONResponse(
                            {"error": "Payload Too Large"}, status_code=413
                        )
                except ValueError:
                    pass

            form = await request.form()
            response_data: Dict[str, Any] = {}
            upload_errors: Dict[str, str] = {}
            items_iter = (
                form.multi_items() if hasattr(form, "multi_items") else form.items()
            )
            for field_name, file in items_iter:
                if not hasattr(file, "filename"):
                    continue
                from starlette.datastructures import UploadFile

                try:
                    upload_id = upload_manager.save(
                        cast(UploadFile, file), max_size=self.max_upload_size
                    )
                except ValueError:
                    upload_errors[field_name] = "Payload Too Large"
                    continue

                existing = response_data.get(field_name)
                if existing is None:
                    response_data[field_name] = upload_id
                    continue
                if isinstance(existing, list):
                    existing.append(upload_id)
                    continue
                response_data[field_name] = [existing, upload_id]

            logger.debug(f"Upload successful. Returning: {response_data}")
            if upload_errors:
                return JSONResponse(
                    {"uploads": response_data, "errors": upload_errors}, status_code=400
                )
            return JSONResponse(response_data)
        except Exception as e:
            logger.error(f"Upload failed: {e}", exc_info=True)
            return JSONResponse({"error": str(e)}, status_code=500)

    async def _handle_source(self, request: Request) -> Response:
        """Serve source code for debugging. Requires both debug=True AND _is_dev_mode=True."""
        if not (self._is_dev_mode and self.debug):
            return Response("Not Found", status_code=404)

        path_str = request.query_params.get("path")
        logger.debug("_handle_source path=%s", path_str)
        if not path_str:
            return Response("Missing path", status_code=400)

        try:
            path = Path(path_str).resolve()
            logger.debug(
                "_handle_source resolved path=%s, exists=%s", path, path.exists()
            )
            # Path existence check
            if not path.exists():
                return Response("File not found", status_code=404)

            content = path.read_text(encoding="utf-8")
            return Response(content, media_type="text/plain")
        except Exception as e:
            logger.debug(f"_handle_source exception: {e}")
            return Response(str(e), status_code=500)

    async def _handle_file(self, request: Request) -> Response:
        """Serve source file by base64-encoded path (for DevTools source mapping)."""
        if not (self._is_dev_mode and self.debug):
            return Response("Not Found", status_code=404)

        import base64

        encoded_path = request.path_params.get("encoded", "")

        # If the path contains a slash, it means we appended the filename for Chrome's benefit
        # e.g., "BASE64STRING/my_file.py"
        # We only care about the first part
        if "/" in encoded_path:
            encoded = encoded_path.split("/")[0]
        else:
            encoded = encoded_path

        try:
            # Decode the base64 path (URL-safe variant)
            # Restore padding
            padding = 4 - (len(encoded) % 4)
            if padding != 4:
                encoded += "=" * padding
            # Restore standard base64 chars
            encoded = encoded.replace("-", "+").replace("_", "/")
            path_str = base64.b64decode(encoded).decode("utf-8")

            path = Path(path_str).resolve()
            if not path.is_file():
                return Response("File not found", status_code=404)

            content = path.read_text(encoding="utf-8")
            # Return as JavaScript so browser DevTools can parse it
            return Response(content, media_type="text/plain")
        except Exception as e:
            logger.debug(f"_handle_file exception: {e}")
            return Response(str(e), status_code=500)

    async def _handle_devtools_json(self, request: Request) -> JSONResponse:
        """Serve Chrome DevTools project settings for automatic workspace folders."""
        if not (self._is_dev_mode and self.debug):
            return JSONResponse({}, status_code=404)

        import hashlib
        import uuid

        # Use current working directory as project root
        project_root = Path.cwd()

        # Generate a consistent UUID from the project path
        path_hash = hashlib.md5(str(project_root).encode()).hexdigest()
        project_uuid = str(uuid.UUID(path_hash[:32]))

        return JSONResponse(
            {"workspace": {"root": str(project_root.resolve()), "uuid": project_uuid}}
        )

    def _load_pages(self) -> None:
        """Discover and compile all .pywire files."""
        # Scan pages directory
        # We need to sort files to ensure deterministic order but scanning is recursive
        self._scan_directory(self.pages_dir)

        # Explicitly check for __error__.wire in root pages dir
        # (It is skipped by _scan_directory because it starts with _)
        error_page_path = self.pages_dir / "__error__.wire"
        if error_page_path.exists():
            try:
                root_layout = None
                if (self.pages_dir / "__layout__.wire").exists():
                    root_layout = str((self.pages_dir / "__layout__.wire").resolve())

                page_class = self.loader.load(
                    error_page_path, implicit_layout=root_layout
                )
                self.router.add_route("/__error__", page_class)
                self.router.add_route("/__error__", page_class)
            except Exception as e:
                logger.error(
                    f"Failed to load error page {error_page_path}: {e}", exc_info=True
                )

        # Check for __reconnect__.wire — custom reconnection overlay template
        reconnect_page_path = self.pages_dir / "__reconnect__.wire"
        if reconnect_page_path.exists():
            self._load_reconnect_template(reconnect_page_path)

    def _load_default_reconnect_template(self) -> None:
        """Load the built-in default reconnect overlay from templates/reconnect/default.html.

        This provides the default "Reconnecting..." / "Connection lost" overlay.
        It can be overridden by a user's ``__reconnect__.wire`` in their pages dir.
        """
        import re

        default_path = (
            Path(__file__).parent.parent / "templates" / "reconnect" / "default.html"
        )
        try:
            content = default_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            logger.warning("Built-in reconnect template not found at %s", default_path)
            return

        # Extract <style>...</style> blocks
        style_parts: list[str] = []

        def _collect_style(m: re.Match[str]) -> str:
            style_parts.append(m.group(1))
            return ""

        html = re.sub(r"<style>(.*?)</style>", _collect_style, content, flags=re.DOTALL)
        html = html.strip()

        if html:
            self._reconnect_template_html = html
        if style_parts:
            self._reconnect_template_style = "\n".join(style_parts)

    def _load_reconnect_template(self, file_path: Path) -> None:
        """Load __reconnect__.wire as a static HTML template with optional scoped styles.

        Python frontmatter is warned about (it cannot execute client-side when
        disconnected). The resulting HTML is stored for injection as a
        ``<template id="_pywire_reconnect">`` into each page.
        """
        try:
            from pywire.compiler.parser import PyWireParser

            parser = PyWireParser()
            parsed = parser.parse_file(file_path)

            # Warn if the file contains Python frontmatter
            if parsed.python_code and parsed.python_code.strip():
                logger.warning(
                    "__reconnect__.wire contains Python frontmatter which will be "
                    "ignored — Python cannot execute on the client when disconnected."
                )

            # Render template nodes to raw HTML
            html_parts: list[str] = []
            style_parts: list[str] = []

            for node in parsed.template:
                if hasattr(node, "tag") and node.tag == "style":
                    # Extract style content
                    css = self._extract_text_content(node)
                    if css:
                        style_parts.append(css)
                else:
                    html_parts.append(self._render_template_node(node))

            html = "\n".join(html_parts).strip()
            if html:
                self._reconnect_template_html = html
            if style_parts:
                self._reconnect_template_style = "\n".join(style_parts)

            logger.info("Loaded custom reconnect template from %s", file_path)
        except Exception as e:
            logger.error(
                "Failed to load reconnect template %s: %s", file_path, e, exc_info=True
            )

    @staticmethod
    def _extract_text_content(node: Any) -> str:
        """Recursively extract text content from a template node."""
        parts: list[str] = []
        if hasattr(node, "text_content") and node.text_content:
            parts.append(node.text_content)
        if hasattr(node, "children"):
            for child in node.children:
                parts.append(PyWire._extract_text_content(child))
        return "".join(parts)

    @staticmethod
    def _render_template_node(node: Any) -> str:
        """Render a template node back to HTML string (simple reconstruction)."""
        if (
            hasattr(node, "text_content")
            and node.text_content
            and not hasattr(node, "tag")
        ):
            return node.text_content
        if not hasattr(node, "tag") or not node.tag:
            # Text node
            text = getattr(node, "text_content", "") or ""
            return text

        tag = node.tag
        attrs = ""
        if hasattr(node, "attributes") and node.attributes:
            attr_parts = []
            for k, v in node.attributes.items():
                if v is True:
                    attr_parts.append(k)
                elif v is not None:
                    attr_parts.append(f'{k}="{v}"')
            if attr_parts:
                attrs = " " + " ".join(attr_parts)

        # Self-closing tags
        void_tags = {"br", "hr", "img", "input", "meta", "link"}
        if tag in void_tags:
            return f"<{tag}{attrs} />"

        children_html = ""
        if hasattr(node, "children"):
            children_html = "".join(
                PyWire._render_template_node(c) for c in node.children
            )

        text = getattr(node, "text_content", "") or ""
        return f"<{tag}{attrs}>{text}{children_html}</{tag}>"

    def _scan_directory(
        self, dir_path: Path, layout_path: Optional[str] = None, url_prefix: str = ""
    ) -> None:
        """Recursively scan directory for pages and layouts."""
        current_layout = layout_path

        # Priority: __layout__.wire ONLY
        potential_layout = dir_path / "__layout__.wire"

        if potential_layout.exists():
            # Compile layout first (it might use the parent layout!)
            try:
                # Layouts can inherit from parent layouts too
                self.loader.load(potential_layout, implicit_layout=layout_path)
                current_layout = str(potential_layout.resolve())
            except Exception as e:
                logger.error(
                    f"Failed to load layout {potential_layout}: {e}", exc_info=True
                )

        # 2. Iterate identifiers
        # Sort to ensure index processed or consistent order
        try:
            entries = sorted(list(dir_path.iterdir()))
        except FileNotFoundError:
            return

        for entry in entries:
            if entry.name.startswith("_") or entry.name.startswith("."):
                continue

            if entry.is_dir():
                # Determine new prefix
                # Check if it's a param directory [param]
                name = entry.name
                new_segment = name

                # Check for [param] or [param:type] syntax
                param_match = re.match(r"^\[(.*?)(?::(.*?))?\]$", name)
                if param_match:
                    param_name = param_match.group(1)
                    type_name = param_match.group(2)
                    # Convert to routing syntax :{name} (or whatever Router supports)
                    # Router supports :name:type or {name:type}
                    if type_name:
                        new_segment = f"{{{param_name}:{type_name}}}"
                    else:
                        new_segment = f"{{{param_name}}}"

                new_prefix = (url_prefix + "/" + new_segment).replace("//", "/")
                self._scan_directory(entry, current_layout, new_prefix)

            elif entry.is_file() and entry.suffix == ".wire":
                if entry.name == "layout.wire":
                    # Previously supported layout file, now ignored (or treated
                    # as normal page? No, starts with l)
                    # Wait, layout.pywire doesn't start with _. So it would be registered as /layout
                    # We should probably explicitly IGNORE it if we want strictness?
                    # The prompt says: "absolutely NOT layout.pywire".
                    # If it's not a layout, is it a page? Usually layout.pywire
                    # has slots and shouldn't be a page.
                    # Let's Skip it to be safe/clean.
                    continue

                # Determine route path
                name = entry.stem  # filename without .wire

                route_segment = name
                if name == "index":
                    route_segment = ""
                else:
                    # Check for [param] or [param:type] in filename
                    param_match = re.match(r"^\[(.*?)(?::(.*?))?\]$", name)
                    if param_match:
                        param_name = param_match.group(1)
                        type_name = param_match.group(2)
                        if type_name:
                            route_segment = f"{{{param_name}:{type_name}}}"
                        else:
                            route_segment = f"{{{param_name}}}"

                route_path = (url_prefix + "/" + route_segment).replace("//", "/")

                # Strip trailing slash for index pages (unless root)
                if route_path != "/" and route_path.endswith("/"):
                    route_path = route_path.rstrip("/")

                if not route_path:
                    route_path = "/"

                try:
                    # Load page with implicit layout
                    page_class = self.loader.load(entry, implicit_layout=current_layout)

                    # Register routes
                    # 1. explicit !path overrides implicit routing?
                    # Generally yes. If !path exists, we might add those IN ADDITION or INSTEAD.
                    # Current logic in add_page inspects __routes__ (from !path).
                    # If present, use that. If not, use implicit route_path.

                    if hasattr(page_class, "__routes__") and page_class.__routes__:
                        # User specified explicit paths
                        self.router.add_page(page_class)
                    elif hasattr(page_class, "__route__") and page_class.__route__:
                        # Should not happen as __route__ is derived from __routes__ usually
                        self.router.add_page(page_class)
                    elif self.path_based_routing:
                        # No explicit !path, use file-based route ONLY if enabled
                        self.router.add_route(route_path, page_class)

                except Exception as e:
                    logger.error(f"Failed to load page {entry}: {e}", exc_info=True)
                    self._register_error_page(entry, e)

    def _register_error_page(self, file_path: Path, error: Exception) -> None:
        """Register an error page for a failed file."""
        # Try to infer route from file path/content
        # 1. Start with path relative to pages_dir
        try:
            rel_path = file_path.relative_to(self.pages_dir)

            # Basic route inference from path
            route_path = "/" + str(rel_path.with_suffix("")).replace("index", "").strip(
                "/"
            )
            if not route_path:
                route_path = "/"

            # Also try to regex extract !path directives from file content
            # to handle custom routes properly even if compilation fails
            try:
                content = file_path.read_text()
                # Look for !path "..." or !path '...'
                # This is a simple regex, might need refinement
                path_directives = re.findall(r'!path\s+[\'"]([^\'"]+)[\'"]', content)

                routes_to_register = []
                if path_directives:
                    routes_to_register = path_directives
                else:
                    routes_to_register = [route_path]

                # Use a ModeAwareErrorPage that checks debug/dev mode at RENDER time
                # This is necessary because _is_dev_mode is set AFTER __init__ by dev_server.py
                from pywire.runtime.compile_error_page import CompileErrorPage
                from pywire.runtime.page import BasePage

                for route in routes_to_register:
                    # Capture error and file_path in closure
                    captured_error = error
                    captured_file_path = str(file_path)
                    captured_app = self  # Reference to PyWire app for mode checking

                    class ModeAwareErrorPage(BasePage):
                        """Error page that decides whether to show details or trigger 500."""

                        def __init__(
                            self, request: Request, *args: Any, **kwargs: Any
                        ) -> None:
                            # Store for parent __init__
                            super().__init__(request, *args, **kwargs)

                        async def render(self, init: bool = True) -> Any:
                            # Check mode at render time (not registration time!)
                            # This allows dev_server.py to set _is_dev_mode after app init
                            if captured_app.debug or getattr(
                                captured_app, "_is_dev_mode", False
                            ):
                                # DEV MODE: Show detailed CompileErrorPage
                                detail_page = CompileErrorPage(
                                    self.request,
                                    captured_error,
                                    file_path=captured_file_path,
                                )
                                return await detail_page.render()
                            else:
                                # PROD MODE: Raise to trigger _handle_500
                                raise RuntimeError("Page failed to load")

                    ModeAwareErrorPage.__file_path__ = captured_file_path
                    self.router.add_route(route, ModeAwareErrorPage)

            except Exception:
                # Fallback to basic path if regex fails
                pass

        except Exception as e:
            logger.error(f"Failed to register error page for {file_path}: {e}")

    def _get_implicit_route(self, file_path: Path) -> Optional[str]:
        """Calculate implicit route path from file path."""
        try:
            rel_path = file_path.relative_to(self.pages_dir)
        except ValueError:
            return None

        segments = []
        for i, part in enumerate(rel_path.parts):
            if part.startswith("_") or part.startswith("."):
                return None

            name = part
            is_file = i == len(rel_path.parts) - 1

            if is_file:
                if not name.endswith(".wire"):
                    return None
                if name == "layout.wire":
                    return None
                name = Path(name).stem

            segment = name
            if name == "index":
                segment = ""

            param_match = re.match(r"^\[(.*?)(?::(.*?))?\]$", name)
            if param_match:
                param_name = param_match.group(1)
                type_name = param_match.group(2)
                if type_name:
                    segment = f"{{{param_name}:{type_name}}}"
                else:
                    segment = f"{{{param_name}}}"

            segments.append(segment)

        route_path = "/" + "/".join(segments)
        while "//" in route_path:
            route_path = route_path.replace("//", "/")

        if route_path != "/" and route_path.endswith("/"):
            route_path = route_path.rstrip("/")

        if not route_path:
            route_path = "/"

        return route_path

    def _resolve_implicit_layout(self, page_path: Path) -> Optional[str]:
        """Resolve the implicit layout path for a given page."""
        # Traverse up from page directory to pages_dir
        current_dir = page_path.parent

        # Ensure we don't traverse above pages_dir
        try:
            # Check if page is within pages_dir
            current_dir.relative_to(self.pages_dir)
        except ValueError:
            # Page is outside pages_dir? Should not happen normally.
            return None

        while True:
            # Check for layout files
            layout = current_dir / "__layout__.wire"

            if layout.exists():
                # Don't use layout if it is the file itself (e.g. reloading a layout file)
                if layout.resolve() == page_path.resolve():
                    pass
                else:
                    return str(layout.resolve())

            if current_dir == self.pages_dir:
                break

            current_dir = current_dir.parent

            # Safety check: stop at root
            if current_dir == current_dir.parent:
                break  # Original line

    def reload_page(self, path: Path) -> bool:
        """Reload and recompile a specific page and its dependents."""
        # Invalidate cache for this file and dependents
        invalidated_paths = self.loader.invalidate_cache(path)

        # Always include the original path even if not in cache (to trigger load)
        str_path = str(path.resolve())
        if str_path not in invalidated_paths:
            invalidated_paths.add(str_path)

        for file_path_str in invalidated_paths:
            file_path = Path(file_path_str)

            is_in_pages = False
            try:
                file_path.relative_to(self.pages_dir)
                is_in_pages = True
            except ValueError:
                is_in_pages = False

            try:
                # Resolve implicit layout for re-compilation
                implicit_layout = self._resolve_implicit_layout(file_path)

                # Recompile
                new_page_class = self.loader.load(
                    file_path, implicit_layout=implicit_layout
                )

                self.router.remove_routes_for_file(str(file_path))

                # Special handling for __error__.wire
                if file_path.name == "__error__.wire":
                    self.router.add_route("/__error__", new_page_class)
                elif file_path.name == "__reconnect__.wire":
                    self._load_reconnect_template(file_path)
                elif is_in_pages:
                    self.router.add_page(new_page_class)

                    # Re-apply implicit routing if not explicitly defined
                    has_explicit = hasattr(new_page_class, "__routes__") or hasattr(
                        new_page_class, "__route__"
                    )
                    if not has_explicit and self.path_based_routing:
                        route_path = self._get_implicit_route(file_path)
                        if route_path:
                            self.router.add_route(route_path, new_page_class)

                logger.info("Reloaded: %s", file_path)

            except Exception as e:
                logger.error(f"Failed to reload {file_path}: {e}", exc_info=True)

                # If it was a page, show error
                if is_in_pages or file_path.name == "__error__.wire":
                    self.router.remove_routes_for_file(str(file_path))
                    self._register_error_page(file_path, e)

                # If original file failed, re-raise because the watcher expects it
                if str(file_path) == str_path:
                    raise e
        return True

    async def _handle_500(self, request: Request, exc: Exception) -> Response:
        """Handle 500 errors with custom page if available."""
        # Try to find /__error__ page
        match = self.router.match("/__error__")

        if match:
            try:
                page_class, params, variant_name = match
                # Minimal context
                page = page_class(request, params, {}, path={"main": True}, url=None)
                # Inject error code
                page.error_code = 500
                # Inject exception details if debug mode?
                if self.debug:
                    page.error_detail = str(exc)
                    page.error_trace = traceback.format_exc()

                response = await page.render()
                # Force 500 status
                response.status_code = 500
                return response
            except Exception as e:
                # If 500 page fails, fall back
                print(f"Error rendering 500 page: {e}")
                pass

        # If no custom page or it failed:
        if self.debug:
            # Re-raise to let Starlette/Server show debug traceback
            raise exc

        return PlainTextResponse("Internal Server Error", status_code=500)

    async def _handle_request(self, request: Request) -> Response:
        """Handle HTTP request.

        Also serves internal ASGI replay requests from the WebSocket handler
        when ``X-PyWire-Internal: relocate`` is present. In that case, renders
        body-only HTML (init=False) to avoid re-injecting client scripts.
        """
        is_internal_relocate = request.headers.get("x-pywire-internal") == "relocate"

        path = request.url.path
        # When mounted at a prefix (e.g. /app), strip the root_path
        # so PyWire's router matches against local paths (/ not /app/)
        root_path = request.scope.get("root_path", "")
        if root_path and path.startswith(root_path):
            path = path[len(root_path) :] or "/"
        match = self.router.match(path)
        if not match:
            # Fallthrough mode: return bare 404 so host framework tries next
            if self.fallthrough_404 and not is_internal_relocate:
                return Response(status_code=404)

            # Try custom __error__
            match_error = self.router.match("/__error__")

            if match_error:
                page_class, params, variant_name = match_error
                # Render 404/error page
                # Note: We pass original request so URL is preserved?
                # Yes, user checking request.url on 404 page might want to know what failed.

                # Construct params/query
                query = dict(request.query_params)

                # Path info
                path_info = {}
                routes = getattr(page_class, "__routes__", {})
                if routes:
                    for name in routes.keys():
                        path_info[name] = name == variant_name
                elif hasattr(page_class, "__route__"):
                    path_info["main"] = True

                from pywire.runtime.router import URLHelper

                url_helper = None
                url_helper = None
                routes = getattr(page_class, "__routes__", None)
                if routes:
                    url_helper = URLHelper(cast(dict[str, str], routes))

                try:
                    page = page_class(
                        request, {}, query, path=path_info, url=url_helper
                    )
                    # Inject error code
                    page.error_code = 404
                    response = await page.render(init=not is_internal_relocate)
                    response.status_code = 404
                    return response
                except Exception as e:
                    print(f"Failed to render custom error page {page_class}: {e}")
                    import traceback

                    traceback.print_exc()
                    pass  # Fallback

            # Default 404 with client script
            page = ErrorPage(
                request, "404 Not Found", f"The path '{path}' could not be found."
            )
            response = await page.render(init=not is_internal_relocate)
            response.status_code = 404
            return response

        page_class, params, variant_name = match
        # ... (params, query, path_info, url_helper construction)
        # Build query params
        query = dict(request.query_params)

        # Build path info dict
        path_info = {}
        routes = getattr(page_class, "__routes__", {})
        if routes:
            for name in routes.keys():
                path_info[name] = name == variant_name
        elif hasattr(page_class, "__route__"):
            path_info["main"] = True

        # Build URL helper
        from pywire.runtime.router import URLHelper

        url_helper = None
        routes = getattr(page_class, "__routes__", None)
        if routes:
            url_helper = URLHelper(cast(dict[str, str], routes))

        # Instantiate page
        page = page_class(request, params, query, path=path_info, url=url_helper)

        # In non-interactive mode, restore session state if available
        session_id = request.scope.get("pywire_session_id")
        if not self.interactive_server_mode and session_id:
            session_data = request.scope.get("pywire_session_data")
            if session_data:
                from pywire.runtime.session_serializer import restore_page_state

                restore_page_state(page, session_data)

        # Check if this is an event request (interactive mode JSON events)
        if request.method == "POST" and "X-PyWire-Event" in request.headers:
            # Handle event
            try:
                event_data = await request.json()
                update = await page.handle_event(
                    event_data.get("handler", ""), event_data
                )
                if isinstance(update, dict):
                    return JSONResponse(update)
                response = cast(Response, update)
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=500)
        elif (
            request.method == "POST"
            and not self.interactive_server_mode
            and "X-PyWire-Event" not in request.headers
        ):
            # Non-interactive mode: standard form POST → @submit handler
            response = await self._handle_form_post(request, page)
        elif is_internal_relocate:
            # Internal ASGI replay from WS handler — body-only, no client scripts
            response = await page.render(init=False)
        else:
            # Normal render
            response = await page.render()

        # In non-interactive mode, persist session state after handling
        if not self.interactive_server_mode and session_id:
            from pywire.runtime.session_serializer import snapshot_page_state

            snapshot = snapshot_page_state(page, warn_size=self.session_warn_size)
            await self.session_store.set(session_id, snapshot, ttl=self.session_ttl)

        # Script injection is now handled by the compiler (generator.py)
        # to ensure it's present in both dev and production.

        # Inject WebTransport certificate hash if available (Dev Mode)
        if isinstance(response, Response) and response.media_type == "text/html":
            body = cast(bytes, response.body).decode("utf-8")
            injections = []

            # WebTransport Hash
            if hasattr(request.app.state, "webtransport_cert_hash"):
                cert_hash = list(request.app.state.webtransport_cert_hash)
                injections.append(
                    f"<script>window.PYWIRE_CERT_HASH = {cert_hash};</script>"
                )

            # Upload Token Injection
            if getattr(page, "__has_uploads__", False):
                import secrets

                token = secrets.token_urlsafe(32)
                self._store_upload_token(token, None, time.time())
                # Token meta tag
                injections.append(
                    f'<meta name="pywire-upload-token" content="{token}">'
                )

            if injections:
                injection_str = "\n".join(injections)
                if "</body>" in body:
                    parts = body.rsplit("</body>", 1)
                    body = parts[0] + injection_str + "</body>" + parts[1]
                else:
                    body += injection_str
                response = Response(body, media_type="text/html")

        return response

    async def _handle_form_post(self, request: Request, page: Any) -> Response:
        """Handle a standard HTML form POST in non-interactive mode.

        Parses form data, calls the page's ``@submit`` handler (named
        ``handle_submit``), re-renders the page, and returns the HTML.
        If no submit handler exists, just re-renders with the form data
        available via ``request.form()``.
        """
        try:
            form_data = await request.form()
            # Build event data dict from form fields
            event_data: Dict[str, Any] = {str(k): v for k, v in form_data.multi_items()}

            # Look for a submit handler on the page
            handler = getattr(page, "handle_submit", None)
            if handler and callable(handler):
                await handler(event_data)

            # Re-render the page with updated state
            response = await page.render()

            # Check for pending navigation (e.g. redirect after form submit)
            if hasattr(page, "_pending_navigation") and page._pending_navigation:
                from starlette.responses import RedirectResponse

                redirect_path = page._pending_navigation
                page._pending_navigation = None
                return RedirectResponse(redirect_path, status_code=303)

            return response
        except Exception as e:
            logger.error("Form POST error: %s", e, exc_info=True)
            # Re-render with error state
            if hasattr(page, "_form_error"):
                page._form_error = str(e)
            try:
                return await page.render()
            except Exception:
                return PlainTextResponse("Internal Server Error", status_code=500)

    def _cleanup_upload_tokens(self) -> None:
        cutoff = time.time() - self.upload_token_ttl_seconds
        stale = [
            token
            for token, (_, issued_ts) in self._upload_token_meta.items()
            if issued_ts < cutoff
        ]
        for token in stale:
            self._delete_upload_token(token)

        for token_file in self._upload_token_dir.glob("*.json"):
            token = token_file.stem
            meta = self._load_upload_token(token)
            if meta is None:
                continue
            if meta[1] < cutoff:
                self._delete_upload_token(token)

    def _token_file_path(self, token: str) -> Path:
        return self._upload_token_dir / f"{token}.json"

    def _store_upload_token(
        self, token: str, session_id: Optional[str], issued_ts: float
    ) -> None:
        self.upload_tokens.add(token)
        self._upload_token_meta[token] = (session_id, issued_ts)
        token_file = self._token_file_path(token)
        temp_file = token_file.with_suffix(".tmp")
        payload = {"session_id": session_id, "issued_ts": issued_ts}
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(payload, f)
        temp_file.replace(token_file)

    def _load_upload_token(self, token: str) -> Optional[Tuple[Optional[str], float]]:
        if token in self._upload_token_meta:
            return self._upload_token_meta[token]

        token_file = self._token_file_path(token)
        if not token_file.exists():
            return None
        try:
            with open(token_file, "r", encoding="utf-8") as f:
                payload = json.load(f)
            session_id = payload.get("session_id")
            issued_ts = float(payload.get("issued_ts", 0))
            self.upload_tokens.add(token)
            self._upload_token_meta[token] = (session_id, issued_ts)
            return (session_id, issued_ts)
        except (OSError, ValueError, json.JSONDecodeError):
            return None

    def _delete_upload_token(self, token: str) -> None:
        self.upload_tokens.discard(token)
        self._upload_token_meta.pop(token, None)
        self._token_file_path(token).unlink(missing_ok=True)

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        """ASGI interface."""
        logger.debug("Scope type: %s", scope["type"])
        if (
            scope["type"] == "webtransport"
            and self.interactive_server_mode
            and self.web_transport_handler is not None
        ):
            await self.web_transport_handler.handle(scope, receive, send)
            return

        await self.app(scope, receive, send)

    # --- Extensible Hooks ---

    async def on_ws_connect(self, websocket: Any) -> bool:
        """
        Hook called before WebSocket upgrade.
        Return False to reject connection.
        """
        return True

    def get_user(self, request_or_websocket: Any) -> Any:
        """
        Hook to populate page.user from request/websocket.
        Override to return user from session/JWT.
        """
        if "user" in request_or_websocket.scope:
            return request_or_websocket.user
        return None
