import argparse
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import questionary
import tomllib
from jinja2 import Environment, PackageLoader, select_autoescape
from pywire_templates import render_deploy_template
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from create_pywire_app import __version__

console = Console()

LOGO = r"""
 [bold cyan]
██████╗ ██╗   ██╗██╗    ██╗██╗██████╗ ███████╗
██╔══██╗╚██╗ ██╔╝██║    ██║██║██╔══██╗██╔════╝
██████╔╝ ╚████╔╝ ██║ █╗ ██║██║██████╔╝█████╗  
██╔═══╝   ╚██╔╝  ██║███╗██║██║██╔══██╗██╔══╝  
██║        ██║   ╚███╔███╔╝██║██║  ██║███████╗
╚═╝        ╚═╝    ╚══╝╚══╝ ╚═╝╚═╝  ╚═╝╚══════╝
 [/bold cyan]
"""


def get_local_version(path: Path) -> Optional[str]:
    """Try to read version from a local pyproject.toml file."""
    try:
        if path.exists():
            with open(path, "rb") as f:
                data = tomllib.load(f)
                return data.get("project", {}).get("version")
    except Exception:
        pass
    return None


def get_version() -> str:
    return __version__


def resolve_pywire_version(pywire_dep: str) -> Optional[str]:
    """Resolve the actual pywire version that will be installed.

    Args:
        pywire_dep: Dependency spec (e.g., 'pywire', 'pywire==0.1.4', 'pywire @ /path')

    Returns:
        Resolved version string or None if resolution fails
    """
    # For local paths, we can't resolve via uv pip compile
    if "@" in pywire_dep:
        return None

    try:
        # Use uv pip compile to resolve the version without installing
        process = subprocess.run(
            ["uv", "pip", "compile", "-", "--quiet"],
            input=pywire_dep,
            text=True,
            capture_output=True,
            check=True,
            timeout=10,
        )

        # Parse the output for pywire==<version>
        import re

        match = re.search(r"pywire==([^\s]+)", process.stdout)
        if match:
            return match.group(1)

    except (
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        FileNotFoundError,
    ):
        pass

    return None


class TemplateRenderer:
    """Handles template loading and rendering using Jinja2."""

    def __init__(self):
        self.env = Environment(
            loader=PackageLoader("create_pywire_app", "templates"),
            autoescape=select_autoescape(),
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def render(self, template_path: str, context: Dict[str, Any]) -> str:
        """Render a template with the given context."""
        template = self.env.get_template(template_path)
        return template.render(**context)

    def copy_static(self, source_path: str, dest: Path) -> None:
        """Copy a static template file (no Jinja2 rendering)."""
        template_root = Path(__file__).parent / "templates"
        source = template_root / source_path
        dest.write_text(source.read_text())


class ProjectGenerator:
    """Generates pywire projects from templates."""

    def __init__(
        self,
        project_path: Path,
        project_name: str,
        template: str,
        routing_strategy: str,
        use_src: bool,
        adapters: List[str],
        pywire_dep: str,
        redis_enabled: bool = False,
        workers: int = 1,
    ):
        self.project_path = project_path
        self.project_name = project_name
        self.template = template
        self.routing_strategy = routing_strategy
        self.use_src = use_src
        self.adapters = adapters
        self.pywire_dep = pywire_dep
        self.redis_enabled = redis_enabled
        self.workers = workers
        self.renderer = TemplateRenderer()

        self.app_root = project_path / "src" if use_src else project_path
        self.pages_dir = self.app_root / "pages"

    def get_dependencies(self) -> List[str]:
        """Get runtime dependencies for the selected template."""
        import re

        deploy_adapters = self.get_deploy_adapters()
        docker_adapters = {"docker", "render", "fly", "railway"}
        has_docker = bool(set(deploy_adapters) & docker_adapters)

        # Include pydantic (forms extra) for non-CF-only projects
        if has_docker or not deploy_adapters:
            base = self.pywire_dep
            if "[" not in base and "@" not in base:
                match = re.match(r"^(pywire)(.*)", base)
                if match:
                    pywire_dep = f"{match.group(1)}[forms]{match.group(2)}"
                else:
                    pywire_dep = base
            else:
                pywire_dep = base
        else:
            pywire_dep = self.pywire_dep

        dependencies = [pywire_dep]

        if self.template == "blog":
            dependencies.append("markdown>=3.6")
        if self.template == "saas":
            dependencies.extend(["stripe>=7.0.0", "sqlalchemy>=2.0.0"])

        return dependencies

    def get_dev_dependencies(self) -> List[str]:
        """Get dev dependencies — CLI tooling and platform-specific packages."""
        dev_deps: List[str] = []

        # All projects need pywire[cli] for dev/build/deploy commands
        base = self.pywire_dep
        if "[" not in base and "@" not in base:
            import re

            match = re.match(r"^(pywire)(.*)", base)
            if match:
                dev_deps.append(f"{match.group(1)}[cli]{match.group(2)}")
            else:
                dev_deps.append(base)
        else:
            dev_deps.append(base)

        if "Cloudflare Workers (wrangler.toml)" in self.adapters:
            dev_deps.append("workers-py>=1.9.2")

        return dev_deps

    def get_template_description(self) -> str:
        """Get description for the selected template."""
        descriptions = {
            "skeleton": "A blank slate with only a single page.",
            "counter": "A minimal counter app demonstrating interactivity.",
            "blog": "A blog and portfolio starter with Markdown content stored in SQLite.",
            "saas": "A SaaS starter with Stripe, SQLAlchemy models, and stubbed auth.",
        }
        return descriptions.get(self.template, "")

    def get_deploy_adapters(self) -> List[str]:
        """Get list of selected deployment adapter names."""
        adapter_map = {
            "Fly.io (fly.toml + Dockerfile)": "fly",
            "Railway (Dockerfile)": "railway",
            "Docker (Dockerfile)": "docker",
            "Render (render.yaml)": "render",
            "Cloudflare Workers (wrangler.toml)": "cloudflare",
        }
        return [adapter_map[a] for a in self.adapters if a in adapter_map]

    def generate(self) -> None:
        """Generate the complete project structure."""
        self.project_path.mkdir(parents=True, exist_ok=True)
        self.app_root.mkdir(exist_ok=True)
        self.pages_dir.mkdir(exist_ok=True)

        # Generate base files
        self._generate_pyproject()
        self._generate_readme()
        self._generate_gitignore()
        self._generate_main()
        self._generate_error_page()
        self._generate_vscode_settings()

        # Generate template-specific files
        if self.template == "skeleton":
            self._generate_skeleton()
        if self.template == "counter":
            self._generate_counter()
        if self.template == "blog":
            self._generate_blog()
        if self.template == "saas":
            self._generate_saas()

        # Generate deployment adapters
        self._generate_adapters()

    def _generate_skeleton(self) -> None:
        """Generate Skeleton template files."""
        context = {
            "project_name": self.project_name,
            "routing": self.routing_strategy,
        }
        content = self.renderer.render("skeleton/index.wire.j2", context)
        (self.pages_dir / "index.wire").write_text(content)

    def _generate_pyproject(self) -> None:
        """Generate pyproject.toml."""
        context = {
            "project_name": self.project_name,
            "dependencies": self.get_dependencies(),
            "dev_dependencies": self.get_dev_dependencies(),
            "deploy_adapters": self.get_deploy_adapters(),
            "workers": self.workers,
        }
        content = self.renderer.render("common/pyproject.toml.j2", context)
        (self.project_path / "pyproject.toml").write_text(content)

    def _generate_readme(self) -> None:
        """Generate README.md."""
        routing_label = "Path-based" if self.routing_strategy == "path" else "Explicit"
        context = {
            "project_name": self.project_name,
            "template_description": self.get_template_description(),
            "routing_style": routing_label,
            "deploy_adapters": self.get_deploy_adapters(),
            "redis_enabled": self.redis_enabled,
            "workers": self.workers,
        }
        content = self.renderer.render("common/README.md.j2", context)
        (self.project_path / "README.md").write_text(content)

    def _generate_gitignore(self) -> None:
        """Generate .gitignore."""
        self.renderer.copy_static("common/.gitignore", self.project_path / ".gitignore")

    def _generate_vscode_settings(self) -> None:
        """Generate VS Code settings."""
        vscode_dir = self.project_path / ".vscode"
        vscode_dir.mkdir(exist_ok=True)
        self.renderer.copy_static(
            "common/extensions.json", vscode_dir / "extensions.json"
        )

    def _generate_main(self) -> None:
        """Generate main.py."""
        template_name = (
            "main-path.py.j2"
            if self.routing_strategy == "path"
            else "main-explicit.py.j2"
        )
        context = {
            "pages_dir": "src/pages" if self.use_src else "pages",
        }
        content = self.renderer.render(f"common/{template_name}", context)
        (self.app_root / "main.py").write_text(content)

    def _generate_error_page(self) -> None:
        """Generate __error__.wire."""
        self.renderer.copy_static(
            "common/__error__.wire", self.pages_dir / "__error__.wire"
        )

    def _generate_counter(self) -> None:
        """Generate Counter template files."""
        context = {"project_name": self.project_name}
        routing = self.routing_strategy

        if routing == "path":
            layout_content = self.renderer.render(
                "counter/path-based/__layout__.wire.j2", context
            )
            (self.pages_dir / "__layout__.wire").write_text(layout_content)
            self.renderer.copy_static(
                "counter/path-based/index.wire", self.pages_dir / "index.wire"
            )
        else:
            layout_content = self.renderer.render(
                "counter/explicit/layout.wire.j2", context
            )
            (self.pages_dir / "layout.wire").write_text(layout_content)
            self.renderer.copy_static(
                "counter/explicit/home.wire", self.pages_dir / "home.wire"
            )

    def _generate_blog(self) -> None:
        """Generate Blog template files."""
        context = {"project_name": self.project_name}
        routing = self.routing_strategy

        # Create data directory
        (self.app_root / "data").mkdir(exist_ok=True)

        if routing == "path":
            # Create posts subdirectory
            (self.pages_dir / "posts").mkdir(exist_ok=True)

            # Layouts
            layout_content = self.renderer.render(
                "blog/path-based/__layout__.wire.j2", context
            )
            (self.pages_dir / "__layout__.wire").write_text(layout_content)

            posts_layout_content = self.renderer.render(
                "blog/path-based/posts__layout__.wire.j2", context
            )
            (self.pages_dir / "posts" / "__layout__.wire").write_text(
                posts_layout_content
            )

            # Pages
            self.renderer.copy_static(
                "blog/path-based/index.wire", self.pages_dir / "index.wire"
            )
            self.renderer.copy_static(
                "blog/path-based/posts_index.wire",
                self.pages_dir / "posts" / "index.wire",
            )
            self.renderer.copy_static(
                "blog/path-based/posts_slug.wire",
                self.pages_dir / "posts" / "[slug].wire",
            )
        else:
            # Layout
            layout_content = self.renderer.render(
                "blog/explicit/layout.wire.j2", context
            )
            (self.pages_dir / "layout.wire").write_text(layout_content)

            # Pages
            self.renderer.copy_static(
                "blog/explicit/home.wire", self.pages_dir / "home.wire"
            )
            self.renderer.copy_static(
                "blog/explicit/blog-posts.wire", self.pages_dir / "blog-posts.wire"
            )
            self.renderer.copy_static(
                "blog/explicit/about.wire", self.pages_dir / "about.wire"
            )

    def _generate_saas(self) -> None:
        """Generate SaaS template files."""
        context = {"project_name": self.project_name}
        routing = self.routing_strategy

        # Copy models.py
        self.renderer.copy_static("saas/models.py", self.app_root / "models.py")

        if routing == "path":
            # Create dashboard subdirectory
            (self.pages_dir / "dashboard").mkdir(exist_ok=True)

            # Layouts
            layout_content = self.renderer.render(
                "saas/path-based/__layout__.wire.j2", context
            )
            (self.pages_dir / "__layout__.wire").write_text(layout_content)

            dashboard_layout_content = self.renderer.render(
                "saas/path-based/dashboard__layout__.wire.j2", context
            )
            (self.pages_dir / "dashboard" / "__layout__.wire").write_text(
                dashboard_layout_content
            )

            # Pages
            self.renderer.copy_static(
                "saas/path-based/index.wire", self.pages_dir / "index.wire"
            )
            self.renderer.copy_static(
                "saas/path-based/pricing.wire", self.pages_dir / "pricing.wire"
            )
            self.renderer.copy_static(
                "saas/path-based/login.wire", self.pages_dir / "login.wire"
            )
            self.renderer.copy_static(
                "saas/path-based/dashboard_index.wire",
                self.pages_dir / "dashboard" / "index.wire",
            )
            self.renderer.copy_static(
                "saas/path-based/dashboard_settings.wire",
                self.pages_dir / "dashboard" / "settings.wire",
            )
        else:
            # Layouts
            public_layout_content = self.renderer.render(
                "saas/explicit/public-layout.wire.j2", context
            )
            (self.pages_dir / "public-layout.wire").write_text(public_layout_content)

            auth_layout_content = self.renderer.render(
                "saas/explicit/auth-layout.wire.j2", context
            )
            (self.pages_dir / "auth-layout.wire").write_text(auth_layout_content)

            # Pages
            self.renderer.copy_static(
                "saas/explicit/landing.wire", self.pages_dir / "landing.wire"
            )
            self.renderer.copy_static(
                "saas/explicit/pricing.wire", self.pages_dir / "pricing.wire"
            )
            self.renderer.copy_static(
                "saas/explicit/login.wire", self.pages_dir / "login.wire"
            )
            self.renderer.copy_static(
                "saas/explicit/dashboard-pages.wire",
                self.pages_dir / "dashboard-pages.wire",
            )

    def _generate_dockerfile(self) -> None:
        """Generate Dockerfile (templated with workers count)."""
        content = render_deploy_template("Dockerfile.j2", workers=self.workers)
        (self.project_path / "Dockerfile").write_text(content)

    def _generate_adapters(self) -> None:
        """Generate deployment adapter files."""
        if "Docker (Dockerfile)" in self.adapters:
            self._generate_dockerfile()

        if "Render (render.yaml)" in self.adapters:
            content = render_deploy_template(
                "render.yaml.j2",
                project_name=self.project_name,
                redis_enabled=self.redis_enabled,
            )
            (self.project_path / "render.yaml").write_text(content)
            if not (self.project_path / "Dockerfile").exists():
                self._generate_dockerfile()

        if "Fly.io (fly.toml + Dockerfile)" in self.adapters:
            content = render_deploy_template(
                "fly.toml.j2", project_name=self.project_name
            )
            (self.project_path / "fly.toml").write_text(content)
            if not (self.project_path / "Dockerfile").exists():
                self._generate_dockerfile()

        if "Railway (Dockerfile)" in self.adapters:
            content = render_deploy_template("railway.json.j2")
            (self.project_path / "railway.json").write_text(content)
            if not (self.project_path / "Dockerfile").exists():
                self._generate_dockerfile()

        if "Cloudflare Workers (wrangler.toml)" in self.adapters:
            app_module = "src.main" if self.use_src else "main"
            wrangler_content = render_deploy_template(
                "wrangler.toml.j2",
                project_name=self.project_name,
                app_module=app_module,
                app_attr="app",
            )
            (self.project_path / "wrangler.toml").write_text(wrangler_content)

            # Exclude local .venv from CF bundle to avoid duplicate packages
            (self.project_path / ".wranglerignore").write_text(
                ".venv/\n.git/\n__pycache__/\n.pywire/build/\n"
            )

            entry_content = render_deploy_template(
                "entry.py.j2", app_module=app_module, app_attr="app"
            )
            (self.project_path / "entry.py").write_text(entry_content)

            do_content = render_deploy_template(
                "pywire_do.py.j2", app_module=app_module, app_attr="app"
            )
            (self.project_path / "pywire_do.py").write_text(do_content)


def main():
    # Fix for macOS when running with redirected stdin (e.g. via pipe)
    # KqueueSelector fails with /dev/tty on macOS, so we force SelectSelector.
    if sys.platform == "darwin":
        import asyncio
        import selectors

        class MacOSEventLoopPolicy(asyncio.DefaultEventLoopPolicy):
            def new_event_loop(self):
                selector = selectors.SelectSelector()
                return asyncio.SelectorEventLoop(selector)

        asyncio.set_event_loop_policy(MacOSEventLoopPolicy())

    console.clear()

    # Parse arguments
    parser = argparse.ArgumentParser(
        description=(
            "Create a new PyWire application. Run without flags for the "
            "interactive wizard, or pass a PROJECT_PATH with --yes / "
            "--template / --deploy for non-interactive scaffolding."
        )
    )
    parser.add_argument(
        "project_path",
        nargs="?",
        default=None,
        help="Target directory (skips path prompt when provided).",
    )
    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Non-interactive: accept defaults for every unprovided option.",
    )
    parser.add_argument(
        "--template",
        choices=["skeleton", "counter", "blog", "saas"],
        default=None,
        help="Starting template. Default: counter.",
    )
    parser.add_argument(
        "--deploy",
        action="append",
        choices=["docker", "render", "fly", "railway", "cloudflare"],
        default=None,
        help="Deploy adapter (repeat to pick multiple). Default: none.",
    )
    parser.add_argument(
        "--routing",
        choices=["path", "explicit"],
        default=None,
        help="Routing strategy. Default: path.",
    )
    parser.add_argument(
        "--no-src",
        action="store_true",
        help="Flat layout instead of src/ layout.",
    )
    parser.add_argument(
        "--no-git",
        action="store_true",
        help="Skip git init + initial commit.",
    )
    parser.add_argument(
        "--no-install",
        action="store_true",
        help="Skip uv sync.",
    )
    parser.add_argument(
        "--redis",
        action="store_true",
        help="Enable Redis/Valkey for multi-worker scaling.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Worker count when --redis is set. Default: 4.",
    )
    parser.add_argument(
        "--pywire-version", help="Specify a specific version of pywire to install"
    )
    args = parser.parse_args()

    # --yes triggers full non-interactive mode (all prompts default).
    # Without --yes, any provided flag skips only its own prompt (partial
    # non-interactive — matches pnpm/cargo convention).
    non_interactive = args.yes

    # When running non-interactive, refuse to scaffold into a non-empty
    # directory so we don't silently clobber existing work.
    if non_interactive:
        target = Path(args.project_path or "./my-pywire-app").expanduser().resolve()
        if target.exists() and any(target.iterdir()):
            print(
                f"Error: target directory '{target}' exists and is not empty. "
                "Pass a different PROJECT_PATH or remove the directory first.",
                file=sys.stderr,
            )
            sys.exit(1)

    # Check for local override for testing (highest priority)
    use_local = os.environ.get("USE_LOCAL_PYWIRE") == "1"

    if use_local:
        pywire_dep = "pywire @ /Users/rholmdahl/projects/pywire-workspace/pywire"
        # Try to resolve actual local version for display
        # In a workspace structure, we might be in src/create_pywire_app, so up 3 levels is create-pywire-app, then up 1 is workspace
        # actually let's try a safer relative resolution based on known structure
        # /Users/rholmdahl/projects/pywire-workspace/create-pywire-app/src/create_pywire_app/main.py
        # -> create-pywire-app (repo root) = parents[2]
        # -> pywire-workspace = parents[3]
        workspace_root = Path(__file__).resolve().parents[3]
        local_pywire_path = workspace_root / "pywire"

        # Try reading _version.py first (generated by hatch-vcs)
        local_pywire_version_file = local_pywire_path / "src" / "pywire" / "_version.py"
        pywire_version_display = "Local (Source)"

        if local_pywire_version_file.exists():
            # Basic regex search for version string to avoid importing it
            import re

            content = local_pywire_version_file.read_text()
            match = re.search(r'version = ["\']([^"\']+)["\']', content)
            if match:
                pywire_version_display = f"{match.group(1)} (Local)"

        if pywire_version_display == "Local (Source)":
            # Fallback to toml if needed, though with hatch-vcs pyproject.toml won't have it.
            # but check anyway? hatch-vcs usually cleans it.
            # If completely failing, just stick with "Local (Source)"
            pass

    elif args.pywire_version:
        pywire_dep = f"pywire=={args.pywire_version}"
        pywire_version_display = args.pywire_version
    else:
        pywire_dep = "pywire"  # Latest
        pywire_version_display = "Latest"

    # Resolve the actual version if not local
    if not use_local and pywire_version_display == "Latest":
        with console.status("[dim]Resolving version...", spinner="dots"):
            resolved_version = resolve_pywire_version(pywire_dep)
            if resolved_version:
                pywire_version_display = resolved_version

    tool_version = get_version()

    console.print(LOGO)
    console.print(f"[dim]v{tool_version} • PyWire {pywire_version_display}[/dim]\n")

    if use_local:
        console.print("[yellow]WARNING: Using local pywire dependency[/yellow]")

    adapter_label = {
        "docker": "Docker (Dockerfile)",
        "render": "Render (render.yaml)",
        "fly": "Fly.io (fly.toml + Dockerfile)",
        "railway": "Railway (Dockerfile)",
        "cloudflare": "Cloudflare Workers (wrangler.toml)",
    }

    try:
        # Project Location
        if args.project_path is not None:
            project_location = args.project_path
        elif non_interactive:
            project_location = "./my-pywire-app"
        else:
            project_location = questionary.path(
                "Where should we initialize the system?",
                default="./my-pywire-app",
                style=questionary.Style(
                    [
                        ("qmark", "fg:#00ffff bold"),
                        ("question", "bold"),
                        ("answer", "fg:#00ffff"),
                    ]
                ),
            ).unsafe_ask()

        project_path = Path(project_location).expanduser().resolve()
        project_name = project_path.name

        # Project Template
        if args.template is not None:
            template = args.template
        elif non_interactive:
            template = "counter"
        else:
            template = questionary.select(
                "Select a starting template:",
                choices=[
                    questionary.Choice("Skeleton (minimal)", value="skeleton"),
                    questionary.Choice("Counter", value="counter"),
                    questionary.Choice(
                        "Blog/Portfolio (Markdown + SQLite)", value="blog"
                    ),
                    questionary.Choice(
                        "SaaS Starter (Stripe + SQLAlchemy + Auth Stub)",
                        value="saas",
                    ),
                ],
                default="counter",
                pointer=">",
            ).unsafe_ask()

        # Routing Strategy
        if args.routing is not None:
            routing_strategy = args.routing
        elif non_interactive:
            routing_strategy = "path"
        else:
            routing_strategy = questionary.select(
                "Choose a routing architecture:",
                choices=[
                    questionary.Choice(
                        "Path-based", value="path", checked=True, shortcut_key="p"
                    ),
                    questionary.Choice(
                        "Explicit", value="explicit", shortcut_key="e"
                    ),
                ],
                qmark="?",
                pointer=">",
            ).unsafe_ask()

        # Project Structure
        if args.no_src:
            use_src = False
        elif non_interactive:
            use_src = True
        else:
            use_src = questionary.confirm(
                "Use 'src/' directory layout?",
                default=True,
                auto_enter=False,
                instruction=" (Y/n) Recommended for larger projects ",
            ).unsafe_ask()

        # Deployment Adapters
        if args.deploy is not None:
            adapters = [adapter_label[d] for d in args.deploy]
        elif non_interactive:
            adapters = []
        else:
            adapters = questionary.checkbox(
                "Select deployment adapters to configure:",
                choices=list(adapter_label.values()),
            ).unsafe_ask()

        if "Cloudflare Workers (wrangler.toml)" in adapters:
            console.print(
                "\n[bold yellow]Note:[/] Cloudflare Python Workers requires a "
                "[bold]Workers Paid plan[/] ($5/month).\n"
                "  The free plan's size and startup limits are incompatible with "
                "Python frameworks.\n"
            )

        # Redis/workers scaling options (not applicable to Cloudflare-only setups)
        redis_enabled = False
        workers = 1
        _docker_platforms = {
            "Docker (Dockerfile)",
            "Render (render.yaml)",
            "Fly.io (fly.toml + Dockerfile)",
            "Railway (Dockerfile)",
        }
        has_docker_platform = bool(set(adapters or []) & _docker_platforms)
        if adapters and has_docker_platform:
            if args.redis:
                redis_enabled = True
            elif non_interactive:
                redis_enabled = False
            else:
                redis_enabled = questionary.confirm(
                    "Enable Redis/Valkey for multi-worker scaling?\n"
                    "  (Increases resource usage and may cost more on paid hosting tiers)",
                    default=False,
                    auto_enter=False,
                    instruction=" (y/N) ",
                ).unsafe_ask()

            if redis_enabled:
                if args.workers is not None:
                    workers = args.workers
                elif non_interactive:
                    workers = 4
                else:
                    workers_str = questionary.text(
                        "Number of workers:",
                        default="4",
                        validate=lambda v: (
                            True
                            if v.isdigit() and int(v) > 0
                            else "Enter a positive number"
                        ),
                    ).unsafe_ask()
                    workers = int(workers_str)

        # Generate project
        console.print()

        with console.status(
            "[bold cyan]Synthesizing project structure...", spinner="simpleDots"
        ):
            if not non_interactive:
                time.sleep(0.5)

            generator = ProjectGenerator(
                project_path=project_path,
                project_name=project_name,
                template=template,
                routing_strategy=routing_strategy,
                use_src=use_src,
                adapters=adapters,
                pywire_dep=pywire_dep,
                redis_enabled=redis_enabled,
                workers=workers,
            )
            generator.generate()

            # Initialize git repo
            git_initialized = False
            if not args.no_git:
                try:
                    subprocess.run(
                        ["git", "init"],
                        cwd=project_path,
                        check=True,
                        capture_output=True,
                        text=True,
                    )
                    git_initialized = True
                except (FileNotFoundError, subprocess.CalledProcessError):
                    pass  # Silently skip if git is not available

            if git_initialized:
                try:
                    subprocess.run(
                        ["git", "add", "."],
                        cwd=project_path,
                        check=True,
                        capture_output=True,
                        text=True,
                    )
                    subprocess.run(
                        ["git", "commit", "-m", "feat: initial project structure"],
                        cwd=project_path,
                        check=True,
                        capture_output=True,
                        text=True,
                    )
                except subprocess.CalledProcessError as e:
                    console.print(
                        "[yellow]![/yellow] Git commit skipped (configure user.name/email to enable)."
                    )
                    if e.stderr:
                        console.print(e.stderr)
                except FileNotFoundError:
                    console.print("[yellow]![/yellow] Git not found, skipping commit")

            console.print("[green]✓[/green] Project structure created")

        # UV SYNC
        sync_success = False
        if args.no_install:
            console.print("[dim]Skipping uv sync (--no-install)[/dim]")
        else:
            with console.status(
                "[bold cyan]Initializing environment (uv sync)...",
                spinner="bouncingBar",
            ):
                try:
                    env = os.environ.copy()
                    env.pop("VIRTUAL_ENV", None)

                    sync_cmd = ["uv", "sync"]
                    if not use_local:
                        # Prevent inheriting workspace source overrides (e.g. pywire = { workspace = true })
                        # so the generated uv.lock always resolves pywire from PyPI, not a local path.
                        sync_cmd.append("--no-sources")
                    subprocess.run(
                        sync_cmd,
                        cwd=project_path,
                        check=True,
                        capture_output=True,
                        text=True,
                        env=env,
                    )
                    console.print("[green]✓[/green] Environment optimized")
                    sync_success = True
                except subprocess.CalledProcessError as e:
                    console.print("[red]✗[/red] Failed to sync environment")
                    console.print(e.stderr)
                except FileNotFoundError:
                    console.print("[yellow]![/yellow] uv not found, skipping sync")

        if non_interactive:
            next_action = "instructions"
        else:
            next_action = questionary.select(
                "What would you like to do next?",
                choices=[
                    questionary.Choice("Start development server", value="start"),
                    questionary.Choice(
                        "Show instructions and exit", value="instructions"
                    ),
                ],
                pointer=">",
            ).unsafe_ask()

        should_show_instructions = next_action == "instructions"
        if next_action == "start":
            try:
                subprocess.run(
                    ["uv", "run", "pywire", "dev"],
                    cwd=project_path,
                    check=True,
                )
                return
            except subprocess.CalledProcessError:
                console.print("[red]✗[/red] Failed to start the dev server")
                should_show_instructions = True
            except FileNotFoundError:
                console.print("[yellow]![/yellow] uv not found, cannot start server")
                should_show_instructions = True

        if should_show_instructions:
            console.print()

            is_windows = os.name == "nt"
            commands = [f"cd {project_location}"]
            if not sync_success:
                commands.append("uv sync")
            if is_windows:
                activate_cmd = r".venv\Scripts\activate"
            else:
                activate_cmd = "source .venv/bin/activate"
            commands.extend(
                [
                    activate_cmd,
                    "pywire dev",
                ]
            )

            if "Cloudflare Workers (wrangler.toml)" in adapters:
                commands.extend(
                    [
                        "",
                        "# Cloudflare Workers — fast local dev (standard hot-reload):",
                        "pywire dev",
                        "# Cloudflare Workers — workerd local dev (matches CF production):",
                        "pywire build --platform cloudflare",
                        "pywrangler dev",
                    ]
                )

            cmd_text = "\n    ".join(commands)

            cf_tip = ""
            if "Cloudflare Workers (wrangler.toml)" in adapters:
                cf_tip = "\n> **Deploy:** `pywire build --platform cloudflare && pywrangler deploy`"

            console.print(
                Panel(
                    Markdown(
                        f"""
# System Online 🟢

Run the following commands to enter the environment:

    {cmd_text}

> **Tip:** Install the **PyWire** extension (id: `pywire.pywire`) in VS Code for syntax highlighting and snippets.
{cf_tip}
            """
                    ),
                    border_style="cyan",
                    title="Initialization Complete",
                    title_align="left",
                )
            )
    except KeyboardInterrupt:
        console.print("\n[bold red]System Aborted.[/bold red]")
        sys.exit(1)


if __name__ == "__main__":
    main()
