import json
import logging
import os
import sys
from contextlib import suppress
from pathlib import Path
from typing import Any, Dict

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

log = logging.getLogger(__name__)

class CustomBuildHook(BuildHookInterface):
    def initialize(self, version: str, build_data: Dict[str, Any]) -> None:
        # Guarantee static dir exists absolutely first. 
        # Hatchling will crash with FileNotFoundError if it doesn't exist 
        # because of the force-include in pyproject.toml.
        static_dir = Path(self.root) / "src" / "pywire" / "static"
        static_dir.mkdir(parents=True, exist_ok=True)

        real_version = self.metadata.version
        
        # We only want to do this if we actually have a version
        if not real_version:
            return

        # Attempt to find the client package.json
        pkg_path = Path(self.root) / "src" / "pywire" / "client" / "package.json"
        
        if not pkg_path.exists():
            log.warning(f"Client package.json not found at {pkg_path}")
            return

        try:
            content = pkg_path.read_text("utf-8")
            data = json.loads(content)
            
            current_version = data.get("version")
            
            # Normalize PEP 440 to SemVer
            # 0.1.5.dev0+... -> 0.1.5-dev0+...
            semver = real_version.replace(".dev", "-dev")
            semver = semver.replace(".a", "-alpha")
            semver = semver.replace(".b", "-beta")
            semver = semver.replace(".rc", "-rc")
            
            version_changed = False
            if current_version != semver:
                log.info(f"Syncing client version: {current_version} -> {semver}")
                data["version"] = semver
                
                # formatting with 2 spaces to match typical usage
                pkg_path.write_text(json.dumps(data, indent=2) + "\n", "utf-8")
                version_changed = True
                
            # Now run the build
            # We need to run pnpm install and pnpm run build
            import subprocess
            import shutil
            
            client_dir = pkg_path.parent
            static_dir = client_dir.parent / "static"
            

            # Determine how to run pnpm
            pnpm_bin = shutil.which("pnpm")
            
            # On Windows, pnpm is often pnpm.cmd or pnpm.ps1
            # Using shell=True and just "pnpm" is often more reliable if it's in PATH
            if os.name == "nt":
                pnpm_command = "pnpm"
                use_shell = True
                # Even if shutil.which didn't find it, the shell might
                if not pnpm_bin:
                    log.debug("pnpm not found by shutil.which, will try calling 'pnpm' via shell")
            else:
                pnpm_command = pnpm_bin
                use_shell = False

            if not pnpm_command:
                # If assets are missing and we don't have pnpm, we can't build
                if not (static_dir / "pywire.core.min.js").exists():
                    msg = (
                        "pnpm not found. Building pywire from source (e.g. git install) "
                        "requires pnpm to build client assets. Please install pnpm or "
                        "use a pre-built package from PyPI."
                    )
                    log.error(msg)
                    raise RuntimeError(msg)
                
                log.warning("pnpm not found, skipping client build. Assets may be stale.")
                return

            # Helper to run commands
            def run_command(args, cwd, env=None):
                if use_shell:
                    # On Windows with shell=True, distinct arguments in a list are not
                    # automatically quoted/joined correctly by subprocess.run in all cases.
                    # It's safer to pass a full command string.
                    import subprocess
                    cmd_str = subprocess.list2cmdline(args)
                    log.debug(f"Running command (shell=True): {cmd_str}")
                    subprocess.run(
                        cmd_str,
                        cwd=cwd,
                        check=True,
                        shell=True,
                        env=env
                    )
                else:
                    log.debug(f"Running command: {args}")
                    subprocess.run(
                        args,
                        cwd=cwd,
                        check=True,
                        shell=False,
                        env=env
                    )

            # Check if we need to install
            if self._should_install(client_dir):
                log.info(f"Installing client dependencies using {pnpm_command}...")
                env = os.environ.copy()
                env["CI"] = "true"
                run_command([pnpm_command, "install", "--config.confirmModulesPurge=false"], cwd=client_dir, env=env)
            else:
                log.debug("Client dependencies up to date.")

            # Check if we need to build
            if self._should_build(client_dir, static_dir) or version_changed:
                log.info(f"Building client assets with {pnpm_command}...")
                run_command([pnpm_command, "run", "build"], cwd=client_dir)
                log.info("Client build complete.")
            else:
                log.info("Client assets up to date, skipping build.")
                
        except Exception as e:
            if isinstance(e, RuntimeError):
                raise
            log.error(f"Failed to sync client version: {e}")
            raise RuntimeError(f"Client build failed: {e}") from e

    def _should_install(self, client_dir: Path) -> bool:
        """Check if node_modules is missing or package.json changed."""
        node_modules = client_dir / "node_modules"
        package_json = client_dir / "package.json"
        lock_file = client_dir / "pnpm-lock.yaml"
        
        if not node_modules.exists():
            return True
        
        # If no package.json, can't install (shouldn't happen here)
        if not package_json.exists():
            return False
            
        # Check timestamps
        # Use node_modules directory mtime as proxy for install time
        nm_mtime = node_modules.stat().st_mtime
        pkg_mtime = package_json.stat().st_mtime
        
        if pkg_mtime > nm_mtime:
            return True
            
        if lock_file.exists():
            if lock_file.stat().st_mtime > nm_mtime:
                return True
                
        return False

    def _should_build(self, client_dir: Path, static_dir: Path) -> bool:
        """Check if source files are newer than built assets."""
        core_bundle = static_dir / "pywire.core.min.js"
        
        if not core_bundle.exists():
            return True
            
        build_mtime = core_bundle.stat().st_mtime
        
        # Check source files
        src_dir = client_dir / "src"
        if not src_dir.exists():
            return False
            
        # Recursive check for any file in src
        for root, _, files in os.walk(src_dir):
            for file in files:
                file_path = Path(root) / file
                if file_path.stat().st_mtime > build_mtime:
                    return True
                    
        # Check build script and package.json
        build_script = client_dir / "build.mjs"
        if build_script.exists() and build_script.stat().st_mtime > build_mtime:
            return True
            
        if (client_dir / "package.json").stat().st_mtime > build_mtime:
            return True
            
        return False
