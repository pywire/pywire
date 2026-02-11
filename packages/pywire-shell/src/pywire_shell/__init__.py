import threading
import ctypes
import uvicorn
from pywire_shell._loader import load_runtime

class App:
    def __init__(self, title="PyWire App", width=800, height=600, url=None, pywire_app=None, on_event=None):
        self.title = title
        self.width = width
        self.height = height
        self.url = url
        self.pywire_app = pywire_app
        self.on_event = on_event
        self._runtime = None
        self._server_thread = None
        self._port = 17181 # Let's use a nice custom port

    def execute_javascript(self, script: str):
        """Execute a string of JavaScript in the webview."""
        if not self._runtime:
            raise RuntimeError("App not started")
        return self._runtime.pw_execute_javascript(script.encode("utf-8"))

    def set_title(self, title: str):
        """Update the window title."""
        if not self._runtime:
            self.title = title
            return
        return self._runtime.pw_set_title(title.encode("utf-8"))

    def resize(self, width: int, height: int):
        """Resize the window."""
        if not self._runtime:
            self.width = width
            self.height = height
            return
        return self._runtime.pw_resize_window(width, height)

    def _on_shell_event(self, payload_ptr):
        """Callback from native shell when an event occurs in JS."""
        payload = ctypes.string_at(payload_ptr).decode("utf-8")
        print(f"[pywire-shell] Received event: {payload}")
        if self.on_event:
            self.on_event(payload)

    def start(self):
        """Load the native runtime and open the window. Blocks until close."""
        self._runtime = load_runtime()
        
        # If pywire_app is provided, start the server thread
        if self.pywire_app:
            # Inject shell into PyWire app state for local-first access
            self.pywire_app.app.state.shell = self
            
            def run_server():
                print(f"[pywire-shell] Starting PyWire runtime server on http://localhost:{self._port}")
                uvicorn.run(self.pywire_app.app, host="127.0.0.1", port=self._port, log_level="error")
            
            self._server_thread = threading.Thread(target=run_server, daemon=True)
            self._server_thread.start()
            self.url = f"http://127.0.0.1:{self._port}"

        # Define InitParams struct locally for ctypes
        from ctypes import Structure, c_char_p, c_uint32, c_int32, c_void_p, CFUNCTYPE
        
        EVENT_CALLBACK = CFUNCTYPE(None, c_char_p)
        self._on_event_cb = EVENT_CALLBACK(self._on_shell_event)
        
        class InitParams(Structure):
            _fields_ = [
                ("title", c_char_p),
                ("url", c_char_p),
                ("width", c_uint32),
                ("height", c_int32),
                ("on_event", c_void_p),
            ]
        
        params = InitParams(
            title=self.title.encode("utf-8"),
            url=self.url.encode("utf-8") if self.url else None,
            width=self.width,
            height=self.height,
            on_event=ctypes.cast(self._on_event_cb, c_void_p)
        )
        
        print(f"[pywire-shell] Starting window: {self.title} ({self.width}x{self.height})")
        result = self._runtime.pw_start_app(params)
        if result != 0:
            print(f"[pywire-shell] Error: pw_start_app returned {result}")
        else:
            print("[pywire-shell] Window closed successfully")
