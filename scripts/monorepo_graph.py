#!/usr/bin/env python3
"""Monorepo dependency-graph tooling (stdlib-only, Python >= 3.11).

The cross-package graph is DERIVED from packages/*/pyproject.toml
(plus a small side-table for units without pyproject edges) instead of
being hand-maintained in ci.yml `if:` conditions, release-please floors
and root orchestrator scripts. Subcommands:

  print                       human-readable graph (units, edges, floors)
  units                       all checkable units, topological (upstream first)
  affected [base-ref]         units affected by working-tree / branch diff
  check-floors                floors vs published versions + _FLOORS equality
  check-ci                    ci.yml fan-out vs graph-derived fan-out
  check-publishable PKG       PKG's floors satisfiable by published versions
  release-order [PKGS...]     topological merge order (auto-detects release PRs)
  check-scripts               local-tooling contract (scripts/check, orchestrators)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tomllib
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

# Units without pyproject edges: repo-relative unit path -> dist names they
# depend on (floorless — examples are not published, so no floor to check).
SIDE_DEPS: dict[str, list[str]] = {"examples": ["pywire"]}

# Repo-root config that affects every unit; other scripts/ files (the
# orchestrators themselves) too. scripts/hooks and scripts/tests are exempt.
_FULL_WORKSPACE_PREFIXES = ("scripts/",)
_FULL_WORKSPACE_FILES = {
    "pyproject.toml",
    "uv.lock",
    "package.json",
    "pnpm-lock.yaml",
    "pnpm-workspace.yaml",
}


def norm(name: str) -> str:
    return name.lower().replace("_", "-")


def version_tuple(v: str) -> tuple[int, ...]:
    out: list[int] = []
    for chunk in v.split("."):
        digits = ""
        for ch in chunk:
            if not ch.isdigit():
                break
            digits += ch
        out.append(int(digits) if digits else 0)
    return tuple(out)


_REQ_RE = re.compile(r"^([A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?)\s*(?:\[[^\]]*\])?\s*(.*)$")
_FLOOR_RE = re.compile(r">=\s*([0-9][0-9A-Za-z.*-]*)")


def parse_requirement(req: str) -> tuple[str, str | None] | None:
    """'pywire[build]>=0.13.0' -> ('pywire', '0.13.0'); bare deps -> (name, None)."""
    m = _REQ_RE.match(req.strip())
    if not m:
        return None
    floor = None
    fm = _FLOOR_RE.search(m.group(2))
    if fm:
        floor = fm.group(1).rstrip(".*")
    return m.group(1), floor


def parse_semver_floor(spec: str) -> str | None:
    """'^1.2.0' / '>=1.0.0' / '1.2.0' -> the minimum version, or None."""
    s = spec.strip()
    m = re.match(r"^[\^~>]?=?\s*(>=)?\s*([0-9][0-9A-Za-z.*-]*)", s)
    return m.group(2).rstrip(".*") if m else None


@dataclass
class Unit:
    path: str  # repo-relative, e.g. "packages/pywire"
    kind: str  # "python" | "js" | "plain"
    name: str | None = None  # PyPI/npm dist name
    version: str | None = None
    floors: dict[str, str] = field(default_factory=dict)  # dep name -> floor
    bare_deps: list[str] = field(default_factory=list)  # floorless monorepo deps
    compat_floors: dict[str, str] = field(default_factory=dict)  # from _compat.py

    @property
    def label(self) -> str:
        return self.name or self.path


@dataclass
class Monorepo:
    root: Path
    units: dict[str, Unit]  # path -> Unit
    edges: list[tuple[str, str, str | None]]  # (from, to, floor)

    def by_name(self, name: str) -> str | None:
        target = norm(name)
        for path, unit in self.units.items():
            if unit.name and norm(unit.name) == target:
                return path
        return None

    def upstream(self, path: str) -> set[str]:
        return {b for a, b, _ in self.edges if a == path}

    def upstream_closure(self, path: str) -> set[str]:
        seen: set[str] = set()
        stack = list(self.upstream(path))
        while stack:
            u = stack.pop()
            if u in seen:
                continue
            seen.add(u)
            stack.extend(self.upstream(u) - seen)
        return seen

    def downstream(self, path: str) -> set[str]:
        return {a for a, b, _ in self.edges if b == path}

    def downstream_closure(self, path: str) -> set[str]:
        seen: set[str] = set()
        stack = list(self.downstream(path))
        while stack:
            u = stack.pop()
            if u in seen:
                continue
            seen.add(u)
            stack.extend(self.downstream(u) - seen)
        return seen

    def topo_order(self) -> list[str]:
        """Deterministic topological order (upstream first)."""
        remaining = {p: len(self.upstream(p)) for p in self.units}
        ready = sorted(p for p, n in remaining.items() if n == 0)
        order: list[str] = []
        while ready:
            p = ready.pop(0)
            order.append(p)
            for d in sorted(self.downstream(p)):
                remaining[d] -= 1
                if remaining[d] == 0:
                    ready.append(d)
            ready.sort()
        if len(order) != len(self.units):
            raise SystemExit("monorepo graph has a dependency cycle: " + ", ".join(sorted(set(self.units) - set(order))))
        return order


def _read_compat_floors(unit_dir: Path) -> dict[str, str]:
    floors: dict[str, str] = {}
    for compat in unit_dir.glob("src/**/_compat.py"):
        text = compat.read_text()
        m = re.search(r"_FLOORS\s*=\s*\{(.*?)\}", text, re.S)
        if not m:
            continue
        for name, version in re.findall(r'"([^"]+)"\s*:\s*"([^"]+)"', m.group(1)):
            floors[name] = version
    return floors


def load(root: Path) -> Monorepo:
    root = Path(root)
    units: dict[str, Unit] = {}

    def add_unit(rel: str, kind: str) -> Unit:
        unit = Unit(path=rel, kind=kind)
        units[rel] = unit
        return unit

    for pkg_dir in sorted((root / "packages").iterdir()) if (root / "packages").is_dir() else []:
        if not pkg_dir.is_dir():
            continue
        rel = f"packages/{pkg_dir.name}"
        pyproject = pkg_dir / "pyproject.toml"
        if pyproject.exists():
            unit = add_unit(rel, "python")
            data = tomllib.loads(pyproject.read_text())
            project = data.get("project", {})
            unit.name = project.get("name")
            unit.version = project.get("version")
            reqs = list(project.get("dependencies", []))
            for extra in project.get("optional-dependencies", {}).values():
                reqs.extend(extra)
            for req in reqs:
                parsed = parse_requirement(req)
                if not parsed:
                    continue
                dep, floor = parsed
                if unit.name and norm(dep) == norm(unit.name):
                    continue  # self-referential extras (pywire[cli,forms])
                if floor is not None:
                    unit.floors[dep] = floor
                else:
                    unit.bare_deps.append(dep)
            unit.compat_floors = _read_compat_floors(pkg_dir)
        elif (pkg_dir / "package.json").exists():
            unit = add_unit(rel, "js")
            data = json.loads((pkg_dir / "package.json").read_text())
            unit.name = data.get("name")
            unit.version = data.get("version")
            for dep, spec in data.get("dependencies", {}).items():
                floor = parse_semver_floor(spec)
                if floor is not None:
                    unit.floors[dep] = floor
                else:
                    unit.bare_deps.append(dep)

    for rel in ("examples", "docs"):
        if (root / rel).is_dir():
            add_unit(rel, "plain")

    edges: list[tuple[str, str, str | None]] = []
    for path, unit in units.items():
        if unit.kind == "python":
            for dep, floor in sorted(unit.floors.items()):
                target = None
                for other_path, other in units.items():
                    if other.kind != "python" or other_path == path:
                        continue
                    if other.name and norm(other.name) == norm(dep):
                        target = other_path
                        break
                if target:
                    edges.append((path, target, floor))
        elif unit.kind == "js":
            for dep, floor in sorted(unit.floors.items()):
                target = None
                for other_path, other in units.items():
                    if other.kind != "js" or other_path == path:
                        continue
                    if other.name and norm(other.name) == norm(dep):
                        target = other_path
                        break
                if target:
                    edges.append((path, target, floor))
        for dep in SIDE_DEPS.get(path, []):
            target = None
            for other_path, other in units.items():
                if other.name and norm(other.name) == norm(dep):
                    target = other_path
                    break
            if target:
                edges.append((path, target, None))

    return Monorepo(root=root, units=units, edges=edges)


# --- affected -----------------------------------------------------------


def _file_unit(path: str) -> str | None | "FULL":
    if path in _FULL_WORKSPACE_FILES or (
        path.startswith(_FULL_WORKSPACE_PREFIXES)
        and not path.startswith("scripts/hooks/")
        and not path.startswith("scripts/tests/")
    ):
        return "FULL"
    if path.startswith("docs/superpowers/"):
        return None  # spec/planning docs never trigger checks
    if path.startswith("docs/"):
        return "docs"
    if path.startswith("examples/"):
        return "examples"
    m = re.match(r"^packages/([^/]+)/", path + "/")
    if m:
        return f"packages/{m.group(1)}"
    return None


def affected(mono: Monorepo, files: list[str]) -> set[str]:
    """Units to check for the given changed files: the touched units plus
    everything downstream (consumers), or all units on workspace-config
    changes."""
    result: set[str] = set()
    for f in files:
        unit = _file_unit(f)
        if unit == "FULL":
            return set(mono.units)
        if unit:
            result.add(unit)
    closure = set(result)
    for u in result:
        closure |= mono.downstream_closure(u)
    return {u for u in closure if u in mono.units}


# --- checks -------------------------------------------------------------


def check_floors(mono: Monorepo, published: dict[str, str]) -> list[str]:
    """Floor(A -> B) must be >= the latest PUBLISHED version of B, and any
    _FLOORS entry must equal the pyproject floor."""
    violations: list[str] = []
    for path, unit in sorted(mono.units.items()):
        for dep, floor in sorted(unit.floors.items()):
            target = mono.by_name(dep)
            if not target or target == path:
                continue
            latest = published.get(dep)
            if latest and version_tuple(floor) < version_tuple(latest):
                violations.append(
                    f"{path}: floor {dep}>={floor} is below published {dep} {latest} — bump to >={latest}"
                )
        for name, compat_floor in sorted(unit.compat_floors.items()):
            pyproject_floor = unit.floors.get(name)
            if pyproject_floor is None:
                violations.append(
                    f"{path}: _FLOORS entry {name}>={compat_floor} has no matching pyproject floor"
                )
            elif pyproject_floor != compat_floor:
                violations.append(
                    f"{path}: _FLOORS {name}>={compat_floor} != pyproject floor {name}>={pyproject_floor}"
                )
    return violations


def parse_workflow(text: str) -> dict[str, dict]:
    """Minimal line-based workflow parse: per job, whether it needs the
    `changes` job, its joined `if:` expression, and any `cd <unit>` targets."""
    jobs: dict[str, dict] = {}
    current_job: str | None = None
    in_jobs = False
    if_indent = 0
    collecting_if = False
    for line in text.splitlines():
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        stripped = line.strip()
        if indent == 0:
            in_jobs = stripped == "jobs:"
            current_job = None
            collecting_if = False
            continue
        if not in_jobs:
            continue
        if indent == 2:
            current_job = stripped.rstrip(":")
            jobs[current_job] = {"needs_changes": False, "if": "", "cd_units": set()}
            collecting_if = False
            continue
        if current_job is None:
            continue
        job = jobs[current_job]
        if collecting_if:
            if indent > if_indent:
                job["if"] += " " + stripped
                continue
            collecting_if = False
        if indent == 4:
            if stripped.startswith("needs:") and "changes" in stripped:
                job["needs_changes"] = True
            elif stripped.startswith("if:"):
                value = stripped[3:].strip()
                if value in (">", "|", "|-", ">-"):
                    if_indent = indent
                    collecting_if = True
                else:
                    job["if"] += " " + value
        m = re.search(r"\bcd\s+([^\s;&|]+)", stripped)
        if m and (m.group(1).startswith("packages/") or m.group(1) in ("examples", "docs")):
            job["cd_units"].add(m.group(1).rstrip("/"))
    return jobs


def parse_changes(text: str) -> tuple[set[str], dict[str, str]]:
    """The changes job's declared outputs and its paths-filter block:
    output key -> unit path."""
    outputs: set[str] = set()
    for m in re.finditer(r"^\s+([\w-]+):\s*\$\{\{\s*steps\.filter\.outputs\.", text, re.M):
        outputs.add(m.group(1))

    filter_units: dict[str, str] = {}
    lines = text.splitlines()
    idx = next((i for i, line in enumerate(lines) if line.strip() == "filters: |"), None)
    if idx is not None:
        block_indent = None
        current_key: str | None = None
        for line in lines[idx + 1:]:
            if not line.strip():
                continue
            indent = len(line) - len(line.lstrip(" "))
            if block_indent is None:
                block_indent = indent
            elif indent < block_indent:
                break
            stripped = line.strip()
            if indent == block_indent and stripped.endswith(":"):
                current_key = stripped[:-1]
            elif stripped.startswith("- ") and current_key is not None:
                pattern = stripped[2:].strip("'\"")
                if not pattern.startswith("!"):
                    filter_units[current_key] = pattern.rstrip("/*") or pattern
    return outputs, filter_units


def check_ci(mono: Monorepo, ci_text: str) -> list[str]:
    """Each check job's trigger set must equal its own unit plus all
    transitive upstream units (the graph-derived fan-out)."""
    jobs = parse_workflow(ci_text)
    outputs, filter_units = parse_changes(ci_text)
    unit_to_key = {path: key for key, path in filter_units.items()}
    violations: list[str] = []

    for path in sorted(mono.units):
        if path not in unit_to_key:
            violations.append(f"ci.yml: no paths-filter entry for unit {path}")
    if outputs != set(filter_units):
        violations.append(
            f"ci.yml: changes job outputs {sorted(outputs)} != paths-filter keys {sorted(filter_units)}"
        )

    for job_id, job in sorted(jobs.items()):
        if not job["needs_changes"]:
            continue
        triggers = set(re.findall(r"needs\.changes\.outputs\.([\w-]+)", job["if"]))
        undeclared = triggers - outputs
        if undeclared:
            violations.append(f"{job_id}: references undeclared changes outputs {sorted(undeclared)}")
        if len(job["cd_units"]) != 1:
            continue
        unit = next(iter(job["cd_units"]))
        if unit not in mono.units:
            violations.append(f"{job_id}: cd target {unit} is not a known unit")
            continue
        expected = {unit_to_key.get(u) for u in [unit] + sorted(mono.upstream_closure(unit))}
        expected.discard(None)
        if expected != triggers:
            violations.append(
                f"{job_id}: trigger set mismatch — graph expects {sorted(expected)}, ci.yml has {sorted(triggers)}"
            )
    return violations


def check_publishable(mono: Monorepo, pkg: str, published: dict[str, str]) -> list[str]:
    """Every monorepo floor of PKG must be satisfiable by a version already
    published to PyPI/npm (the release-ordering invariant)."""
    path = _resolve_pkg(mono, pkg)
    unit = mono.units[path]
    violations: list[str] = []
    for dep, floor in sorted(unit.floors.items()):
        target = mono.by_name(dep)
        if not target or target == path:
            continue
        latest = published.get(dep)
        if latest is None:
            violations.append(f"{path}: could not determine published version of {dep}")
        elif version_tuple(floor) > version_tuple(latest):
            violations.append(
                f"{path}: floor {dep}>={floor} is not satisfiable — latest published is {dep} {latest}"
                f" (merge and publish {dep} first)"
            )
    return violations


def _resolve_pkg(mono: Monorepo, pkg: str) -> str:
    candidates = {pkg, f"packages/{pkg}", pkg.rstrip("/")}
    for path in mono.units:
        if path in candidates:
            return path
    for path, unit in mono.units.items():
        if unit.name and norm(unit.name) == norm(pkg):
            return path
    raise SystemExit(f"unknown package: {pkg} (try a unit path like packages/pywire or a dist name)")


def release_order(mono: Monorepo, pkgs: list[str]) -> list[tuple[str, bool]]:
    """Topological merge order for the given packages. The bool marks
    order-free units (no monorepo deps and no monorepo dependents)."""
    requested = {_resolve_pkg(mono, p) for p in pkgs}
    topo = mono.topo_order()
    result: list[tuple[str, bool]] = []
    for path in topo:
        if path not in requested:
            continue
        order_free = not mono.upstream(path) and not mono.downstream(path)
        result.append((path, order_free))
    return result


def release_component_from_branch(branch: str) -> str | None:
    """'release-please--main--pywire' -> 'pywire'; grouped PRs -> None."""
    prefix = "release-please--"
    if not branch.startswith(prefix):
        return None
    segments = branch[len(prefix):].split("--")
    if "components" in segments:
        idx = segments.index("components")
        return segments[idx + 1] if idx + 1 < len(segments) else None
    if len(segments) == 2 and segments[0] != "branches":
        return segments[1]
    return None


def check_scripts(root: Path) -> list[str]:
    """Local-tooling contract: every unit exposes executable scripts/check,
    and the root orchestrators + commit hook are graph-driven (no hardcoded
    unit lists)."""
    mono = load(root)
    violations: list[str] = []
    for path, _unit in sorted(mono.units.items()):
        check = root / path / "scripts" / "check"
        if not (check.is_file() and os.access(check, os.X_OK)):
            violations.append(f"{path}: missing executable scripts/check")
    for name in ("check", "test", "lint"):
        script = root / "scripts" / name
        text = script.read_text() if script.exists() else ""
        if "monorepo_graph.py" not in text:
            violations.append(f"scripts/{name}: not graph-driven (no monorepo_graph.py reference)")
        if re.search(r"cd\s+packages/|cd\s+examples\b|cd\s+docs\b", text):
            violations.append(
                f"scripts/{name}: hardcoded unit list — iterate `monorepo_graph.py units` instead"
            )
    hook = root / "scripts" / "hooks" / "pre-git-check.sh"
    if hook.exists() and "monorepo_graph.py" not in hook.read_text():
        violations.append("scripts/hooks/pre-git-check.sh: does not source the unit list from monorepo_graph.py")
    return violations


# --- registries ---------------------------------------------------------

_REGISTRY_CACHE: dict[str, str] = {}


def fetch_published(name: str, registry: str) -> str:
    """Latest published version of NAME on PyPI ('pypi') or npm ('npm')."""
    if name in _REGISTRY_CACHE:
        return _REGISTRY_CACHE[name]
    if registry == "npm":
        url = f"https://registry.npmjs.org/{name}"
        with urllib.request.urlopen(url, timeout=30) as resp:
            version = json.load(resp)["dist-tags"]["latest"]
    else:
        url = f"https://pypi.org/pypi/{name}/json"
        with urllib.request.urlopen(url, timeout=30) as resp:
            version = json.load(resp)["info"]["version"]
    _REGISTRY_CACHE[name] = version
    return version


def _published_for(mono: Monorepo, names: set[str]) -> dict[str, str]:
    published: dict[str, str] = {}
    for name in sorted(names):
        target = mono.by_name(name)
        registry = "npm" if target and mono.units[target].kind == "js" else "pypi"
        try:
            published[name] = fetch_published(name, registry)
        except Exception as exc:  # noqa: BLE001 — report and continue with the rest
            print(f"warning: could not fetch {registry} version for {name}: {exc}", file=sys.stderr)
    return published


def _monorepo_dep_names(mono: Monorepo, paths: list[str] | None = None) -> set[str]:
    names: set[str] = set()
    paths = paths or list(mono.units)
    for path in paths:
        unit = mono.units.get(path)
        if not unit:
            continue
        for dep in unit.floors:
            if mono.by_name(dep):
                names.add(dep)
    for deps in SIDE_DEPS.values():
        names.update(deps)
    return names


# --- CLI ----------------------------------------------------------------


def _changed_files(base_ref: str | None) -> list[str]:
    files: set[str] = set()
    if base_ref:
        base = subprocess.run(
            ["git", "merge-base", base_ref, "HEAD"], capture_output=True, text=True, check=False
        ).stdout.strip()
        if base:
            diff = subprocess.run(
                ["git", "diff", "--name-only", f"{base}...HEAD"], capture_output=True, text=True, check=False
            )
            files.update(diff.stdout.splitlines())
        else:
            print(f"warning: no merge-base with {base_ref}, using working tree only", file=sys.stderr)
    status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"], capture_output=True, text=True, check=False
    )
    for line in status.stdout.splitlines():
        if line.strip():
            files.add(line[3:].strip())
    return sorted(files)


def _cmd_units(mono: Monorepo) -> int:
    for path in mono.topo_order():
        print(path)
    return 0


def _cmd_print(mono: Monorepo) -> int:
    for path in mono.topo_order():
        unit = mono.units[path]
        bits = [path, unit.kind, unit.name or "-", f"v{unit.version}" if unit.version else "-"]
        print("  ".join(bits))
        for dep in sorted(unit.floors):
            if mono.by_name(dep):
                print(f"    -> {dep}>={unit.floors[dep]}")
        for dep in unit.bare_deps:
            if mono.by_name(dep):
                print(f"    -> {dep} (no floor; dev convenience)")
    return 0


def _cmd_affected(mono: Monorepo, base_ref: str | None) -> int:
    units = affected(mono, _changed_files(base_ref))
    for path in sorted(units, key=lambda p: mono.topo_order().index(p)):
        print(path)
    return 0


def _cmd_check_floors(mono: Monorepo) -> int:
    published = _published_for(mono, _monorepo_dep_names(mono))
    violations = check_floors(mono, published)
    for v in violations:
        print(v)
    print(f"check-floors: {'FAIL' if violations else 'ok'} ({len(violations)} violations)")
    return 1 if violations else 0


def _cmd_check_ci(mono: Monorepo, root: Path) -> int:
    ci_path = root / ".github" / "workflows" / "ci.yml"
    violations = check_ci(mono, ci_path.read_text())
    for v in violations:
        print(v)
    print(f"check-ci: {'FAIL' if violations else 'ok'} ({len(violations)} violations)")
    return 1 if violations else 0


def _cmd_check_publishable(mono: Monorepo, pkg: str) -> int:
    path = _resolve_pkg(mono, pkg)
    published = _published_for(mono, _monorepo_dep_names(mono, [path]))
    violations = check_publishable(mono, pkg, published)
    for v in violations:
        print(v)
    print(f"check-publishable {pkg}: {'FAIL' if violations else 'ok'}")
    return 1 if violations else 0


def _cmd_release_order(mono: Monorepo, pkgs: list[str]) -> int:
    if not pkgs:
        result = subprocess.run(
            ["gh", "pr", "list", "--state", "open", "--limit", "100", "--json", "headRefName"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            print("error: could not list open PRs with `gh pr list`", file=sys.stderr)
            return 2
        pkgs = []
        for pr in json.loads(result.stdout):
            component = release_component_from_branch(pr["headRefName"])
            if component:
                pkgs.append(component)
        if not pkgs:
            print("no open release-please PRs")
            return 0
    for path, order_free in release_order(mono, pkgs):
        suffix = "  (order-free)" if order_free else ""
        print(f"{path}{suffix}")
    return 0


def _cmd_check_scripts(root: Path) -> int:
    violations = check_scripts(root)
    for v in violations:
        print(v)
    print(f"check-scripts: {'FAIL' if violations else 'ok'} ({len(violations)} violations)")
    return 1 if violations else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", default=None, help="repo root (default: script's parent parent)")
    args, rest = parser.parse_known_args(argv)

    root = Path(args.root).resolve() if args.root else Path(__file__).resolve().parent.parent
    mono = load(root)

    sub = argparse.ArgumentParser(prog="monorepo_graph.py")
    subs = sub.add_subparsers(dest="command", required=True)
    subs.add_parser("print", help="human-readable graph")
    subs.add_parser("units", help="all units, topological order")
    p = subs.add_parser("affected", help="units affected by the working tree / branch diff")
    p.add_argument("base_ref", nargs="?", default=None)
    subs.add_parser("check-floors", help="floors vs published versions + _FLOORS equality")
    p = subs.add_parser("check-ci", help="ci.yml fan-out vs graph")
    p = subs.add_parser("check-publishable", help="floors satisfiable by published versions")
    p.add_argument("pkg")
    p = subs.add_parser("release-order", help="merge order (default: open release-please PRs)")
    p.add_argument("pkgs", nargs="*", default=[])
    subs.add_parser("check-scripts", help="local-tooling contract")
    ns = sub.parse_args(rest)

    if ns.command == "print":
        return _cmd_print(mono)
    if ns.command == "units":
        return _cmd_units(mono)
    if ns.command == "affected":
        return _cmd_affected(mono, ns.base_ref)
    if ns.command == "check-floors":
        return _cmd_check_floors(mono)
    if ns.command == "check-ci":
        return _cmd_check_ci(mono, root)
    if ns.command == "check-publishable":
        return _cmd_check_publishable(mono, ns.pkg)
    if ns.command == "release-order":
        return _cmd_release_order(mono, ns.pkgs)
    if ns.command == "check-scripts":
        return _cmd_check_scripts(root)
    return 2


if __name__ == "__main__":
    sys.exit(main())
