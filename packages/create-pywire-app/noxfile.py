import nox

nox.options.sessions = ["lint", "tests"]

@nox.session(python=["3.11", "3.12", "3.13", "3.14"], venv_backend="uv")
def tests(session):
    session.install(".[dev]")
    session.run("pytest", *session.posargs)

@nox.session(python="3.11", venv_backend="uv")
def lint(session):
    session.install(".[dev]")
    session.run("ruff", "check", "src", "tests")
    session.run("ruff", "format", "--check", "src", "tests")
    session.run("ty", "check", "src")

@nox.session(python="3.11", venv_backend="uv")
def coverage(session):
    session.install(".[dev]")
    session.run("pytest", "--cov=src/create_pywire_app", "--cov-report=term-missing")
