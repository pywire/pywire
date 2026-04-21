import os
import re
import signal
import subprocess
import time
import socket
from pathlib import Path

import pytest
from playwright.sync_api import Page


@pytest.fixture(autouse=True)
def assert_no_nested_html_body(page: Page):
    yield
    # Run this assertion after the test finishes to ensure layout is not duplicated
    assert page.locator("html html").count() == 0, "Found nested <html> tags!"
    assert page.locator("body body").count() == 0, "Found nested <body> tags!"


@pytest.fixture(scope="session")
def server_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def test_app_dir(tmp_path_factory):
    # Copy basic_app to tmp_path
    fixture_dir = Path(__file__).parent / "fixtures" / "basic_app"
    app_dir = tmp_path_factory.mktemp("app")

    # Simple copy
    for item in fixture_dir.glob("**/*"):
        if item.is_file():
            relative = item.relative_to(fixture_dir)
            target = app_dir / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(item.read_bytes())

    return app_dir


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args):
    return {**browser_context_args, "ignore_https_errors": True}


@pytest.fixture(scope="session")
def pywire_server(test_app_dir, server_port):
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"

    import sys

    cmd = [
        sys.executable,
        "-m",
        "pywire_cli.main",
        "dev",
        "app:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(server_port),
        "--no-tui",
    ]
    print(f"\nDEBUG: Starting server with command: {' '.join(cmd)}")

    process = subprocess.Popen(
        cmd,
        cwd=test_app_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        preexec_fn=os.setsid,
        text=True,
        bufsize=1,  # Line buffered
        env=env,
    )

    url = None
    timeout = 20
    start_time = time.time()

    captured_output = []

    # Use non-blocking read approach
    import fcntl

    fd = process.stdout.fileno()
    fl = fcntl.fcntl(fd, fcntl.F_GETFL)
    fcntl.fcntl(fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)

    import threading

    url_found_event = threading.Event()
    stop_event = threading.Event()

    def output_printer():
        while not stop_event.is_set():
            if process.poll() is not None:
                # Read remaining
                try:
                    remaining = process.stdout.read()
                    if remaining:
                        print(remaining, end="", flush=True)
                except (IOError, ValueError):
                    pass
                break
            try:
                chunk = process.stdout.read()
                if chunk:
                    print(chunk, end="", flush=True)
                    captured_output.append(chunk)
                    if not url_found_event.is_set():
                        full_output = "".join(captured_output)
                        match = re.search(
                            r"Running on\s+.*?(https?://127.0.0.1:\d+)",
                            full_output,
                            re.DOTALL,
                        ) or re.search(
                            r"Uvicorn running on\s+.*?(https?://127.0.0.1:\d+)",
                            full_output,
                            re.DOTALL,
                        )
                        if match:
                            nonlocal url
                            url = match.group(1).strip()
                            url_found_event.set()
            except (IOError, TypeError, ValueError):
                pass
            time.sleep(0.1)

    thread = threading.Thread(target=output_printer, daemon=True)
    thread.start()

    while time.time() - start_time < timeout:
        if url_found_event.is_set():
            break
        if process.poll() is not None:
            raise RuntimeError(
                f"Server exited prematurely.\nOutput so far: {''.join(captured_output)}"
            )
        time.sleep(0.1)

    if not url:
        os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        raise RuntimeError(
            f"Server timeout or URL not found.\nCaptured Output: {''.join(captured_output)}"
        )

    yield url

    # Cleanup
    stop_event.set()
    try:
        os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        process.wait(timeout=5)
    except Exception:
        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
    thread.join(timeout=2)
    if process.stdout:
        process.stdout.close()
