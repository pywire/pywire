import pytest
from pywire_shell._loader import load_runtime

def test_pw_version():
    """Verify we can load the library and call pw_version()."""
    lib = load_runtime()
    version = lib.pw_version().decode("utf-8")
    assert version == "0.2.0"

def test_runtime_loading():
    """Verify runtime paths are resolved correctly."""
    from pywire_shell._loader import get_runtime_path
    path = get_runtime_path()
    assert path.exists()
    assert path.suffix in [".dylib", ".so", ".dll"]
