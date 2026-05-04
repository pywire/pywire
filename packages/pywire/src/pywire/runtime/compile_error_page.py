import linecache
import os
import random
import traceback
from typing import Any, Optional, Union

from starlette.requests import Request
from starlette.responses import HTMLResponse

from pywire import __version__
from pywire.compiler.exceptions import PyWireSyntaxError
from pywire.runtime.page import BasePage

# Tagline pools — random electricity/wire puns per error category.
# Keep short, technical, never cute. Sentence case, period.
_TAGLINES_SYNTAX = [
    "Solder cracked.",
    "Bad joint in the wire.",
    "Polarity reversed.",
    "Pin out of place.",
    "Wires crossed.",
    "Compiler smelled smoke.",
    "Lead came loose.",
    "Open trace on the board.",
]
_TAGLINES_RUNTIME = [
    "The wire shorted.",
    "Sparks flew.",
    "Magic smoke escaped.",
    "Fuse blew.",
    "Circuit overloaded.",
    "Ground fault detected.",
    "Insulation failed.",
    "Capacitor sang its last.",
]


class CompileErrorPage(BasePage):
    """Page used to display compilation errors with helpful context.

    Handles both PyWireSyntaxError (with known file/line) and generic
    exceptions (extracting info from traceback). The rendered HTML lives
    in ``src/pywire/templates/error/compile_error.html.j2`` and is loaded via
    Jinja's PackageLoader.
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

        if isinstance(error, PyWireSyntaxError):
            self.error_file = error.file_path
            self.error_line = error.line
            self.error_message = error.message
            self.traceback_lines = None
        else:
            self.error_message = f"{type(error).__name__}: {str(error)}"
            self.traceback_lines = traceback.format_exception(
                type(error), error, error.__traceback__
            )

            self.error_file = file_path
            self.error_line = None
            if error.__traceback__:
                tb_summary = traceback.extract_tb(error.__traceback__)
                for frame in reversed(tb_summary):
                    if frame.filename.endswith(".pywire"):
                        self.error_file = frame.filename
                        self.error_line = frame.lineno
                        break
                    if (
                        "pywire/src/pywire" not in frame.filename
                        and "site-packages" not in frame.filename
                    ):
                        self.error_file = frame.filename
                        self.error_line = frame.lineno
                        break
                if self.error_line is None and tb_summary:
                    self.error_file = tb_summary[-1].filename
                    self.error_line = tb_summary[-1].lineno

    def _collect_context_lines(self) -> list[dict[str, Any]]:
        if not (
            self.error_file and self.error_line and os.path.exists(self.error_file)
        ):
            return []
        try:
            linecache.checkcache(self.error_file)
            lines = linecache.getlines(self.error_file)
            start = max(1, self.error_line - 5)
            end = min(len(lines), self.error_line + 5)
            return [
                {
                    "num": i,
                    "content": lines[i - 1].rstrip(),
                    "is_current": i == self.error_line,
                }
                for i in range(start, end + 1)
                if i <= len(lines)
            ]
        except Exception:
            return []

    def _display_path(self) -> str:
        if not self.error_file:
            return "unknown"
        try:
            cwd = os.getcwd()
            if self.error_file.startswith(cwd):
                return os.path.relpath(self.error_file, cwd)
        except Exception:
            pass
        return self.error_file

    async def render(self, init: bool = True) -> HTMLResponse:
        is_syntax = isinstance(self.error, PyWireSyntaxError)
        title = "PyWire Syntax Error" if is_syntax else "Compilation Error"
        tagline = random.choice(_TAGLINES_SYNTAX if is_syntax else _TAGLINES_RUNTIME)
        root_path = ""
        try:
            root_path = str(self.request.scope.get("root_path", "") or "")
        except (AttributeError, KeyError):
            pass
        script_url = f"{root_path}/_pywire/static/pywire.dev.min.js?v={__version__}"

        from pywire.runtime.error_renderer import render_template

        html = render_template(
            "error/compile_error.html.j2",
            {
                "title": title,
                "tagline": tagline,
                "file_display": self._display_path(),
                "error_line": self.error_line,
                "error_message": self.error_message,
                "context_lines": self._collect_context_lines(),
                "traceback_text": "".join(self.traceback_lines)
                if self.traceback_lines
                else None,
                "script_url": script_url,
            },
        )
        return HTMLResponse(html, status_code=500)

    async def handle_event(
        self, event_name: str, event_data: dict[str, Any]
    ) -> dict[str, Any]:
        """No-op for error page."""
        return await self.render_update(init=False)
