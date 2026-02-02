import linecache
import os
import traceback
import urllib.parse
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from types import TracebackType

from starlette.responses import HTMLResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from pywire.compiler.exceptions import PyWireSyntaxError


class DevErrorMiddleware:
    """
    Middleware to catch exceptions and render a helpful debug page.
    Active only in development mode.
    """

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        try:
            await self.app(scope, receive, send)
        except Exception as exc:
            # Check if headers already sent? Starlette handles this if we return Response?
            # If we are midway through streaming, we might be in trouble, but for now catch all.
            response = self.render_error_page(exc)
            await response(scope, receive, send)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.app, name)

    def render_error_page(self, exc: Exception) -> HTMLResponse:
        # Check if this is a compile-time error
        if isinstance(exc, PyWireSyntaxError):
            return self._render_compile_error(exc)

        exc_type = type(exc).__name__
        exc_msg = str(exc)

        # Get traceback
        tb = exc.__traceback__

        # Skip top-level framework frames to focus on user code/relevant calls
        # (optional refinement)

        frames = self._get_frames(tb)
        is_framework_error = (
            self._is_framework_error(frames[-1]["filename"]) if frames else False
        )

        html_content = self._generate_html(
            exc_type, exc_msg, frames, is_framework_error
        )
        return HTMLResponse(html_content, status_code=500)

    def _render_compile_error(self, exc: PyWireSyntaxError) -> HTMLResponse:
        """Render a specialized error page for compile-time syntax errors."""
        from pywire.runtime.error_renderer import render_template

        # Script URL logic for 500 pages (usually dev mode)
        script_url = "/_pywire/static/pywire.dev.min.js"
        if hasattr(self.app, "state") and hasattr(self.app.state, "pywire"):
            script_url = self.app.state.pywire._get_client_script_url()

        # Context lines logic reused...
        # (Alternatively, could we reuse CompileErrorPage?
        # No, DevErrorMiddleware catches exceptions, CompileErrorPage is a page.
        # But logic is identical. For now, copying logic for simplicity
        # as CompileErrorPage might have different lifecycle).

        context_lines_data = []
        if exc.file_path and exc.line and os.path.exists(exc.file_path):
            try:
                linecache.checkcache(exc.file_path)
                lines = linecache.getlines(exc.file_path)
                start = max(1, exc.line - 5)
                end = min(len(lines), exc.line + 5)

                for i in range(start, end + 1):
                    if i <= len(lines):
                        context_lines_data.append(
                            {
                                "num": i,
                                "content": lines[i - 1].rstrip(),
                                "is_current": i == exc.line,
                            }
                        )
            except Exception:
                pass

        short_path = (
            self._shorten_path(exc.file_path) if exc.file_path else "unknown file"
        )

        html_content = render_template(
            "error/compile_error.html",
            {
                "file_display": short_path,
                "error_line": exc.line,
                "error_message": exc.message,
                "context_lines": context_lines_data,
                "script_url": script_url,
                "title": "PyWire Syntax Error",
            },
        )
        return HTMLResponse(html_content, status_code=500)

    def _get_frames(self, tb: Optional["TracebackType"]) -> List[Dict[str, Any]]:
        frames = []
        for frame, lineno in traceback.walk_tb(tb):
            filename = frame.f_code.co_filename
            func_name = frame.f_code.co_name
            context = []

            # Simple context reading for frames
            try:
                if os.path.exists(filename):
                    # linecache handles reading
                    start = max(1, lineno - 5)
                    end = lineno + 5
                    lines = linecache.getlines(filename)  # Will return [] if fails?
                    if lines:
                        for i in range(start, end + 1):
                            if i <= len(lines):
                                context.append(
                                    {
                                        "num": i,
                                        "content": lines[i - 1].rstrip(),
                                        "is_current": i == lineno,
                                    }
                                )
            except Exception:
                pass

            frames.append(
                {
                    "filename": filename,
                    "short_filename": self._shorten_path(filename),
                    "func_name": func_name,
                    "lineno": lineno,
                    "context": context,
                    "is_user_code": self._is_user_code(filename),
                }
            )
        return frames

    def _is_framework_error(self, filename: str) -> bool:
        return "pywire/src/pywire" in filename or "site-packages/pywire" in filename

    def _is_user_code(self, filename: str) -> bool:
        return not self._is_framework_error(filename) and "<frozen" not in filename

    def _shorten_path(self, path: str) -> str:
        cwd = os.getcwd()
        if path.startswith(cwd):
            return os.path.relpath(path, cwd)
        return path

    def _generate_html(
        self,
        exc_type: str,
        exc_msg: str,
        frames: List[Dict[str, Any]],
        is_framework_error: bool,
    ) -> str:
        from pywire.runtime.error_renderer import render_template

        script_url = "/_pywire/static/pywire.dev.min.js"
        if hasattr(self.app, "state") and hasattr(self.app.state, "pywire"):
            script_url = self.app.state.pywire._get_client_script_url()

        issue_title = urllib.parse.quote(f"Bug: {exc_type}: {exc_msg}")
        issue_body = urllib.parse.quote(
            f"### Description\nEncountered an error in PyWire.\n\n"
            f"### Error\n`{exc_type}: {exc_msg}`\n\n### Traceback\n"
            f"(Please paste relevant traceback here)"
        )
        github_url = f"https://github.com/pywire/pywire/issues/new?title={issue_title}&body={issue_body}"

        return render_template(
            "error/500.html",
            {
                "exc_type": exc_type,
                "exc_msg": exc_msg,
                "frames": frames,
                "is_framework_error": is_framework_error,
                "github_url": github_url,
                "script_url": script_url,
                "title": exc_type,
            },
        )


# import urllib.parse  # Moved to top
