import sys
import os
import json
import time

# Add bundled libs to path
BUNDLED_LIBS = os.path.join(os.path.dirname(__file__), '..', 'bundled', 'libs')
sys.path.insert(0, BUNDLED_LIBS)

# FOR DEVELOPMENT ONLY: Add the sibling pywire-language-server/src to path
# In a real build, we would bundle this too.
DEV_SERVER_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'pywire-language-server'))
DEV_SERVER_SRC = os.path.join(DEV_SERVER_ROOT, 'src')
sys.path.insert(0, DEV_SERVER_SRC)

# Check for sibling .venv and add site-packages
venv_dir = os.path.join(DEV_SERVER_ROOT, '.venv')
if os.path.exists(venv_dir):
    # Try to find site-packages
    # Unix: lib/pythonX.X/site-packages
    lib_dir = os.path.join(venv_dir, 'lib')
    if os.path.exists(lib_dir):
        for item in os.listdir(lib_dir):
            if item.startswith('python'):
                site_packages = os.path.join(lib_dir, item, 'site-packages')
                if os.path.exists(site_packages):
                    sys.path.insert(0, site_packages)
                    # Also add bin path for potential executable lookup helpers involving PATH
                    bin_dir = os.path.join(venv_dir, 'bin')
                    os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")
                    break


# #region agent log
try:
    from pathlib import Path
    with open('/Users/rholmdahl/projects/pywire/.cursor/debug.log', 'a') as f:
        log_entry = {
            "sessionId": "debug-session",
            "runId": "run_launcher",
            "hypothesisId": "H4_vendored",
            "location": "lsp_launcher:start",
            "message": "Launcher started",
            "data": {
                "sys.path": sys.path,
                "bundled_libs": BUNDLED_LIBS,
                "dev_src": DEV_SERVER_SRC
            },
            "timestamp": int(time.time() * 1000)
        }
        f.write(json.dumps(log_entry) + "\n")
except Exception:
    pass
# #endregion

try:
    from pywire_language_server.server import start
    if __name__ == '__main__':
        start()
except ImportError as e:
    # Log failure to stderr so it shows up in LS output
    sys.stderr.write(f"Failed to import language server: {e}\n")
    sys.stderr.write(f"sys.path: {sys.path}\n")
    sys.exit(1)
