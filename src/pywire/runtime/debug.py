import html
import linecache
import os
import traceback
import urllib.parse
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union, cast

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
        is_framework_error = self._is_framework_error(frames[-1]["filename"]) if frames else False

        html_content = self._generate_html(exc_type, exc_msg, frames, is_framework_error)
        return HTMLResponse(html_content, status_code=500)

    def _render_compile_error(self, exc: PyWireSyntaxError) -> HTMLResponse:
        """Render a specialized error page for compile-time syntax errors."""
        # Read the context around the error line
        context_lines: List[Dict[str, Union[int, str, bool]]] = []
        if exc.file_path and exc.line and os.path.exists(exc.file_path):
            try:
                lines = linecache.getlines(exc.file_path)
                start = max(1, exc.line - 5)
                end = min(len(lines), exc.line + 5)

                for i in range(start, end + 1):
                    if i <= len(lines):
                        context_lines.append(
                            {
                                "num": i,
                                "content": lines[i - 1].rstrip(),
                                "is_current": i == exc.line,
                            }
                        )
            except Exception:
                pass

        # Generate code context HTML
        context_html = ""
        for line in context_lines:
            content = cast(str, line["content"])
            cls = "line-current" if line["is_current"] else "line"
            context_html += (
                f"<div class='{cls}'><span class='line-num'>{line['num']}</span> "
                f"<span class='code'>{html.escape(content)}</span></div>"
            )

        short_path = self._shorten_path(exc.file_path) if exc.file_path else "unknown file"

        return HTMLResponse(
            f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>PyWire Syntax Error</title>
            <style>
                body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI",
                                     Roboto, sans-serif;
                       background: #1a1a1a; color: #e0e0e0; margin: 0; padding: 20px; }}
                h1 {{ color: #ff6b6b; font-size: 24px; margin-bottom: 5px; }}
                .exc-msg {{ font-size: 16px; color: #fff; margin-bottom: 20px;
                          white-space: pre-wrap; font-family: monospace; line-height: 1.6; }}
                .container {{ max-width: 1000px; margin: 0 auto; }}
                .error-location {{ background: #2d2d2d; border-radius: 8px; padding: 15px;
                                 margin-bottom: 20px; border-left: 4px solid #ff6b6b; }}
                .file-info {{ color: #ffd43b; font-family: monospace; font-size: 14px;
                            margin-bottom: 10px; }}
                .code-context {{ padding: 10px 0; background: #222; font-family: "Fira Code",
                               monospace; font-size: 13px; overflow-x: auto; border-radius: 4px; }}
                .line {{ padding: 2px 15px; color: #888; display: flex; }}
                .line-current {{ padding: 2px 15px; background: #3c1e1e; color: #ffcccc;
                               display: flex; border-left: 3px solid #ff6b6b; }}
                .line-num {{ width: 40px; text-align: right; margin-right: 15px; opacity: 0.5;
                           user-select: none; }}
                .code {{ white-space: pre; }}
                .help-box {{ background: #1e3a3a; border: 1px solid #69db7c; color: #69db7c;
                           padding: 15px; border-radius: 8px; margin-top: 20px; }}
                .help-box strong {{ display: block; margin-bottom: 8px; font-size: 16px; }}
                .header-block {{ border-bottom: 1px solid #333; padding-bottom: 20px;
                                margin-bottom: 20px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header-block">
                    <h1>PyWire Syntax Error</h1>
                </div>

                <div class="error-location">
                    <div class="file-info">{html.escape(short_path)}:{exc.line}</div>
                    <div class="exc-msg">{html.escape(exc.message)}</div>
                </div>

                {f'<div class="code-context">{context_html}</div>' if context_html else ""}
            </div>
            <!-- Standard PyWire Client Script for Hot Reload -->
            <script src="/_pywire/static/pywire.dev.min.js"></script>
        </body>
        </html>
        """,
            status_code=500,
        )

    def _get_frames(self, tb: Optional["TracebackType"]) -> List[Dict[str, Any]]:
        frames = []
        for frame, lineno in traceback.walk_tb(tb):
            filename = frame.f_code.co_filename
            func_name = frame.f_code.co_name
            # locals_vars = frame.f_locals # Could be huge/sensitive, maybe filter or omit

            # Read context
            # linecache.checkcache(filename) # Check for updates
            context_lines = []
            try:
                # If file exists, read it.
                # Note: valid line numbers are 1-based.
                # We want a window around lineno.
                start = max(1, lineno - 5)
                end = lineno + 5

                # Check if file exists
                if os.path.exists(filename):
                    lines = linecache.getlines(filename)
                    for i in range(start, end + 1):
                        if i <= len(lines):
                            context_lines.append(
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
                    "context": context_lines,
                    "is_user_code": self._is_user_code(filename),
                }
            )
        return frames

    def _is_framework_error(self, filename: str) -> bool:
        # If the LAST frame is in pywire package, it's likely a framework error
        # UNLESS it's a template compilation error which might manifest differently.
        return "pywire/src/pywire" in filename or "site-packages/pywire" in filename

    def _is_user_code(self, filename: str) -> bool:
        return not self._is_framework_error(filename) and "<frozen" not in filename

    def _shorten_path(self, path: str) -> str:
        cwd = os.getcwd()
        if path.startswith(cwd):
            return os.path.relpath(path, cwd)
        return path

    def _generate_html(
        self, exc_type: str, exc_msg: str, frames: List[Dict[str, Any]], is_framework_error: bool
    ) -> str:
        # GitHub issue URL generation
        issue_title = urllib.parse.quote(f"Bug: {exc_type}: {exc_msg}")
        issue_body = urllib.parse.quote(
            f"### Description\nEncountered an error in PyWire.\n\n"
            f"### Error\n`{exc_type}: {exc_msg}`\n\n### Traceback\n"
            f"(Please paste relevant traceback here)"
        )
        github_url = f"https://github.com/reecelikesramen/pywire/issues/new?title={issue_title}&body={issue_body}"

        frames_html = []
        for frame in reversed(frames):  # Show most recent call first
            context_html = ""
            for line in frame["context"]:
                cls = "line-current" if line["is_current"] else "line"
                context_html += (
                    f"<div class='{cls}'><span class='line-num'>{line['num']}</span> "
                    f"<span class='code'>{html.escape(line['content'])}</span></div>"
                )

            frame_class = "frame-user" if frame["is_user_code"] else "frame-vendor"

            frames_html.append(f"""
            <div class="frame {frame_class}">
                <div class="frame-header">
                    <span class="func">{html.escape(frame["func_name"])}</span>
                    <span class="file">{html.escape(frame["short_filename"])}:
                        {frame["lineno"]}</span>
                </div>
                <div class="code-context">
                    {context_html}
                </div>
            </div>
            """)

        frames_joined = "\n".join(frames_html)

        framework_alert = ""
        if is_framework_error:
            framework_alert = f"""
            <div class="alert alert-warning">
                <strong>Potential Framework Bug</strong>
                <p>This error seems to originate from within PyWire. If you believe this is a bug,
                   please <a href="{github_url}" target="_blank" class="issue-link">open an issue
                   on GitHub</a>.</p>
            </div>
            """

        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>{html.escape(exc_type)}</title>
            <style>
                body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI",
                                     Roboto, sans-serif;
                       background: #1a1a1a; color: #e0e0e0; margin: 0; padding: 20px; }}
                h1 {{ color: #ff6b6b; font-size: 24px; margin-bottom: 5px; }}
                .exc-msg {{ font-size: 18px; color: #fff; margin-bottom: 20px; font-weight: 500; }}
                .container {{ max-width: 1000px; margin: 0 auto; }}
                .frames {{ display: flex; flex-direction: column; gap: 15px; }}
                .frame {{ background: #2d2d2d; border-radius: 8px; overflow: hidden;
                        border: 1px solid #333; }}
                .frame-user {{ border-left: 4px solid #69db7c; }}
                .frame-vendor {{ border-left: 4px solid #74c0fc; opacity: 0.8; }}
                .frame-header {{ padding: 10px 15px; background: #333; display: flex;
                                justify-content: space-between; font-family: monospace;
                                font-size: 14px; }}
                .func {{ color: #ffd43b; font-weight: bold; }}
                .file {{ color: #aaa; }}
                .code-context {{ padding: 10px 0; background: #222; font-family: "Fira Code",
                               monospace; font-size: 13px; overflow-x: auto; }}
                .line {{ padding: 2px 15px; color: #888; display: flex; }}
                .line-current {{ padding: 2px 15px; background: #3c1e1e; color: #ffcccc;
                               display: flex; }}
                .line-num {{ width: 40px; text-align: right; margin-right: 15px; opacity: 0.5;
                           select-user: none; }}
                .code {{ white-space: pre; }}
                .alert {{ background: #3d2800; border: 1px solid #fcc419; color: #fcc419;
                        padding: 15px; border-radius: 8px; margin-bottom: 20px; }}
                .issue-link {{ color: #ffd43b; text-decoration: underline; }}
                .header-block {{ border-bottom: 1px solid #333; padding-bottom: 20px;
                                margin-bottom: 20px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header-block">
                    <h1>{html.escape(exc_type)}</h1>
                    <div class="exc-msg">{html.escape(exc_msg)}</div>
                    {framework_alert}
                </div>
                <h2>Traceback</h2>
                <div class="frames">
                    {frames_joined}
                </div>
            </div>
        </body>
        </html>
        """


# import urllib.parse  # Moved to top
