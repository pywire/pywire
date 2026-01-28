import html
from typing import Any, Dict

from starlette.requests import Request
from starlette.responses import HTMLResponse

from pywire.runtime.page import BasePage


class ErrorPage(BasePage):
    """Page used to display compilation errors."""

    def __init__(self, request: Request, error_title: str, error_detail: str):
        # Initialize base directly without calling super().__init__ completely
        # because we don't have all the normal params
        self.request = request
        self.error_title = error_title
        self.error_detail = error_detail

    async def render(self, init: bool = True) -> HTMLResponse:
        """Render the error page."""
        escaped_detail = html.escape(self.error_detail or "")
        content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>PyWire Error: {html.escape(self.error_title)}</title>
            <style>
                body {{
                    font-family: system-ui, -apple-system, sans-serif;
                    padding: 2rem;
                    background: #fff0f0;
                    color: #333;
                }}
                .error-container {{
                    max-width: 900px;
                    margin: 0 auto;
                    background: white;
                    padding: 2rem;
                    border-radius: 8px;
                    box-shadow: 0 4px 6px rgba(0,0,0,0.1);
                    border-left: 6px solid #ff4444;
                }}
                h1 {{
                    margin-top: 0;
                    color: #cc0000;
                }}
                pre {{
                    background: #f8f8f8;
                    padding: 1rem;
                    border-radius: 4px;
                    overflow-x: auto;
                    font-size: 14px;
                    border: 1px solid #eee;
                    white-space: pre-wrap;
                }}
            </style>
        </head>
        <body>
            <div class="error-container">
                <h1>{html.escape(self.error_title)}</h1>
                <pre>{escaped_detail}</pre>
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
