import nox

nox.options.sessions = ["tests"]

@nox.session(python=["3.11", "3.12", "3.13", "3.14"], venv_backend="uv")
def tests(session):
    session.install(".[dev]")
    session.run("pytest", *session.posargs)
