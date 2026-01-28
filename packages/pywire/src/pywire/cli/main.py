"""Main CLI entry point."""

import os
import sys
from pathlib import Path
from typing import Any, Optional

import click


def import_app(app_str: str) -> Any:
    """Import application from string (e.g. 'main:app')."""
    if ":" not in app_str:
        raise click.BadParameter("App must be in format 'module:app'", param_hint="APP")

    module_name, app_name = app_str.split(":", 1)

    # Add current directory to path so we can import local modules
    sys.path.insert(0, os.getcwd())

    try:
        import importlib

        module = importlib.import_module(module_name)
    except ImportError as e:
        raise click.BadParameter(f"Could not import module '{module_name}': {e}", param_hint="APP")

    try:
        app = getattr(module, app_name)
    except AttributeError:
        raise click.BadParameter(
            f"Attribute '{app_name}' not found in module '{module_name}'", param_hint="APP"
        )

    return app


def _discover_app_str() -> str:
    """Try to discover the app string automatically."""
    cwd = Path(os.getcwd())

    # Priority: main.py, app.py, api.py
    # Also check src/ directory
    search_paths = [cwd, cwd / "src"]

    for path in search_paths:
        if not path.exists():
            continue

        for filename in ["main.py", "app.py", "api.py"]:
            if (path / filename).exists():
                # Check for common app instance names: app, api
                module_name = filename[:-3]

                # Construct module path (e.g. src.main)
                if path.name == "src":
                    module_path = f"src.{module_name}"
                else:
                    module_path = module_name

                # Simple check: try to import and look for app
                try:
                    sys.path.insert(0, str(cwd))
                    import importlib

                    module = importlib.import_module(module_path)

                    if hasattr(module, "app"):
                        return f"{module_path}:app"
                    if hasattr(module, "api"):
                        return f"{module_path}:api"

                except ImportError:
                    continue

    raise click.UsageError(
        "Could not auto-discover app. Please provide 'APP' argument (e.g. 'main:app')."
    )


@click.group()
@click.version_option()
def cli() -> None:
    """PyWire framework CLI.

    Run 'pywire dev APP' to start development server.
    Run 'pywire run APP' to start production server.

    APP should be a string in format 'module:instance', e.g. 'main:app'
    If not provided, PyWire tries to discover it in main.py, app.py, etc.
    """
    pass


@cli.command()
@click.argument("app", required=False)
@click.option("--host", default="127.0.0.1", help="Host to bind to")
@click.option("--port", default=3000, type=int, help="Port to bind to")
@click.option("--ssl-keyfile", default=None, help="SSL key file")
@click.option("--ssl-certfile", default=None, help="SSL certificate file")
@click.option("--env-file", default=None, help="Environment configuration file")
def dev(
    app: Optional[str],
    host: str,
    port: int,
    ssl_keyfile: Optional[str],
    ssl_certfile: Optional[str],
    env_file: Optional[str],
) -> None:
    """Start development server."""
    import asyncio

    from pywire.runtime.dev_server import run_dev_server

    if not app:
        app = _discover_app_str()
        click.echo(f"🔍 Auto-discovered app: {app}")

    # Verify import
    import_app(app)

    click.echo(f"🚀 Starting PyWire dev server on http://{host}:{port}")
    if ssl_certfile:
        click.echo("🔒 SSL enabled")

    asyncio.run(
        run_dev_server(
            app_str=app,  # Pass string for reloadability hooks if needed
            host=host,
            port=port,
            ssl_keyfile=ssl_keyfile,
            ssl_certfile=ssl_certfile,
        )
    )


@cli.command()
@click.argument("app", required=False)
def build(app: Optional[str]) -> None:
    """Build the application for production (stub)."""
    if not app:
        app = _discover_app_str()

    click.echo(f"🔨 Building {app}...")
    # TODO: Implement build logic (static asset compilation, etc.)
    click.echo("✅ Build complete (stub)")


@cli.command()
@click.argument("app", required=False)
@click.option("--host", default="0.0.0.0", help="Host to bind to")
@click.option("--port", default=8000, type=int, help="Port to bind to")
@click.option("--workers", default=None, type=int, help="Number of worker processes")
@click.option("--no-access-log", is_flag=True, help="Disable access logging")
def run(
    app: Optional[str], host: str, port: int, workers: Optional[int], no_access_log: bool
) -> None:
    """Run production server using Uvicorn."""
    import multiprocessing

    import uvicorn

    if not app:
        app = _discover_app_str()
        click.echo(f"🔍 Auto-discovered app: {app}")

    if workers is None:
        workers = (multiprocessing.cpu_count() * 2) + 1

    click.echo(f"🚀 Starting production server for {app}")
    click.echo(f"🌍 Listening on http://{host}:{port}")
    click.echo(f"👷 Workers: {workers}")

    # Locate the app object to verify, but pass string to uvicorn
    import_app(app)

    uvicorn.run(
        app, host=host, port=port, workers=workers, access_log=not no_access_log, factory=False
    )


if __name__ == "__main__":
    cli()
