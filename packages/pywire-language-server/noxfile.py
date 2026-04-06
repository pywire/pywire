import os
import nox

nox.options.sessions = ["tests"]

@nox.session(python=["3.11", "3.12", "3.13", "3.14"], venv_backend="uv")
def tests(session):
    # Determine the absolute path to the potential local pywire
    here = os.path.dirname(__file__)
    pywire_path = os.path.abspath(os.path.join(here, "..", "pywire"))
    
    # Ensure we use the latest pywire with correct line-number reporting.
    # We prefer the local workspace version, but fall back to GitHub main in CI.
    if os.path.exists(pywire_path):
        print(f"Using local pywire from {pywire_path}")
        session.run("uv", "pip", "install", "-e", pywire_path, external=True)
    else:
        print("Local pywire not found. Installing latest from GitHub main...")
        # Fallback to the GitHub version to avoid the buggy/outdated PyPI version.
        # This is critical for CI environments that only check out the LSP repo.
        session.run(
            "uv", "pip", "install", 
            "git+https://github.com/pywire/pywire.git", 
            external=True
        )
    
    # Install language server in editable mode
    session.run("uv", "pip", "install", "-e", ".", external=True)
    
    # Install dev dependencies manually
    session.run("uv", "pip", "install", "pytest>=7.4.0", "pytest-asyncio>=0.21.0", "pytest-cov", external=True)
    
    session.run("pytest", *session.posargs)
