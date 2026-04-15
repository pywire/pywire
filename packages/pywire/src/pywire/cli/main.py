"""Main CLI entry point."""

import os
import sys
from pathlib import Path
from typing import Any, Optional

try:
    import rich.panel
    import rich_click as click
    from rich.console import Console
except ImportError:
    print(
        "Error: pywire CLI requires additional dependencies.\n"
        "Install them with: uv add pywire[cli]  (or: pip install pywire[cli])",
        file=sys.stderr,
    )
    sys.exit(1)

from pywire import __version__
from pywire.cli.config import config_command

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
        },
        {
            "name": "Configuration",
            "commands": ["config"],
        },
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


cli.add_command(config_command)


@cli.command()
@click.argument("app", required=False)
@click.option("--host", default="127.0.0.1", help="Host to bind to")
@click.option(
    "--port", default=None, type=int, help="Port to bind to (default: 3000 or config)"
)
@click.option("--ssl-keyfile", default=None, help="SSL key file")
@click.option("--ssl-certfile", default=None, help="SSL certificate file")
@click.option("--env-file", default=None, help="Environment configuration file")
@click.option("--tui/--no-tui", default=None, help="Enable/disable TUI dashboard")
def dev(
    app: Optional[str],
    host: str,
    port: Optional[int],
    ssl_keyfile: Optional[str],
    ssl_certfile: Optional[str],
    env_file: Optional[str],
    tui: Optional[bool],
) -> None:
    """Start development server."""
    import asyncio

    from pywire.cli.config import get_setting
    from pywire.runtime.dev_server import run_dev_server

    # Resolve TUI setting: CLI flag > settings.toml > default (False)
    if tui is None:
        saved = get_setting("tui")
        use_tui = saved if isinstance(saved, bool) else False
    else:
        use_tui = tui

    # Resolve port: CLI flag > settings.toml > default (3000)
    if port is None:
        saved_port = get_setting("port")
        port = int(saved_port) if saved_port is not None else 3000
    assert port is not None

    if not app:
        app = _discover_app_str()
        if not use_tui:
            console.print(f"🔍 Auto-discovered app: [cyan]{app}[/]")

    # Verify import
    import_app(app)

    # Find available port
    original_port = port
    port = _find_available_port(host, port)

    if port != original_port and not use_tui:
        console.print(
            f"⚠️  Port {original_port} is busy, using [bold cyan]{port}[/] instead."
        )

    if not use_tui:
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
@click.option(
    "--platform",
    type=click.Choice(["cloudflare"]),
    default=None,
    help="Generate platform-specific build output.",
)
def build(
    app: Optional[str],
    optimize: bool,
    out_dir: str,
    pages_dir: Optional[str],
    platform: Optional[str],
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

    if platform == "cloudflare":
        import shutil

        from pywire.compiler.build_artifacts import generate_cf_bundle

        cf_bundle_dir = Path.cwd() / "_pywire_build"
        routes_path = generate_cf_bundle(
            build_dir=Path(out_dir),
            cf_bundle_dir=cf_bundle_dir,
            app_import=app,
        )

        # Copy static assets to .pywire/deploy/public/ for Cloudflare's
        # native static assets binding (served from edge CDN, not the Worker).
        # The wrangler.toml [assets] directive points to .pywire/deploy/public.
        deploy_public = Path.cwd() / ".pywire" / "deploy" / "public"
        if deploy_public.exists():
            shutil.rmtree(deploy_public)

        # PyWire framework JS
        pywire_static_src = Path(__file__).parent.parent / "static"
        pywire_static_dest = deploy_public / "_pywire" / "static"
        if pywire_static_src.exists():
            pywire_static_dest.mkdir(parents=True, exist_ok=True)
            for f in pywire_static_src.iterdir():
                if f.is_file() and (f.suffix in (".js", ".css", ".map")):
                    shutil.copy2(f, pywire_static_dest / f.name)

        # User static files — respect the app's configured static_url_path
        user_static = app_instance.static_dir if app_instance else None
        static_url_path = getattr(app_instance, "static_url_path", "/static")
        # Strip leading slash to make it a relative path for the deploy dir
        static_subdir = static_url_path.lstrip("/")
        if user_static and Path(user_static).exists() and Path(user_static).is_dir():
            user_static_dest = deploy_public / static_subdir
            shutil.copytree(user_static, user_static_dest)

        # Regenerate pywire_do.py (contains app import path)
        from pywire.cli.deploy import generate_cf_durable_object

        do_content = generate_cf_durable_object(Path.cwd(), app or "src.main:app")
        (Path.cwd() / "pywire_do.py").write_text(do_content)

        console.print(
            f"✅ Generated [cyan]_pywire_build/[/], [cyan]{routes_path.name}[/], "
            f"and [cyan]pywire_do.py[/] for Cloudflare Workers"
        )
        console.print(
            "✅ Static assets → [cyan].pywire/deploy/public/[/] "
            "(served by Cloudflare edge CDN)"
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


def _print_skip_hint(
    filename: str,
    platform: str,
    workers: int,
    redis: bool,
    project_name: str,
) -> None:
    """Print manual instructions when a file overwrite is declined."""
    if filename == "Dockerfile":
        console.print(
            f"  [dim]To apply [cyan]--workers {workers}[/], update your Dockerfile CMD:[/]\n"
            f'  [dim]  CMD ["uv", "run", "pywire", "run", "--host", "0.0.0.0",'
            f' "--port", "8000", "--workers", "{workers}"][/]'
        )
    elif filename == "render.yaml" and redis:
        console.print(
            "  [dim]To add Redis manually, add to [cyan]render.yaml[/]:[/]\n"
            "  [dim]  - type: keyvalue[/]\n"
            f"  [dim]    name: {project_name}-kv[/]\n"
            "  [dim]    plan: starter[/]\n"
            "  [dim]    ipAllowList: [][/]\n"
            "  [dim]And bind REDIS_URL in your web service envVars.[/]"
        )


@cli.command()
@click.argument("app", required=False)
@click.option(
    "--platform",
    type=click.Choice(["render", "docker", "fly", "railway", "cloudflare"]),
    default="docker",
    help="Deployment platform",
)
@click.option(
    "--out-dir",
    default=".",
    type=click.Path(),
    help="Output directory for deploy configs",
)
@click.option(
    "--workers",
    default=1,
    type=int,
    help="Number of worker processes (default: 1)",
)
@click.option(
    "--redis",
    is_flag=True,
    help="Include Redis/Valkey KV store in deployment config",
)
def deploy(
    app: Optional[str],
    platform: str,
    out_dir: str,
    workers: int,
    redis: bool,
) -> None:
    """Generate deployment configuration for your PyWire app."""
    from pywire.cli.deploy import (
        generate_dockerfile,
        generate_fly_toml,
        generate_railway_json,
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

    # Cloudflare Workers requires a paid plan
    if platform == "cloudflare":
        console.print(
            "\n[bold yellow]Note:[/] Cloudflare Python Workers requires a "
            "[bold]Workers Paid plan[/] ($5/month).\n"
            "  The free plan's size and startup limits are incompatible with "
            "Python frameworks.\n"
            "  [link=https://dash.cloudflare.com/workers/plans]"
            "https://dash.cloudflare.com/workers/plans[/link]\n"
        )

    # Cloudflare uses Durable Objects — workers/redis flags don't apply
    if platform == "cloudflare" and (workers > 1 or redis):
        console.print(
            "[bold red]Error:[/] [cyan]--workers[/] and [cyan]--redis[/] are not applicable "
            "to Cloudflare Workers.\n"
            "  Cloudflare uses Durable Objects for session state — no Redis or worker "
            "processes needed."
        )
        raise SystemExit(1)

    # Warn about workers vs redis (not applicable to Cloudflare)
    if platform != "cloudflare":
        if workers > 1 and not redis:
            console.print(
                "\n[bold yellow]⚠️  Warning:[/] Running multiple workers without Redis "
                "will break session state.\n"
                "  Add [cyan]--redis[/] or set [cyan]REDIS_URL[/] at runtime.\n"
            )

        if redis:
            console.print(
                "\n[bold yellow]⚠️  Note:[/] Adding a Redis/Valkey store will increase "
                "resource usage and may\n"
                "  incur additional costs depending on your hosting provider.\n"
            )

    # Generate config files
    files_to_write: list[tuple[str, str]] = []

    if platform == "docker":
        files_to_write.append(
            ("Dockerfile", generate_dockerfile(project_root, workers=workers))
        )
    elif platform == "render":
        files_to_write.append(
            (
                "render.yaml",
                generate_render_yaml(project_root, project_name, redis=redis),
            )
        )
        # Render uses Docker — always include Dockerfile so workers changes are picked up
        files_to_write.append(
            ("Dockerfile", generate_dockerfile(project_root, workers=workers))
        )
    elif platform == "fly":
        files_to_write.append(
            ("fly.toml", generate_fly_toml(project_root, project_name))
        )
        # Fly.io uses Docker — always include Dockerfile so workers changes are picked up
        files_to_write.append(
            ("Dockerfile", generate_dockerfile(project_root, workers=workers))
        )
    elif platform == "railway":
        files_to_write.append(("railway.json", generate_railway_json(project_root)))
        # Always include Dockerfile so workers changes are picked up
        files_to_write.append(
            ("Dockerfile", generate_dockerfile(project_root, workers=workers))
        )
    elif platform == "cloudflare":
        from pywire.cli.deploy import (
            generate_wrangler_toml,
            generate_cf_entry,
            generate_cf_durable_object,
        )

        files_to_write.append(
            ("wrangler.toml", generate_wrangler_toml(project_root, project_name))
        )
        files_to_write.append(
            ("entry.py", generate_cf_entry(project_root, app_string=app))
        )
        files_to_write.append(
            ("pywire_do.py", generate_cf_durable_object(project_root, app_string=app))
        )
        # Exclude local .venv from CF bundle to avoid duplicate packages
        files_to_write.append(
            (
                ".wranglerignore",
                ".venv/\n.git/\n__pycache__/\n.pywire/build/\n",
            )
        )
    else:
        raise click.UsageError(f"Unknown platform: {platform}")

    for filename, content in files_to_write:
        target = out_path / filename
        if target.exists():
            if not click.confirm(f"'{target}' already exists. Overwrite?"):
                console.print(f"Skipped [cyan]{target}[/]")
                _print_skip_hint(filename, platform, workers, redis, project_name)
                continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        console.print(f"✅ Generated [cyan]{target}[/]")

    # Next steps guidance
    redis_hint = (
        "\n[bold]Scaling with Redis/Valkey:[/]\n"
        f"  The Dockerfile runs with [cyan]--workers {workers}[/].\n"
        "  To scale, install [cyan]pywire[redis][/] and set [cyan]REDIS_URL[/] —\n"
        "  PyWire auto-detects it for shared session state (no code changes needed)."
    )

    if platform == "docker":
        console.print(
            "\n[bold]Next steps:[/]\n"
            f"  1. [cyan]docker build -t {project_name} .[/]\n"
            f"  2. [cyan]docker run -p 8000:8000 {project_name}[/]"
        )
        if not redis:
            console.print(
                redis_hint + "\n"
                f"  [cyan]docker run -p 8000:8000 -e REDIS_URL=redis://your-redis:6379 {project_name}[/]"
            )
        else:
            console.print(
                "\n  Redis is configured. Run with [cyan]REDIS_URL[/]:\n"
                f"  [cyan]docker run -p 8000:8000 -e REDIS_URL=redis://your-redis:6379 {project_name}[/]"
            )
    elif platform == "render":
        console.print(
            "\n[bold]Next steps:[/]\n"
            "  1. Push your code to a Git repository\n"
            "  2. Go to [link=https://dashboard.render.com]dashboard.render.com[/link] "
            "→ [bold]New → Blueprint[/] and connect your repo\n"
            "  3. Render reads [cyan]render.yaml[/] automatically and provisions the service"
        )
        if redis:
            console.print(
                "\n  Redis KV store is included in [cyan]render.yaml[/]. Render will provision\n"
                "  it and inject [cyan]REDIS_URL[/] automatically."
            )
        else:
            console.print(
                redis_hint + "\n"
                "  Use [cyan]pywire deploy --platform render --redis[/] to generate a\n"
                "  [cyan]render.yaml[/] with a KV store pre-configured."
            )
    elif platform == "fly":
        console.print(
            "\n[bold]Next steps:[/]\n"
            "  1. Install the Fly CLI: [cyan]curl -L https://fly.io/install.sh | sh[/]\n"
            "  2. Run [cyan]fly launch --no-deploy[/] to import [cyan]fly.toml[/]\n"
            "  3. Deploy with [cyan]fly deploy[/]\n"
            "\n[bold]Scaling:[/]\n"
            f"  The Dockerfile runs with [cyan]--workers {workers}[/].\n"
            "  To scale to multiple machines ([cyan]fly scale count N[/]):\n"
            "  • [bold]Option A — Fly sticky sessions:[/] Route sessions to the same machine\n"
            "    using [cyan]fly-replay[/]. Simple but breaks for VPNs/corporate proxies.\n"
            "  • [bold]Option B — Redis/Valkey (recommended):[/] Add Upstash Redis via\n"
            "    [cyan]fly redis create[/], set [cyan]REDIS_URL[/], and install\n"
            "    [cyan]pywire[redis][/]. PyWire auto-detects it — no code changes needed."
        )
    elif platform == "railway":
        console.print(
            "\n[bold]Next steps:[/]\n"
            "  1. Install the Railway CLI: [cyan]npm i -g @railway/cli[/]\n"
            "  2. Run [cyan]railway login[/] and [cyan]railway init[/]\n"
            "  3. Run [cyan]railway link[/] to connect to your Railway project\n"
            "  4. Deploy with [cyan]railway up[/]\n"
            "\n  Railway auto-detects the Dockerfile and builds your app."
        )
        if redis or workers > 1:
            console.print(
                redis_hint + "\n"
                "  [bold]Note:[/] Redis cannot be provisioned via [cyan]railway.json[/].\n"
                "  Add it with [cyan]railway add[/] (select Redis/Valkey) or via the\n"
                "  Railway dashboard. Railway injects [cyan]REDIS_URL[/] automatically.\n"
                "  Then install the Redis extra: [cyan]uv add pywire[redis][/]"
            )
        else:
            console.print(
                redis_hint + "\n"
                "  Add a Redis addon via [cyan]railway add[/] or the Railway dashboard.\n"
                "  Railway injects [cyan]REDIS_URL[/] automatically.\n"
                "  Then install the Redis extra: [cyan]uv add pywire[redis][/]"
            )
    elif platform == "cloudflare":
        console.print(
            "\n[bold]Local development:[/]\n"
            "  • [bold]Fast mode[/] (standard hot-reload, no build step needed):\n"
            "      [cyan]uv run pywire dev[/]\n"
            "  • [bold]Workers mode[/] (runs in local workerd — matches CF production):\n"
            "      [cyan]uv run pywire build --platform cloudflare[/]\n"
            "      [cyan]uv run pywrangler dev[/]\n"
            "\n[bold]Deploy to Cloudflare:[/]\n"
            "  1. Add workers-py if not present: [cyan]uv add --dev workers-py[/]\n"
            "  2. Build: [cyan]uv run pywire build --platform cloudflare[/]\n"
            "  3. Deploy: [cyan]uv run pywrangler deploy[/]\n"
            "\n[bold]Generated files:[/]\n"
            "  • [cyan]wrangler.toml[/] — Cloudflare config with Durable Objects binding\n"
            "  • [cyan]entry.py[/] — Workers entry point (routes WS to Durable Objects)\n"
            "  • [cyan]pywire_do.py[/] — Durable Object for session + WebSocket handling\n"
            "\n[bold]Architecture:[/]\n"
            "  Each session runs in a Durable Object with persistent storage and\n"
            "  WebSocket support. Real-time reactivity works out of the box.\n"
            "  No Redis or worker processes needed — Durable Objects handle state.\n"
            "\n[bold]CI/CD:[/]\n"
            "  [cyan]uv sync && uv run pywire build --platform cloudflare "
            "&& uv run pywrangler deploy[/]"
        )


if __name__ == "__main__":
    cli()
