"""Base page class with lifecycle system."""

import inspect
import re
import asyncio
from collections import defaultdict
from .events import create_event_data
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
)
import logging

from starlette.requests import Request
from starlette.responses import Response

if TYPE_CHECKING:
    from pywire.runtime.router import URLHelper

from pywire.runtime.style_collector import StyleCollector
from pywire.core.snippet import HeadBuffer, Snippet

logger = logging.getLogger(__name__)


class DotDict(dict):
    """Dict that allows dot-access to keys. Returns None for missing keys."""

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError:
            return None

    def __setattr__(self, name: str, value: Any) -> None:
        self[name] = value


# EventData moved to .events


_SITE_ID_RE = re.compile(r"^render_(?P<name>.+?)_(?P<line>\d+)_(?P<col>\d+)$")


def _parse_site_id(site_id: str) -> Tuple[str, Optional[int], Optional[int]]:
    """Split a snippet site_id back into (snippet_name, line, col)."""
    m = _SITE_ID_RE.match(site_id)
    if not m:
        return site_id, None, None
    return m["name"], int(m["line"]), int(m["col"])


def _missing_snippet_message(site_id: str, class_name: str) -> str:
    name, line, col = _parse_site_id(site_id)
    loc = f" (line {line}, col {col})" if line is not None else ""
    return (
        f"{class_name}: required snippet {name!r}{loc} was not provided "
        f"by the caller. Pass it as a named snippet (e.g. "
        f"``{{$snippet {name}}}...{{/snippet}}``), or add a fallback "
        f"with ``{{$render {name}}}...{{/render}}``."
    )


def _rewrite_snippet_typeerror(err: TypeError, site_id: str) -> TypeError:
    """Rewrite TypeErrors from a snippet invocation to reference the
    author-visible snippet name instead of the mangled codegen symbol."""
    name, line, col = _parse_site_id(site_id)
    msg = str(err)
    # Codegen names snippet methods like ``_snippet_<name>_<l>_<c>_<n>``,
    # nested under the enclosing render method's ``<locals>``. Strip
    # everything up to and including that mangled call so the error
    # speaks in snippet terms.
    mangled_prefix = re.compile(r"^.*?\._snippet_[A-Za-z0-9_]+\(\)\s*")
    msg = mangled_prefix.sub("", msg, count=1)
    loc = f" (line {line}, col {col})" if line is not None else ""
    return TypeError(f"{{$render {name}}}{loc}: {msg}")


class BasePage:
    """Base class for all compiled pages."""

    __file_path__: ClassVar[str]
    _FRAMEWORK_PROP_KEYS: ClassVar[Set[str]] = {
        "request",
        "params",
        "query",
        "path",
        "url",
        "__is_component__",
        "_style_collector",
        "_parent_page",
        "_component_key",
    }

    # Lifecycle hooks registry
    BEFORE_LOAD_HOOKS: ClassVar[
        List[str]
    ] = []  # @before_load — pages only, before page setup
    INIT_HOOKS: ClassVar[List[str]] = []  # @init — before first render (data fetching)
    MOUNT_HOOKS: ClassVar[
        List[str]
    ] = []  # @mount — after first render delivered to client
    UNMOUNT_HOOKS: ClassVar[
        List[str]
    ] = []  # @unmount — component removed from render tree
    BEFORE_UPDATE_HOOKS: ClassVar[
        List[str]
    ] = []  # @before_update — before re-render (can cancel)
    AFTER_UPDATE_HOOKS: ClassVar[
        List[str]
    ] = []  # @after_update — after re-render sent to client
    ERROR_HOOKS: ClassVar[List[str]] = []  # @error — exception in handler or render

    # Legacy alias
    RENDER_HOOKS: ClassVar[List[str]] = []

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
        self.errors: Dict[str, Any] = {}
        self.loading: Dict[str, bool] = {}
        self._pending_cookies: List[Dict[str, Any]] = []

        # Component flag (internal)
        self.__is_component__ = kwargs.pop("__is_component__", False)
        self._parent_page: Optional["BasePage"] = kwargs.pop("_parent_page", None)
        self._component_key: Optional[str] = kwargs.pop("_component_key", None)
        self._handler_prefix: str = ""
        if self.__is_component__ and self._parent_page and self._component_key:
            self._handler_prefix = (
                f"{self._parent_page._handler_prefix}_comp:{self._component_key}:"
            )

        # ``children`` is a protected prop: it holds the implicit children
        # Snippet passed by a parent (layout composition) and must not fall
        # through into ``self.attrs`` where it would leak into HTML rendering.
        children_arg = kwargs.pop("children", None)

        # Store remaining kwargs as fallthrough attributes
        self.attrs = dict(kwargs)

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

        # Render-region (snippet) system:
        # - ``_head_buffer``: accumulator for ``{$head}...{/head}`` contributions
        #   from this page and any descendant component in the render tree.
        #   Shared with ``_parent_page`` so contributions from any depth reach
        #   the root layout's flush point.
        # - ``_snippet_invocations``: per-site memo cache. Keyed by the stable
        #   ``site_id`` codegen assigns to each ``{$render}`` call. Each entry
        #   is (args_tuple, cached_html). Site_ids double as region_ids so the
        #   existing wire-dep tracker handles invalidation on wire writes.
        if self._parent_page is not None:
            self._head_buffer: HeadBuffer = self._parent_page._head_buffer
        else:
            self._head_buffer = HeadBuffer()
        self._snippet_invocations: Dict[str, Tuple[Any, str]] = {}
        # Output-equality cache for the general region system. Keyed by
        # ``region_id``; value is the last rendered HTML. Used by
        # ``render_update`` to skip morphdom patches when a dirty region
        # re-renders to identical HTML (e.g. a wire flipped then flipped
        # back, or changed in a way that doesn't affect output).
        self._region_output_cache: Dict[str, str] = {}

        # Protected ``children`` prop for layout composition. Default to
        # ``None`` so layouts that never receive children don't AttributeError
        # on ``{$render children}`` lookups; ``_update_props`` later sets the
        # real snippet when the parent resolves this instance.
        self.children: Optional[Snippet] = children_arg

        self._instance_id = id(self)
        logger.debug(f"[{self._instance_id}] BasePage initialized")

        # Await block state: await_id -> {"status": "pending"|"success"|"error", "result": Any, "error": Any}

        # Await block state: await_id -> {"status": "pending"|"success"|"error", "result": Any, "error": Any}
        self._await_states: Dict[str, Dict[str, Any]] = {}
        # {$auth} block state: region_id -> {"status": "pending"|"allowed"|"denied"}
        # Mirrors _await_states but for region-scoped policy evaluation.
        self._auth_states: Dict[str, Dict[str, Any]] = {}
        self._background_tasks: Set["asyncio.Task[Any]"] = set()

        # Component ref support
        self._ref: Optional[Any] = None  # wire passed via $ref={my_ref}
        self._refs_by_id: Dict[str, Any] = {}  # registry for ref instances
        self._exposed_methods: Set[str] = getattr(self, "__exposed_methods__", set())
        self._pending_navigation: Optional[str] = None
        self._pending_dispatches: List[Dict[str, Any]] = []
        self._pending_intercepted_handlers: List[tuple[str, dict]] = []
        self._components: Dict[str, "BasePage"] = {}
        self._active_component_keys: Set[str] = set()
        self._component_state_snapshots: Dict[str, Dict[str, Any]] = {}

    @property
    def navigate(self) -> Callable[[str], None]:
        """Return a callable that sets the pending navigation path."""

        def _navigate(path: str) -> None:
            self._pending_navigation = path

        return _navigate

    def set_cookie(
        self,
        key: str,
        value: str = "",
        *,
        max_age: Optional[int] = None,
        expires: Optional[int] = None,
        path: str = "/",
        domain: Optional[str] = None,
        secure: bool = False,
        httponly: bool = False,
        samesite: Optional[str] = "lax",
    ) -> None:
        """Queue a cookie to be set on the response.

        Works in both HTTP (applied to Response headers) and
        WebSocket (sent as a client command) contexts.

        Note: httponly cookies can only be set via HTTP response headers.
        Over WebSocket, the httponly flag is ignored since document.cookie
        cannot set httponly cookies.
        """
        self._pending_cookies.append(
            {
                "action": "set",
                "key": key,
                "value": value,
                "max_age": max_age,
                "expires": expires,
                "path": path,
                "domain": domain,
                "secure": secure,
                "httponly": httponly,
                "samesite": samesite,
            }
        )

    def delete_cookie(
        self,
        key: str,
        *,
        path: str = "/",
        domain: Optional[str] = None,
    ) -> None:
        """Queue a cookie for deletion."""
        self._pending_cookies.append(
            {
                "action": "delete",
                "key": key,
                "path": path,
                "domain": domain,
            }
        )

    def _flush_cookie_commands(self) -> List[Dict[str, Any]]:
        """Convert pending cookies to client commands for WebSocket delivery."""
        commands = []
        for cookie in self._pending_cookies:
            commands.append(
                {
                    "cmd": "set_cookie"
                    if cookie["action"] == "set"
                    else "delete_cookie",
                    "refId": "__page__",
                    "args": {
                        k: v
                        for k, v in cookie.items()
                        if k != "action" and v is not None
                    },
                }
            )
        self._pending_cookies.clear()
        return commands

    def asset(self, path: str) -> str:
        """Return a fingerprinted URL for a user static asset.

        Usage in .wire templates: {asset('images/logo.png')}

        Behavior depends on mode:
        - Dev: ?v={mtime} for instant invalidation
        - Prod with build: filename-based (logo.a1b2c3d4.png) for CDN caching
        - Prod without build: ?v={content_hash} fallback
        """
        import hashlib
        import os

        try:
            pywire_app = self.request.app.state.pywire
        except (AttributeError, KeyError):
            return f"/static/{path}"

        static_dir = pywire_app.static_dir
        static_url_path = getattr(pywire_app, "static_url_path", "/static")

        if static_dir is None:
            return f"{static_url_path}/{path}"

        base_url = f"{static_url_path}/{path}"

        if pywire_app._is_dev_mode:
            # Dev: timestamp-based, no caching
            file_path = static_dir / path
            try:
                mtime = os.path.getmtime(file_path)
                return f"{base_url}?v={int(mtime)}"
            except OSError:
                logger.warning("Static asset not found: %s (in %s)", path, file_path)
                return base_url

        # Prod with manifest (pywire build was run): filename-based
        manifest = pywire_app._asset_manifest
        if manifest is not None and path in manifest:
            return f"{static_url_path}/{manifest[path]}"

        # Prod without manifest: content hash fallback
        cache = pywire_app._asset_hash_cache
        if path in cache:
            return f"{base_url}?v={cache[path]}"

        file_path = static_dir / path
        try:
            content_hash = hashlib.md5(file_path.read_bytes()).hexdigest()[:12]
            cache[path] = content_hash
            return f"{base_url}?v={content_hash}"
        except OSError:
            warned = getattr(pywire_app, "_asset_warned_missing", None)
            if warned is not None:
                if path not in warned:
                    warned.add(path)
                    logger.warning(
                        "Static asset not found: %s (in %s)", path, file_path
                    )
            else:
                logger.warning("Static asset not found: %s (in %s)", path, file_path)
            return base_url

    def _is_debug(self) -> bool:
        try:
            return getattr(self.request.app.state, "debug", False)
        except Exception:
            return False

    @classmethod
    def _is_framework_prop_key(cls, key: str) -> bool:
        return key in cls._FRAMEWORK_PROP_KEYS

    def _update_props(self, new_kwargs: Dict[str, Any]) -> None:
        if "request" in new_kwargs:
            self.request = new_kwargs["request"]
        if "params" in new_kwargs:
            self.params = DotDict(new_kwargs["params"] or {})
        if "query" in new_kwargs:
            self.query = DotDict(new_kwargs["query"] or {})
        if "path" in new_kwargs:
            self.path = DotDict(new_kwargs["path"] or {})
        if "url" in new_kwargs:
            self.url = new_kwargs["url"]
        if "_style_collector" in new_kwargs:
            self._style_collector = new_kwargs["_style_collector"]
        fallback_attrs: Dict[str, Any] = {}
        for key, value in new_kwargs.items():
            if self._is_framework_prop_key(key):
                continue

            # Snippet props are always stored directly on ``self`` so
            # ``{$render name}`` can reach them via attribute lookup,
            # regardless of whether the component declared ``name`` in
            # ``@props``.
            if isinstance(value, Snippet):
                setattr(self, key, value)
                continue

            # Prop reconciliation:
            # - existing attributes on the component instance are treated as props/state
            # - unknown keys are fallthrough HTML attrs
            if hasattr(self, key):
                setattr(self, key, value)
                continue
            fallback_attrs[key] = value

        self.attrs = fallback_attrs

    def _resolve_component(
        self, key: str, cls: type["BasePage"], **kwargs: Any
    ) -> "BasePage":
        self._active_component_keys.add(key)

        component = self._components.get(key)
        if component is not None and isinstance(component, cls):
            component._update_props(kwargs)
            return component

        kwargs["_parent_page"] = self
        kwargs["_component_key"] = key
        instance = cls(**kwargs)

        snapshot = self._component_state_snapshots.pop(key, None)
        if snapshot:
            for attr, value in snapshot.items():
                try:
                    setattr(instance, attr, value)
                except AttributeError:
                    continue

        self._components[key] = instance
        return instance

    def _collect_all_commands(self) -> List[Dict[str, Any]]:
        """Collect commands from all internal refs, pending dispatches, and recursive child components."""
        commands = []
        # 1. Collect from own refs
        for rid, r in self._refs_by_id.items():
            cmds = r._collect_commands()
            if cmds:
                commands.extend(cmds)

        # 2. Collect pending dispatch commands
        if self._pending_dispatches:
            commands.extend(self._pending_dispatches)
            self._pending_dispatches.clear()

        # 3. Collect from all child components
        for key, comp in self._components.items():
            cmds = comp._collect_all_commands()
            if cmds:
                commands.extend(cmds)
        return commands

    def _cleanup_components(self) -> None:
        stale_keys = [
            key
            for key in self._components.keys()
            if key not in self._active_component_keys
        ]
        for key in stale_keys:
            component = self._components.pop(key, None)
            if component is not None:
                # Schedule @unmount hooks for removed components (async-safe)
                for hook_name in component.UNMOUNT_HOOKS:
                    hook = getattr(component, hook_name, None)
                    if hook is not None:
                        if inspect.iscoroutinefunction(hook):
                            asyncio.get_event_loop().create_task(hook())
                        else:
                            hook()
        self._active_component_keys.clear()

    def _sync_ref_data(self, event_data: Dict[str, Any]) -> None:
        ref_id = event_data.get("refId")
        if not ref_id:
            return

        ref_obj = self._refs_by_id.get(ref_id)
        if ref_obj is None:
            return

        if "formData" in event_data:
            ref_obj._update_data(event_data["formData"])
        if "value" in event_data:
            ref_obj._update_value(event_data["value"])
        if "rect" in event_data:
            ref_obj._update_rect(event_data["rect"])

    @staticmethod
    def _parse_component_event(event_name: str) -> Optional[Tuple[str, str]]:
        if not event_name.startswith("_comp:"):
            return None

        payload = event_name[len("_comp:") :]
        comp_key, sep, remainder = payload.partition(":")
        if not sep or not comp_key or not remainder:
            raise ValueError(f"Malformed component event '{event_name}'")
        return comp_key, remainder

    async def _dispatch_handler(
        self, event_name: str, event_data: Dict[str, Any]
    ) -> None:
        self._sync_ref_data(event_data)

        # Framework-generated handlers are always allowed (form wrappers, bindings)
        is_framework_handler = event_name.startswith(
            "_handle_bind_"
        ) or event_name.startswith("_handler_")
        if not is_framework_handler and event_name.startswith("_"):
            raise ValueError(f"Handler '{event_name}' not allowed")

        handler = getattr(self, event_name, None)
        if not handler:
            # Handler not found — likely a stale reference from pre-reload
            # DOM (client hasn't applied morphdom update yet).  Silently
            # ignore; the client will receive updated HTML with the correct
            # handler names momentarily.
            logger.debug(
                "Ignoring missing handler '%s' (likely stale from hot reload)",
                event_name,
            )
            return

        if event_name.startswith("_handle_bind_"):
            if inspect.iscoroutinefunction(handler):
                await handler(event_data)
            else:
                handler(event_data)
            return

        args = event_data.get("args", {})
        normalized_args = {}
        for key, value in args.items():
            if key.startswith("arg"):
                normalized_args[key.replace("-", "")] = value
                continue
            normalized_args[key] = value

        call_kwargs = {k: v for k, v in event_data.items() if k != "args"}
        call_kwargs.update(normalized_args)

        sig = inspect.signature(handler)
        bound_kwargs = {}

        has_var_kw = False
        for param in sig.parameters.values():
            if param.kind == inspect.Parameter.VAR_KEYWORD:
                has_var_kw = True
                break

        if has_var_kw:
            bound_kwargs = call_kwargs
        else:
            for name in sig.parameters:
                if name == "event_data" or name == "event":
                    bound_kwargs[name] = create_event_data(call_kwargs)
                    continue
                if name in call_kwargs:
                    bound_kwargs[name] = call_kwargs[name]

            # Parity with the non-interactive form-post path (which calls
            # ``handler(event_data)`` positionally): if a required positional
            # param is still unbound, give it the event-data object so
            # handlers like ``def on_click(e):`` or ``def handler(_):`` work
            # across both dispatch paths.
            event_obj: Any = None
            for name, param in sig.parameters.items():
                if name in bound_kwargs:
                    continue
                if param.kind not in (
                    inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    inspect.Parameter.KEYWORD_ONLY,
                ):
                    continue
                if param.default is not inspect.Parameter.empty:
                    continue
                if event_obj is None:
                    event_obj = create_event_data(call_kwargs)
                bound_kwargs[name] = event_obj
                break

        from pywire.shell import _request_ctx
        from pywire.core.dispatch import _page_context

        request_token = _request_ctx.set(self.request)
        page_token = _page_context.set(self)
        try:
            if inspect.iscoroutinefunction(handler):
                await handler(**bound_kwargs)
            else:
                handler(**bound_kwargs)
        finally:
            _page_context.reset(page_token)
            _request_ctx.reset(request_token)

    async def _handle_component_event(
        self, event_name: str, event_data: Dict[str, Any]
    ) -> None:
        parsed = self._parse_component_event(event_name)
        if parsed:
            comp_key, remainder = parsed
            component = self._components.get(comp_key)
            if component is None:
                raise ValueError(f"Component '{comp_key}' not found")
            await component._handle_component_event(remainder, event_data)
            return

        await self._dispatch_handler(event_name, event_data)

    async def _invoke_render(
        self,
        snippet: Optional[Snippet],
        site_id: str,
        *args: Any,
    ) -> str:
        """Render a snippet at invocation site ``site_id`` with ``args``.

        Memoization: if the site has a cached (args, html) pair whose args
        compare equal to the current ``args`` and the site has not been
        marked dirty by a wire write since the last render, returns the
        cached html. Otherwise runs the snippet under a region context
        that tracks wire reads at ``site_id``, caches the output, and
        returns it.

        Raises ``TypeError`` if ``snippet`` is ``None`` — a required
        snippet prop was not provided. For optional snippets with a
        fallback, use :meth:`_invoke_render_with_fallback`.
        """
        if snippet is None:
            raise TypeError(_missing_snippet_message(site_id, self.__class__.__name__))
        try:
            return await self._invoke_snippet_inner(snippet, site_id, args)
        except TypeError as e:
            raise _rewrite_snippet_typeerror(e, site_id) from e

    async def _invoke_render_with_fallback(
        self,
        snippet: Optional[Snippet],
        site_id: str,
        fallback: Callable[..., Awaitable[str]],
        *args: Any,
    ) -> str:
        """Render ``snippet`` at ``site_id``; on ``None`` run ``fallback``.

        ``fallback`` is a zero-arg async callable generated by codegen
        from the body of ``{$render name(args)}fallback{/render}``.
        """
        if snippet is None:
            # Fallback runs under the same site_id so its wire reads
            # invalidate this site if they change.
            return await self._invoke_region(site_id, fallback, args=())
        return await self._invoke_snippet_inner(snippet, site_id, args)

    async def _invoke_snippet_inner(
        self, snippet: Snippet, site_id: str, args: Tuple[Any, ...]
    ) -> str:
        # If a wire write marked this site dirty since the last render,
        # drop the cache entry before checking for a hit.
        if site_id in self._dirty_regions:
            self._snippet_invocations.pop(site_id, None)
            self._dirty_regions.discard(site_id)

        cached = self._snippet_invocations.get(site_id)
        if cached is not None:
            prev_args, prev_html = cached
            try:
                args_match = prev_args == args
            except Exception:
                args_match = prev_args is args
            if args_match:
                # Keep the output-equality cache aligned so ``render_update``
                # can skip the morphdom patch when this site re-renders to
                # the same HTML.
                self._region_output_cache[site_id] = prev_html
                return prev_html

        html = await self._invoke_region(site_id, snippet.render, args=args)
        self._snippet_invocations[site_id] = (args, html)
        self._region_output_cache[site_id] = html
        return html

    async def _invoke_region(
        self,
        region_id: str,
        func: Callable[..., Awaitable[str]],
        args: Tuple[Any, ...] = (),
    ) -> str:
        """Run ``func`` under a region-scoped render context.

        Centralizes the begin-region + context-set + try/finally reset
        ritual so snippet invocations and framework-internal regions
        share the same machinery.
        """
        # Lazy import to avoid circular references between page.py and wire.py
        from pywire.core.wire import (  # noqa: PLC0415
            set_render_context,
            reset_render_context,
        )

        self._begin_region_render(region_id)
        token = set_render_context(self, region_id)
        try:
            return await func(*args)
        finally:
            reset_render_context(token)

    def _flush_head(self) -> str:
        """Return accumulated ``{$head}`` HTML and clear the buffer.

        Called by the layout/page during document assembly just before
        emitting ``</head>``.
        """
        html = self._head_buffer.flush()
        self._head_buffer.clear()
        return html

    def _inject_head_into(self, html: str) -> str:
        """Flush head buffer into ``html``'s ``</head>`` tag (if any).

        Used as the single injection point whether the page is rendered
        via ``render()`` (HTTP response builder) or ``_render_template()``
        directly (tests / SSR integration).
        """
        if self._parent_page is not None:
            # Nested render: defer to the root page so head contributions
            # accumulate before a single flush. Return ``html`` untouched.
            return html
        head_html = self._flush_head()
        if not head_html:
            return html
        if "</head>" in html:
            left, _, right = html.rpartition("</head>")
            return f"{left}{head_html}</head>{right}"
        return f"{head_html}{html}"

    async def _run_hooks(self, hook_list: List[str]) -> None:
        """Run a list of lifecycle hooks by method name."""
        for hook_name in hook_list:
            hook = getattr(self, hook_name, None)
            if hook is not None:
                if inspect.iscoroutinefunction(hook):
                    await hook()
                else:
                    hook()

    async def _run_before_update_hooks(self) -> bool:
        """Run @before_update hooks. Returns False if any hook returns False (skip update)."""
        for hook_name in self.BEFORE_UPDATE_HOOKS:
            hook = getattr(self, hook_name, None)
            if hook is not None:
                if inspect.iscoroutinefunction(hook):
                    result = await hook()
                else:
                    result = hook()
                if result is False:
                    return False
        return True

    async def _run_error_hooks(self, exc: Exception) -> bool:
        """Run @error hooks. Returns True if any hook returns truthy (suppress error)."""
        for hook_name in self.ERROR_HOOKS:
            hook = getattr(self, hook_name, None)
            if hook is not None:
                if inspect.iscoroutinefunction(hook):
                    result = await hook(exc)
                else:
                    result = hook(exc)
                if result:
                    return True
        return False

    async def render(self, init: bool = True) -> Response:
        """Main render method - calls lifecycle hooks."""

        # Cleanup background tasks on new full load
        if init:
            for task in self._background_tasks:
                if not task.done():
                    task.cancel()
            self._background_tasks.clear()
            self._await_states.clear()

        # Auth guard — must short-circuit before any user code runs so
        # unauthorized requests never trigger side effects. Runs on BOTH
        # init=True (hard load) and init=False (SPA relocate via internal
        # ASGI replay); skipping on relocate would let an anonymous SPA
        # nav reach a protected page. Lazy-imported so unprotected pages
        # don't pull in the auth submodule.
        if getattr(self.__class__, "__auth_required__", False):
            from pywire.auth.guard import run_auth_guard

            guard_response = await run_auth_guard(self)
            if guard_response is not None:
                location = guard_response.headers.get("location")
                if location:
                    # Mirror on _pending_navigation so the WS transport's
                    # existing drain sends a navigate message instead of
                    # update HTML.
                    self._pending_navigation = location
                return guard_response

        # Run @before_load hooks (pages only, before any page logic)
        if init:
            await self._run_hooks(self.BEFORE_LOAD_HOOKS)

        # Run @init hooks only if requested (new page load — data fetching)
        if init:
            await self._run_hooks(self.INIT_HOOKS)

        self._clear_wire_tracking()
        self._expr_counts.clear()

        # Initial render: we populate the cache
        # Future renders: we use the cache
        # The cache is persistent across renders

        from pywire.core.wire import set_render_context, reset_render_context

        token = set_render_context(self, None)
        try:
            self._active_component_keys.clear()
            html = await self._render_template()
            self._cleanup_components()
        finally:
            reset_render_context(token)

        # If this is an update (init=False), strip the surrounding <html>/<body> tags
        # and return only the inner content. This prevents nested HTML on the client.
        if not init:
            import re

            # Try to match body content
            body_match = re.search(
                r"<body[^>]*>(.*)</body>", html, re.IGNORECASE | re.DOTALL
            )
            if body_match:
                html = body_match.group(1)
            else:
                # Fallback: if no body tag found, maybe it's already a fragment?
                # But if it has <html, strip it?
                # For safety, let's look for html tags and warn/strip if we can't find body
                pass

        # Flush {$head} contributions into the document head.
        html = self._inject_head_into(html)

        # Inject styles if this is the root render (not a component or partial update)
        styles = self._style_collector.render()
        if styles:
            if "</head>" in html:
                parts = html.rsplit("</head>", 1)
                html = parts[0] + f"{styles}</head>" + parts[1]
            else:
                html = f"{styles}{html}"

        # Inject PyWire client and SPA metadata only on initial page load (init=True)
        # Components and WebSocket updates (init=False) should NOT include these scripts,
        # otherwise they trigger redundant re-initialization and loops.
        if init:
            no_spa = getattr(self, "__no_spa__", False)
            is_component = getattr(self, "__is_component__", False)

            # Check if SPA features are enabled via attribute or app state
            pjax_enabled = False
            debug_mode = False
            static_url_path = "/static"
            try:
                pjax_enabled = bool(
                    getattr(self.request.app.state, "enable_pjax", False)
                )
                debug_mode = bool(getattr(self.request.app.state, "debug", False))
            except (AttributeError, KeyError):
                pass  # request.app.state may not exist in testing or non-Starlette contexts
            try:
                pywire_app = self.request.app.state.pywire
                _url_path = getattr(pywire_app, "static_url_path", None)
                if isinstance(_url_path, str):
                    static_url_path = _url_path
            except (AttributeError, KeyError):
                pass  # fall back to default static_url_path
            # Collect all wire route patterns for whitelist SPA navigation
            all_wire_paths: list = []
            try:
                pywire_app = self.request.app.state.pywire
                router = getattr(pywire_app, "router", None)
                if router is not None:
                    patterns = router.get_all_patterns()
                    if isinstance(patterns, list):
                        all_wire_paths = patterns
            except (AttributeError, KeyError):
                pass  # no router available; SPA navigation will use sibling paths only

            # ASGI mount prefix — when PyWire is mounted under e.g. /app on a
            # host FastAPI/Starlette app, every URL we emit must be prefixed
            # with it. Starlette sets scope["root_path"] on mounted sub-apps.
            root_path: str = ""
            try:
                root_path = str(self.request.scope.get("root_path", "") or "")
            except (AttributeError, KeyError):
                pass

            def _prefix(p: str) -> str:
                if not root_path or not isinstance(p, str) or not p.startswith("/"):
                    return p
                if p.startswith(root_path + "/") or p == root_path:
                    return p
                return root_path + p

            if not no_spa and not is_component:
                # Reconnect overlay config from PyWire app
                reconnect_max_attempts = 10
                reconnect_overlay_enabled = True
                try:
                    pywire_app = self.request.app.state.pywire
                    _rma = getattr(pywire_app, "reconnect_max_attempts", 10)
                    if isinstance(_rma, int):
                        reconnect_max_attempts = _rma
                    _roe = getattr(pywire_app, "reconnect_overlay", True)
                    if isinstance(_roe, bool):
                        reconnect_overlay_enabled = _roe
                except (AttributeError, KeyError):
                    pass

                # Check interactive server mode
                interactive_mode = True
                try:
                    interactive_mode = bool(
                        getattr(self.request.app.state, "interactive_server_mode", True)
                    )
                except (AttributeError, KeyError):
                    pass

                # Dev-only SSE reload channel for non-interactive mode. The
                # dev server mounts /_pywire/dev/reload when both conditions
                # hold; client subscribes via EventSource if this is set.
                dev_reload_url = None
                try:
                    pywire_app = self.request.app.state.pywire
                    if not interactive_mode and getattr(
                        pywire_app, "_is_dev_mode", False
                    ):
                        dev_reload_url = _prefix("/_pywire/dev/reload")
                except (AttributeError, KeyError):
                    pass

                sibling_paths_raw = getattr(self, "__sibling_paths__", []) or []
                meta = {
                    "sibling_paths": [_prefix(p) for p in sibling_paths_raw],
                    "all_paths": [_prefix(p) for p in all_wire_paths],
                    "enable_pjax": pjax_enabled,
                    "debug": debug_mode,
                    "static_path": _prefix(static_url_path),
                    "mount_path": root_path,
                    "reconnect_max_attempts": reconnect_max_attempts,
                    "reconnect_overlay": reconnect_overlay_enabled,
                    "interactive": interactive_mode,
                    "dev_reload_url": dev_reload_url,
                }
                import json

                meta_json = json.dumps(meta)
                meta_script = f'<script id="_pywire_spa_meta" type="application/json">{meta_json}</script>'

                # Determine client script URL
                from pywire import __version__ as _pywire_version

                script_url = (
                    f"{root_path}/_pywire/static/pywire.core.min.js?v={_pywire_version}"
                )
                try:
                    pywire_app = self.request.app.state.pywire
                    script_url = pywire_app._get_client_script_url(root_path=root_path)
                except (AttributeError, KeyError):
                    # Fallback to dev if we can't detect, or keep core default
                    pass

                client_script = f'<script src="{script_url}"></script>'

                # Inject custom reconnect overlay template if loaded
                reconnect_injection = ""
                try:
                    pywire_app = self.request.app.state.pywire
                    tmpl_html = getattr(pywire_app, "_reconnect_template_html", None)
                    tmpl_style = getattr(pywire_app, "_reconnect_template_style", None)
                    if tmpl_html:
                        reconnect_injection += (
                            f'<template id="_pywire_reconnect">{tmpl_html}</template>'
                        )
                    if tmpl_style:
                        reconnect_injection += f"<style>{tmpl_style}</style>"
                except (AttributeError, KeyError):
                    pass

                # Non-interactive mode: warn about unsupported event handlers
                event_warning = ""
                if not interactive_mode and debug_mode:
                    # Check for event handler attributes in the rendered HTML
                    import re

                    event_attrs = re.findall(r"data-on-(\w+)=", html)
                    # Filter out @submit which works via form POST
                    unsupported = [e for e in event_attrs if e != "submit"]
                    if unsupported:
                        unique = sorted(set(unsupported))
                        handlers_str = ", ".join(f"@{e}" for e in unique)
                        event_warning = (
                            f'<script>console.warn("PyWire: Non-interactive mode — '
                            f"these event handlers are inactive: {handlers_str}. "
                            f'Only @submit works via form POST.")</script>'
                        )

                injection = (
                    f"{reconnect_injection}{meta_script}{client_script}{event_warning}"
                )

                if "</body>" in html:
                    parts = html.rsplit("</body>", 1)
                    html = parts[0] + f"{injection}</body>" + parts[1]
                else:
                    html += injection

        response = Response(html, media_type="text/html")

        # Apply any pending cookies to the HTTP response
        for cookie in self._pending_cookies:
            if cookie["action"] == "set":
                response.set_cookie(
                    cookie["key"],
                    cookie["value"],
                    max_age=cookie.get("max_age"),
                    expires=cookie.get("expires"),
                    path=cookie.get("path", "/"),
                    domain=cookie.get("domain"),
                    secure=cookie.get("secure", False),
                    httponly=cookie.get("httponly", False),
                    samesite=cookie.get("samesite", "lax"),
                )
            elif cookie["action"] == "delete":
                response.delete_cookie(
                    cookie["key"],
                    path=cookie.get("path", "/"),
                    domain=cookie.get("domain"),
                )
        self._pending_cookies.clear()

        return response

    def _clear_wire_tracking(self) -> None:
        self._wire_subscribers.clear()
        self._region_dependencies.clear()
        self._dirty_regions.clear()
        # Also drop the output-equality cache so the next full render emits
        # fresh markup (the previous cache belonged to a pre-hot-reload
        # template that may have been invalidated).
        self._region_output_cache.clear()
        self._snippet_invocations.clear()

    def _begin_region_render(self, region_id: str) -> None:
        deps = self._region_dependencies.get(region_id)
        if deps:
            for dep in deps:
                regions = self._wire_subscribers.get(dep)
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

        logger.debug(
            f"register_read: page={id(self)} wire={id(wire_obj)} field={field} region={region_id}"
        )

        if self._capturing_deps:
            self._captured_deps.add(key)

    def _invalidate_wire(self, wire_obj: Any, field: str) -> None:
        regions = set()
        key = (wire_obj, field)
        if key in self._wire_subscribers:
            regions |= self._wire_subscribers[key]

        logger.debug(
            "INVALIDATE: page=%s wire=%s key=%s affected_regions=%s",
            id(self),
            id(wire_obj),
            key,
            regions,
        )

        if regions:
            self._dirty_regions.update(regions)

    async def handle_event(
        self, event_name: str, event_data: dict[str, Any]
    ) -> Dict[str, Any]:
        """Handle client event (from @click, etc.)."""
        try:
            parsed = self._parse_component_event(event_name)
            if parsed:
                comp_key, remainder = parsed
                component = self._components.get(comp_key)
                if component is None:
                    raise ValueError(f"Component '{comp_key}' not found")
                await component._handle_component_event(remainder, event_data)
            else:
                await self._dispatch_handler(event_name, event_data)

            # Drain server-intercepted dispatch handlers (from dispatch()
            # with bubbles=False targeting a ref with a registered handler).
            while self._pending_intercepted_handlers:
                h_name, h_data = self._pending_intercepted_handlers.pop(0)
                await self._dispatch_handler(h_name, h_data)
        except Exception as exc:
            # Run @error hooks — if any returns truthy, suppress the error
            if await self._run_error_hooks(exc):
                logger.debug("Error suppressed by @error hook: %s", exc)
            else:
                raise

        # Run @before_update hooks — if any returns False, skip the update
        should_update = await self._run_before_update_hooks()
        if not should_update:
            # Return empty update (no changes sent to client)
            return {"type": "regions", "regions": []}

        # Re-render without re-initializing
        from pywire.shell import _request_ctx

        token = _request_ctx.set(self.request)
        try:
            return await self.render_update(init=False)
        finally:
            _request_ctx.reset(token)

    async def render_update(self, init: bool = False) -> Dict[str, Any]:
        # Optimization: If we have region renderers (compiled page) and this is a partial update (init=False),
        # check if we really need to update anything.
        if hasattr(self, "__region_renderers__") and (self._dirty_regions or not init):
            # If no dirty regions (and init=False), return empty update
            if not self._dirty_regions:
                result: Dict[str, Any] = {"type": "regions", "regions": []}
                commands = self._collect_all_commands()
                cookie_cmds = self._flush_cookie_commands()
                if cookie_cmds:
                    commands = (commands or []) + cookie_cmds
                if commands:
                    result["commands"] = commands
                return result

            logger.debug(f"render_update: dirty_regions={self._dirty_regions}")

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
                    except Exception:
                        # Region renderer raised — fall back to a full re-render
                        # where template-level {$try} blocks can catch the exception.
                        logger.debug(
                            "render_update: falling back to FULL update, "
                            f"region {region_id} raised an exception"
                        )
                        has_root_dirty = True
                        break
                    finally:
                        reset_render_context(token)

                    stripped_html = region_html.lstrip()
                    if stripped_html.startswith(
                        ("<!DOCTYPE", "<!doctype", "<html", "<HTML")
                    ):
                        logger.debug(
                            "render_update: falling back to FULL update, "
                            f"region {region_id} rendered full-document HTML"
                        )
                        has_root_dirty = True
                        break

                    # Output-equality skip: if the re-rendered HTML matches
                    # what we sent the client last time for this region, skip
                    # emitting a morphdom patch. Still refresh the cache so a
                    # subsequent change continues to match against the latest.
                    cached = self._region_output_cache.get(region_id)
                    if cached == region_html:
                        logger.debug(
                            f"render_update: skipping region {region_id} "
                            "(HTML unchanged)"
                        )
                        continue
                    self._region_output_cache[region_id] = region_html
                    updates.append({"region": region_id, "html": region_html})

                if not has_root_dirty:
                    self._dirty_regions.clear()

                    # If we successfully generated partial updates, return them
                    result = {"type": "regions", "regions": updates}
                    logger.debug("RENDER-UPDATE-REGIONS: %s", updates)

                    # 2. Collect commands from all refs (recursively)
                    commands = self._collect_all_commands()
                    cookie_cmds = self._flush_cookie_commands()
                    if cookie_cmds:
                        commands = (commands or []) + cookie_cmds
                    if commands:
                        result["commands"] = commands

                    return result

        # Flush cookie commands before render() (which would apply them to the
        # discarded HTTP Response and clear _pending_cookies)
        cookie_cmds = self._flush_cookie_commands()

        try:
            response = await self.render(init=init)
        except Exception:
            if not self._is_debug():
                raise  # Production: let _handle_event log it, page stays intact
            # Debug mode: show error page so dev/tutorial users see the traceback
            import traceback as _tb

            tb_text = _tb.format_exc()
            error_html = (
                "<!DOCTYPE html><html><body"
                " style='font-family:monospace;padding:24px;color:#111'>"
                "<h2 style='color:#c00;margin:0 0 12px;font-size:1.1em'>"
                "&#9888; Runtime Error</h2>"
                "<pre style='background:#fff0f0;border:1px solid #fcc;"
                "padding:16px;border-radius:4px;overflow:auto;"
                "white-space:pre-wrap;word-break:break-word;"
                f"font-size:0.85em;line-height:1.5'>{tb_text}</pre>"
                "</body></html>"
            )
            return {"type": "full", "html": error_html}

        html = bytes(response.body).decode("utf-8")
        logger.debug(f"render_update: returning FULL update (len={len(html)})")

        result: dict[str, Any] = {"type": "full", "html": html}
        commands = self._collect_all_commands()
        if cookie_cmds:
            commands = (commands or []) + cookie_cmds
        if commands:
            result["commands"] = commands
        return result

    async def push_state(self) -> None:
        """Force a UI update with current state (useful for streaming progress)."""
        logger.debug(
            f"[{self._instance_id}] push_state called. Has _on_update: {bool(self._on_update)}"
        )
        if self._on_update:
            if inspect.iscoroutinefunction(self._on_update):
                await self._on_update()
            else:
                self._on_update()

    async def _resolve_await(self, await_id: str, awaitable: Awaitable) -> None:
        """Background task to resolve an await block and trigger update."""
        import inspect

        logger.debug(f"[{self._instance_id}] Starting resolution for {await_id}")
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

            logger.debug(
                f"[{self._instance_id}] Resolution success for {await_id}: {result}"
            )
            self._await_states[await_id] = {
                "status": "success",
                "result": result,
                "error": None,
            }
        except Exception as e:
            logger.debug(f"[{self._instance_id}] Resolution error for {await_id}: {e}")
            self._await_states[await_id] = {
                "status": "error",
                "result": None,
                "error": e,
            }

        # Mark region as dirty and push state
        self._dirty_regions.add(await_id)
        logger.debug(
            f"[{self._instance_id}] Marked {await_id} dirty. Calls push_state..."
        )
        try:
            await self.push_state()
        except Exception as e:
            logger.debug(f"[{self._instance_id}] push_state failed: {e}")
            # push_state might fail if connection closed
            pass

    async def _resolve_auth(
        self,
        region_id: str,
        *,
        policy: Optional[str] = None,
        claims: Optional[List[Tuple[str, Optional[str]]]] = None,
    ) -> None:
        """Background task backing the ``{$auth}`` directive.

        Evaluates ``policy`` + ``claims`` against the current principal
        via :func:`pywire.auth.evaluate_auth`, stores the outcome in
        ``_auth_states[region_id]`` as ``{"status": "allowed"|"denied"}``,
        marks the region dirty, and pushes a state update.
        """
        from pywire.auth.guard import evaluate_auth
        from pywire.auth.principal import ANONYMOUS, ClaimsPrincipal

        self._auth_states[region_id] = {"status": "pending"}

        principal = getattr(self, "user", None)
        if not isinstance(principal, ClaimsPrincipal):
            principal = ANONYMOUS

        try:
            allowed = await evaluate_auth(
                principal,
                policy=policy,
                claims=claims,
                request=getattr(self, "request", None),
            )
        except Exception:
            logger.warning(
                f"[{self._instance_id}] {{$auth}} evaluation error for {region_id}; denying",
                exc_info=True,
            )
            allowed = False

        self._auth_states[region_id] = {
            "status": "allowed" if allowed else "denied"
        }
        self._dirty_regions.add(region_id)
        try:
            await self.push_state()
        except Exception:
            pass

    async def _render_template(self) -> str:
        """Render template - implemented by codegen."""
        return ""

    async def _render_and_cleanup(self) -> str:
        """Render template and remove stale child component instances."""
        html = await self._render_template()
        self._cleanup_components()
        # At the root of the render tree (no parent page), flush accumulated
        # ``{$head}`` contributions into the document head so callers that
        # use ``_render_template()`` / ``_render_and_cleanup()`` directly
        # (tests, SSR integrations) get a complete document.
        return self._inject_head_into(html)


class ErrorBasePage(BasePage):
    """Base class for __error__.wire pages. Provides typed error context attributes."""

    error_code: int
    error_message: str
    error_trace: str
