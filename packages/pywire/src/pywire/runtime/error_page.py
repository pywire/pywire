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
        from pywire.runtime.error_renderer import render_template

        # Determine script URL (handled in app or passed here?)
        # For now, default to dev script as ErrorPage is mostly used in dev/mixed?
        # Actually app._get_client_script_url handles this logic, but we don't always have app ref here.
        # But wait, ErrorPage is usually instantiated by app or similar.
        # Let's check constructor. It takes request. We can get app from request.app usually if Starlette?
        # request.app is available.

        script_url = "/_pywire/static/pywire.core.min.js"
        if hasattr(self.request, "app") and hasattr(
            self.request.app, "_get_client_script_url"
        ):
            # Use the private method if available (a bit hacky but correct for PyWire app)
            # Or check debug mode directly
            pass

        # Actually, simpler: check if we are in dev mode via request.app.state if set?
        # The prompt mentioned "attach the correct script based on the environment".
        # PyWire app sets self.app.state.pywire = self.

        try:
            pywire_app = self.request.app.state.pywire
            script_url = pywire_app._get_client_script_url()
        except (AttributeError, KeyError):
            # Fallback
            script_url = "/_pywire/static/pywire.dev.min.js"

        html_content = render_template(
            "error/404.html",
            {
                "title": self.error_title,
                "message": self.error_detail or "",
                "script_url": script_url,
            },
        )

        return HTMLResponse(html_content)

    async def handle_event(
        self, handler_name: str, data: Dict[str, Any]
    ) -> dict[str, Any]:
        """No-op for error page."""
        return await self.render_update(init=False)
