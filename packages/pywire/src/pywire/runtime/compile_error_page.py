import html
import linecache
import os
import traceback
from typing import Any, Dict, Optional, Union, cast

from starlette.requests import Request
from starlette.responses import HTMLResponse

from pywire.compiler.exceptions import PyWireSyntaxError
from pywire.runtime.page import BasePage


class CompileErrorPage(BasePage):
    """Page used to display compilation errors with helpful context.

    Handles both PyWireSyntaxError (with known file/line) and generic
    exceptions (extracting info from traceback).
    """

    def __init__(
        self,
        request: Request,
        error: Union[PyWireSyntaxError, Exception],
        file_path: Optional[str] = None,
    ):
        self.request = request
        self.error = error
        self._file_path = file_path
        self.error_file: Optional[str] = None
        self.error_line: Optional[int] = None

        # Extract file/line info based on error type
        if isinstance(error, PyWireSyntaxError):
            self.error_file = error.file_path
            self.error_line = error.line
            self.error_message = error.message
            self.traceback_lines = None  # No traceback for syntax errors
        else:
            # Generic exception - extract from traceback
            self.error_message = f"{type(error).__name__}: {str(error)}"
            self.traceback_lines = traceback.format_exception(
                type(error), error, error.__traceback__
            )

            # Try to find the most relevant frame (last user code frame)
            self.error_file = file_path
            self.error_line = None
            if error.__traceback__:
                tb_summary = traceback.extract_tb(error.__traceback__)
                for frame in reversed(tb_summary):
                    # Prefer .pywire files
                    if frame.filename.endswith(".pywire"):
                        self.error_file = frame.filename
                        self.error_line = frame.lineno
                        break
                    # Otherwise use last non-framework frame
                    if (
                        "pywire/src/pywire" not in frame.filename
                        and "site-packages" not in frame.filename
                    ):
                        self.error_file = frame.filename
                        self.error_line = frame.lineno
                        break
                # Fallback to last frame if nothing better found
                if self.error_line is None and tb_summary:
                    self.error_file = tb_summary[-1].filename
                    self.error_line = tb_summary[-1].lineno

    async def render(self, init: bool = True) -> HTMLResponse:
        """Render the compile error page."""
        # Read the context around the error line
        context_lines = []
        if self.error_file and self.error_line and os.path.exists(self.error_file):
            try:
                # Force cache update
                linecache.checkcache(self.error_file)
                lines = linecache.getlines(self.error_file)
                start = max(1, self.error_line - 5)
                end = min(len(lines), self.error_line + 5)

                for i in range(start, end + 1):
                    if i <= len(lines):
                        context_lines.append(
                            {
                                "num": i,
                                "content": lines[i - 1].rstrip(),
                                "is_current": i == self.error_line,
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

        # Shorten file path for display
        file_display = self.error_file or "unknown"
        try:
            cwd = os.getcwd()
            if file_display.startswith(cwd):
                file_display = os.path.relpath(file_display, cwd)
        except Exception:
            pass

        # Error title based on type
        if isinstance(self.error, PyWireSyntaxError):
            error_title = "PyWire Syntax Error"
        else:
            error_title = "Compilation Error"

        # Traceback section for generic exceptions
        traceback_html = ""
        if self.traceback_lines:
            tb_text = "".join(self.traceback_lines)
            traceback_html = f"""
            <div class="traceback-section">
                <h3>Full Traceback</h3>
                <pre class="traceback">{html.escape(tb_text)}</pre>
            </div>
            """

        content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>{error_title}</title>
            <style>
                body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI",
                                     Roboto, sans-serif;
                       background: #1a1a1a; color: #e0e0e0; margin: 0; padding: 20px; }}
                h1 {{ color: #ff6b6b; font-size: 24px; margin-bottom: 5px; }}
                h3 {{ color: #aaa; font-size: 16px; margin-top: 30px; margin-bottom: 10px; }}
                .exc-msg {{ font-size: 16px; color: #fff; margin-bottom: 20px;
                           white-space: pre-wrap; font-family: monospace;
                           line-height: 1.6; }}
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
                .traceback-section {{ margin-top: 20px; }}
                .traceback {{ background: #222; padding: 15px; border-radius: 8px; font-size: 12px;
                             overflow-x: auto; color: #ccc; white-space: pre-wrap;
                             word-break: break-word; }}
                .header-block {{ border-bottom: 1px solid #333; padding-bottom: 20px;
                                margin-bottom: 20px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header-block">
                    <h1>{error_title}</h1>
                </div>

                <div class="error-location">
                    <div class="file-info">{html.escape(file_display)}{
            ":" + str(self.error_line) if self.error_line else ""
        }</div>
                    <div class="exc-msg">{html.escape(self.error_message)}</div>
                </div>

                {f'<div class="code-context">{context_html}</div>' if context_html else ""}

                {traceback_html}
            </div>
            <!-- Standard PyWire Client Script for Hot Reload -->
            <script src="/_pywire/static/pywire.dev.min.js"></script>
        </body>
        </html>
        """
        return HTMLResponse(content)

    async def handle_event(self, handler_name: str, data: Dict[str, Any]) -> HTMLResponse:
        """No-op for error page."""
        return HTMLResponse("Error page does not handle events")
