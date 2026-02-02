"""Development server with hot reload."""

import os
import sys
from pathlib import Path
from typing import Any, Optional, Tuple
from rich.console import Console

# Force terminal to ensure ANSI codes are generated even when piped to TUI
console = Console(force_terminal=True, markup=True)


def _import_app(app_str: str) -> Any:
    """Import application from string."""
    module_name, app_name = app_str.split(":", 1)
    # Ensure current directory is in path (should be from main.py, but safe to add)
    if os.getcwd() not in sys.path:
        sys.path.insert(0, os.getcwd())

    import importlib

    module = importlib.import_module(module_name)
    return getattr(module, app_name)


def _generate_cert() -> Tuple[str, str, bytes]:
    """Generate self-signed certificate for localhost."""
    import datetime
    import os
    import tempfile

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    # Use ECDSA P-256 (More standard for QUIC/TLS 1.3 than RSA)
    key = ec.generate_private_key(ec.SECP256R1())

    subject = issuer = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, "localhost"),
        ]
    )

    import ipaddress

    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(
            # Backdate by 1 hour to handle minor clock skew
            datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=1)
        )
        .not_valid_after(
            # Valid for 10 days (Required for WebTransport serverCertificateHashes)
            datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=10)
        )
        .add_extension(
            x509.SubjectAlternativeName(
                [
                    x509.DNSName("localhost"),
                    x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
                    x509.IPAddress(ipaddress.IPv6Address("::1")),
                ]
            ),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )

    cert_dir = tempfile.mkdtemp()
    cert_path = os.path.join(cert_dir, "cert.pem")
    key_path = os.path.join(cert_dir, "key.pem")

    with open(key_path, "wb") as f:
        f.write(
            key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )

    with open(cert_path, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))

    fingerprint = cert.fingerprint(hashes.SHA256())

    return cert_path, key_path, fingerprint


async def run_dev_server(
    app_str: str,
    host: str,
    port: int,
    ssl_keyfile: Optional[str] = None,
    ssl_certfile: Optional[str] = None,
) -> None:
    """Run development server with hot reload."""
    import asyncio
    import logging
    import signal

    from watchfiles import awatch
    from rich.logging import RichHandler

    # Configure logging to see Hypercorn/aioquic debug output
    # Use RichHandler to ensure colored logs for Uvicorn/Hypercorn
    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(console=console, show_path=False, markup=True)],
    )
    logging.getLogger("hypercorn").setLevel(logging.INFO)

    # Load app to get config
    pywire_app = _import_app(app_str)

    # Enable dev mode flag to unlock source endpoints
    pywire_app._is_dev_mode = True

    pages_dir = pywire_app.pages_dir

    # Enable Dev Error Middleware
    from pywire.runtime.debug import DevErrorMiddleware

    pywire_app.app = DevErrorMiddleware(pywire_app.app)

    if not pages_dir.exists():
        console.print(
            f"[bold yellow]Warning[/]: Pages directory '{pages_dir}' does not exist."
        )

    # Try to import Hypercorn for HTTP/3 support
    try:
        from hypercorn.asyncio import serve
        from hypercorn.config import Config

        has_http3 = True
    except ImportError:
        has_http3 = False

    # DEBUG: Force disable HTTP/3 to avoid Hypercorn/aioquic crash (KeyError: 9) on form uploads
    # console.print("[dim]DEBUG: Forcing HTTP/3 disabled for stress testing form uploads.[/]")
    has_http3 = False
    if not has_http3:
        pass
        # console.print("[dim]PyWire: HTTP/3 (WebTransport) disabled. Install 'aioquic' and 'hypercorn' to enable.[/]")

    # Create shutdown event
    shutdown_event = asyncio.Event()

    async def _handle_signal() -> None:
        console.print("\n[bold]PyWire: Shutting down...[/]")
        shutdown_event.set()

    # Register signal handlers
    try:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, lambda: asyncio.create_task(_handle_signal()))
    except NotImplementedError:
        pass

    # Watcher task
    async def watch_changes() -> None:
        try:
            # Determine pywire source directory
            import pywire

            pywire_src_dir = Path(pywire.__file__).parent

            # Install logging interceptor for print capture
            from pywire.runtime.logging import install_logging_interceptor

            install_logging_interceptor()

            if not pages_dir.exists():
                console.print(
                    f"[bold yellow]Warning[/]: Pages directory '{pages_dir}' does not exist."
                )

            # Use pages_dir from app
            console.print(
                f"[bold cyan]PyWire[/]: Watching [bold]{pages_dir}[/] for changes..."
            )

            # Also watch the file defining the app if possible?
            # app_str "main:app" -> main.py
            app_module_path = (
                Path(str(sys.modules[pywire_app.__module__].__file__))
                if hasattr(sys.modules.get(pywire_app.__module__), "__file__")
                else None
            )

            files_to_watch = [pages_dir, pywire_src_dir]
            if app_module_path:
                files_to_watch.append(app_module_path.parent)

            # Explicitly look for a components directory
            components_dir = pages_dir.parent / "components"
            if components_dir.exists():
                files_to_watch.append(components_dir)

            async for changes in awatch(*files_to_watch, stop_event=shutdown_event):
                # Check what changed
                library_changed = False
                app_config_changed = False

                for change_type, file_path in changes:
                    path_str = str(file_path)
                    if path_str.startswith(str(pywire_src_dir)):
                        library_changed = True
                    if app_module_path and path_str == str(app_module_path):
                        app_config_changed = True

                if library_changed or app_config_changed:
                    console.print(
                        "[bold magenta]PyWire[/]: Core/Config change detected. Please restart server manually."
                    )
                    # We can't easily auto-restart from within the process unless we wrap it
                    # But the TUI can handle restarts.

                # First, recompile changed pages
                should_reload = False
                for change_type, file_path in changes:
                    if file_path.endswith(".wire"):
                        should_reload = True
                        if hasattr(pywire_app, "reload_page"):
                            try:
                                pywire_app.reload_page(Path(file_path))
                            except Exception as e:
                                console.print(f"[bold red]Error[/] reloading page: {e}")

                # Then broadcast reload if needed
                if should_reload:
                    console.print(
                        f"[bold green]PyWire[/]: Changes detected in {pages_dir}, reloading clients..."
                    )

                    # Broadcast reload to WebSocket clients
                    if hasattr(pywire_app, "ws_handler"):
                        await pywire_app.ws_handler.broadcast_reload()

                    # Broadcast reload to HTTP polling clients
                    if hasattr(pywire_app, "http_handler"):
                        pywire_app.http_handler.broadcast_reload()

                    # Broadcast to WebTransport clients
                    if hasattr(pywire_app, "web_transport_handler"):
                        await pywire_app.web_transport_handler.broadcast_reload()

        except Exception as e:
            if not shutdown_event.is_set():
                console.print(f"Watcher error: {e}")
                import traceback

                traceback.print_exc()

    # Certificate Discovery
    # We do this for both Hypercorn (HTTP/3) and Uvicorn (HTTPS) to support local SSL
    cert_path, key_path = ssl_certfile, ssl_keyfile

    # Ensure .pywire/ exists for dev artifacts
    from pywire.compiler.paths import ensure_pywire_folder

    dot_pywire = ensure_pywire_folder()

    if not cert_path or not key_path:
        # Check for existing trusted certificates (e.g. from mkcert) in .pywire or root
        potential_certs = [
            (dot_pywire / "localhost.pem", dot_pywire / "localhost-key.pem"),
            (Path("localhost+2.pem"), Path("localhost+2-key.pem")),
            (Path("localhost.pem"), Path("localhost-key.pem")),
            (Path("cert.pem"), Path("key.pem")),
        ]

        found = False
        for c_file, k_file in potential_certs:
            if c_file.exists() and k_file.exists():
                console.print(
                    f"[bold cyan]PyWire[/]: Found local certificates ([bold]{c_file.name}[/]), using them."
                )
                cert_path = str(c_file)
                key_path = str(k_file)
                # Don't inject hash if using trusted certs
                if hasattr(pywire_app.app.state, "webtransport_cert_hash"):
                    del pywire_app.app.state.webtransport_cert_hash
                found = True
                break

        # If not found, try to generate using mkcert if available
        if not found:
            import shutil
            import subprocess

            if shutil.which("mkcert"):
                console.print(
                    "[bold cyan]PyWire[/]: 'mkcert' detected. Generating trusted local certificates..."
                )
                try:
                    # Generate certs in .pywire directory
                    pem_file = dot_pywire / "localhost.pem"
                    key_file = dot_pywire / "localhost-key.pem"

                    subprocess.run(
                        [
                            "mkcert",
                            "-key-file",
                            str(key_file),
                            "-cert-file",
                            str(pem_file),
                            "localhost",
                            "127.0.0.1",
                            "::1",
                        ],
                        check=True,
                        capture_output=True,  # Don't spam stdout unless error?
                    )
                    console.print(
                        f"[bold cyan]PyWire[/]: Certificates generated ({pem_file.name})."
                    )
                    console.print(
                        "[bold cyan]PyWire[/]: Note: Run 'mkcert -install' once if your browser doesn't "
                        "trust the certificate."
                    )

                    cert_path = str(pem_file)
                    key_path = str(key_file)

                    # Cleare hash injection since we expect trust
                    if hasattr(pywire_app.app.state, "webtransport_cert_hash"):
                        del pywire_app.app.state.webtransport_cert_hash

                except subprocess.CalledProcessError as e:
                    console.print(f"[bold red]PyWire Error[/]: mkcert failed: {e}")
            else:
                # No mkcert, will fallback to ephemeral logic downstream
                console.print(
                    "[bold yellow]PyWire Tip[/]: Install 'mkcert' for trusted local HTTPS "
                    "(e.g. 'brew install mkcert')."
                )
                console.print(
                    "[bold yellow]PyWire Warning[/]: Using ephemeral self-signed certificates (browser will warn)."
                )

    async with asyncio.TaskGroup() as tg:
        if has_http3:
            try:
                # If still no certs, generate ephemeral ones for WebTransport
                final_cert, final_key = cert_path, key_path
                if not final_cert:
                    final_cert, final_key, fingerprint = _generate_cert()
                    pywire_app.app.state.webtransport_cert_hash = fingerprint

                config = Config()
                config.loglevel = "INFO"

                # Bind dual-stack (IPv4 + IPv6) for localhost
                if host in ["127.0.0.1", "localhost"]:
                    config.bind = [f"127.0.0.1:{port}", f"[::1]:{port}"]
                    config.quic_bind = [f"127.0.0.1:{port}", f"[::1]:{port}"]
                else:
                    config.bind = [f"{host}:{port}"]
                    config.quic_bind = [f"{host}:{port}"]

                config.certfile = final_cert
                config.keyfile = final_key
                config.use_reloader = False

                display_host = "localhost" if host == "127.0.0.1" else host
                console.print(
                    f"[bold cyan]PyWire[/]: Running on [bold cyan]https://{display_host}:{port}[/] (HTTP/3 + WebSocket)"
                )

                # Serve the starlette app wrapped in PyWire
                tg.create_task(
                    serve(pywire_app.app, config, shutdown_trigger=shutdown_event.wait)
                )
            except Exception as e:
                console.print(
                    f"[bold red]PyWire Error[/]: Failed to start Hypercorn: {e}"
                )
                import traceback

                traceback.print_exc()
                console.print(
                    "[bold yellow]PyWire[/]: Falling back to Uvicorn (HTTP/2 + WebSocket only)"
                )
                has_http3 = False

        if not has_http3:
            # Fallback to Uvicorn
            import uvicorn

            # If explicit SSL provided OR discovered
            ssl_options = {}
            if cert_path and key_path:
                ssl_options["ssl_certfile"] = cert_path
                ssl_options["ssl_keyfile"] = key_path

            uv_config = uvicorn.Config(
                pywire_app.app,
                host=host,
                port=port,
                reload=False,
                log_level="info",
                use_colors=True,  # Force colors for TUI
                **ssl_options,  # type: ignore
            )
            server = uvicorn.Server(uv_config)

            # Disable Uvicorn's signal handlers so we can manage it
            server.install_signal_handlers = lambda: None  # type: ignore

            async def stop_uvicorn() -> None:
                await shutdown_event.wait()
                server.should_exit = True

            protocol = "https" if cert_path else "http"
            console.print(
                f"[bold cyan]PyWire[/]: Running on [bold cyan]{protocol}://{host}:{port}[/]"
            )
            tg.create_task(server.serve())
            tg.create_task(stop_uvicorn())

        # Start watcher
        tg.create_task(watch_changes())
