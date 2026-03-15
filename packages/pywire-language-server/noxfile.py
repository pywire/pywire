import os
import nox

nox.options.sessions = ["tests"]

@nox.session(python=["3.11", "3.12", "3.13", "3.14"], venv_backend="uv")
def tests(session):
    print("STARTING NOX SESSION")
    # Install the local pywire package first so we don't fetch an old version from PyPI
    pywire_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "pywire"))
    print(f"Checking for local pywire at {pywire_path}")
    if os.path.exists(pywire_path):
        print(f"Found local pywire, installing...")
        session.install("-e", pywire_path)
    else:
        print("Local pywire NOT found, falling back to PyPI")
    
    session.install(".[dev]")
    session.run("pytest", *session.posargs)
