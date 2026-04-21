"""Shared Jinja2 templates for PyWire deploy + scaffolding."""

from __future__ import annotations

from importlib import resources
from typing import Any

import jinja2

__version__ = "0.2.0"


def _deploy_env() -> jinja2.Environment:
    return jinja2.Environment(
        loader=jinja2.PackageLoader("pywire_templates", "deploy"),
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )


def render_deploy_template(name: str, **context: Any) -> str:
    """Render a deploy template by file name (e.g. ``Dockerfile.j2``)."""
    return _deploy_env().get_template(name).render(**context)


def deploy_template_path(name: str) -> str:
    """Return absolute path to a deploy template file — useful for copies."""
    return str(resources.files("pywire_templates").joinpath("deploy", name))
