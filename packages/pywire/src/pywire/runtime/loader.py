"""Page loader - compiles and executes .pywire files."""

import ast
import os
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Dict, Optional, Set, Type, cast

from pywire.compiler.codegen.generator import CodeGenerator
from pywire.compiler.parser import PyWireParser
from pywire.runtime.page import BasePage


class PageLoader:
    """Loads and compiles .pywire files into page classes."""

    def __init__(self) -> None:
        self.parser = PyWireParser()
        self.codegen = CodeGenerator()
        self._cache: Dict[str, Type[BasePage]] = {}  # path -> compiled class
        self._reverse_deps: Dict[str, set[str]] = {}  # dependency -> set of dependents
        self._manifest_cache: Dict[str, tuple[float, dict]] = {}

    def load(
        self,
        pywire_file: Path,
        use_cache: bool = True,
        implicit_layout: Optional[str] = None,
    ) -> Type[BasePage]:
        """Load and compile a .pywire file into a page class."""
        # Normalize path
        pywire_file = pywire_file.resolve()
        path_key = str(pywire_file)

        # Check cache first (incorporate layout into key if needed? No,
        # file content + layout dep determines it)
        # Actually if implicit layout changes, we might need to recompile,
        # but for now assume strict mapping
        if use_cache and path_key in self._cache:
            return self._cache[path_key]

        # Try precompiled artifact
        precompiled = self._load_precompiled(pywire_file)
        if precompiled:
            self._cache[path_key] = precompiled
            precompiled.__file_path__ = str(pywire_file)
            return precompiled

        # Parse
        parsed = self.parser.parse_file(pywire_file)

        # Inject implicit layout if no explicit layout present
        if implicit_layout:
            from pywire.compiler.ast_nodes import LayoutDirective

            if not parsed.get_directive_by_type(LayoutDirective):
                # Create directive
                # We need to ensure implicit_layout is relative or absolute?
                # content relies on load_layout taking a path.
                parsed.directives.append(
                    LayoutDirective(
                        name="layout", line=0, column=0, layout_path=implicit_layout
                    )
                )

        # Generate code
        module_ast = self.codegen.generate(parsed)
        ast.fix_missing_locations(module_ast)

        # Compile and load
        code = compile(module_ast, str(pywire_file), "exec")
        module = type(sys)("pywire_page")

        # Inject global load_layout
        module_any = cast(Any, module)
        module_any.load_layout = self.load_layout
        module_any.load_component = self.load_component

        exec(code, module.__dict__)

        page_class = self._find_page_class(module, pywire_file)
        self._cache[path_key] = page_class
        page_class.__file_path__ = str(pywire_file)
        return page_class
        raise ValueError(f"No page class found in {pywire_file}")

    def _find_page_class(self, module: ModuleType, pywire_file: Path) -> Type[BasePage]:
        if hasattr(module, "__page_class__"):
            return cast(Type[BasePage], module.__page_class__)

        import pywire.runtime.page as page_mod

        current_base_page = page_mod.BasePage
        for name, obj in module.__dict__.items():
            if name.startswith("__"):
                continue
            if isinstance(obj, type):
                if (
                    issubclass(obj, current_base_page)
                    and obj is not current_base_page
                    and name != "_LayoutBase"
                ):
                    return cast(Type[BasePage], obj)

        raise ValueError(f"No page class found in {pywire_file}")

    def _load_precompiled(self, pywire_file: Path) -> Optional[Type[BasePage]]:
        manifest_path = self._find_manifest(pywire_file)
        if not manifest_path:
            return None

        manifest = self._load_manifest(manifest_path)
        if not manifest:
            return None

        entries = manifest.get("entries", {})
        entry = entries.get(str(pywire_file))
        if not entry:
            return None

        if not self._is_entry_fresh(pywire_file, entry):
            return None

        artifact_path = (manifest_path.parent / entry.get("artifact", "")).resolve()
        if not artifact_path.exists():
            return None

        module_name = (
            "pywire_build_"
            + hashlib.md5(str(artifact_path).encode("utf-8")).hexdigest()
        )
        spec = importlib.util.spec_from_file_location(module_name, artifact_path)
        if not spec or not spec.loader:
            return None

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return self._find_page_class(module, pywire_file)

    def _find_manifest(self, pywire_file: Path) -> Optional[Path]:
        build_dir_override = os.environ.get("PYWIRE_BUILD_DIR")
        if build_dir_override:
            build_dir = Path(build_dir_override)
            if not build_dir.is_absolute():
                build_dir = Path.cwd() / build_dir
            manifest_path = build_dir / "manifest.json"
            if manifest_path.exists():
                return manifest_path

        current_dir = pywire_file.parent.resolve()
        while True:
            manifest_path = current_dir / ".pywire" / "build" / "manifest.json"
            if manifest_path.exists():
                return manifest_path

            if current_dir == current_dir.parent:
                break
            current_dir = current_dir.parent

        return None

    def _load_manifest(self, manifest_path: Path) -> Optional[dict]:
        try:
            mtime = manifest_path.stat().st_mtime
            cache_key = str(manifest_path)
            cached = self._manifest_cache.get(cache_key)
            if cached and cached[0] == mtime:
                return cached[1]

            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            self._manifest_cache[cache_key] = (mtime, data)
            return data
        except Exception:
            return None

    def _is_entry_fresh(self, pywire_file: Path, entry: dict) -> bool:
        if entry.get("hash") != self._hash_file(pywire_file):
            return False

        for dep in entry.get("deps", []):
            dep_path = Path(dep.get("path", ""))
            if not dep_path.exists():
                return False
            if dep.get("hash") != self._hash_file(dep_path):
                return False

        return True

    def _hash_file(self, path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def invalidate_cache(self, path: Optional[Path] = None) -> Set[str]:
        """Clear cached classes. If path given, only clear that entry and its dependents.
        Returns set of invalidated paths (strings).
        """
        invalidated = set()
        if path:
            key = str(path.resolve())
            if key in self._cache:
                self._cache.pop(key, None)
                invalidated.add(key)

            # Recursively invalidate dependents
            dependents = self._reverse_deps.get(key, set())
            for dependent in list(dependents):
                # We construct a Path object to recurse properly (though internal key is string)
                print(
                    f"PyWire: Invalidating dependent {dependent} because {key} changed."
                )
                invalidated.update(self.invalidate_cache(Path(dependent)))

            return invalidated
        else:
            self._cache.clear()
            self._reverse_deps.clear()
            return set()  # All cleared

    def load_layout(
        self, layout_path: str, base_path: Optional[str] = None
    ) -> Type[BasePage]:
        """Load a layout file and return its class."""
        path = Path(layout_path)
        if not path.is_absolute():
            # Resolve relative to base file's directory
            if base_path:
                base_dir = Path(base_path).parent
                path = base_dir / layout_path
            else:
                # Fallback to CWD
                path = Path.cwd() / layout_path

        # Resolve symlinks for consistent path comparison
        path = path.resolve()

        # Record dependency
        if base_path:
            dep_key = str(path)
            dependent_key = str(Path(base_path).resolve())
            if dep_key not in self._reverse_deps:
                self._reverse_deps[dep_key] = set()
            self._reverse_deps[dep_key].add(dependent_key)

        return self.load(path)

    def load_component(
        self, component_path: str, base_path: Optional[str] = None
    ) -> Type[BasePage]:
        """Load a component file and return its class (same logic as layout)."""
        return self.load_layout(component_path, base_path)


# Global instance for generated code to use
_loader_instance = PageLoader()


def get_loader() -> PageLoader:
    """Get global loader instance."""
    return _loader_instance


def load_layout(path: str, base_path: Optional[str] = None) -> Type[BasePage]:
    """Helper for generated code to load layouts."""
    return _loader_instance.load_layout(path, base_path)


def load_component(path: str, base_path: Optional[str] = None) -> Type[BasePage]:
    """Helper for generated code to load components."""
    return _loader_instance.load_component(path, base_path)
