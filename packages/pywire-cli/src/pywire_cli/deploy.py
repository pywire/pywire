"""Deployment configuration generators for PyWire apps.

Templates live in the ``pywire-templates`` package so ``create-pywire-app``
and ``pywire deploy`` stay in sync. This module is a thin rendering layer
that feeds the right context variables to each template.
"""

from __future__ import annotations

from pathlib import Path

from pywire_templates import render_deploy_template


def _parse_app_string(app_string: str) -> tuple[str, str]:
    """Parse ``'src.main:app'`` into ``('src.main', 'app')``."""
    if ":" in app_string:
        app_module, app_attr = app_string.rsplit(":", 1)
    else:
        app_module, app_attr = app_string, "app"
    return app_module, app_attr


def generate_dockerfile(project_root: Path, workers: int = 1) -> str:
    """Generate Dockerfile content for a PyWire project."""
    return render_deploy_template("Dockerfile.j2", workers=workers)


def generate_render_yaml(
    project_root: Path, project_name: str, redis: bool = False
) -> str:
    """Generate render.yaml content for a PyWire project."""
    return render_deploy_template(
        "render.yaml.j2",
        project_name=project_name,
        redis_enabled=redis,
    )


def generate_fly_toml(project_root: Path, project_name: str) -> str:
    """Generate fly.toml content for a PyWire project."""
    return render_deploy_template("fly.toml.j2", project_name=project_name)


def generate_railway_json(project_root: Path) -> str:
    """Generate railway.json content for a PyWire project."""
    return render_deploy_template("railway.json.j2")


def generate_wrangler_toml(project_root: Path, project_name: str) -> str:
    """Generate wrangler.toml content for Cloudflare Workers with Durable Objects."""
    return render_deploy_template("wrangler.toml.j2", project_name=project_name)


def generate_cf_entry(project_root: Path, app_string: str = "main:app") -> str:
    """Generate entry.py for Cloudflare Workers with Durable Object routing."""
    app_module, app_attr = _parse_app_string(app_string)
    return render_deploy_template(
        "entry.py.j2", app_module=app_module, app_attr=app_attr
    )


def generate_cf_edge_wrangler_toml(project_root: Path, project_name: str) -> str:
    """Generate wrangler.toml for the stateless Cloudflare edge Worker (no DOs)."""
    return render_deploy_template(
        "cloudflare_edge/wrangler.toml.j2", project_name=project_name
    )


def generate_cf_edge_entry(project_root: Path, app_string: str = "main:app") -> str:
    """Generate entry.py for the stateless Cloudflare edge Worker."""
    app_module, app_attr = _parse_app_string(app_string)
    return render_deploy_template(
        "cloudflare_edge/entry.py.j2", app_module=app_module, app_attr=app_attr
    )


def generate_aws_lambda_handler(
    project_root: Path, app_string: str = "main:app"
) -> str:
    """Generate handler.py for the stateless AWS Lambda target."""
    app_module, app_attr = _parse_app_string(app_string)
    return render_deploy_template(
        "aws/handler.py.j2", app_module=app_module, app_attr=app_attr
    )


def generate_azure_function_app(
    project_root: Path, app_string: str = "main:app"
) -> str:
    """Generate function_app.py for the stateless Azure Functions target."""
    app_module, app_attr = _parse_app_string(app_string)
    return render_deploy_template(
        "azure/function_app.py.j2", app_module=app_module, app_attr=app_attr
    )


def generate_gcp_functions_main(
    project_root: Path, app_string: str = "main:app"
) -> str:
    """Generate main.py for the stateless Google Cloud Functions target."""
    app_module, app_attr = _parse_app_string(app_string)
    return render_deploy_template(
        "gcp_functions/main.py.j2", app_module=app_module, app_attr=app_attr
    )


def generate_aws_lambda_requirements(project_root: Path) -> str:
    """Generate runtime requirements for the AWS Lambda package."""
    return render_deploy_template("aws/requirements.txt.j2")


def generate_aws_lambda_readme(project_root: Path, project_name: str) -> str:
    """Generate AWS Lambda deployment instructions."""
    return render_deploy_template(
        "aws/README.md.j2", project_name=project_name, function_name=project_name
    )


def generate_cf_durable_object(project_root: Path, app_string: str = "main:app") -> str:
    """Generate pywire_do.py — the Durable Object class for PyWire sessions."""
    app_module, app_attr = _parse_app_string(app_string)
    return render_deploy_template(
        "pywire_do.py.j2", app_module=app_module, app_attr=app_attr
    )


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
