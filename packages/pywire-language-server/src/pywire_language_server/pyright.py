import json
import logging
import os
import subprocess
import threading
from asyncio import AbstractEventLoop
from typing import Any, Callable, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


class PyrightClient:
    """
    A simple JSON-RPC client to communicate with a pyright-langserver subprocess.
    """

    def __init__(self):
        self.process: Optional[subprocess.Popen] = None
        self._response_callbacks: Dict[
            int, Tuple[AbstractEventLoop, Callable[[Any, Optional[Any]], None]]
        ] = {}
        self._request_id = 0
        self._lock = threading.Lock()
        self.running = False

    def start(self) -> bool:
        """Start the pyright-langserver process."""
        try:
            executable = self._find_pyright_executable()
            if not executable:
                logger.warning("pyright-langserver not found in PATH or venv.")
                return False

            cmd = [executable, "--stdio"]

            logger.info(f"Starting Pyright: {cmd}")
            self.process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,  # Capture stderr to avoid polluting our log?
                bufsize=0,
            )

            self.running = True

            # Start reader thread
            self._reader_thread = threading.Thread(target=self._read_loop, daemon=True)
            self._reader_thread.start()

            # Start stderr reader (optional, for debugging)
            self._stderr_thread = threading.Thread(
                target=self._read_stderr, daemon=True
            )
            self._stderr_thread.start()

            return True

        except FileNotFoundError:
            logger.warning("pyright-langserver not found. Fallback mode disabled.")
            return False
        except Exception as e:
            logger.error(f"Failed to start pyright: {e}")
            return False

    def _find_pyright_executable(self) -> Optional[str]:
        import shutil
        import sys

        # 1. PATH
        path_exe = shutil.which("pyright-langserver")
        if path_exe:
            return path_exe

        # 2. Virtual Env (sys.prefix) - typical venv structure
        # Unix
        venv_exe = os.path.join(sys.prefix, "bin", "pyright-langserver")
        if os.path.exists(venv_exe):
            return venv_exe

        # Windows
        venv_exe_win = os.path.join(sys.prefix, "Scripts", "pyright-langserver.exe")
        if os.path.exists(venv_exe_win):
            return venv_exe_win

        # 3. Next to python executable (sometimes sys.prefix is different)
        # Unix
        py_dir = os.path.dirname(sys.executable)
        same_dir_exe = os.path.join(py_dir, "pyright-langserver")
        if os.path.exists(same_dir_exe):
            return same_dir_exe

        # Windows
        same_dir_exe_win = os.path.join(
            py_dir, "pyright-langserver.exe"
        )  # unlikely but possible
        if os.path.exists(same_dir_exe_win):
            return same_dir_exe_win

        # Scripts relative to executable
        scripts_exe = os.path.join(py_dir, "Scripts", "pyright-langserver.exe")
        if os.path.exists(scripts_exe):
            return scripts_exe

        # 4. Explicit Sibling Venv (Development Mode)
        # src/pywire_language_server/pyright.py -> src/ ../ .venv
        src_root = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )  # .../src
        project_root = os.path.dirname(src_root)  # .../pywire-language-server

        # Unix
        sibling_venv_exe = os.path.join(
            project_root, ".venv", "bin", "pyright-langserver"
        )
        if os.path.exists(sibling_venv_exe):
            return sibling_venv_exe

        # Windows
        sibling_venv_exe_win = os.path.join(
            project_root, ".venv", "Scripts", "pyright-langserver.exe"
        )
        if os.path.exists(sibling_venv_exe_win):
            return sibling_venv_exe_win

        return None

    def stop(self):
        self.running = False
        if self.process:
            try:
                self.process.terminate()
            except Exception:
                pass
            self.process = None

    def send_notification(self, method: str, params: Any):
        """Send a JSON-RPC notification (no ID)."""
        msg = {"jsonrpc": "2.0", "method": method, "params": params}
        self._send(msg)

    async def send_request(self, method: str, params: Any) -> Any:
        """Send a JSON-RPC request and wait for response."""
        import asyncio

        loop = asyncio.get_running_loop()
        future = loop.create_future()

        req_id = self._get_next_id()

        msg = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}

        def resolve_future(result, error=None):
            if not future.done():
                if error:
                    future.set_exception(Exception(f"Pyright Error: {error}"))
                else:
                    future.set_result(result)

        # Store the callback AND the loop so we can schedule it back
        with self._lock:
            self._response_callbacks[req_id] = (loop, resolve_future)

        self._send(msg)
        return await future

    def _get_next_id(self) -> int:
        with self._lock:
            self._request_id += 1
            return self._request_id

    def _send(self, msg: Dict[str, Any]):
        if not self.process or not self.process.stdin:
            return

        content = json.dumps(msg)
        content_bytes = content.encode("utf-8")
        body_bytes = (
            f"Content-Length: {len(content_bytes)}\r\n\r\n".encode("utf-8")
            + content_bytes
        )

        try:
            # logger.debug(f"Sending to Pyright: {content[:200]}...")
            self.process.stdin.write(body_bytes)
            self.process.stdin.flush()
        except BrokenPipeError:
            logger.error("Pyright process died")
            self.stop()

    def _read_loop(self):
        """Reads JSON-RPC messages from stdout."""
        if not self.process or not self.process.stdout:
            return

        while self.running and self.process:
            # Read headers
            # Basic HTTP-like parsing
            line = self.process.stdout.readline()
            if not line:
                logger.info("Pyright stdout closed")
                break

            line_str = line.decode("utf-8", errors="ignore").strip()
            logger.debug(f"[Pyright RAW] {line_str}")

            if line_str.startswith("Content-Length:"):
                try:
                    length = int(line_str.split(":")[1].strip())
                    # Skip empty line
                    self.process.stdout.readline()

                    # Read body
                    body = self.process.stdout.read(length)
                    logger.debug(f"[Pyright BODY] {body.decode('utf-8')[:200]}...")
                    self._handle_message(body)
                except Exception as e:
                    logger.error(f"Error parsing pyright message: {e}")

    def _read_stderr(self):
        if not self.process or not self.process.stderr:
            return
        for line in self.process.stderr:
            logger.info(f"[Pyright STDERR] {line.decode('utf-8').strip()}")

    def _handle_message(self, body: bytes):
        try:
            msg = json.loads(body)

            # Check if it's a Response to our request
            # Responses have 'id' but NO 'method'
            if "id" in msg and "method" not in msg:
                req_id = msg["id"]
                with self._lock:
                    callback_info = self._response_callbacks.pop(req_id, None)

                if callback_info:
                    loop, callback = callback_info
                    if "error" in msg:
                        loop.call_soon_threadsafe(callback, None, msg["error"])
                    else:
                        loop.call_soon_threadsafe(callback, msg.get("result"), None)
                return

            # Check if it's a Request from Pyright (has 'id' AND 'method')
            if "id" in msg and "method" in msg:
                self._handle_incoming_request(msg)
                return

            # Handle notifications (NO 'id', has 'method')
            if "method" in msg:
                if msg["method"] == "window/logMessage":
                    params = msg.get("params", {})
                    message = params.get("message", "")
                    logger.info(f"[Pyright] {message}")

        except Exception as e:
            logger.error(f"Failed to handle message: {e}")

    def _handle_incoming_request(self, msg: Dict[str, Any]):
        """Handle requests initiated by Pyright process."""
        method = msg.get("method")
        req_id = msg.get("id")
        params = msg.get("params") or {}

        logger.info(f"[Pyright Request] {method} id={req_id}")

        if method == "workspace/configuration":
            # Pyright is asking for configuration (e.g. python path)
            # We return a list of nulls to say "use defaults"
            # params['items'] is the list of config items requested
            items = params.get("items", [])
            result = [None] * len(items)

            response = {"jsonrpc": "2.0", "id": req_id, "result": result}
            self._send(response)
        elif method == "client/registerCapability":
            # Just acknowledge
            response = {"jsonrpc": "2.0", "id": req_id, "result": None}
            self._send(response)
        else:
            # Unknown request, reply with error?
            # Or just null to be safe
            logger.warning(f"Unhandled Pyright request: {method}")
            # Reply with MethodNotFound
            response = {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": "Method not found"},
            }
            self._send(response)
