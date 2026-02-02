"""Main CLI entry point."""

import os
import sys
from pathlib import Path
from typing import Any, Optional

import rich.panel
import rich_click as click

from pywire import __version__

# Astro-like styling configuration (Cyan Theme)
click.rich_click.USE_RICH_MARKUP = True
click.rich_click.STYLE_HELPTEXT_FIRST = True
click.rich_click.STYLE_COMMANDS_TABLE_SHOW_LINES = False
click.rich_click.STYLE_COMMANDS_TABLE_PAD_EDGE = False
click.rich_click.STYLE_COMMANDS_TABLE_BOX = None
click.rich_click.STYLE_COMMANDS_TABLE_EXPAND = False
click.rich_click.STYLE_OPTIONS_TABLE_EXPAND = False
click.rich_click.STYLE_COMMANDS_TABLE_HEADER = "bold magenta"
click.rich_click.STYLE_COMMANDS_TABLE_COLUMN_WIDTH_RATIO = None
click.rich_click.SHOW_ARGUMENTS = True
click.rich_click.GROUP_ARGUMENTS_OPTIONS = True
click.rich_click.STYLE_ERRORS_SUGGESTION = "magenta italic"
click.rich_click.ERRORS_SUGGESTION = "Try running 'pywire --help' for more information."
click.rich_click.ERRORS_EPILOGUE = "To find out more, visit [link=https://github.com/pywire/pywire]https://github.com/pywire/pywire[/link]"
click.rich_click.STYLE_OPTIONS_TABLE_BOX = None
click.rich_click.STYLE_COMMANDS_PANEL_BOX = None
click.rich_click.STYLE_OPTIONS_PANEL_BOX = None

# Cyan theme
click.rich_click.STYLE_HEADER_TEXT = "bold cyan"
click.rich_click.STYLE_OPTION = "cyan"
click.rich_click.STYLE_SWITCH = "cyan"
click.rich_click.STYLE_METAVAR = "dim white"
click.rich_click.STYLE_USAGE_COMMAND = "cyan"
click.rich_click.STYLE_USAGE = "dim"

# Grouping options and commands
click.rich_click.OPTION_GROUPS = {
    "pywire": [
        {
            "name": "Global Flags",
            "options": ["--help", "--version"],
        }
    ]
}

click.rich_click.COMMAND_GROUPS = {
    "pywire": [
        {
            "name": "Commands",
            "commands": ["dev", "run", "build"],
        }
    ]
}


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
        raise click.BadParameter(
            f"Could not import module '{module_name}': {e}", param_hint="APP"
        )

    try:
        app = getattr(module, app_name)
    except AttributeError:
        raise click.BadParameter(
            f"Attribute '{app_name}' not found in module '{module_name}'",
            param_hint="APP",
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


# Workaround: rich-click wraps tables in Panels which default to expand=True.
# We monkeypatch Panel to default expand=False to allow natural resizing.
original_panel_init = rich.panel.Panel.__init__


def panel_init(self, *args, **kwargs):
    kwargs.setdefault("expand", False)
    original_panel_init(self, *args, **kwargs)


rich.panel.Panel.__init__ = panel_init  # type: ignore[method-assign]


@click.group(
    help=f"""
[bold white on cyan] pywire [/] [bold cyan]v{__version__}[/] Build faster python web apps.

Run [bold cyan]pywire dev APP[/] to start development server.
Run [bold cyan]pywire run APP[/] to start production server.

[dim]APP should be a string in format 'module:instance', e.g. 'src.main:app' or 'main:app'
If not provided, pywire tries to discover it in main.py, app.py, etc.[/dim]
"""
)
@click.version_option(__version__)
def cli() -> None:
    pass


@cli.command()
@click.argument("app", required=False)
@click.option("--host", default="127.0.0.1", help="Host to bind to")
@click.option("--port", default=3000, type=int, help="Port to bind to")
@click.option("--ssl-keyfile", default=None, help="SSL key file")
@click.option("--ssl-certfile", default=None, help="SSL certificate file")
@click.option("--env-file", default=None, help="Environment configuration file")
@click.option("--no-tui", is_flag=True, help="Disable TUI dashboard")
def dev(
    app: Optional[str],
    host: str,
    port: int,
    ssl_keyfile: Optional[str],
    ssl_certfile: Optional[str],
    env_file: Optional[str],
    no_tui: bool,
) -> None:
    """Start development server."""
    import asyncio

    from pywire.runtime.dev_server import run_dev_server

    if not app:
        app = _discover_app_str()
        if no_tui:
            click.echo(f"🔍 Auto-discovered app: {app}")

    # Verify import
    import_app(app)

    if no_tui:
        click.echo(f"🚀 Starting pywire dev server on http://{host}:{port}")
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
    else:
        from pywire.cli.tui import start_tui

        start_tui(
            app_path=app,
            host=host,
            port=port,
            ssl_keyfile=ssl_keyfile,
            ssl_certfile=ssl_certfile,
            env_file=env_file,
        )


@cli.command()
@click.argument("app", required=False)
@click.option(
    "--optimize",
    is_flag=True,
    help="Compile bytecode artifacts for faster import.",
)
@click.option(
    "--out-dir",
    default=".pywire/build",
    help="Output directory for build artifacts.",
)
@click.option(
    "--pages-dir",
    default=None,
    help="Override pages directory (default: app.pages_dir).",
)
def build(
    app: Optional[str], optimize: bool, out_dir: str, pages_dir: Optional[str]
) -> None:
    """Build the application for production."""
    if not app:
        app = _discover_app_str()

    click.echo(f"🔨 Building {app}...")

    app_instance = import_app(app)

    if pages_dir:
        resolved_pages_dir = Path(pages_dir)
    elif hasattr(app_instance, "pages_dir"):
        resolved_pages_dir = Path(app_instance.pages_dir)
    else:
        resolved_pages_dir = Path("pages")

    from pywire.compiler.build import build_project

    summary = build_project(
        optimize=optimize,
        pages_dir=resolved_pages_dir,
        out_dir=Path(out_dir),
    )

    click.echo(
        "✅ Build complete "
        f"(pages={summary.pages}, layouts={summary.layouts}, "
        f"components={summary.components}, out={summary.out_dir})"
    )


@cli.command()
@click.argument("app", required=False)
@click.option("--host", default="0.0.0.0", help="Host to bind to")
@click.option("--port", default=8000, type=int, help="Port to bind to")
@click.option("--workers", default=None, type=int, help="Number of worker processes")
@click.option("--no-access-log", is_flag=True, help="Disable access logging")
def run(
    app: Optional[str],
    host: str,
    port: int,
    workers: Optional[int],
    no_access_log: bool,
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
        app,
        host=host,
        port=port,
        workers=workers,
        access_log=not no_access_log,
        factory=False,
    )


if __name__ == "__main__":
    cli()
