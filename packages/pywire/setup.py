import json
import logging
import os
import shutil
import subprocess
from pathlib import Path
from setuptools import setup
from setuptools.command.build_py import build_py
from setuptools_rust import Binding, RustExtension

log = logging.getLogger(__name__)

def build_client():
    root = Path(__file__).parent
    client_dir = root / "src" / "pywire" / "client"
    static_dir = root / "src" / "pywire" / "static"
    pkg_path = client_dir / "package.json"

    if not pkg_path.exists():
        return

    # Ensure static dir exists
    static_dir.mkdir(parents=True, exist_ok=True)

    # Sync version if possible (optional but good)
    try:
        from setuptools_scm import get_version
        version = get_version(root=root, relative_to=__file__)
        if version:
            data = json.loads(pkg_path.read_text("utf-8"))
            # Normalize PEP440 to SemVer-ish for npm
            semver = version.replace(".dev", "-dev").split("+")[0] 
            if data.get("version") != semver:
                log.info(f"Syncing client version: {data.get('version')} -> {semver}")
                data["version"] = semver
                pkg_path.write_text(json.dumps(data, indent=2) + "\n", "utf-8")
    except Exception as e:
        log.warning(f"Could not sync version to client package.json: {e}")

    pnpm = shutil.which("pnpm")
    if not pnpm:
        if not (static_dir / "pywire.core.min.js").exists():
            raise RuntimeError("pnpm not found and client assets missing. Please install pnpm.")
        log.warning("pnpm not found, skipping client build.")
        return

    # Install if node_modules missing or package.json newer
    nm = client_dir / "node_modules"
    if not nm.exists() or pkg_path.stat().st_mtime > nm.stat().st_mtime:
        log.info("Installing client dependencies...")
        subprocess.run([pnpm, "install", "--frozen-lockfile"], cwd=client_dir, check=True)

    # Build if assets missing or src newer
    core_bundle = static_dir / "pywire.core.min.js"
    needs_build = not core_bundle.exists()
    if not needs_build:
        bundle_mtime = core_bundle.stat().st_mtime
        for path in (client_dir / "src").rglob("*"):
            if path.is_file() and path.stat().st_mtime > bundle_mtime:
                needs_build = True
                break
    
    if needs_build:
        log.info("Building client assets...")
        subprocess.run([pnpm, "run", "build"], cwd=client_dir, check=True)

class BuildPy(build_py):
    def run(self):
        build_client()
        super().run()

# Correctly import sdist
from setuptools.command.sdist import sdist as _sdist

class Sdist(_sdist):
    def run(self):
        build_client()
        super().run()

setup(
    rust_extensions=[
        RustExtension(
            "pywire._pywire_parser",
            path="Cargo.toml",
            binding=Binding.PyO3,
        )
    ],
    cmdclass={
        "build_py": BuildPy,
        "sdist": Sdist,
    },
    zip_safe=False,
)
