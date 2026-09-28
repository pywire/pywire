"""Tests for scripts/monorepo_graph.py (stdlib-only, offline).

Synthetic fixtures exercise the parsing/graph logic; REPO_* tests are
integration checks against the real tree (offline only — registry checks
run in CI via the check-monorepo-graph job).
"""

from pathlib import Path

import pytest

import monorepo_graph as mg

REPO = Path(__file__).resolve().parents[2]

UPSTREAM_PYPROJECT = """
[project]
name = "upstream"
version = "1.2.3"
dependencies = []
"""

MID_PYPROJECT = """
[project]
name = "mid"
version = "1.0.0"
dependencies = ["upstream>=1.2.3"]

[project.optional-dependencies]
dev = ["pytest"]
"""

DOWN_PYPROJECT = """
[project]
name = "down"
version = "0.1.0"
dependencies = ["mid>=1.0.0", "upstream>=1.2.3"]
"""

# Bare (floorless) monorepo dep: dev convenience, NOT a graph edge.
BARE_PYPROJECT = """
[project]
name = "bare"
version = "0.1.0"
dependencies = ["upstream", "external>=2.0"]
"""


def make_unit(root: Path, rel: str, pyproject: str = "", compat: str = ""):
    d = root / rel
    d.mkdir(parents=True, exist_ok=True)
    if pyproject:
        (d / "pyproject.toml").write_text(pyproject)
    if compat:
        target = d / "src" / rel.split("/")[-1].replace("-", "_") / "_compat.py"
        target.parent.mkdir(parents=True)
        target.write_text(compat)
    return d


def make_repo(tmp_path: Path):
    make_unit(tmp_path, "packages/upstream", UPSTREAM_PYPROJECT)
    make_unit(tmp_path, "packages/mid", MID_PYPROJECT)
    make_unit(tmp_path, "packages/down", DOWN_PYPROJECT)
    make_unit(tmp_path, "packages/bare", BARE_PYPROJECT)
    js = tmp_path / "packages" / "jsone"
    js.mkdir()
    (js / "package.json").write_text('{"name": "jsone", "version": "0.1.0"}')
    (tmp_path / "examples").mkdir()
    (tmp_path / "docs").mkdir()
    return tmp_path


SYNTH_CI = """
name: CI
on:
  pull_request:
jobs:
  changes:
    outputs:
      upstream: ${{ steps.filter.outputs.upstream }}
      mid: ${{ steps.filter.outputs.mid }}
      down: ${{ steps.filter.outputs.down }}
      bare: ${{ steps.filter.outputs.bare }}
      jsone: ${{ steps.filter.outputs.jsone }}
      examples: ${{ steps.filter.outputs.examples }}
      pywire-docs: ${{ steps.filter.outputs.pywire-docs }}
    steps:
      - uses: dorny/paths-filter@v4
        id: filter
        with:
          base: main
          filters: |
            upstream:
              - 'packages/upstream/**'
            mid:
              - 'packages/mid/**'
            down:
              - 'packages/down/**'
            bare:
              - 'packages/bare/**'
            jsone:
              - 'packages/jsone/**'
            examples:
              - 'examples/**'
            pywire-docs:
              - 'docs/**'
  check-mid:
    needs: changes
    if: needs.changes.outputs.mid == 'true' || needs.changes.outputs.upstream == 'true'
    runs-on: ubuntu-latest
    steps:
      - run: cd packages/mid && ./scripts/check
  check-down:
    needs: changes
    if: >
      needs.changes.outputs.down == 'true' ||
      needs.changes.outputs.mid == 'true' ||
      needs.changes.outputs.upstream == 'true'
    steps:
      - run: cd packages/down && ./scripts/check
  check-bare:
    needs: changes
    if: needs.changes.outputs.bare == 'true'
    steps:
      - run: cd packages/bare && ./scripts/check
"""


# --- graph derivation ---


def test_edges_from_floored_deps_only(tmp_path):
    mono = mg.load(make_repo(tmp_path))
    edges = {(a, b): floor for a, b, floor in mono.edges}
    assert edges == {
        ("packages/mid", "packages/upstream"): "1.2.3",
        ("packages/down", "packages/mid"): "1.0.0",
        ("packages/down", "packages/upstream"): "1.2.3",
    }


def test_bare_monorepo_dep_is_not_an_edge(tmp_path):
    mono = mg.load(make_repo(tmp_path))
    assert "packages/bare" not in {a for a, _, _ in mono.edges}


def test_extras_and_self_references_parsed(tmp_path):
    pyproject = """
[project]
name = "selfy"
version = "0.1.0"
dependencies = ["external>=1.0"]

[project.optional-dependencies]
build = ["upstream>=1.1.0"]
dev = ["selfy[build]>=0.1.0", "pytest"]
"""
    make_unit(tmp_path, "packages/selfy", pyproject)
    mono = mg.load(tmp_path)
    assert mono.units["packages/selfy"].floors == {"upstream": "1.1.0", "external": "1.0"}


def test_topological_order_upstream_first(tmp_path):
    mono = mg.load(make_repo(tmp_path))
    order = mono.topo_order()
    assert order.index("packages/upstream") < order.index("packages/mid")
    assert order.index("packages/mid") < order.index("packages/down")


def test_examples_side_table_edge(tmp_path):
    make_unit(tmp_path, "packages/pywire", "")
    (tmp_path / "examples").mkdir()
    (tmp_path / "packages/pywire/pyproject.toml").write_text(
        '[project]\nname = "pywire"\nversion = "0.1.0"\n'
    )
    mono = mg.load(tmp_path)
    assert ("examples", "packages/pywire") in {(a, b) for a, b, _ in mono.edges}


# --- affected (files -> units -> downstream closure) ---


@pytest.mark.parametrize(
    ("files", "expected"),
    [
        (["packages/upstream/src/x.py"], {"packages/upstream", "packages/mid", "packages/down"}),
        (["packages/down/src/x.py"], {"packages/down"}),
        (["packages/mid/x", "packages/down/y"], {"packages/mid", "packages/down"}),
        (["examples/demo/x.py"], {"examples"}),  # examples has no upstream here
        (["README.md"], set()),
        (["pyproject.toml"], None),  # None = all units
        (["scripts/check"], None),
        (["scripts/tests/test_x.py"], set()),
        (["docs/superpowers/specs/x.md"], set()),
        (["docs/src/page.md"], {"docs"}),
    ],
)
def test_affected(tmp_path, files, expected):
    mono = mg.load(make_repo(tmp_path))
    result = mg.affected(mono, files)
    if expected is None:
        assert result == set(mono.units)
    else:
        assert result == expected


# --- check-floors ---


def test_check_floors_passes_when_floors_track_published(tmp_path):
    root = make_repo(tmp_path)
    compat = '_FLOORS = {\n    "upstream": "1.2.3",\n}\n'
    make_unit(root, "packages/mid", MID_PYPROJECT, compat)
    mono = mg.load(root)
    assert mg.check_floors(mono, {"upstream": "1.2.3", "mid": "1.0.0"}) == []


def test_check_floors_flags_stale_floor_with_expected_value(tmp_path):
    mono = mg.load(make_repo(tmp_path))
    violations = mg.check_floors(mono, {"upstream": "1.3.0", "mid": "1.1.0"})
    assert any("packages/mid" in v and "1.2.3" in v and "1.3.0" in v for v in violations), violations
    assert any("packages/down" in v and "mid" in v for v in violations), violations


def test_check_floors_allows_floor_above_published(tmp_path):
    # A floor above the latest published version is a release-ordering
    # concern (check-publishable's job), not a floors violation.
    mono = mg.load(make_repo(tmp_path))
    assert mg.check_floors(mono, {"upstream": "1.0.0", "mid": "0.9.0"}) == []


def test_check_publishable_js_registry(tmp_path):
    make_repo(tmp_path)
    jsapp = tmp_path / "packages" / "jsapp"
    jsapp.mkdir(parents=True)
    (jsapp / "package.json").write_text('{"name": "jsapp", "version": "1.0.0", "dependencies": {"jsone": "^1.0.0"}}')
    mono = mg.load(tmp_path)
    assert mg.check_publishable(mono, "jsapp", {"jsone": "1.4.0"}) == []
    (jsapp / "package.json").write_text('{"name": "jsapp", "version": "1.0.0", "dependencies": {"jsone": "^2.0.0"}}')
    mono = mg.load(tmp_path)
    violations = mg.check_publishable(mono, "packages/jsapp", {"jsone": "1.4.0"})
    assert any("jsone" in v for v in violations), violations


def test_check_floors_flags_compat_mismatch(tmp_path):
    root = make_repo(tmp_path)
    compat = '_FLOORS = {\n    "upstream": "0.9.0",\n}\n'
    make_unit(root, "packages/mid", MID_PYPROJECT, compat)
    mono = mg.load(root)
    violations = mg.check_floors(mono, {"upstream": "1.0.0", "mid": "1.0.0"})
    assert any("0.9.0" in v and "1.2.3" in v and "_FLOORS" in v for v in violations), violations


def test_check_floors_flags_compat_entry_without_pyproject_floor(tmp_path):
    root = make_repo(tmp_path)
    compat = '_FLOORS = {\n    "ghost": "1.0.0",\n}\n'
    make_unit(root, "packages/mid", MID_PYPROJECT, compat)
    mono = mg.load(root)
    violations = mg.check_floors(mono, {"upstream": "1.0.0"})
    assert any("ghost" in v for v in violations), violations


# --- check-ci ---


def test_check_ci_passes_on_matching_fanout(tmp_path):
    mono = mg.load(make_repo(tmp_path))
    assert mg.check_ci(mono, SYNTH_CI) == []


def test_check_ci_flags_missing_trigger_key(tmp_path):
    mono = mg.load(make_repo(tmp_path))
    bad = SYNTH_CI.replace("needs.changes.outputs.upstream == 'true'", "false")
    violations = mg.check_ci(mono, bad)
    assert any("check-mid" in v for v in violations), violations


def test_check_ci_flags_extra_trigger_key(tmp_path):
    mono = mg.load(make_repo(tmp_path))
    bad = SYNTH_CI.replace(
        "if: needs.changes.outputs.bare == 'true'",
        "if: needs.changes.outputs.bare == 'true' || needs.changes.outputs.mid == 'true'",
    )
    violations = mg.check_ci(mono, bad)
    assert any("check-bare" in v for v in violations), violations


def test_check_ci_flags_undeclared_output(tmp_path):
    mono = mg.load(make_repo(tmp_path))
    bad = SYNTH_CI.replace(
        "if: needs.changes.outputs.bare == 'true'",
        "if: needs.changes.outputs.bare == 'true' || needs.changes.outputs.unknown == 'true'",
    )
    violations = mg.check_ci(mono, bad)
    assert any("unknown" in v for v in violations), violations


def test_check_ci_flags_unit_without_filter(tmp_path):
    mono = mg.load(make_repo(tmp_path))
    bad = SYNTH_CI.replace("            down:\n              - 'packages/down/**'\n", "")
    violations = mg.check_ci(mono, bad)
    assert any("packages/down" in v for v in violations), violations


# --- check-publishable ---


def test_check_publishable_ok(tmp_path):
    mono = mg.load(make_repo(tmp_path))
    assert mg.check_publishable(mono, "packages/down", {"upstream": "1.2.3", "mid": "1.0.0"}) == []


def test_check_publishable_flags_unsatisfiable_floor(tmp_path):
    mono = mg.load(make_repo(tmp_path))
    violations = mg.check_publishable(mono, "down", {"upstream": "1.2.3", "mid": "0.9.0"})
    assert any("mid>=1.0.0" in v and "0.9.0" in v for v in violations), violations


def test_check_publishable_unknown_package(tmp_path):
    mono = mg.load(make_repo(tmp_path))
    with pytest.raises(SystemExit):
        mg.check_publishable(mono, "nope", {})


# --- release-order ---


def test_release_order_topological(tmp_path):
    mono = mg.load(make_repo(tmp_path))
    order = mg.release_order(mono, ["packages/down", "packages/upstream", "packages/mid"])
    assert [k for k, _ in order] == ["packages/upstream", "packages/mid", "packages/down"]


def test_release_order_marks_order_free(tmp_path):
    mono = mg.load(make_repo(tmp_path))
    order = mg.release_order(mono, ["packages/jsone", "packages/down"])
    by_key = dict(order)
    assert by_key["packages/jsone"] is True  # no monorepo deps or dependents
    assert by_key["packages/down"] is False


@pytest.mark.parametrize(
    ("branch", "expected"),
    [
        ("release-please--main--pywire", "pywire"),
        ("release-please--branches--main--components--pywire-cli", "pywire-cli"),
        ("release-please--branches--main", None),  # grouped PR
        ("feature/thing", None),
    ],
)
def test_release_component_from_branch(branch, expected):
    assert mg.release_component_from_branch(branch) == expected


# --- check-scripts ---


def make_tooling_repo(tmp_path: Path):
    root = make_repo(tmp_path)
    for rel in ["packages/upstream", "packages/mid", "packages/down", "packages/bare", "packages/jsone", "examples", "docs"]:
        s = root / rel / "scripts"
        s.mkdir()
        (s / "check").write_text("#!/bin/sh\n")
        (s / "check").chmod(0o755)
    (root / "scripts").mkdir()
    (root / "scripts" / "hooks").mkdir()
    return root


def test_check_scripts_passes_on_graph_driven_orchestrators(tmp_path):
    root = make_tooling_repo(tmp_path)
    for name in ("check", "test", "lint"):
        (root / "scripts" / name).write_text(
            "#!/bin/sh\nfor unit in $(python3 scripts/monorepo_graph.py units); do\n"
            '  [ -x "$unit/scripts/%s" ] && (cd "$unit" && ./scripts/%s)\ndone\n' % (name, name)
        )
    (root / "scripts" / "hooks" / "pre-git-check.sh").write_text(
        "#!/bin/sh\n# uses monorepo_graph.py units\n"
    )
    assert mg.check_scripts(root) == []


def test_check_scripts_flags_unit_without_check_script(tmp_path):
    root = make_tooling_repo(tmp_path)
    (root / "packages/mid/scripts/check").unlink()
    assert mg.check_scripts(root) != []


def test_check_scripts_flags_hardcoded_orchestrator(tmp_path):
    root = make_tooling_repo(tmp_path)
    (root / "scripts/check").write_text(
        "#!/bin/sh\ncd packages/mid && ./scripts/check\n"
    )
    violations = mg.check_scripts(root)
    assert any("scripts/check" in v for v in violations), violations


def test_check_scripts_flags_hook_not_sourcing_graph(tmp_path):
    root = make_tooling_repo(tmp_path)
    (root / "scripts/hooks/pre-git-check.sh").write_text("#!/bin/sh\nexit 0\n")
    violations = mg.check_scripts(root)
    assert any("pre-git-check" in v for v in violations), violations


# --- integration against the real repo (offline) ---


def test_real_edges():
    mono = mg.load(REPO)
    edges = {(a, b) for a, b, _ in mono.edges}
    assert edges == {
        ("packages/pywire", "packages/pywire-parser"),
        ("packages/pywire-parser", "packages/tree-sitter-pywire"),
        ("packages/pywire-cli", "packages/pywire"),
        ("packages/pywire-cli", "packages/pywire-templates"),
        ("packages/pywire-auth", "packages/pywire"),
        ("packages/pywire-language-server", "packages/pywire"),
        ("packages/pywire-language-server", "packages/pywire-parser"),
        ("packages/create-pywire-app", "packages/pywire-templates"),
        ("examples", "packages/pywire"),
    }


def test_real_fanout_matches_ci():
    mono = mg.load(REPO)
    assert mg.check_ci(mono, (REPO / ".github/workflows/ci.yml").read_text()) == []


def test_real_compat_floors_match_pyproject():
    mono = mg.load(REPO)
    published = {u.name: u.version for u in mono.units.values() if u.name}
    # Offline part of check-floors: _FLOORS equality (published dict uses
    # in-tree versions only for the entries _FLOORS actually guards).
    violations = [v for v in mg.check_floors(mono, published) if "_FLOORS" in v]
    assert violations == []
