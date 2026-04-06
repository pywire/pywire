"""Build system for precompiled PyWire artifacts."""

from __future__ import annotations

import ast
import hashlib
import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from pywire.compiler.ast_nodes import (
    ComponentDirective,
    LayoutDirective,
    ParsedPyWire,
    PathDirective,
)
from pywire.compiler.codegen.generator import CodeGenerator
from pywire.compiler.parser import PyWireParser


@dataclass
class BuildSummary:
    pages: int
    layouts: int
    components: int
    out_dir: Path


class ArtifactBuilder:
    def __init__(self, pages_dir: Path, out_dir: Path) -> None:
        self.pages_dir = pages_dir.resolve()
        self.out_dir = out_dir.resolve()
        self.parser = PyWireParser()
        self.codegen = CodeGenerator()
        self.entries: Dict[str, dict] = {}
        self._compiled: Set[str] = set()
        self._page_count = 0
        self._layout_count = 0
        self._component_count = 0

    def build(self, optimize: bool = False) -> BuildSummary:
        if self.out_dir.exists():
            shutil.rmtree(self.out_dir)

        (self.out_dir / "pages").mkdir(parents=True, exist_ok=True)
        (self.out_dir / "components").mkdir(parents=True, exist_ok=True)

        self._scan_directory(self.pages_dir, layout_path=None, url_prefix="")
        self._build_error_page()

        manifest = {
            "version": 1,
            "pages_dir": str(self.pages_dir),
            "entries": self.entries,
        }
        manifest_path = self.out_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        if optimize:
            import compileall

            compileall.compile_dir(self.out_dir, quiet=1, optimize=2)

        return BuildSummary(
            pages=self._page_count,
            layouts=self._layout_count,
            components=self._component_count,
            out_dir=self.out_dir,
        )

    def _build_error_page(self) -> None:
        error_page_path = self.pages_dir / "__error__.wire"
        if not error_page_path.exists():
            return

        implicit_layout = None
        root_layout = self.pages_dir / "__layout__.wire"
        if root_layout.exists():
            implicit_layout = str(root_layout.resolve())

        self._compile_file(
            error_page_path, kind="page", implicit_layout=implicit_layout, is_error=True
        )

    def _scan_directory(
        self, dir_path: Path, layout_path: Optional[str], url_prefix: str
    ) -> None:
        current_layout = layout_path
        potential_layout = dir_path / "__layout__.wire"
        if potential_layout.exists():
            self._compile_file(
                potential_layout, kind="layout", implicit_layout=current_layout
            )
            current_layout = str(potential_layout.resolve())

        try:
            entries = sorted(list(dir_path.iterdir()))
        except FileNotFoundError:
            return

        for entry in entries:
            if entry.name.startswith("_") or entry.name.startswith("."):
                continue

            if entry.is_dir():
                name = entry.name
                new_segment = name
                param_match = re.match(r"^\[(.*?)\]$", name)
                if param_match:
                    param_name = param_match.group(1)
                    new_segment = f"{{{param_name}}}"

                new_prefix = (url_prefix + "/" + new_segment).replace("//", "/")
                self._scan_directory(entry, current_layout, new_prefix)
                continue

            if not entry.is_file() or entry.suffix != ".wire":
                continue

            if entry.name == "layout.wire":
                continue

            self._compile_file(
                entry, kind="page", implicit_layout=current_layout, is_error=False
            )

    def _compile_file(
        self,
        file_path: Path,
        kind: str,
        implicit_layout: Optional[str],
        is_error: bool = False,
    ) -> None:
        resolved_path = file_path.resolve()
        key = str(resolved_path)

        if key in self._compiled:
            if kind == "page":
                entry = self.entries.get(key)
                if entry and entry.get("kind") != "page":
                    entry["kind"] = "page"
                    parsed = self.parser.parse_file(resolved_path)
                    entry["routes"] = self._get_routes(parsed, resolved_path, is_error)
            return

        parsed = self.parser.parse_file(resolved_path)
        if implicit_layout:
            if not parsed.get_directive_by_type(LayoutDirective):
                parsed.directives.append(
                    LayoutDirective(
                        name="layout",
                        line=0,
                        column=0,
                        layout_path=implicit_layout,
                    )
                )

        module_ast = self.codegen.generate(parsed)
        ast.fix_missing_locations(module_ast)
        source = ast.unparse(module_ast)

        artifact_rel = self._artifact_path_for(resolved_path)
        artifact_path = self.out_dir / artifact_rel
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_path.write_text(source, encoding="utf-8")

        deps = self._collect_deps(parsed, implicit_layout, resolved_path)
        entry_deps = []
        for dep_path, dep_kind in deps:
            if not dep_path.exists():
                continue
            entry_deps.append(
                {"path": str(dep_path), "hash": self._hash_file(dep_path)}
            )

        entry = {
            "artifact": str(artifact_rel),
            "hash": self._hash_file(resolved_path),
            "deps": entry_deps,
            "kind": kind,
            "routes": self._get_routes(parsed, resolved_path, is_error)
            if kind == "page"
            else [],
            "implicit_layout": implicit_layout,
        }
        self.entries[key] = entry
        self._compiled.add(key)

        if kind == "page":
            self._page_count += 1
        elif kind == "layout":
            self._layout_count += 1
        elif kind == "component":
            self._component_count += 1

        for dep_path, dep_kind in deps:
            if not dep_path.exists():
                continue
            dep_implicit_layout = None
            if self._is_in_pages(dep_path):
                dep_implicit_layout = self._resolve_implicit_layout(dep_path)
            self._compile_file(
                dep_path, kind=dep_kind, implicit_layout=dep_implicit_layout
            )

    def _collect_deps(
        self, parsed: ParsedPyWire, implicit_layout: Optional[str], base_path: Path
    ) -> List[Tuple[Path, str]]:
        deps: Dict[str, str] = {}

        if implicit_layout:
            deps[str(Path(implicit_layout).resolve())] = "layout"

        for directive in parsed.directives:
            if isinstance(directive, LayoutDirective):
                path = self._resolve_path(directive.layout_path, base_path)
                deps[str(path)] = "layout"
            elif isinstance(directive, ComponentDirective):
                path = self._resolve_path(directive.path, base_path)
                deps[str(path)] = "component"

        # Scan Python imports for component dependencies
        if parsed.python_ast:
            for node in parsed.python_ast.body:
                if isinstance(node, ast.ImportFrom) and node.module:
                    # Resolve 'from .Child import Child' or 'from Child import Child'
                    dep_path = self._resolve_import_to_path(node, base_path)
                    if dep_path:
                        deps[str(dep_path)] = "component"
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        # Resolve 'import Button'
                        dep_path = self._resolve_import_to_path_simple(
                            alias.name, base_path
                        )
                        if dep_path:
                            deps[str(dep_path)] = "component"
        return [(Path(path), kind) for path, kind in deps.items()]

    def _resolve_path(self, path_str: str, base_path: Path) -> Path:
        path = Path(path_str)
        if not path.is_absolute():
            path = base_path.parent / path
        return path.resolve()

    def _resolve_import_to_path(
        self, node: ast.ImportFrom, base_path: Path
    ) -> Optional[Path]:
        """Resolve an ImportFrom node to a .wire file path if possible."""
        if not node.module:
            return None

        # 1. Try relative to base_path (handles level > 0 and level == 0 in same dir)
        target_dir = base_path.parent
        if node.level > 1:
            for _ in range(node.level - 1):
                target_dir = target_dir.parent

        # Check target_dir / module.wire (e.g. from .Child -> Child.wire)
        # and also target_dir / module / module.wire (if it's a package? probably not common for .wire)
        potential = target_dir / f"{node.module}.wire"
        if potential.exists():
            return potential.resolve()

        # 2. Try relative to pages_dir
        potential = self.pages_dir / f"{node.module.replace('.', '/')}.wire"
        if potential.exists():
            return potential.resolve()

        # 3. Try in sibling 'components' directory if pages_dir has one
        components_dir = self.pages_dir.parent / "components"
        if components_dir.exists():
            potential = components_dir / f"{node.module.replace('.', '/')}.wire"
            if potential.exists():
                return potential.resolve()

        return None

    def _resolve_import_to_path_simple(
        self, name: str, base_path: Path
    ) -> Optional[Path]:
        """Resolve a simple 'import Name' to a .wire file path."""
        # Check same dir
        potential = base_path.parent / f"{name}.wire"
        if potential.exists():
            return potential.resolve()

        # Check pages_dir
        potential = self.pages_dir / f"{name.replace('.', '/')}.wire"
        if potential.exists():
            return potential.resolve()

        return None

    def _artifact_path_for(self, file_path: Path) -> Path:
        if self._is_in_pages(file_path):
            rel = file_path.relative_to(self.pages_dir)
            return Path("pages") / rel.with_suffix(".py")

        file_hash = hashlib.md5(str(file_path).encode("utf-8")).hexdigest()[:10]
        safe_name = f"{file_path.stem}_{file_hash}.py"
        return Path("components") / safe_name

    def _get_routes(
        self, parsed: ParsedPyWire, file_path: Path, is_error: bool
    ) -> List[str]:
        if is_error:
            return ["/__error__"]

        path_directive = parsed.get_directive_by_type(PathDirective)
        if isinstance(path_directive, PathDirective):
            return list(path_directive.routes.values())

        implicit = self._get_implicit_route(file_path)
        if implicit:
            return [implicit]
        return []

    def _get_implicit_route(self, file_path: Path) -> Optional[str]:
        try:
            rel_path = file_path.relative_to(self.pages_dir)
        except ValueError:
            return None

        segments = []
        for i, part in enumerate(rel_path.parts):
            if part.startswith("_") or part.startswith("."):
                return None

            name = part
            is_file = i == len(rel_path.parts) - 1
            if is_file:
                if not name.endswith(".wire"):
                    return None
                if name == "layout.wire":
                    return None
                name = Path(name).stem

            segment = name
            if name == "index":
                segment = ""

            param_match = re.match(r"^\[(.*?)\]$", name)
            if param_match:
                param_name = param_match.group(1)
                segment = f"{{{param_name}}}"

            segments.append(segment)

        route_path = "/" + "/".join(segments)
        while "//" in route_path:
            route_path = route_path.replace("//", "/")

        if route_path != "/" and route_path.endswith("/"):
            route_path = route_path.rstrip("/")

        if not route_path:
            route_path = "/"

        return route_path

    def _resolve_implicit_layout(self, page_path: Path) -> Optional[str]:
        current_dir = page_path.parent
        try:
            current_dir.relative_to(self.pages_dir)
        except ValueError:
            return None

        while True:
            layout = current_dir / "__layout__.wire"
            if layout.exists():
                if layout.resolve() != page_path.resolve():
                    return str(layout.resolve())

            if current_dir == self.pages_dir:
                break

            current_dir = current_dir.parent
            if current_dir == current_dir.parent:
                break

        return None

    def _hash_file(self, path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def _is_in_pages(self, path: Path) -> bool:
        try:
            path.resolve().relative_to(self.pages_dir)
            return True
        except ValueError:
            return False


def build_artifacts(
    pages_dir: Path, out_dir: Optional[Path] = None, optimize: bool = False
) -> BuildSummary:
    if out_dir is None:
        from pywire.compiler.paths import get_build_path

        out_dir = get_build_path()

    builder = ArtifactBuilder(pages_dir=pages_dir, out_dir=out_dir)
    return builder.build(optimize=optimize)
