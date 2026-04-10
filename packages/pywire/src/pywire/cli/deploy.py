"""Deployment configuration generators for PyWire apps."""

from pathlib import Path

DOCKERFILE_TEMPLATE = """\
FROM python:3.12-slim
WORKDIR /app

# Install build dependencies (build-essential, git, curl for Node.js setup)
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends build-essential git curl && rm -rf /var/lib/apt/lists/*

# Install Node.js 22 and pnpm (needed for building PyWire's TypeScript client)
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && apt-get install -y nodejs && corepack enable pnpm

# Install uv and copy dependency files first for layer caching
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Copy application code
COPY . .

EXPOSE 8000
CMD ["uv", "run", "pywire", "run", "--host", "0.0.0.0", "--port", "8000", "--workers", "{workers}"]
"""

RENDER_YAML_TEMPLATE = """\
services:
  - type: web
    name: {project_name}
    runtime: docker
    plan: free
    envVars: []
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
