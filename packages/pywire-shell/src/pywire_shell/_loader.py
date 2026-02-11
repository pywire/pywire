import sys
import ctypes
from pathlib import Path

def get_runtime_path():
    """Locate the pywire_servo shared library."""
    # Logic for Phase 1: Look in the build directory
    root = Path(__file__).parent.parent.parent.parent
    rust_target = root / "pywire-shell" / "target" / "release"
    
    if sys.platform == "darwin":
        lib_name = "libpywire_servo.dylib"
    elif sys.platform == "win32":
        lib_name = "pywire_servo.dll"
    else:
        lib_name = "libpywire_servo.so"
        
    path = rust_target / lib_name
    if not path.exists():
        # Fallback to debug build
        path = root / "pywire-shell" / "target" / "debug" / lib_name
        
    if not path.exists():
        raise RuntimeError(f"Runtime library not found at {path}. Have you run scripts/install?")
        
    return path

def load_runtime():
    """Load the shared library and bind functions."""
    path = get_runtime_path()
    lib = ctypes.CDLL(str(path))
    
    # pw_version bindings
    lib.pw_version.restype = ctypes.c_char_p
    lib.pw_version.argtypes = []
    
    # pw_execute_javascript bindings
    lib.pw_execute_javascript.restype = ctypes.c_int32
    lib.pw_execute_javascript.argtypes = [ctypes.c_char_p]

    # pw_set_title bindings
    lib.pw_set_title.restype = ctypes.c_int32
    lib.pw_set_title.argtypes = [ctypes.c_char_p]

    # pw_resize_window bindings
    lib.pw_resize_window.restype = ctypes.c_int32
    lib.pw_resize_window.argtypes = [ctypes.c_uint32, ctypes.c_uint32]
    
    return lib
