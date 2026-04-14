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
    static_assets: int = 0


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


def generate_cf_bundle(
    build_dir: Path,
    cf_bundle_dir: Path,
    app_import: str = "src.main:app",
) -> Path:
    """Generate a Cloudflare Workers-compatible bundle from precompiled artifacts.

    Rewrites artifacts to use direct Python imports instead of load_layout() calls,
    and generates a _routes.py that registers all routes with the app.

    Args:
        build_dir: Path to .pywire/build/ directory containing manifest.json
        cf_bundle_dir: Output directory for the CF bundle (e.g. project_root/_pywire_build)
        app_import: Module:attribute string like "src.main:app"

    Returns:
        Path to the generated _routes.py file (in cf_bundle_dir's parent).
    """
    manifest_path = build_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = manifest.get("entries", {})

    # Parse app import string
    if ":" in app_import:
        app_module, app_attr = app_import.rsplit(":", 1)
    else:
        app_module, app_attr = app_import, "app"

    # Determine the bundle package name from the output dir name
    bundle_pkg = cf_bundle_dir.name  # e.g. "_pywire_build"

    # Build mapping: absolute source path -> {artifact_rel, module_path, class_name, routes, kind}
    artifact_map: Dict[str, dict] = {}

    # First pass: copy artifacts and extract class names
    if cf_bundle_dir.exists():
        shutil.rmtree(cf_bundle_dir)
    cf_bundle_dir.mkdir(parents=True, exist_ok=True)

    for abs_path, entry in entries.items():
        artifact_rel = entry["artifact"]  # e.g. "pages/__layout__.py"
        src_artifact = build_dir / artifact_rel
        dst_artifact = cf_bundle_dir / artifact_rel

        dst_artifact.parent.mkdir(parents=True, exist_ok=True)
        source = src_artifact.read_text(encoding="utf-8")

        # Extract class name from __page_class__ = ClassName
        class_name = _extract_page_class_name(source)

        # Build module path: "pages/__layout__.py" -> "pages.__layout__"
        module_path = str(Path(artifact_rel).with_suffix("")).replace("/", ".")

        artifact_map[abs_path] = {
            "artifact_rel": artifact_rel,
            "module_path": module_path,  # e.g. "pages.__layout__"
            "class_name": class_name,  # e.g. "LayoutPage"
            "routes": entry.get("routes", []),
            "kind": entry.get("kind", "page"),
        }

    # Second pass: rewrite artifacts (replace load_layout calls with direct imports)
    for abs_path, info in artifact_map.items():
        artifact_rel = info["artifact_rel"]
        src_artifact = build_dir / artifact_rel
        dst_artifact = cf_bundle_dir / artifact_rel

        source = src_artifact.read_text(encoding="utf-8")
        rewritten = _rewrite_artifact_for_cf(source, artifact_map, bundle_pkg)
        dst_artifact.write_text(rewritten, encoding="utf-8")

    # Generate __init__.py files for all directories
    for dirpath in cf_bundle_dir.rglob("*"):
        if dirpath.is_dir():
            init_file = dirpath / "__init__.py"
            if not init_file.exists():
                init_file.write_text("", encoding="utf-8")
    # Root __init__.py
    root_init = cf_bundle_dir / "__init__.py"
    if not root_init.exists():
        root_init.write_text("", encoding="utf-8")

    # Generate _routes.py in the bundle dir's parent (project root)
    routes_path = cf_bundle_dir.parent / "_routes.py"
    routes_source = _generate_routes_module(
        artifact_map, bundle_pkg, app_module, app_attr
    )
    routes_path.write_text(routes_source, encoding="utf-8")

    return routes_path


def _extract_page_class_name(source: str) -> str:
    """Extract class name from __page_class__ = ClassName in artifact source."""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "__page_class__":
                    if isinstance(node.value, ast.Name):
                        return node.value.id
    return "Page"


def _rewrite_artifact_for_cf(
    source: str,
    artifact_map: Dict[str, dict],
    bundle_pkg: str,
) -> str:
    """Rewrite a precompiled artifact for Cloudflare Workers.

    - Replaces load_layout('/abs/path', ...) with direct import from layout module
    - Replaces load_component('/abs/path', ...) with direct import from component module
    - Clears __file_path__ assignments
    - Removes unused load_layout/load_component imports
    """
    tree = ast.parse(source)
    removals = []  # indices in tree.body to remove
    insertions = []  # (index, node) to insert

    for i, node in enumerate(tree.body):
        # Remove: from pywire.runtime.loader import load_layout
        if (
            isinstance(node, ast.ImportFrom)
            and node.module == "pywire.runtime.loader"
            and node.names
        ):
            import_names = [alias.name for alias in node.names]
            if "load_layout" in import_names or "load_component" in import_names:
                # Remove only load_layout/load_component, keep others
                remaining = [
                    alias
                    for alias in node.names
                    if alias.name not in ("load_layout", "load_component")
                ]
                if remaining:
                    node.names = remaining
                else:
                    removals.append(i)

        # Rewrite: _LayoutBase = load_layout('abs_path', 'base_path')
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if (
                isinstance(target, ast.Name)
                and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Name)
                and node.value.func.id in ("load_layout", "load_component")
                and len(node.value.args) >= 1
                and isinstance(node.value.args[0], ast.Constant)
            ):
                dep_path = node.value.args[0].value
                var_name = target.id  # e.g. "_LayoutBase"

                # Find this dependency in the artifact map
                dep_info = artifact_map.get(dep_path)
                if dep_info:
                    # Replace with: from _pywire_build.pages.__layout__ import LayoutPage as _LayoutBase
                    import_module = f"{bundle_pkg}.{dep_info['module_path']}"
                    import_node = ast.ImportFrom(
                        module=import_module,
                        names=[
                            ast.alias(
                                name=dep_info["class_name"],
                                asname=var_name
                                if var_name != dep_info["class_name"]
                                else None,
                            )
                        ],
                        level=0,
                    )
                    ast.fix_missing_locations(import_node)
                    removals.append(i)
                    insertions.append((i, import_node))

    # Apply removals and insertions
    new_body = []
    for i, node in enumerate(tree.body):
        if i in removals:
            # Check if there's an insertion at this index
            for ins_idx, ins_node in insertions:
                if ins_idx == i:
                    new_body.append(ins_node)
            continue
        new_body.append(node)

    tree.body = new_body

    # Clear __file_path__ and __sibling_paths__ inside class bodies
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for item in node.body:
                if (
                    isinstance(item, ast.Assign)
                    and len(item.targets) == 1
                    and isinstance(item.targets[0], ast.Name)
                ):
                    name = item.targets[0].id
                    if name == "__file_path__":
                        item.value = ast.Constant(value="")
                    elif name == "__sibling_paths__":
                        item.value = ast.List(elts=[], ctx=ast.Load())

    ast.fix_missing_locations(tree)
    return ast.unparse(tree)


def _generate_routes_module(
    artifact_map: Dict[str, dict],
    bundle_pkg: str,
    app_module: str,
    app_attr: str,
) -> str:
    """Generate _routes.py that imports page classes and registers routes."""
    lines = [
        '"""Auto-generated by pywire deploy --platform cloudflare."""',
        f"from {app_module} import {app_attr}",
        "",
    ]

    # Sort: layouts first (they're dependencies), then pages/components
    layout_imports = []
    page_imports = []
    registrations = []

    for info in artifact_map.values():
        module_path = f"{bundle_pkg}.{info['module_path']}"
        class_name = info["class_name"]
        imp = f"from {module_path} import {class_name}"

        if info["kind"] == "layout":
            layout_imports.append(imp)
        else:
            page_imports.append(imp)

        if info["kind"] == "page" and info["routes"]:
            for route in info["routes"]:
                registrations.append(
                    f'{app_attr}.router.add_route("{route}", {class_name})'
                )

    lines.extend(layout_imports)
    lines.extend(page_imports)
    lines.append("")
    lines.extend(registrations)
    lines.append("")

    return "\n".join(lines)
