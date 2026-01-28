"""Development server with hot reload."""

import os
import sys
from pathlib import Path
from typing import Any, Optional, Tuple


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

    from cryptography import x509  # type: ignore
    from cryptography.hazmat.primitives import hashes, serialization  # type: ignore
    from cryptography.hazmat.primitives.asymmetric import ec  # type: ignore
    from cryptography.x509.oid import NameOID  # type: ignore

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

    # Configure logging to see Hypercorn/aioquic debug output
    logging.basicConfig(level=logging.INFO)  # Reduced from DEBUG to avoid spam
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
        print(f"Warning: Pages directory '{pages_dir}' does not exist.")

    # Try to import Hypercorn for HTTP/3 support
    try:
        from hypercorn.asyncio import serve  # type: ignore
        from hypercorn.config import Config  # type: ignore

        has_http3 = True
    except ImportError:
        has_http3 = False

    # DEBUG: Force disable HTTP/3 to avoid Hypercorn/aioquic crash (KeyError: 9) on form uploads
    print("DEBUG: Forcing HTTP/3 disabled for stress testing form uploads.")
    has_http3 = False
    if not has_http3:
        print(
            "PyWire: HTTP/3 (WebTransport) disabled. Install 'aioquic' and 'hypercorn' to enable."
        )

    # Create shutdown event
    shutdown_event = asyncio.Event()

    async def _handle_signal() -> None:
        print("\nPyWire: Shutting down...")
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

            # Use pages_dir from app
            print(f"PyWire: Watching {pages_dir} for changes...")

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
            # Common pattern: pages/../components OR pages/components??
            # Usually components are siblings to pages or in root.
            # Start with pages_dir parent
            components_dir = pages_dir.parent / "components"
            if components_dir.exists():
                files_to_watch.append(components_dir)

            print(f"PyWire: files_to_watch: {files_to_watch}")

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
                    print("PyWire: Core/Config change detected. Please restart server manually.")

                # First, recompile changed pages
                should_reload = False
                for change_type, file_path in changes:
                    if file_path.endswith(".pywire"):
                        should_reload = True
                        # Reload logic needs access to the *current* running app instance
                        # We have pywire_app
                        if hasattr(pywire_app, "reload_page"):
                            try:
                                pywire_app.reload_page(Path(file_path))
                            except Exception as e:
                                print(f"Error reloading page: {e}")

                # Then broadcast reload if needed
                if should_reload:
                    print(f"PyWire: Changes detected in {pages_dir}, reloading clients...")

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
                print(f"Watcher error: {e}")
                import traceback

                traceback.print_exc()

    # Certificate Discovery
    # We do this for both Hypercorn (HTTP/3) and Uvicorn (HTTPS) to support local SSL
    cert_path, key_path = ssl_certfile, ssl_keyfile

    if not cert_path or not key_path:
        # Check for existing trusted certificates (e.g. from mkcert)
        potential_certs = [
            (Path("localhost+2.pem"), Path("localhost+2-key.pem")),
            (Path("localhost.pem"), Path("localhost-key.pem")),
            (Path("cert.pem"), Path("key.pem")),
        ]

        found = False
        for c_file, k_file in potential_certs:
            if c_file.exists() and k_file.exists():
                print(f"PyWire: Found local certificates ({c_file}), using them.")
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
                print("PyWire: 'mkcert' detected. Generating trusted local certificates...")
                try:
                    # Generate certs in current directory (standard matching default checks)
                    # We check localhost.pem first
                    subprocess.run(
                        [
                            "mkcert",
                            "-key-file",
                            "localhost-key.pem",
                            "-cert-file",
                            "localhost.pem",
                            "localhost",
                            "127.0.0.1",
                            "::1",
                        ],
                        check=True,
                        capture_output=True,  # Don't spam stdout unless error?
                    )
                    print("PyWire: Certificates generated (localhost.pem).")
                    print(
                        "PyWire: Note: Run 'mkcert -install' once if your browser doesn't "
                        "trust the certificate."
                    )

                    cert_path = "localhost.pem"
                    key_path = "localhost-key.pem"
                    # Cleare hash injection since we expect trust
                    if hasattr(pywire_app.app.state, "webtransport_cert_hash"):
                        del pywire_app.app.state.webtransport_cert_hash

                except subprocess.CalledProcessError as e:
                    print(f"PyWire: mkcert failed: {e}")
                    # Fallback to ephemeral
            else:
                # No mkcert, will fallback to ephemeral logic downstream
                print(
                    "PyWire: Tip: Install 'mkcert' for trusted local HTTPS "
                    "(e.g. 'brew install mkcert')."
                )
                print("PyWire: Using ephemeral self-signed certificates (browser will warn).")

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
                print(
                    f"PyWire: Running with Hypercorn (HTTP/3 + WebSocket) on https://{display_host}:{port}"
                )

                # Serve the starlette app wrapped in PyWire
                tg.create_task(serve(pywire_app.app, config, shutdown_trigger=shutdown_event.wait))
            except Exception as e:
                print(f"PyWire: Failed to start Hypercorn: {e}")
                import traceback

                traceback.print_exc()
                print("PyWire: Falling back to Uvicorn (HTTP/2 + WebSocket only)")
                has_http3 = False

        if not has_http3:
            # Fallback to Uvicorn
            import uvicorn

            # If explicit SSL provided OR discovered
            ssl_options = {}
            if cert_path and key_path:
                ssl_options["ssl_certfile"] = cert_path
                ssl_options["ssl_keyfile"] = key_path

            config = uvicorn.Config(
                pywire_app.app,
                host=host,
                port=port,
                reload=False,
                log_level="info",
                **ssl_options,  # type: ignore
            )
            server = uvicorn.Server(config)

            # Disable Uvicorn's signal handlers so we can manage it
            # Disable Uvicorn's signal handlers so we can manage it
            server.install_signal_handlers = lambda: None  # type: ignore

            async def stop_uvicorn() -> None:
                await shutdown_event.wait()
                server.should_exit = True

            protocol = "https" if cert_path else "http"
            print(f"PyWire: Running with Uvicorn on {protocol}://{host}:{port}")
            tg.create_task(server.serve())
            tg.create_task(stop_uvicorn())

        # Start watcher
        tg.create_task(watch_changes())
