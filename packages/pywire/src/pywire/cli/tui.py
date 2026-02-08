import asyncio
import sys
import time
from textual.app import App, ComposeResult
from textual.coordinate import Coordinate
from textual.widgets import Header, Footer, Label, DataTable
from textual.binding import Binding
from rich.text import Text
import shutil
import subprocess
from textual import events
from typing import cast, TYPE_CHECKING

if TYPE_CHECKING:
    # Use forward references for types defined in this file
    pass


class LogTable(DataTable):
    async def on_mouse_down(self, event: events.MouseDown) -> None:
        if self.app and hasattr(self.app, "handle_log_mouse_down"):
            try:
                coord = Coordinate(event.offset.x, event.offset.y)
                meta = self.get_cell_at(coord)
                if meta:
                    row_key = self.coordinate_to_cell_key(meta).row_key
                    if row_key and row_key.value:
                        app = cast("PyWireDevDashboard", self.app)
                        if app.handle_log_mouse_down(row_key.value, shift=event.shift):
                            self.capture_mouse()
                            self._mouse_captured = True
            except Exception:
                pass

    async def on_mouse_move(self, event: events.MouseMove) -> None:
        if (
            getattr(self, "_mouse_captured", False)
            and self.app
            and hasattr(self.app, "handle_log_mouse_move")
        ):
            try:
                coord = Coordinate(event.offset.x, event.offset.y)
                meta = self.get_cell_at(coord)
                if meta:
                    row_key = self.coordinate_to_cell_key(meta).row_key
                    if row_key and row_key.value:
                        app = cast("PyWireDevDashboard", self.app)
                        app.handle_log_mouse_move(row_key.value)
            except Exception:
                pass

    async def on_mouse_up(self, event: events.MouseUp) -> None:
        if getattr(self, "_mouse_captured", False):
            self.release_mouse()
            self._mouse_captured = False

    def on_click(self, event: events.Click) -> None:
        # We handle click logic mostly in mouse_down for drag start,
        # but simple toggle/click might need to be resolved here if not dragging?
        # Actually, mouse_down starts a potential drag.
        # If we release on same cell without moving much, it's a click.
        # But we can just use mouse_down to "start selection" (select 1 cell).
        # And mouse_move to "extend".
        # So on_click is less needed if we handle mouse_down?
        # But super().on_click handles row cursor activation.
        # We'll pass through.
        # super().on_click(event) - AttributeError: 'super' object has no attribute 'on_click'
        pass


class PyWireDevDashboard(App):
    CSS = """
    Screen { layout: vertical; }
    DataTable { width: 100%; height: 1fr; border: solid $accent; }
    DataTable > .datatable--cursor { background: $accent 20%; }
    DataTable > .datatable--header { display: none; }
    #header-info { dock: top; height: 1; content-align: center middle; background: $primary; color: $text; }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "restart_server", "Restart Server"),
        Binding("c", "clear_logs", "Clear Logs"),
        Binding("l", "toggle_log_level", "Toggle Log Level"),
        Binding("y", "copy_logs", "Copy Logs (Clipboard)"),
        Binding("space", "toggle_selection", "Select/Deselect Line"),
        Binding("enter", "toggle_selection", "Select/Deselect Line"),
        Binding("escape", "deselect_all", "Deselect All"),
    ]

    def __init__(self, command: list[str], host: str, port: int):
        super().__init__()
        self.command = command
        self.host = host
        self.port = port
        self.server_process: asyncio.subprocess.Process | None = None
        self.start_time = time.time()
        # User requested: Debug -> Info -> Warning -> Error, starting at Info
        self.log_levels = ["DEBUG", "INFO", "WARNING", "ERROR"]
        self.current_log_level_index = 1  # Start at INFO
        self._log_store: list[tuple[Text, int]] = []
        self._selected_indices: set[int] = set()
        self._last_selected_index: int | None = None
        self._drag_start_index: int | None = None
        self._is_dragging: bool = False

    @property
    def current_log_level(self) -> str:
        return self.log_levels[self.current_log_level_index]

    def compose(self) -> ComposeResult:
        self.title = "pywire Dev Dashboard"
        yield Header(show_clock=False)
        yield Label(
            f"Server: http://{self.host}:{self.port} | Uptime: 00:00:00",
            id="header-info",
        )

        # Using DataTable for selectable log rows
        # Using LogTable for selectable log rows (supports shift+click)
        table = LogTable(id="log-window", cursor_type="row", zebra_stripes=False)
        table.add_column("Log", key="log")
        yield table

        yield Footer()

    async def on_mount(self) -> None:
        """Start the server when the TUI loads."""
        protocol = "https" if "--ssl-keyfile" in self.command else "http"
        self.log_write(
            f"[bold yellow]Initializing pywire Server on {protocol}://{self.host}:{self.port}...[/]",
            level=20,
        )

        # Start server task
        self.server_task = asyncio.create_task(self.run_server())
        self.set_interval(1, self.update_uptime)

    async def on_unmount(self) -> None:
        """Ensure server subprocess is killed when TUI exits."""
        # Cancel the server loop task
        if hasattr(self, "server_task"):
            self.server_task.cancel()
            try:
                await self.server_task
            except asyncio.CancelledError:
                pass

        if self.server_process and self.server_process.returncode is None:
            try:
                self.server_process.terminate()
                # Give it 1 second to die gracefully
                try:
                    await asyncio.wait_for(self.server_process.wait(), timeout=1.0)
                except asyncio.TimeoutError:
                    self.server_process.kill()
                    await self.server_process.wait()
            except ProcessLookupError:
                pass
            except Exception:
                try:
                    self.server_process.kill()
                except Exception:
                    pass

    def update_uptime(self) -> None:
        uptime_seconds = int(time.time() - self.start_time)
        hours, remainder = divmod(uptime_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        uptime_str = f"{hours:02}:{minutes:02}:{seconds:02}"

        protocol = "https" if "--ssl-keyfile" in self.command else "http"

        header_info = self.query_one("#header-info", Label)
        header_info.update(
            f"Server: {protocol}://{self.host}:{self.port} | Uptime: {uptime_str} | Log Level: {self.current_log_level}"
        )

    def log_write(self, message: str | Text, level: int = 20) -> None:
        """Writes a message to the internal log store and updates the widget if visible."""
        if isinstance(message, str):
            text = Text.from_markup(message)
        else:
            text = message

        entry = (text, level)
        self._log_store.append(entry)

        level_map = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40}
        current_threshold = level_map.get(self.current_log_level, 20)

        if level >= current_threshold:
            self._add_log_to_table(text, len(self._log_store) - 1)

    def _add_log_to_table(self, text: Text, store_index: int):
        """Helper to add a row to the table safely."""
        try:
            table = self.query_one("#log-window", DataTable)

            # Check if this index is selected
            if store_index in self._selected_indices:
                # User requested NO caret, just highlight
                display_text = text
                # Use a specific high-contrast style for selection
                display_text.style = "bold white on $secondary"
            else:
                display_text = text

            table.add_row(display_text, key=str(store_index))

            # Auto-scroll to bottom
            table.move_cursor(row=table.row_count - 1, animate=False)
        except Exception:
            # Widget might be unmounted or not found
            pass

    def refresh_log_view(self):
        """Clears and repopulates the log window based on current filter."""
        try:
            table = self.query_one("#log-window", DataTable)
            table.clear()

            level_map = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40}
            current_threshold = level_map.get(self.current_log_level, 20)

            for idx, (text, level) in enumerate(self._log_store):
                # Always show system messages (level >= 100) or if meets threshold
                if level >= 100 or level >= current_threshold:
                    self._add_log_to_table(text, idx)

        except Exception:
            pass

    def _update_row_appearance(self, store_index: int):
        """Updates the appearance of a single row based on selection state."""
        try:
            table = self.query_one("#log-window", DataTable)
            if 0 <= store_index < len(self._log_store):
                text, _ = self._log_store[store_index]
                if store_index in self._selected_indices:
                    # User requested NO caret, just highlight
                    display_text = text
                    display_text.stylize("bold white on $secondary")
                else:
                    display_text = text

                # We need the key as string
                table.update_cell(str(store_index), "log", display_text)
        except Exception:
            pass

    def handle_log_mouse_down(self, store_index_str: str, shift: bool = False) -> bool:
        """Handle mouse down: toggle single or start range."""
        try:
            store_index = int(store_index_str)
        except ValueError:
            return False

        if shift and self._last_selected_index is not None:
            # Shift+Click (immediate range)
            # Clear purely if we want standard behavior?
            # Or add to selection?
            # Standard: Select range from anchor to here.
            # We clear current explicit selection if it's a new range?
            # User said: "shift click to select a range".
            # Usually implies resetting selection to just that range?
            # Or extending?
            # Let's say: Reset others, select range.
            self.action_deselect_all_silent()

            start = min(self._last_selected_index, store_index)
            end = max(self._last_selected_index, store_index)
            for i in range(start, end + 1):
                self._selected_indices.add(i)

            # Don't update last_selected_index on shift-click usually, or do?
            # Usually Shift+Click preserves anchor.
            # We keep _last_selected_index as anchor.
        else:
            # Regular Click/Drag Start
            # If simple click: Toggle? Or select exclusive?
            # User liked "clicking added/removed" (Toggle).
            # We will toggle.
            if store_index in self._selected_indices:
                self._selected_indices.remove(store_index)
            else:
                self._selected_indices.add(store_index)

            self._last_selected_index = store_index
            self._drag_start_index = store_index  # Anchor for drag

        self.refresh_visible_rows()
        return True  # Capture mouse

    def handle_log_mouse_move(self, store_index_str: str):
        """Handle drag: extend selection from drag anchor."""
        try:
            current_index = int(store_index_str)
        except ValueError:
            return

        if self._drag_start_index is not None:
            # Select range [start, current]
            # But wait, we want to toggle them? Or force select?
            # Drag usually force selects.
            # We should probably clear OTHER selections if we assume standard behavior?
            # But user likes toggle.
            # "Click + Drag" usually means: Select everything in dragged range.
            # We'll validly set everything in range to selected.

            start = min(self._drag_start_index, current_index)
            end = max(self._drag_start_index, current_index)

            # Optimization: only update what changed?
            # For now, just add loop.
            for i in range(start, end + 1):
                self._selected_indices.add(i)

            self._last_selected_index = current_index
            self.refresh_visible_rows()

    def action_deselect_all_silent(self):
        """Deselect without refresh (internal)."""
        self._selected_indices.clear()

    def refresh_visible_rows(self):
        """Efficiently update appearance of rows."""
        # This is expensive if we do ALL.
        # But we only need to update visible or changed?
        # For simplicity, we loop log store for now, or just trust reactive updates?
        # We need to manually call _update_row_appearance.
        # Instead of updating ALL (expensive), we should track what we acted on.
        # But for 'deselect all' we need to update all old ones.

        # We'll just force refresh of current view - or just update rows that CHANGED?
        # That requires diffing.
        # Let's iterate all valid indices in table?
        # We can iterate self._log_store and update.
        # We'll accept O(N) for now (~1000 lines is fine, 100k is slow).
        # We can optimize later.

        # Actually, iterating 0 to len(_log_store) and calling update_cell on every mouse move is BAD.
        # We should optimize handle_log_mouse_move to only update specific rows.
        # But for now, we leave it to be safe on logic.

        # Better: _update_row_appearance only calls update_cell.
        # We can just iterate visible range?
        try:
            # Just iterate all simple for correctness first.
            for i in range(len(self._log_store)):
                self._update_row_appearance(i)
        except Exception:
            pass

    def action_toggle_log_level(self):
        self.current_log_level_index = (self.current_log_level_index + 1) % len(
            self.log_levels
        )
        self.update_uptime()  # Update header
        self.refresh_log_view()

    def action_toggle_selection(self):
        """Toggle selection of the current row."""
        try:
            table = self.query_one("#log-window", DataTable)
            cursor_row = table.cursor_row
            if cursor_row is None:
                return

            row_key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key
            if row_key.value is None:
                return
            store_index = int(row_key.value)

            if store_index in self._selected_indices:
                self._selected_indices.remove(store_index)
            else:
                self._selected_indices.add(store_index)

            self._last_selected_index = store_index
            self._update_row_appearance(store_index)

        except Exception:
            pass

    def action_deselect_all(self):
        """Deselect all rows."""
        old_indices = list(self._selected_indices)
        self._selected_indices.clear()
        self._last_selected_index = None
        for idx in old_indices:
            self._update_row_appearance(idx)

    async def run_server(self):
        """Runs the actual Uvicorn server as a subprocess."""
        self.server_process = await asyncio.create_subprocess_exec(
            *self.command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        async def read_stream(stream):
            while True:
                line = await stream.readline()
                if not line:
                    break
                text_content = line.decode().strip()

                if "Press CTRL+C to quit" in text_content:
                    text_content = text_content.replace(
                        "Press CTRL+C to quit", "Press q to quit"
                    )

                # Determine level
                level = 20  # Default INFO
                upper_text = text_content.upper()
                if "DEBUG" in upper_text:
                    level = 10
                elif "INFO" in upper_text:
                    level = 20
                elif "WARNING" in upper_text:
                    level = 30
                elif "ERROR" in upper_text:
                    level = 40

                # System/Always visible messages logic
                if "PyWire" in text_content:
                    if "Error" in text_content:
                        level = 40
                    elif "Warning" in text_content:
                        level = 30
                    else:
                        level = 20

                renderable = Text.from_ansi(text_content)
                self.log_write(renderable, level=level)

        if self.server_process.stdout and self.server_process.stderr:
            try:
                await asyncio.gather(
                    read_stream(self.server_process.stdout),
                    read_stream(self.server_process.stderr),
                )
            except asyncio.CancelledError:
                # Task cancelled (shutdown)
                pass

    async def action_restart_server(self):
        """Kill and restart the subprocess."""
        self.log_write("\n[bold magenta]↻ Restarting Server...[/]\n", level=100)

        if self.server_process:
            try:
                self.server_process.terminate()
                await self.server_process.wait()
            except ProcessLookupError:
                pass

        self.start_time = time.time()
        # Cancel old task?
        if hasattr(self, "server_task"):
            self.server_task.cancel()
        self.server_task = asyncio.create_task(self.run_server())

    def action_clear_logs(self):
        try:
            self.query_one("#log-window", DataTable).clear()
        except Exception:
            pass
        self._log_store = []
        self._selected_indices = set()
        self._last_selected_index = None

    def action_copy_logs(self):
        """Copy current log view to system clipboard."""
        lines = []

        # If selection exists, copy only selection
        if self._selected_indices:
            sorted_indices = sorted(self._selected_indices)
            for idx in sorted_indices:
                if 0 <= idx < len(self._log_store):
                    text_obj, _ = self._log_store[idx]
                    plain = text_obj.plain
                    # Exclude tips if needed? User said "Tip: ... to be part of output" (Don't want)
                    if "Tip: Use Space or Click" in plain:
                        continue
                    lines.append(plain)
        else:
            # Copy all visible logs
            level_map = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40}
            current_threshold = level_map.get(self.current_log_level, 20)
            for text_obj, level in self._log_store:
                # Level 100 are system messages. User said "don't want Copied n lines..."
                # Copied messages are level 100.
                # We should probably filters out "Copied ..." messages themselves?
                # Or just not store Copied messages in the log store?
                # Ah, log_write stores them.
                plain = text_obj.plain
                if "Copied" in plain and "lines" in plain and "clipboard" in plain:
                    continue
                if "Tip: Use Space or Click" in plain:
                    continue

                if level >= 100 or level >= current_threshold:
                    lines.append(plain)

        content = "\n".join(lines)

        copied = False
        try:
            if sys.platform == "darwin" and shutil.which("pbcopy"):
                subprocess.run("pbcopy", input=content, text=True)
                copied = True
            elif sys.platform.startswith("linux"):
                if shutil.which("wl-copy"):
                    subprocess.run("wl-copy", input=content, text=True)
                    copied = True
                elif shutil.which("xclip"):
                    subprocess.run(
                        ["xclip", "-selection", "clipboard"], input=content, text=True
                    )
                    copied = True
            elif sys.platform == "win32":
                subprocess.run("clip", input=content, text=True)
                copied = True
        except Exception as e:
            self.notify(f"Copy failed: {e}", severity="error")
            return

        if copied:
            self.notify(f"Copied {len(lines)} lines to clipboard!")
            # Deselect lines after copying
            self.action_deselect_all()
        else:
            self.notify("Clipboard tool not found.", severity="error")


def start_tui(
    app_path: str,
    host: str,
    port: int,
    ssl_keyfile: str | None,
    ssl_certfile: str | None,
    env_file: str | None,
) -> None:
    cmd = [
        sys.executable,
        "-m",
        "pywire.cli.main",
        "dev",
        app_path,
        "--no-tui",
        "--host",
        host,
        "--port",
        str(port),
    ]

    if ssl_keyfile:
        cmd.extend(["--ssl-keyfile", ssl_keyfile])
    if ssl_certfile:
        cmd.extend(["--ssl-certfile", ssl_certfile])
    if env_file:
        cmd.extend(["--env-file", env_file])

    app = PyWireDevDashboard(cmd, host, port)
    app.run()
