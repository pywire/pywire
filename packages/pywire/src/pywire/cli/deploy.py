"""Deployment configuration generators for PyWire apps."""

from pathlib import Path

DOCKERFILE_TEMPLATE = """\
FROM python:3.12-slim
WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY . .

# Session timeout in seconds (default: 1800 = 30 min)
ENV SESSION_TTL=1800

EXPOSE 8000
CMD ["uv", "run", "pywire", "run", "--host", "0.0.0.0", "--port", "8000", "--workers", "{workers}"]
"""

RENDER_YAML_TEMPLATE = """\
services:
  - type: web
    name: {project_name}
    runtime: docker
    plan: free
    envVars:
      - key: SESSION_TTL
        value: "1800"  # Session timeout in seconds (default: 30 min)
"""

RENDER_YAML_REDIS_TEMPLATE = """\
services:
  - type: web
    name: {project_name}
    runtime: docker
    plan: starter
    envVars:
      - key: REDIS_URL
        fromService:
          name: {project_name}-kv
          type: keyvalue
          property: connectionString
      - key: SESSION_TTL
        value: "1800"  # Session timeout in seconds (default: 30 min)

  - type: keyvalue
    name: {project_name}-kv
    plan: starter
    ipAllowList: []
"""

FLY_TOML_TEMPLATE = """\
app = "{app_name}"
primary_region = "ord"

[build]
  dockerfile = "Dockerfile"

[http_service]
  internal_port = 8000
  force_https = true
  auto_stop_machines = "stop"
  auto_start_machines = true

[env]
  # Session timeout in seconds (default: 1800 = 30 min)
  SESSION_TTL = "1800"

[[vm]]
  memory = "512mb"
  cpus = 1
"""

RAILWAY_JSON_TEMPLATE = """\
{
  "$schema": "https://railway.com/railway.schema.json",
  "build": {
    "dockerfilePath": "Dockerfile"
  }
}
"""

WRANGLER_TOML_TEMPLATE = """\
name = "{project_name}"
main = "entry.py"
compatibility_date = "2025-01-01"
compatibility_flags = ["python_workers"]

[vars]
PAGES_DIR = "pages"
"""

CF_ENTRY_TEMPLATE = """\
import asgi
import micropip
from workers import WorkerEntrypoint

from pywire import PyWire

# Install WASM-only PyWire dependencies from the PyWire CDN.
# These are C extensions compiled for Pyodide and are not available as native PyPI wheels.
# To pin a specific version or use a different source, see:
# https://pywire.dev/docs/deploy/cloudflare-workers#wasm-dependencies
await micropip.install(
    "tree-sitter-pywire",
    index_urls=["https://pywire.dev/cdn/simple", "https://pypi.org/simple"],
)

app = PyWire(pages_dir="pages")


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        return await asgi.fetch(app, request.js_object, self.env)
"""

CF_REQUIREMENTS_TEMPLATE = """\
pywire
starlette
pydantic
anyio
msgpack
typing-extensions
"""


def generate_dockerfile(project_root: Path, workers: int = 1) -> str:
    """Generate Dockerfile content for a PyWire project."""
    return DOCKERFILE_TEMPLATE.format(workers=workers)


def generate_render_yaml(
    project_root: Path, project_name: str, redis: bool = False
) -> str:
    """Generate render.yaml content for a PyWire project."""
    if redis:
        return RENDER_YAML_REDIS_TEMPLATE.format(project_name=project_name)
    return RENDER_YAML_TEMPLATE.format(project_name=project_name)


def generate_fly_toml(project_root: Path, project_name: str) -> str:
    """Generate fly.toml content for a PyWire project."""
    return FLY_TOML_TEMPLATE.format(app_name=project_name)


def generate_railway_json(project_root: Path) -> str:
    """Generate railway.json content for a PyWire project."""
    return RAILWAY_JSON_TEMPLATE


def generate_wrangler_toml(project_root: Path, project_name: str) -> str:
    """Generate wrangler.toml content for Cloudflare Workers."""
    return WRANGLER_TOML_TEMPLATE.format(project_name=project_name)


def generate_cf_entry(project_root: Path) -> str:
    """Generate entry.py for Cloudflare Workers."""
    return CF_ENTRY_TEMPLATE


def generate_cf_requirements(project_root: Path) -> str:
    """Generate requirements.txt for Cloudflare Workers."""
    return CF_REQUIREMENTS_TEMPLATE


def validate_deploy_config(platform: str, project_root: Path) -> list[str]:
    """Check what's missing for deployment on the given platform.

    Returns a list of warning/error messages. An empty list means
    everything looks good.
    """
    issues: list[str] = []

    if not (project_root / "pyproject.toml").exists():
        issues.append("Missing pyproject.toml — required for dependency installation.")

    if (
        platform in ("docker", "fly", "render", "railway")
        and not (project_root / "uv.lock").exists()
    ):
        issues.append(
            "Missing uv.lock — run 'uv lock' to generate a lock file for reproducible builds."
        )

    return issues
