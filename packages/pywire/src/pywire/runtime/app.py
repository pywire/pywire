"""Main ASGI application."""

import re
import traceback
from pathlib import Path
from typing import Any, Dict, Optional, Set, cast

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, Response
from starlette.routing import Mount, Route, WebSocketRoute
from starlette.staticfiles import StaticFiles

from pywire.runtime.error_page import ErrorPage
from pywire.runtime.http_transport import HTTPTransportHandler
from pywire.runtime.router import Router
from pywire.runtime.upload_manager import upload_manager
from pywire.runtime.websocket import WebSocketHandler


class PyWire:
    """Main ASGI application and configuration."""

    def __init__(
        self,
        pages_dir: Optional[str] = None,
        path_based_routing: bool = True,
        enable_pjax: bool = True,
        debug: bool = False,
        enable_webtransport: bool = False,
        static_dir: Optional[str] = None,
        static_path: str = "/static",
    ) -> None:
        if pages_dir is None:
            # Auto-discovery
            cwd = Path.cwd()
            potential_paths = [cwd / "pages", cwd / "src" / "pages"]

            discovered = False
            for path in potential_paths:
                if path.exists() and path.is_dir():
                    self.pages_dir = path
                    discovered = True
                    break

            if not discovered:
                # Default to 'pages' and let it fail/warn later if missing
                self.pages_dir = Path("pages")
        else:
            self.pages_dir = Path(pages_dir)

        self.pages_dir = self.pages_dir.resolve()

        # User configured static directory (disabled by default)
        self.static_dir = None
        if static_dir:
            path = Path(static_dir)
            if not path.is_absolute():
                # Try relative to CWD
                potential = Path.cwd() / path
                if not potential.exists():
                    # Try src/ fallback
                    src_potential = Path.cwd() / "src" / path
                    if src_potential.exists():
                        potential = src_potential
                self.static_dir = potential.resolve()
            else:
                self.static_dir = path

        self.static_url_path = static_path

        self.path_based_routing = path_based_routing
        self.enable_pjax = enable_pjax
        self.debug = debug
        self.enable_webtransport = enable_webtransport
        # Internal flag set by dev_server.py when running via 'pywire dev'
        self._is_dev_mode = False

        self.router = Router()

        from pywire.runtime.loader import get_loader

        self.loader = get_loader()

        self.ws_handler = WebSocketHandler(self)
        self.http_handler = HTTPTransportHandler(self)

        # Initialize WebTransport handler
        from pywire.runtime.webtransport_handler import WebTransportHandler

        self.web_transport_handler = WebTransportHandler(self)

        # Valid upload tokens
        self.upload_tokens: Set[str] = set()

        # Compile and register all pages
        self._load_pages()

        # Static files (PyWire Internal)
        internal_static_dir = Path(__file__).parent.parent / "static"

        # Prepare exception handlers
        exception_handlers: Dict[int, Any] = {}
        # Always register our handler to check for custom error pages
        exception_handlers[500] = self._handle_500

        # Build routes list
        routes = [
            # Capabilities endpoint for transport negotiation
            Route("/_pywire/capabilities", self._handle_capabilities, methods=["GET"]),
            # WebSocket transport
            WebSocketRoute("/_pywire/ws", self.ws_handler.handle),
            # HTTP transport endpoints
            Route("/_pywire/session", self.http_handler.create_session, methods=["POST"]),
            Route("/_pywire/poll", self.http_handler.poll, methods=["GET"]),
            Route("/_pywire/event", self.http_handler.handle_event, methods=["POST"]),
            # Upload endpoint
            Route("/_pywire/upload", self._handle_upload, methods=["POST"]),
            # Internal Static files
            Mount(
                "/_pywire/static",
                app=StaticFiles(directory=str(internal_static_dir)),
                name="internal_static",
            ),
        ]

        # Mount User Static Files if configured
        if self.static_dir:
            if not self.static_dir.exists():
                print(f"Warning: Configured static directory '{self.static_dir}' does not exist.")
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
            routes.append(Route("/_pywire/source", self._handle_source, methods=["GET"]))
            routes.append(Route("/_pywire/file/{encoded:path}", self._handle_file, methods=["GET"]))
            # Chrome DevTools automatic workspace folders (M-135+)
            routes.append(
                Route(
                    "/.well-known/appspecific/com.chrome.devtools.json",
                    self._handle_devtools_json,
                    methods=["GET"],
                )
            )

        # Default page handler (catch-all, must be last)
        routes.append(Route("/{path:path}", self._handle_request, methods=["GET", "POST"]))

        # Create Starlette app with all transport routes
        self.app = Starlette(routes=routes, exception_handlers=exception_handlers)

        # Store configuration in app state for runtime access (e.g. by pages)
        self.app.state.enable_pjax = self.enable_pjax
        self.app.state.debug = self.debug
        self.app.state.pywire = self

    async def _handle_capabilities(self, request: Request) -> JSONResponse:
        """Return server transport capabilities for client negotiation."""
        return JSONResponse(
            {
                "transports": ["websocket", "http"],
                # WebTransport requires HTTP/3 - only available when running with Hypercorn
                "webtransport": False,
                "version": "0.0.1",
            }
        )

    def _get_client_script_url(self) -> str:
        """Return the appropriate client bundle URL based on server mode.

        Returns dev bundle when running via 'pywire dev', core bundle otherwise.
        """
        if self._is_dev_mode:
            return "/_pywire/static/pywire.dev.min.js"
        return "/_pywire/static/pywire.core.min.js"

    async def _handle_upload(self, request: Request) -> JSONResponse:
        """Handle file uploads."""
        print(f"DEBUG: Handling upload request for {request.url}")
        try:
            # Check for upload token
            token = request.headers.get("X-Upload-Token")
            if not token or token not in self.upload_tokens:
                return JSONResponse({"error": "Invalid or expired upload token"}, status_code=403)

            # Fail-fast: Check Content-Length header
            content_length = request.headers.get("content-length")
            if content_length:
                try:
                    length = int(content_length)
                    # Global safety limit: 10MB (allows for 5MB file + overhead)
                    # Real app might configure this or inspect specific field limits after streaming
                    if length > 10 * 1024 * 1024:
                        print(f"WARN: Upload rejected. Content-Length {length} exceeds 10MB limit.")
                        return JSONResponse({"error": "Payload Too Large"}, status_code=413)
                except ValueError:
                    pass

            form = await request.form()
            response_data = {}
            for field_name, file in form.items():
                if hasattr(file, "filename"):  # It's an UploadFile
                    # We don't really need the ID if we are just testing upload for now?
                    # Wait, saving returns the ID!
                    from starlette.datastructures import UploadFile

                    upload_id = upload_manager.save(cast(UploadFile, file))
                    response_data[field_name] = upload_id

            print(f"DEBUG: Upload successful. Returning: {response_data}")
            return JSONResponse(response_data)
        except Exception as e:
            traceback.print_exc()
            return JSONResponse({"error": str(e)}, status_code=500)

    async def _handle_source(self, request: Request) -> Response:
        """Serve source code for debugging."""
        print(f"DEBUG: _handle_source called, debug={self.debug}")
        if not self.debug:
            print("DEBUG: _handle_source returning 404 because debug=False")
            return Response("Not Found", status_code=404)

        if not self._is_dev_mode:
            print("DEBUG: _handle_source returning 404 because _is_dev_mode=False")
            return Response("Not Found", status_code=404)

        path_str = request.query_params.get("path")
        print(f"DEBUG: _handle_source path={path_str}")
        if not path_str:
            return Response("Missing path", status_code=400)

        try:
            path = Path(path_str).resolve()
            print(
                f"DEBUG: _handle_source resolved path={path}, exists={path.exists()}, "
                f"is_file={path.is_file()}"
            )
            # Security check: Ensure we are only serving files from allowed directories?
            # For a dev tool, we might want to allow viewing any file in the
            # traceback which might include library files.
            # But normally we want to restrict to project and maybe venv.
            # Let's just check it exists and is a file for now.
            if not path.is_file():
                return Response("File not found", status_code=404)

            content = path.read_text(encoding="utf-8")
            return Response(content, media_type="text/plain")
        except Exception as e:
            print(f"DEBUG: _handle_source exception: {e}")
            return Response(str(e), status_code=500)

    async def _handle_file(self, request: Request) -> Response:
        """Serve source file by base64-encoded path (for DevTools source mapping)."""
        if not self.debug or not self._is_dev_mode:
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
            print(f"DEBUG: _handle_file exception: {e}")
            return Response(str(e), status_code=500)

    async def _handle_devtools_json(self, request: Request) -> JSONResponse:
        """Serve Chrome DevTools project settings for automatic workspace folders."""
        if not self.debug or not self._is_dev_mode:
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

        # Explicitly check for __error__.pywire in root pages dir
        # (It is skipped by _scan_directory because it starts with _)
        error_page_path = self.pages_dir / "__error__.pywire"
        if error_page_path.exists():
            try:
                root_layout = None
                if (self.pages_dir / "__layout__.pywire").exists():
                    root_layout = str((self.pages_dir / "__layout__.pywire").resolve())

                page_class = self.loader.load(error_page_path, implicit_layout=root_layout)
                self.router.add_route("/__error__", page_class)
            except Exception as e:
                print(f"Failed to load error page {error_page_path}: {e}")
                traceback.print_exc()

    def _scan_directory(
        self, dir_path: Path, layout_path: Optional[str] = None, url_prefix: str = ""
    ) -> None:
        """Recursively scan directory for pages and layouts."""
        current_layout = layout_path

        # Priority: __layout__.pywire ONLY
        potential_layout = dir_path / "__layout__.pywire"

        if potential_layout.exists():
            # Compile layout first (it might use the parent layout!)
            try:
                # Layouts can inherit from parent layouts too
                self.loader.load(potential_layout, implicit_layout=layout_path)
                current_layout = str(potential_layout.resolve())
            except Exception as e:
                print(f"Failed to load layout {potential_layout}: {e}")
                traceback.print_exc()

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

                # Check for [param] syntax
                param_match = re.match(r"^\[(.*?)\]$", name)
                if param_match:
                    param_name = param_match.group(1)
                    # Convert to routing syntax :{name} (or whatever Router supports)
                    # Router supports :name or {name}
                    new_segment = f"{{{param_name}}}"

                new_prefix = (url_prefix + "/" + new_segment).replace("//", "/")
                self._scan_directory(entry, current_layout, new_prefix)

            elif entry.is_file() and entry.suffix == ".pywire":
                if entry.name == "layout.pywire":
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
                name = entry.stem  # filename without .pywire

                route_segment = name
                if name == "index":
                    route_segment = ""
                else:
                    # Check for [param] in filename
                    param_match = re.match(r"^\[(.*?)\]$", name)
                    if param_match:
                        param_name = param_match.group(1)
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
                    print(f"Failed to load page {entry}: {e}")
                    traceback.print_exc()
                    self._register_error_page(entry, e)

    def _register_error_page(self, file_path: Path, error: Exception) -> None:
        """Register an error page for a failed file."""
        # Try to infer route from file path/content
        # 1. Start with path relative to pages_dir
        try:
            rel_path = file_path.relative_to(self.pages_dir)

            # Basic route inference from path
            route_path = "/" + str(rel_path.with_suffix("")).replace("index", "").strip("/")
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

                        def __init__(self, request: Request, *args: Any, **kwargs: Any) -> None:
                            # Store for parent __init__
                            super().__init__(request, *args, **kwargs)

                        async def render(self, init: bool = True) -> Any:
                            # Check mode at render time (not registration time!)
                            # This allows dev_server.py to set _is_dev_mode after app init
                            if captured_app.debug or getattr(captured_app, "_is_dev_mode", False):
                                # DEV MODE: Show detailed CompileErrorPage
                                detail_page = CompileErrorPage(
                                    self.request, captured_error, file_path=captured_file_path
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
            print(f"Failed to register error page for {file_path}: {e}")

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
                if not name.endswith(".pywire"):
                    return None
                if name == "layout.pywire":
                    return None
                name = Path(name).stem

            segment = name
            if name == "index":
                segment = ""

            param_match = re.match(r"^\[(.*?)\]$", name)
            if param_match:
                param_name = param_match.group(1)
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
            layout = current_dir / "__layout__.pywire"

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
                break

        return None

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
            try:
                # Resolve implicit layout for re-compilation
                implicit_layout = self._resolve_implicit_layout(file_path)

                # Recompile
                new_page_class = self.loader.load(file_path, implicit_layout=implicit_layout)

                is_in_pages = False
                try:
                    file_path.relative_to(self.pages_dir)
                    is_in_pages = True
                except ValueError:
                    is_in_pages = False

                self.router.remove_routes_for_file(str(file_path))

                # Special handling for __error__.pywire
                if file_path.name == "__error__.pywire":
                    self.router.add_route("/__error__", new_page_class)
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

                print(f"Reloaded: {file_path}")

            except Exception as e:
                print(f"Failed to reload {file_path}: {e}")
                traceback.print_exc()

                # If it was a page, show error
                if is_in_pages or file_path.name == "__error__.pywire":
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
        """Handle HTTP request."""
        # Check for uploads first
        # (This was handled in Route declarations, but uploads go to /_pywire/upload)

        path = request.url.path
        match = self.router.match(path)
        if not match:
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
                if hasattr(page_class, "__routes__"):
                    for name in page_class.__routes__.keys():
                        path_info[name] = name == variant_name
                elif hasattr(page_class, "__route__"):
                    path_info["main"] = True

                from pywire.runtime.router import URLHelper

                url_helper = None
                if hasattr(page_class, "__routes__"):
                    url_helper = URLHelper(page_class.__routes__)

                try:
                    page = page_class(request, {}, query, path=path_info, url=url_helper)
                    # Inject error code
                    page.error_code = 404
                    response = await page.render()
                    response.status_code = 404
                    return response
                except Exception as e:
                    print(f"Failed to render custom error page {page_class}: {e}")
                    import traceback

                    traceback.print_exc()
                    pass  # Fallback

            # Default 404 with client script
            page = ErrorPage(request, "404 Not Found", f"The path '{path}' could not be found.")
            response = await page.render()
            response.status_code = 404
            return response

        page_class, params, variant_name = match
        # ... (params, query, path_info, url_helper construction)
        # Build query params
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

        # Instantiate page
        page = page_class(request, params, query, path=path_info, url=url_helper)

        # Check if this is an event request
        if request.method == "POST" and "X-PyWire-Event" in request.headers:
            # Handle event
            try:
                event_data = await request.json()
                response = await page.handle_event(event_data.get("handler", ""), event_data)
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=500)
        else:
            # Normal render
            response = await page.render()

        # Script injection is now handled by the compiler (generator.py)
        # to ensure it's present in both dev and production.

        # Inject WebTransport certificate hash if available (Dev Mode)
        if isinstance(response, Response) and response.media_type == "text/html":
            body = bytes(response.body).decode("utf-8")
            injections = []

            # WebTransport Hash
            if hasattr(request.app.state, "webtransport_cert_hash"):
                cert_hash = list(request.app.state.webtransport_cert_hash)
                injections.append(f"<script>window.PYWIRE_CERT_HASH = {cert_hash};</script>")

            # Upload Token Injection
            if getattr(page, "__has_uploads__", False):
                import secrets

                token = secrets.token_urlsafe(32)
                self.upload_tokens.add(token)
                # Token meta tag
                injections.append(f'<meta name="pywire-upload-token" content="{token}">')

            if injections:
                injection_str = "\n".join(injections)
                if "</body>" in body:
                    body = body.replace("</body>", injection_str + "</body>")
                else:
                    body += injection_str
                response = Response(body, media_type="text/html")

        return response

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        """ASGI interface."""
        print(f"DEBUG: Scope type: {scope['type']}")
        if scope["type"] == "webtransport":
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
