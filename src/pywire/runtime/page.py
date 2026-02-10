"""Base page class with lifecycle system."""

import inspect
from collections import defaultdict
from typing import (
    TYPE_CHECKING,
    Any,
    Awaitable,
    Callable,
    ClassVar,
    Dict,
    List,
    Optional,
    Set,
    Tuple,
    Union,
)
import asyncio

from starlette.requests import Request
from starlette.responses import Response

if TYPE_CHECKING:
    from pywire.runtime.router import URLHelper

from pywire.runtime.style_collector import StyleCollector


class DotDict(dict):
    """Dict that allows dot-access to keys. Returns None for missing keys."""

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError:
            return None

    def __setattr__(self, name: str, value: Any) -> None:
        self[name] = value


class EventData(dict):
    """Dict that allows dot-access to keys for Alpine.js compatibility."""

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError:
            # Check for camelCase version of name
            import re

            camel = re.sub(r"(?!^)_([a-z])", lambda x: x.group(1).upper(), name)
            if camel in self:
                return self[camel]
            return None

    def __setattr__(self, name: str, value: Any) -> None:
        self[name] = value


class BasePage:
    """Base class for all compiled pages."""

    # Layout ID (overridden by generator)
    LAYOUT_ID: Optional[str] = None
    __file_path__: ClassVar[str]

    # Lifecycle hooks registry (extensible!)
    INIT_HOOKS = [
        "on_before_load",
        "on_load",
    ]

    RENDER_HOOKS = [
        "on_after_render",
    ]

    # Legacy support / full list
    LIFECYCLE_HOOKS = INIT_HOOKS + RENDER_HOOKS

    def __init__(
        self,
        request: Request,
        params: Dict[str, str],
        query: Dict[str, str],
        path: Optional[Dict[str, bool]] = None,
        url: Optional["URLHelper"] = None,
        **kwargs: Any,
    ) -> None:
        self.request = request
        self.params = DotDict(params or {})  # URL params from route
        self.query = DotDict(query or {})  # Query string params
        self.path = DotDict(path or {})
        self.url = url

        # Style collector management
        # If passed from parent component (via kwargs), reuse it.
        # Otherwise create new one (root page).
        if "_style_collector" in kwargs:
            self._style_collector: StyleCollector = kwargs.pop("_style_collector")
        else:
            self._style_collector = StyleCollector()

        # Context inheritance for !provide/!inject
        # If passed from parent component, make a shallow copy for child-specific shadowing.
        # Otherwise create a new empty context (root page).
        if "_context" in kwargs:
            self.context = kwargs.pop("_context").copy()
        else:
            self.context = {}
        self.context: Dict[str, Any]

        self.user: Any = None  # Set by middleware

        # Expose params as attributes for easy access in templates
        for k, v in self.params.items():
            setattr(self, k, v)

        # Ensure path is exhaustive if __routes__ is present
        routes = getattr(self.__class__, "__routes__", {})
        if routes:
            for name in routes:
                if name not in self.path:
                    self.path[name] = False
        elif hasattr(self.__class__, "__route__") and "main" not in self.path:
            self.path["main"] = self.path.get("main", False)

        # Framework-managed state
        self.errors: Dict[str, str] = {}
        self.loading: Dict[str, bool] = {}

        # Slot registry: layout_id -> slot_name -> renderer (replacement semantics)
        self.slots: Dict[str, Dict[str, Union[Callable, str]]] = defaultdict(dict)

        # Populate slots from kwargs (for components)
        if "slots" in kwargs and self.LAYOUT_ID:
            self.slots[self.LAYOUT_ID].update(kwargs["slots"])

        # Component flag (internal)
        self.__is_component__ = kwargs.pop("__is_component__", False)

        # Store remaining kwargs as fallthrough attributes
        self.attrs = {k: v for k, v in kwargs.items() if k != "slots"}

        # Head slot registry: layout_id -> list of renderers (append semantics, top-down order)
        self.head_slots: Dict[str, List[Callable]] = defaultdict(list)

        # Async update hook for intermediate state (injected by runtime)
        self._on_update: Optional[Callable[[], Awaitable[None]]] = None
        self._wire_subscribers: Dict[Tuple[Any, str], Set[str]] = defaultdict(set)
        self._region_dependencies: Dict[str, Set[Tuple[Any, str]]] = defaultdict(set)
        self._dirty_regions: Set[str] = set()

        # Error state for error pages
        self.error_code: Optional[int] = None
        self.error_detail: Optional[str] = None
        self.error_trace: Optional[str] = None

        # Partial update static cache
        self._static_cache: Dict[str, Any] = {}
        self._expr_counts: Dict[str, int] = defaultdict(int)
        self._capturing_deps: bool = False
        self._captured_deps: Set[Tuple[Any, str]] = set()

        self._instance_id = id(self)
        self._instance_id = id(self)
        if self._is_debug:
            print(f"DEBUG: [{self._instance_id}] BasePage initialized")

        # Await block state: await_id -> {"status": "pending"|"success"|"error", "result": Any, "error": Any}

        # Await block state: await_id -> {"status": "pending"|"success"|"error", "result": Any, "error": Any}
        self._await_states: Dict[str, Dict[str, Any]] = {}
        self._background_tasks: Set["asyncio.Task[Any]"] = set()

        # Component ref support (groundwork)
        self._ref: Optional[Any] = None  # wire passed via ref={my_ref}
        self._exposed_methods: Set[str] = getattr(self, "__exposed_methods__", set())

    @property
    def _is_debug(self) -> bool:
        try:
            return getattr(self.request.app.state, "debug", False)
        except Exception:
            return False

    def register_slot(
        self, layout_id: str, slot_name: str, renderer: Callable[..., Any]
    ) -> None:
        """Register a content renderer for a slot in a specific layout."""
        self.slots[layout_id][slot_name] = renderer

    def register_head_slot(self, layout_id: str, renderer: Callable[..., Any]) -> None:
        """Register head content to be appended (top-down order)."""
        # Prevent duplicate registration (can happen with super()._init_slots() chaining)
        if renderer not in self.head_slots[layout_id]:
            self.head_slots[layout_id].append(renderer)

    async def render_slot(
        self,
        slot_name: str,
        default_renderer: Optional[Callable[..., Any]] = None,
        layout_id: Optional[str] = None,
        append: bool = False,
    ) -> str:
        """Render a slot for the current layout."""
        target_id = layout_id or self.LAYOUT_ID

        # Handle $head slots with append semantics
        if append:
            parts = []
            # Render default content first (from the layout itself)
            if default_renderer:
                if inspect.iscoroutinefunction(default_renderer):
                    parts.append(await default_renderer())
                else:
                    parts.append(default_renderer())

            # Collect head content from ALL layout IDs in the inheritance chain
            for layout_id_key in self.head_slots:
                for head_renderer in self.head_slots[layout_id_key]:
                    if inspect.iscoroutinefunction(head_renderer):
                        parts.append(await head_renderer())
                    else:
                        parts.append(head_renderer())
            return "".join(parts)

        # Normal replacement semantics
        if target_id and slot_name in self.slots[target_id]:
            renderer: Union[Callable[..., Any], str] = self.slots[target_id][slot_name]
            if callable(renderer):
                if inspect.iscoroutinefunction(renderer):
                    return str(await renderer())
                return str(renderer())
            return str(renderer)

        # Fallback to default content if provided
        if default_renderer:
            if inspect.iscoroutinefunction(default_renderer):
                return str(await default_renderer())
            return str(default_renderer())

        return ""

    async def render(self, init: bool = True) -> Response:
        """Main render method - calls lifecycle hooks."""

        # Cleanup background tasks on new full load
        if init:
            for task in self._background_tasks:
                if not task.done():
                    task.cancel()
            self._background_tasks.clear()
            self._await_states.clear()

        # Run init hooks only if requested (new page load)
        if init:
            for hook_name in self.INIT_HOOKS:
                if hasattr(self, hook_name):
                    hook = getattr(self, hook_name)
                    if inspect.iscoroutinefunction(hook):
                        await hook()
                    else:
                        hook()

        # Render template (may be async for layouts with render_slot calls)
        # Render HTML
        # Render template (may be async for layouts with render_slot calls)
        # Render HTML
        self._clear_wire_tracking()
        self._expr_counts.clear()

        # Initial render: we populate the cache
        # Future renders: we use the cache
        # The cache is persistent across renders

        from pywire.core.wire import set_render_context, reset_render_context

        token = set_render_context(self, None)
        try:
            html = await self._render_template()
        finally:
            reset_render_context(token)

        # If this is an update (init=False), strip the surrounding <html>/<body> tags
        # and return only the inner content. This prevents nested HTML on the client.
        if not init:
            import re

            # Try to match body content
            body_match = re.search(
                r"<body[^>]*>(.*?)</body>", html, re.IGNORECASE | re.DOTALL
            )
            if body_match:
                html = body_match.group(1)
            else:
                # Fallback: if no body tag found, maybe it's already a fragment?
                # But if it has <html, strip it?
                # For safety, let's look for html tags and warn/strip if we can't find body
                pass

        # Inject styles if this is the root render (not a component or partial update)
        styles = self._style_collector.render()
        if styles:
            if "</head>" in html:
                html = html.replace("</head>", f"{styles}</head>", 1)
            else:
                html = f"{styles}{html}"

        # Inject PyWire client and SPA metadata only on initial page load (init=True)
        # Components and WebSocket updates (init=False) should NOT include these scripts,
        # otherwise they trigger redundant re-initialization and loops.
        if init:
            no_spa = getattr(self, "__no_spa__", False)
            is_component = getattr(self, "__is_component__", False)

            # Check if SPA features are enabled via attribute or app state
            spa_enabled = getattr(self, "__spa_enabled__", False)
            pjax_enabled = False
            debug_mode = False
            try:
                pjax_enabled = self.request.app.state.enable_pjax
                debug_mode = self.request.app.state.debug
            except (AttributeError, KeyError):
                pass

            if not no_spa and not is_component and (spa_enabled or pjax_enabled):
                meta = {
                    "sibling_paths": getattr(self, "__sibling_paths__", []),
                    "enable_pjax": pjax_enabled,
                    "debug": debug_mode,
                }
                import json

                meta_json = json.dumps(meta)
                meta_script = f'<script id="_pywire_spa_meta" type="application/json">{meta_json}</script>'

                # Determine client script URL
                script_url = "/_pywire/static/pywire.core.min.js"
                try:
                    pywire_app = self.request.app.state.pywire
                    script_url = pywire_app._get_client_script_url()
                except (AttributeError, KeyError):
                    # Fallback to dev if we can't detect, or keep core default
                    pass

                client_script = f'<script src="{script_url}"></script>'
                injection = f"{meta_script}{client_script}"

                if "</body>" in html:
                    html = html.replace("</body>", f"{injection}</body>", 1)
                else:
                    html += injection

        # Run post-render hooks (always run on render)
        for hook_name in self.RENDER_HOOKS:
            if hasattr(self, hook_name):
                hook = getattr(self, hook_name)
                if inspect.iscoroutinefunction(hook):
                    await hook()
                else:
                    hook()

        return Response(html, media_type="text/html")

    def _clear_wire_tracking(self) -> None:
        self._wire_subscribers.clear()
        self._region_dependencies.clear()
        self._dirty_regions.clear()

    def _begin_region_render(self, region_id: str) -> None:
        deps = self._region_dependencies.get(region_id)
        if deps:
            for dep in deps:
                regions = self._wire_subscribers.get(dep)
                if regions and region_id in regions:
                    regions.discard(region_id)
                    if not regions:
                        self._wire_subscribers.pop(dep, None)
                    if regions and region_id in regions:
                        regions.discard(region_id)
                        if not regions:
                            self._wire_subscribers.pop(dep, None)
        self._region_dependencies[region_id] = set()

    def _render_expr(self, static_id: str, compute_func: Callable[[], Any]) -> Any:
        # Generate instance ID based on execution count
        count = self._expr_counts[static_id]
        self._expr_counts[static_id] += 1
        instance_id = f"{static_id}:{count}"

        # If cached, return it
        if instance_id in self._static_cache:
            return self._static_cache[instance_id]

        # Otherwise compute and potentially cache
        # We need to capture dependencies to know if it's static
        prev_capturing = self._capturing_deps
        prev_captured = self._captured_deps

        self._capturing_deps = True
        self._captured_deps = set()

        try:
            result = compute_func()
        finally:
            deps = self._captured_deps
            self._capturing_deps = prev_capturing
            self._captured_deps = prev_captured

        # If no wire dependencies, cache it
        if not deps:
            self._static_cache[instance_id] = result

        return result

    def _register_wire_read(self, wire_obj: Any, field: str, region_id: str) -> None:
        key = (wire_obj, field)
        self._wire_subscribers[key].add(region_id)
        self._region_dependencies[region_id].add(key)

        if self._is_debug:
            print(
                f"DEBUG register_read: page={id(self)} wire={id(wire_obj)} field={field} region={region_id}"
            )

        if self._capturing_deps:
            self._captured_deps.add(key)

    def _invalidate_wire(self, wire_obj: Any, field: str) -> None:
        regions = set()
        key = (wire_obj, field)
        if key in self._wire_subscribers:
            regions |= self._wire_subscribers[key]

        if self._is_debug:
            print(
                f"DEBUG invalidate_wire: page={id(self)} wire={id(wire_obj)} key={key} affected_regions={regions}"
            )

        if regions:
            self._dirty_regions.update(regions)

    async def handle_event(
        self, event_name: str, event_data: dict[str, Any]
    ) -> Dict[str, Any]:
        """Handle client event (from @click, etc.)."""

        # Security: Validate handler is allowed (prevents arbitrary method invocation)
        allowed = getattr(self, "__allowed_handlers__", None)

        # Framework-generated handlers are always allowed (form wrappers, bindings)
        is_framework_handler = (
            event_name.startswith("_handle_bind_")
            or event_name.startswith("_handler_")
            or event_name.startswith("_form_submit_")
        )

        if not is_framework_handler:
            # Block private methods (leading underscore) unless in allowlist
            if event_name.startswith("_"):
                raise ValueError(f"Handler '{event_name}' not allowed")

            # Check explicit allowlist if defined
            if allowed is not None and event_name not in allowed:
                raise ValueError(f"Handler '{event_name}' not allowed")

        # Retrieve handler
        handler = getattr(self, event_name, None)
        if not handler:
            raise ValueError(f"Handler {event_name} not found")

        # Call handler
        if event_name.startswith("_handle_bind_"):
            # Binding handlers expect raw event_data
            if inspect.iscoroutinefunction(handler):
                await handler(event_data)
            else:
                handler(event_data)
        else:
            # Regular handlers: intelligent argument mapping
            args = event_data.get("args", {})

            # Normalize args keys (arg-0 -> arg0) because dataset keys preserve hyphens
            # before digits
            normalized_args = {}
            for k, v in args.items():
                if k.startswith("arg"):
                    normalized_args[k.replace("-", "")] = v
                else:
                    normalized_args[k] = v

            call_kwargs = {k: v for k, v in event_data.items() if k != "args"}
            call_kwargs.update(normalized_args)

            # Check signature to see what arguments the handler accepts
            sig = inspect.signature(handler)
            bound_kwargs = {}

            has_var_kw = False
            for param in sig.parameters.values():
                if param.kind == inspect.Parameter.VAR_KEYWORD:
                    has_var_kw = True
                    break

            if has_var_kw:
                # If accepts **kwargs, pass everything
                bound_kwargs = call_kwargs
            else:
                # Only pass arguments that match parameters
                for name in sig.parameters:
                    if name == "event_data" or name == "event":
                        bound_kwargs[name] = EventData(call_kwargs)
                    elif name in call_kwargs:
                        bound_kwargs[name] = call_kwargs[name]

            try:
                if inspect.iscoroutinefunction(handler):
                    await handler(**bound_kwargs)
                else:
                    handler(**bound_kwargs)
            except Exception as e:
                # Let the runtime handle logging and reporting
                raise e

        # Re-render without re-initializing
        return await self.render_update(init=False)

    async def render_update(self, init: bool = False) -> Dict[str, Any]:
        if self._is_debug:
            # DEBUG: Trace region state
            has_regions = hasattr(self, "__region_renderers__")
            region_map = getattr(self, "__region_renderers__", {})
            dirty: Set[str] = getattr(self, "_dirty_regions", set())
            print(
                f"DEBUG render_update: init={init}, has_regions={has_regions}, region_map={region_map}, dirty_regions={dirty}"
            )

        # Optimization: If we have region renderers (compiled page) and this is a partial update (init=False),
        # check if we really need to update anything.
        if hasattr(self, "__region_renderers__") and (self._dirty_regions or not init):
            # If no dirty regions (and init=False), return empty update
            if not self._dirty_regions:
                # print("DEBUG render_update: No dirty regions, returning empty regions list")
                return {"type": "regions", "regions": []}

            if self._is_debug:
                print(f"DEBUG render_update: dirty_regions={self._dirty_regions}")

            # Check for Root invalidation (None in dirty set)
            # If the root scope is dirty, we must do a full render.
            has_root_dirty = None in self._dirty_regions

            if not has_root_dirty:
                self._expr_counts.clear()

                from pywire.core.wire import set_render_context, reset_render_context

                updates = []
                region_map = getattr(self, "__region_renderers__", {}) or {}

                # Safe to sort now as we know no None is present
                for region_id in sorted(self._dirty_regions):
                    method_name = region_map.get(region_id)
                    if not method_name:
                        continue
                    renderer = getattr(self, method_name, None)
                    if not renderer:
                        continue

                    token = set_render_context(self, region_id)
                    try:
                        if inspect.iscoroutinefunction(renderer):
                            region_html = await renderer()
                        else:
                            region_html = renderer()
                    finally:
                        reset_render_context(token)

                    updates.append({"region": region_id, "html": region_html})

                self._dirty_regions.clear()

                # If we successfully generated partial updates, return them
                if updates:
                    # print(f"DEBUG render_update: returning regions update with {len(updates)} regions")
                    return {"type": "regions", "regions": updates}

        response = await self.render(init=init)
        html = bytes(response.body).decode("utf-8")
        if self._is_debug:
            print(f"DEBUG render_update: returning FULL update (len={len(html)})")
            if "Test" in html:
                print("DEBUG render_update: HTML contains 'Test'")
            else:
                print("DEBUG render_update: HTML does NOT contain 'Test'")
        return {"type": "full", "html": html}

    async def push_state(self) -> None:
        """Force a UI update with current state (useful for streaming progress)."""
        if self._is_debug:
            print(
                f"DEBUG: [{self._instance_id}] push_state called. Has _on_update: {bool(self._on_update)}"
            )
        if self._on_update:
            if inspect.iscoroutinefunction(self._on_update):
                await self._on_update()
            else:
                self._on_update()

    async def _resolve_await(self, await_id: str, awaitable: Awaitable) -> None:
        """Background task to resolve an await block and trigger update."""
        import inspect

        if self._is_debug:
            print(f"DEBUG: [{self._instance_id}] Starting resolution for {await_id}")
        self._await_states[await_id] = {
            "status": "pending",
            "result": None,
            "error": None,
        }

        try:
            if inspect.isawaitable(awaitable):
                result = await awaitable
            else:
                result = awaitable

            if self._is_debug:
                print(
                    f"DEBUG: [{self._instance_id}] Resolution success for {await_id}: {result}"
                )
            self._await_states[await_id] = {
                "status": "success",
                "result": result,
                "error": None,
            }
        except Exception as e:
            if self._is_debug:
                print(
                    f"DEBUG: [{self._instance_id}] Resolution error for {await_id}: {e}"
                )
            self._await_states[await_id] = {
                "status": "error",
                "result": None,
                "error": e,
            }

        # Mark region as dirty and push state
        self._dirty_regions.add(await_id)
        if self._is_debug:
            print(
                f"DEBUG: [{self._instance_id}] Marked {await_id} dirty. Calls push_state..."
            )
        try:
            await self.push_state()
        except Exception as e:
            if self._is_debug:
                print(f"DEBUG: [{self._instance_id}] push_state failed: {e}")
            # push_state might fail if connection closed
            pass

    async def _render_template(self) -> str:
        """Render template - implemented by codegen."""
        return ""
