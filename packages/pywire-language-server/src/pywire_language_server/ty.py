from importlib.util import find_spec
import json
import logging
import os
import subprocess
import threading
from asyncio import AbstractEventLoop
from typing import Any, Callable, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


class TyClient:
    """
    A simple JSON-RPC client to communicate with a ty subprocess.
    """

    def __init__(self):
        self.process: Optional[subprocess.Popen] = None
        self._response_callbacks: Dict[
            int, Tuple[AbstractEventLoop, Callable[[Any, Optional[Any]], None]]
        ] = {}
        self._request_id = 0
        self._lock = threading.Lock()
        self.running = False
        self._diagnostics_callback: Optional[Callable[[Dict[str, Any]], None]] = None

    def set_diagnostics_callback(
        self, callback: Callable[[Dict[str, Any]], None]
    ) -> None:
        self._diagnostics_callback = callback

    def start(self, ty_path: Optional[str] = None) -> bool:
        """Start the ty server process."""
        try:
            cmd = self._build_ty_command(ty_path)
            if not cmd:
                logger.warning("ty binary not found in PATH or provided path.")
                return False

            logger.info(f"Starting Ty: {cmd}")
            # Ty runs as a standalone binary, no special env vars needed
            env = os.environ.copy()
            
            self.process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
                env=env,
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
            logger.warning("ty binary not found.")
            return False
        except Exception as e:
            logger.error(f"Failed to start ty: {e}")
            return False

    def _build_ty_command(self, ty_path: Optional[str] = None) -> Optional[list]:
        """Build command to start ty server."""
        executable = ty_path or self._find_ty_executable()
        if executable:
            return [executable, "server"]
        return None

    def _find_ty_executable(self) -> Optional[str]:
        import shutil
        
        # 1. PATH
        path_exe = shutil.which("ty")
        if path_exe:
            return path_exe

        # 2. Check for bundled binary? (Implement later if needed)
        
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
                    future.set_exception(Exception(f"Ty Error: {error}"))
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
            # logger.debug(f"Sending to Ty: {content[:200]}...")
            self.process.stdin.write(body_bytes)
            self.process.stdin.flush()
        except BrokenPipeError:
            logger.error("Ty process died")
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
                logger.info("Ty stdout closed")
                break

            line_str = line.decode("utf-8", errors="ignore").strip()
            line_str = line.decode("utf-8", errors="ignore").strip()
            # LOG RAW HEADER for debugging
            logger.info(f"[Ty RAW HEADER] {line_str}")

            if line_str.startswith("Content-Length:"):
                try:
                    length = int(line_str.split(":")[1].strip())
                    # Skip empty line
                    self.process.stdout.readline()

                    # Read body exactly
                    body = self._read_exact(length)
                    if body:
                        self._handle_message(body)
                except Exception as e:
                    logger.error(f"Error parsing ty message: {e}")

    def _read_exact(self, length: int) -> Optional[bytes]:
        """Read exactly n bytes from stdout."""
        if not self.process or not self.process.stdout:
            return None
            
        chunks = []
        bytes_read = 0
        while bytes_read < length:
            chunk = self.process.stdout.read(min(length - bytes_read, 65536))
            if not chunk:
                return None  # EOF
            chunks.append(chunk)
            bytes_read += len(chunk)
        return b"".join(chunks)

    def _read_stderr(self):
        if not self.process or not self.process.stderr:
            return
        for line in self.process.stderr:
            logger.info(f"[Ty STDERR] {line.decode('utf-8').strip()}")

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

            # Check if it's a Request from Ty (has 'id' AND 'method')
            if "id" in msg and "method" in msg:
                self._handle_incoming_request(msg)
                return

            # Handle notifications (NO 'id', has 'method')
            if "method" in msg:
                if msg["method"] == "textDocument/publishDiagnostics":
                    if self._diagnostics_callback:
                        params = msg.get("params") or {}
                        try:
                            logger.info(f"[Ty Diagnostics Received] Params: {json.dumps(params)}")
                            self._diagnostics_callback(params)
                        except Exception as e:
                            logger.error(f"Diagnostics callback failed: {e}")
                    return
                if msg["method"] == "window/logMessage":
                    params = msg.get("params", {})
                    message = params.get("message", "")
                    logger.info(f"[Ty] {message}")

        except Exception as e:
            logger.error(f"Failed to handle message: {e}")

    def _handle_incoming_request(self, msg: Dict[str, Any]):
        """Handle requests initiated by Ty process."""
        method = msg.get("method")
        req_id = msg.get("id")
        params = msg.get("params") or {}

        logger.info(f"[Ty Request] {method} id={req_id}")

        if method == "workspace/configuration":
            # Ty is asking for configuration
            items = params.get("items", [])
            result = [None] * len(items)

            response = {"jsonrpc": "2.0", "id": req_id, "result": result}
            self._send(response)
        elif method == "client/registerCapability":
            # Just acknowledge
            response = {"jsonrpc": "2.0", "id": req_id, "result": None}
            self._send(response)
        else:
            logger.warning(f"Unhandled Ty request: {method}")
            # Reply with MethodNotFound
            response = {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": "Method not found"},
            }
            self._send(response)
