# pywire-templates

Shared Jinja2 templates consumed by `pywire-cli` (for `pywire deploy`) and `create-pywire-app` (for project scaffolding).

End users should not depend on this package directly. It exists so deployment configs (Dockerfile, fly.toml, render.yaml, wrangler.toml, railway.json, Cloudflare entry/DO) live in one place.

## Layout

```
src/pywire_templates/
  deploy/          # deployment config templates
    Dockerfile.j2
    fly.toml.j2
    render.yaml.j2
    wrangler.toml.j2
    railway.json.j2
    entry.py.j2
    pywire_do.py.j2
```

## Usage

```python
from pywire_templates import render_deploy_template

content = render_deploy_template("Dockerfile.j2", workers=4)
```
