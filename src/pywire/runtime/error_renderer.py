from typing import Any, Dict

from jinja2 import Environment, PackageLoader, select_autoescape

# Initialize templating environment for internal error pages
_env = Environment(
    loader=PackageLoader("pywire", "templates"),
    autoescape=select_autoescape(["html", "xml"]),
)


def render_template(template_name: str, context: Dict[str, Any]) -> str:
    """Render a Jinja2 template with the given context.

    Args:
        template_name: Name of the template relative to src/pywire/templates/
        context: Dictionary of variables to pass to the template

    Returns:
        Rendered HTML string
    """
    template = _env.get_template(template_name)
    return template.render(**context)
