import nox

nox.options.sessions = ["tests"]


@nox.session(python=["3.11", "3.12", "3.13", "3.14"], venv_backend="uv")
def tests(session):
    session.install(".[dev]")
    # Install the chromium browser for the playwright version this session
    # just resolved. The outer CI venv may have a different playwright
    # version than what `[dev]` resolves to here, leading to a browser
    # cache version mismatch (e.g. outer downloads chromium-1208, nox
    # session expects chromium-1217).
    session.run("playwright", "install", "chromium")
    session.run("pytest", *session.posargs)
