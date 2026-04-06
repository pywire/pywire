"""Code generators for scaffolding."""

from pathlib import Path


def generate_page(name: str) -> None:
    """Generate a new page."""
    pages_dir = Path("pages")
    pages_dir.mkdir(exist_ok=True)

    page_file = pages_dir / f"{name}.pywire"

    if page_file.exists():
        raise ValueError(f"Page {name} already exists")

    template = f"""!path {{ '{name}': '/{name}' }}

# Page code here

---html---
<div>
    <h1>{name.title()} Page</h1>
    <p>Welcome to the {name} page!</p>
</div>
"""

    page_file.write_text(template)


def generate_component(name: str) -> None:
    """Generate a new component."""
    components_dir = Path("components")
    components_dir.mkdir(exist_ok=True)

    component_file = components_dir / f"{name}.pywire"

    if component_file.exists():
        raise ValueError(f"Component {name} already exists")

    template = f"""# Component code here

---html---
<div class="{name}">
    <!-- Component code here -->
</div>
"""

    component_file.write_text(template)
