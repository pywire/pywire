"""Prebuilt deploy bundles (FaaS and Cloudflare) must carry .wire components.

The bundle ships compiled pages and no pywire-parser. A component import left
as written goes through the runtime .wire import hook, which compiles on
import and so fails without the parser; the bundle has to compile each
component and point the import at it.
"""

import shutil
import subprocess
import sys
from pathlib import Path

from pywire.compiler.build_artifacts import build_artifacts, generate_cf_bundle

INDEX = """---
from components.Badge import Badge
from components.Navlink import Navlink as Link
count = wire(0)
def increment():
    count.value += 1
---
<p id="c">{count}</p><Badge label="hi" /><Link href="/x" />
<button @click={increment()}>+</button>
"""

BADGE = """---
from pywire import props

@props
class Props:
    label: str = "x"
---
<span class="badge">{label}</span>
"""

NAVLINK = """---
from pywire import props

@props
class Props:
    href: str = "/"
---
<a class="navlink" href={href}>link</a>
"""

SERVE = """
import asyncio
import os
import sys

sys.modules["pywire_parser"] = None  # importing it raises ImportError
sys.path.insert(0, ".")
os.environ["PYWIRE_PREBUILT"] = "1"  # as every prebuilt entrypoint does
import _routes  # noqa: F401  (imports src.main and registers bundled pages)
from src.main import app
from pywire.adapters.oneshot import OneShotASGIAdapter

status, _, body = asyncio.run(OneShotASGIAdapter(app).fetch("GET", "/"))
print(status, b'class="badge"' in body, b'class="navlink"' in body)
"""


def test_bundle_serves_component_imports_without_parser(tmp_path: Path) -> None:
    pages = tmp_path / "src" / "pages"
    components = tmp_path / "src" / "components"
    pages.mkdir(parents=True)
    components.mkdir()
    (pages / "index.wire").write_text(INDEX)
    (components / "Badge.wire").write_text(BADGE)
    (components / "Navlink.wire").write_text(NAVLINK)
    (tmp_path / "src" / "main.py").write_text(
        "from pywire import PyWire\n"
        "app = PyWire(pages_dir='src/pages', stateless=True, secret_key='k' * 32)\n"
    )

    build_dir = tmp_path / ".pywire" / "build"
    summary = build_artifacts(pages, out_dir=build_dir)
    assert summary.components == 2
    generate_cf_bundle(
        build_dir,
        tmp_path / "_pywire_build",
        app_import="src.main:app",
        durable_objects=False,
    )
    index = (tmp_path / "_pywire_build" / "pages" / "index.py").read_text()
    assert "from components" not in index
    # Deployed bundles don't carry the build dir (the loader would find its
    # manifest and load the unrewritten pages from it).
    shutil.rmtree(build_dir)

    proc = subprocess.run(
        [sys.executable, "-c", SERVE],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.split() == ["200", "True", "True"], proc.stderr[-3000:]
    # The shipped src/pages/*.wire are not compiled at startup: _routes.py
    # registers the prebuilt pages, and there is no compiler to run.
    assert "Failed to load" not in proc.stderr, proc.stderr[-3000:]
