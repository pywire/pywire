"""Main CLI entry point."""

import os
import sys
from pathlib import Path
from typing import Any, Optional

import rich.panel
import rich_click as click
from pywire import __version__
from rich.console import Console

console = Console()

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
            "commands": ["dev", "run", "build", "deploy"],
        }
    ]
}


def _setup_import_paths(module_name: str) -> None:
    """Configure sys.path so a dotted module string and its sibling imports resolve.

    For ``src.main``, both the project root (so ``src`` is a package) and
    ``src/`` itself (so ``from auth_middleware import …`` works inside main.py)
    are prepended.  Works for arbitrary nesting depth.
    """
    cwd = os.getcwd()
    if cwd not in sys.path:
        sys.path.insert(0, cwd)

    # Add every intermediate directory so that relative-style imports within
    # each layer work without requiring the full dotted prefix.
    parts = module_name.split(".")
    for depth in range(1, len(parts)):
        subdir = os.path.join(cwd, *parts[:depth])
        if os.path.isdir(subdir) and subdir not in sys.path:
            sys.path.insert(0, subdir)


def import_app(app_str: str) -> Any:
    """Import application from string (e.g. 'main:app' or 'src.main:app')."""
    if ":" not in app_str:
        raise click.BadParameter("App must be in format 'module:app'", param_hint="APP")

    module_name, app_name = app_str.split(":", 1)

    _setup_import_paths(module_name)

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
                    _setup_import_paths(module_path)
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


rich.panel.Panel.__init__ = panel_init  # type: ignore[method-assign]  # ty: ignore[invalid-assignment]


def _find_available_port(host: str, port: int, max_attempts: int = 100) -> int:
    """Find an available port starting from 'port'."""
    import socket

    # Try to determine if we should use IPv4 or IPv6
    try:
        addr_info = socket.getaddrinfo(host, port, socket.AF_UNSPEC, socket.SOCK_STREAM)
        family = addr_info[0][0]
    except Exception:
        family = socket.AF_INET  # Fallback

    for p in range(port, port + max_attempts):
        with socket.socket(family, socket.SOCK_STREAM) as s:
            try:
                s.bind((host, p))
                return p
            except OSError:
                continue

    raise click.UsageError(
        f"Could not find an available port starting from {port} after {max_attempts} attempts."
    )


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
            console.print(f"🔍 Auto-discovered app: [cyan]{app}[/]")

    # Verify import
    import_app(app)

    # Find available port
    original_port = port
    port = _find_available_port(host, port)

    if port != original_port and no_tui:
        console.print(
            f"⚠️  Port {original_port} is busy, using [bold cyan]{port}[/] instead."
        )

    if no_tui:
        console.print(
            f"🚀 Starting pywire dev server on [link=http://{host}:{port}]http://{host}:{port}[/link]"
        )
        if ssl_certfile:
            console.print("🔒 SSL enabled")

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

    console.print(f"🔨 Building [cyan]{app}[/]...")

    app_instance = import_app(app)

    if pages_dir:
        resolved_pages_dir = Path(pages_dir)
    elif hasattr(app_instance, "pages_dir"):
        resolved_pages_dir = Path(app_instance.pages_dir)
    else:
        resolved_pages_dir = Path("pages")

    from pywire.compiler.build import build_project

    # Resolve static_dir for asset fingerprinting
    resolved_static_dir = None
    if hasattr(app_instance, "static_dir") and app_instance.static_dir:
        resolved_static_dir = Path(app_instance.static_dir)

    summary = build_project(
        optimize=optimize,
        pages_dir=resolved_pages_dir,
        out_dir=Path(out_dir),
        static_dir=resolved_static_dir,
    )

    parts = [
        f"pages={summary.pages}",
        f"layouts={summary.layouts}",
        f"components={summary.components}",
    ]
    if summary.static_assets > 0:
        parts.append(f"static_assets={summary.static_assets}")
    parts.append(f"out={summary.out_dir}")

    console.print(f"✅ Build complete ({', '.join(parts)})")


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

    console.print(f"🚀 Starting [bold]production[/] server for [cyan]{app}[/]")
    console.print(
        f"🌍 Listening on [link=http://{host}:{port}]http://{host}:{port}[/link]"
    )
    console.print(f"👷 Workers: {workers}")

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


@cli.command()
@click.argument("app", required=False)
@click.option(
    "--platform",
    type=click.Choice(["render", "docker", "fly"]),
    default="docker",
    help="Deployment platform",
)
@click.option(
    "--out-dir",
    default=".",
    type=click.Path(),
    help="Output directory for deploy configs",
)
def deploy(app: Optional[str], platform: str, out_dir: str) -> None:
    """Generate deployment configuration for your PyWire app."""
    from pywire.cli.deploy import (
        generate_dockerfile,
        generate_fly_toml,
        generate_render_yaml,
        validate_deploy_config,
    )

    project_root = Path(os.getcwd())
    out_path = Path(out_dir)

    # Auto-discover and verify app
    if not app:
        app = _discover_app_str()
    console.print(f"📦 Preparing deploy config for [cyan]{app}[/]...")

    # Pre-compile
    app_instance = import_app(app)

    pages_dir = Path(getattr(app_instance, "pages_dir", "pages"))

    from pywire.compiler.build import build_project

    build_project(pages_dir=pages_dir, out_dir=Path(".pywire/build"))
    console.print("✅ Build complete")

    # Validate
    issues = validate_deploy_config(platform, project_root)
    if issues:
        for issue in issues:
            console.print(f"⚠️  {issue}")

    # Derive project name from directory
    project_name = project_root.name

    # Generate config files
    files_to_write: list[tuple[str, str]] = []

    if platform == "docker":
        files_to_write.append(("Dockerfile", generate_dockerfile(project_root)))
    elif platform == "render":
        files_to_write.append(
            ("render.yaml", generate_render_yaml(project_root, project_name))
        )
    elif platform == "fly":
        files_to_write.append(
            ("fly.toml", generate_fly_toml(project_root, project_name))
        )
        # Fly.io uses Docker — generate a Dockerfile if one doesn't already exist
        if not (out_path / "Dockerfile").exists():
            files_to_write.append(("Dockerfile", generate_dockerfile(project_root)))
    else:
        raise click.UsageError(f"Unknown platform: {platform}")

    for filename, content in files_to_write:
        target = out_path / filename
        if target.exists():
            if not click.confirm(f"'{target}' already exists. Overwrite?"):
                console.print(f"Skipped [cyan]{target}[/]")
                continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        console.print(f"✅ Generated [cyan]{target}[/]")

    # Next steps guidance
    if platform == "docker":
        console.print(
            "\n[bold]Next steps:[/]\n"
            f"  1. [cyan]docker build -t {project_name} .[/]\n"
            f"  2. [cyan]docker run -p 8000:8000 {project_name}[/]\n"
            "\n[bold]Scaling with Redis:[/]\n"
            "  To run multiple workers or containers, install [cyan]pywire[redis][/] and set\n"
            "  [cyan]REDIS_URL[/] — PyWire auto-detects it for shared session state.\n"
            f"  [cyan]docker run -p 8000:8000 -e REDIS_URL=redis://your-redis:6379 {project_name}[/]"
        )
    elif platform == "render":
        console.print(
            "\n[bold]Next steps:[/]\n"
            "  1. Push your code to a Git repository\n"
            "  2. Go to [link=https://dashboard.render.com]dashboard.render.com[/link] "
            "→ [bold]New → Blueprint[/] and connect your repo\n"
            "  3. Render reads [cyan]render.yaml[/] automatically and provisions the service\n"
            "\n[bold]Scaling with Redis:[/]\n"
            "  The generated [cyan]render.yaml[/] runs with [cyan]--workers 1[/] (safe default).\n"
            "  To scale, add a Render KV store and set [cyan]REDIS_URL[/]:\n"
            "  1. [cyan]uv add pywire[redis][/]\n"
            "  2. Add a [cyan]keyvalue[/] service to [cyan]render.yaml[/] with [cyan]fromService[/]\n"
            "  3. Increase [cyan]--workers[/] in [cyan]startCommand[/]\n"
            "  PyWire auto-detects [cyan]REDIS_URL[/] for shared session state — no code changes needed."
        )
    elif platform == "fly":
        console.print(
            "\n[bold]Next steps:[/]\n"
            "  1. Install the Fly CLI: [cyan]curl -L https://fly.io/install.sh | sh[/]\n"
            "  2. Run [cyan]fly launch --no-deploy[/] to import [cyan]fly.toml[/]\n"
            "  3. Deploy with [cyan]fly deploy[/]\n"
            "\n[bold]Scaling:[/]\n"
            "  The generated Dockerfile runs with [cyan]--workers 1[/] (safe default).\n"
            "  To scale to multiple machines ([cyan]fly scale count N[/]):\n"
            "  • [bold]Option A — Fly sticky sessions:[/] Route sessions to the same machine\n"
            "    using [cyan]fly-replay[/]. Simple but breaks for VPNs/corporate proxies.\n"
            "  • [bold]Option B — Redis (recommended):[/] Add Upstash Redis via\n"
            "    [cyan]fly redis create[/], set [cyan]REDIS_URL[/], and install\n"
            "    [cyan]pywire[redis][/]. PyWire auto-detects it — no code changes needed."
        )


if __name__ == "__main__":
    cli()
