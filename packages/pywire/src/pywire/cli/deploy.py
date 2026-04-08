"""Deployment configuration generators for PyWire apps."""

from pathlib import Path

DOCKERFILE_TEMPLATE = """\
FROM python:3.12-slim
WORKDIR /app

# Install uv and copy dependency files first for layer caching
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Copy application code
COPY . .

EXPOSE 8000
CMD ["uv", "run", "pywire", "run", "--host", "0.0.0.0", "--port", "8000"]
"""

RENDER_YAML_TEMPLATE = """\
services:
  - type: web
    name: {project_name}
    runtime: python
    buildCommand: pip install uv && uv sync --frozen
    startCommand: uv run pywire run --host 0.0.0.0 --port $PORT
    envVars:
      - key: PYTHON_VERSION
        value: "3.12"
"""


def generate_dockerfile(project_root: Path) -> str:
    """Generate Dockerfile content for a PyWire project."""
    return DOCKERFILE_TEMPLATE


def generate_render_yaml(project_root: Path, project_name: str) -> str:
    """Generate render.yaml content for a PyWire project."""
    return RENDER_YAML_TEMPLATE.format(project_name=project_name)


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


def generate_fly_toml(project_root: Path, project_name: str) -> str:
    """Generate fly.toml content for a PyWire project."""
    return FLY_TOML_TEMPLATE.format(app_name=project_name)


def validate_deploy_config(platform: str, project_root: Path) -> list[str]:
    """Check what's missing for deployment on the given platform.

    Returns a list of warning/error messages. An empty list means
    everything looks good.
    """
    issues: list[str] = []

    if not (project_root / "pyproject.toml").exists():
        issues.append("Missing pyproject.toml — required for dependency installation.")

    if platform in ("docker", "fly") and not (project_root / "uv.lock").exists():
        issues.append(
            "Missing uv.lock — run 'uv lock' to generate a lock file for reproducible builds."
        )

    if platform == "render" and not (project_root / "uv.lock").exists():
        issues.append(
            "Missing uv.lock — run 'uv lock' to generate a lock file for reproducible builds."
        )

    return issues
