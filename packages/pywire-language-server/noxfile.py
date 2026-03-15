import os
import nox

nox.options.sessions = ["tests"]

@nox.session(python=["3.11", "3.12", "3.13", "3.14"], venv_backend="uv")
def tests(session):
    # Install the local pywire package first so we don't fetch an old version from PyPI
    if os.path.exists("../pywire"):
        session.install("-e", "../pywire")
    session.install(".[dev]")
    session.run("pytest", *session.posargs)
