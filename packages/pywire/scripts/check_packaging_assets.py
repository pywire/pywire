from __future__ import annotations

import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path


REQUIRED_ASSETS = (
    "pywire/static/pywire.core.min.js",
    "pywire/static/pywire.dev.min.js",
    "pywire/templates/error/compile_error.html.j2",
    "pywire/templates/error/default.wire",
)


def _run(cmd: list[str], cwd: Path) -> None:
    subprocess.run(cmd, cwd=cwd, check=True)


def _contains_required(paths: set[str], label: str) -> None:
    for required in REQUIRED_ASSETS:
        if required in paths:
            continue
        if any(name.endswith(required) for name in paths):
            continue
        raise AssertionError(f"{label} missing required asset: {required}")


def _read_wheel_paths(wheel_file: Path) -> set[str]:
    with zipfile.ZipFile(wheel_file) as zf:
        return set(zf.namelist())


def _read_sdist_paths(sdist_file: Path) -> set[str]:
    with tarfile.open(sdist_file, "r:gz") as tf:
        return set(tf.getnames())


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    dist_dir = repo_root / "dist"

    if shutil.which("pnpm") is None:
        raise RuntimeError("pnpm is required for packaging asset checks.")

    _run(["pnpm", "install", "--frozen-lockfile"], cwd=repo_root / "src/pywire/client")
    _run(["pnpm", "build"], cwd=repo_root / "src/pywire/client")

    if dist_dir.exists():
        shutil.rmtree(dist_dir)
    dist_dir.mkdir(parents=True, exist_ok=True)

    _run([sys.executable, "-m", "build", "--wheel", "--sdist"], cwd=repo_root)

    wheel_files = sorted(dist_dir.glob("*.whl"))
    sdist_files = sorted(dist_dir.glob("*.tar.gz"))
    if not wheel_files:
        raise AssertionError("No wheel artifact produced in dist/.")
    if not sdist_files:
        raise AssertionError("No sdist artifact produced in dist/.")

    wheel_paths = _read_wheel_paths(wheel_files[0])
    _contains_required(wheel_paths, "wheel")

    sdist_paths = _read_sdist_paths(sdist_files[0])
    _contains_required(sdist_paths, "sdist")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        unpack_dir = tmp_path / "unpack"
        unpack_dir.mkdir(parents=True, exist_ok=True)

        shutil.unpack_archive(str(sdist_files[0]), str(unpack_dir), format="gztar")
        unpacked_roots = [p for p in unpack_dir.iterdir() if p.is_dir()]
        if len(unpacked_roots) != 1:
            raise AssertionError("Expected a single root directory in unpacked sdist.")
        sdist_root = unpacked_roots[0]

        roundtrip_dist = tmp_path / "roundtrip-dist"
        roundtrip_dist.mkdir(parents=True, exist_ok=True)
        _run(
            [sys.executable, "-m", "build", "--wheel", "--outdir", str(roundtrip_dist)],
            cwd=sdist_root,
        )

        roundtrip_wheels = sorted(roundtrip_dist.glob("*.whl"))
        if not roundtrip_wheels:
            raise AssertionError("No wheel produced from unpacked sdist.")
        roundtrip_paths = _read_wheel_paths(roundtrip_wheels[0])
        _contains_required(roundtrip_paths, "wheel-from-sdist")

    print("Packaging assets verified in wheel, sdist, and wheel-from-sdist.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
