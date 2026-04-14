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
"""

WRANGLER_TOML_KV_TEMPLATE = """\
name = "{project_name}"
main = "entry.py"
compatibility_date = "2025-01-01"
compatibility_flags = ["python_workers"]

[[kv_namespaces]]
binding = "PYWIRE_SESSIONS"
id = "<YOUR_KV_NAMESPACE_ID>"
"""

CF_ENTRY_TEMPLATE = """\
import asgi
from {app_module} import {app_attr}
import _routes
from workers import WorkerEntrypoint


class Default(WorkerEntrypoint):
    async def on_fetch(self, request):
        return await asgi.fetch({app_attr}, request.js_object, self.env)
"""

CF_ENTRY_KV_TEMPLATE = """\
import asgi
from {app_module} import {app_attr}
import _routes
from pywire.runtime.cf_kv_store import CloudflareKVSessionStore
from workers import WorkerEntrypoint

_kv_initialized = False


class Default(WorkerEntrypoint):
    async def on_fetch(self, request):
        global _kv_initialized
        if not _kv_initialized:
            {app_attr}.session_store = CloudflareKVSessionStore(self.env.PYWIRE_SESSIONS)
            _kv_initialized = True
        return await asgi.fetch({app_attr}, request.js_object, self.env)
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


def generate_wrangler_toml(
    project_root: Path,
    project_name: str,
    kv: bool = False,
) -> str:
    """Generate wrangler.toml content for Cloudflare Workers."""
    template = WRANGLER_TOML_KV_TEMPLATE if kv else WRANGLER_TOML_TEMPLATE
    return template.format(project_name=project_name)


def generate_cf_entry(
    project_root: Path, app_string: str = "main:app", kv: bool = False
) -> str:
    """Generate entry.py for Cloudflare Workers.

    Args:
        app_string: Module:attribute string like "src.main:app"
    """
    # Parse "src.main:app" into module="src.main", attr="app"
    if ":" in app_string:
        app_module, app_attr = app_string.rsplit(":", 1)
    else:
        app_module, app_attr = app_string, "app"

    template = CF_ENTRY_KV_TEMPLATE if kv else CF_ENTRY_TEMPLATE
    return template.format(app_module=app_module, app_attr=app_attr)


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
