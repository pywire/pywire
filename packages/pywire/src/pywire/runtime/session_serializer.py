"""Session state serialization for PyWire.

Converts live BasePage instances to/from plain dicts suitable for
storage in a SessionStore (memory or Redis). Generalizes the
hot-reload state migration pattern from websocket.py broadcast_reload.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any, Callable, Dict, Optional, Set

from pywire.core.signals import Derived
from pywire.core.wire import (
    WireBase,
    WireDict,
    WireList,
    WireNamespace,
    WirePrimitive,
    WireSet,
    wire,
)

logger = logging.getLogger(__name__)

# Attributes that are always managed by the framework and should never
# be serialized or restored from a snapshot.
_FRAMEWORK_ATTRS: Set[str] = {
    "request",
    "params",
    "query",
    "path",
    "url",
    "loading",
    "user",
    "attrs",
    "base_path",
}

# Wire type tags for reconstruction
_WIRE_TYPE_TAGS: Dict[type, str] = {
    WirePrimitive: "primitive",
    WireList: "list",
    WireDict: "dict",
    WireSet: "set",
    WireNamespace: "namespace",
}

_WIRE_TAG_TO_FACTORY: Dict[str, Any] = {
    "primitive": wire,
    "list": wire,
    "dict": wire,
    "set": lambda v: wire(set(v) if isinstance(v, list) else v),
    "namespace": lambda v: wire(**v) if isinstance(v, dict) else wire(v),
}


def _owned_by(page: Any) -> Callable[[WireBase], bool]:
    """Whether a wire is state of this page tree (see BasePage._owning).

    A module-level wire aliased into the frontmatter (``votes = shared.votes``)
    is shared by every user: it is not this page's state, and restoring it from
    a snapshot would roll everyone back.
    """
    owner_tokens = getattr(page, "_owner_tokens", None)
    if owner_tokens is None:
        # Duck-typed page without ownership tracking: every wire is its own.
        return lambda _wire: True
    tokens = owner_tokens()
    return lambda w: w._owner in tokens


class HookedState:
    """Snapshot state of an object with ``__pw_restore__`` (e.g. a Form),
    carried to a component that is instantiated after the restore."""

    __slots__ = ("state",)

    def __init__(self, state: Any) -> None:
        self.state = state


def _hook_snapshot(value: Any, name: str) -> Any:
    """``value.__pw_snapshot__()`` when the type defines it, else None.

    Objects that are not wires but own client-visible state (a Form's typed
    values and errors) opt in with ``__pw_snapshot__``/``__pw_restore__``.
    """
    hook = getattr(type(value), "__pw_snapshot__", None)
    if hook is None:
        return None
    try:
        state = hook(value)
    except Exception:
        logger.warning("Snapshot hook failed for attr '%s'", name, exc_info=True)
        return None
    if not _is_serializable(state):
        logger.warning(
            "Snapshot hook for attr '%s' returned non-serializable data", name
        )
        return None
    return state


def restore_hooked(current: Any, state: Any) -> bool:
    """Feed snapshot state back through ``__pw_restore__``; False if absent."""
    hook = getattr(type(current), "__pw_restore__", None)
    if hook is None:
        return False
    try:
        hook(current, state)
    except Exception:
        logger.warning("Restore hook failed on %r", current, exc_info=True)
    return True


def _peek_wire(obj: WireBase) -> Any:
    """Extract the raw value from a wire, handling sets for JSON/msgpack compat."""
    val = obj.peek()
    # msgpack can't serialize sets — convert to list
    if isinstance(val, set):
        return list(val)
    return val


def _get_wire_tag(obj: WireBase) -> Optional[str]:
    """Get the type tag for a wire object."""
    for cls, tag in _WIRE_TYPE_TAGS.items():
        if isinstance(obj, cls):
            return tag
    return None


def _is_serializable(value: Any) -> bool:
    """Check if a value can be serialized to msgpack/JSON."""
    if value is None or isinstance(value, (bool, int, float, str, bytes)):
        return True
    if isinstance(value, (list, tuple)):
        return all(_is_serializable(v) for v in value)
    if isinstance(value, dict):
        return all(
            isinstance(k, (str, int)) and _is_serializable(v) for k, v in value.items()
        )
    return False


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]


def page_identity(page: Any) -> str:
    """Which page a snapshot belongs to: its ``.wire`` file and class.

    Stays the same across processes and hot reloads of that file.
    """
    cls = type(page)
    source = getattr(cls, "__file_path__", None) or cls.__module__
    return _digest(f"{source}\0{cls.__qualname__}")


def _route(page: Any) -> str:
    try:
        return str(page.request.url.path)
    except AttributeError:
        return ""


def principal_key(user: Any) -> str:
    """Who a snapshot was taken for, so it is only restored for them."""
    if user is None or getattr(user, "is_authenticated", True) is False:
        return ""
    for attr in ("user_id", "id", "username"):
        value = getattr(user, attr, None)
        if value not in (None, ""):
            return _digest(f"{type(user).__qualname__}\0{attr}\0{value}")
    return _digest(f"{type(user).__qualname__}\0{user!r}")


def page_state_key(session_id: str, page: Any) -> str:
    """Session-store key of one page's state in one session.

    Each page (class and URL path) of a session keeps its own record, so one
    page's state never lands in another.
    """
    return f"{session_id}:page:{_digest(page_identity(page) + chr(0) + _route(page))}"


def snapshot_page_state(page: Any, *, warn_size: int = 0) -> Dict[str, Any]:
    """Extract serializable user state from a BasePage instance.

    Args:
        page: The BasePage instance to snapshot.
        warn_size: If > 0, log a warning when the snapshot exceeds this
            many bytes. Set via ``PyWire(session_warn_size=...)``.

    Returns a dict with:
    - "attrs": user-defined attributes (wire values peeked to raw)
    - "wire_tags": maps attr name to wire type tag for reconstruction
    - "loading": page.loading dict
    - "await_states": page._await_states
    - "component_snapshots": nested component state
    - "page": ``page_identity`` of the page it was taken from
    - "route_path": current URL path
    - "principal": ``principal_key`` of the page's user

    The user itself is never in a snapshot: it comes from each request.
    """
    snapshot: Dict[str, Any] = {}
    attrs: Dict[str, Any] = {}
    wire_tags: Dict[str, str] = {}
    owned = _owned_by(page)
    hooked: Dict[str, Any] = {}

    for name, value in page.__dict__.items():
        # Skip private/framework attributes
        if name.startswith("_"):
            continue
        if name in _FRAMEWORK_ATTRS:
            continue

        # Skip framework artifacts that are rebuilt from the page class on
        # restore — they hold no user state and are never serializable:
        #   * bound event handlers / `def` helpers from the page's frontmatter
        #     (stored on self by codegen for event dispatch)
        #   * ``@derived`` computed values (Derived instances, cached lazily)
        if isinstance(value, Derived):
            continue
        if callable(value) and not isinstance(value, WireBase):
            continue

        state = _hook_snapshot(value, name)
        if state is not None:
            hooked[name] = state
            continue

        # Handle wire types
        if isinstance(value, WireBase):
            if value._locked or not owned(value):
                continue
            tag = _get_wire_tag(value)
            if tag:
                wire_tags[name] = tag
                raw = _peek_wire(value)
                if _is_serializable(raw):
                    attrs[name] = raw
                else:
                    logger.warning(
                        "Skipping non-serializable wire attr '%s' on %s",
                        name,
                        type(page).__name__,
                    )
            continue

        # Plain attributes — check serializability
        if _is_serializable(value):
            attrs[name] = value
        else:
            # Frontmatter often holds non-picklable handles (e.g. an
            # ``idp = app.state.local_idp`` reference, an open DB engine,
            # or a third-party SDK client). These are reconstructed by
            # ``__top_level_init__`` on every page instantiation, so
            # losing them from the snapshot is harmless. Log at debug
            # rather than warning so this isn't noise on every persist.
            logger.debug(
                "Skipping non-serializable attr '%s' (%s) on %s",
                name,
                type(value).__name__,
                type(page).__name__,
            )

    snapshot["attrs"] = attrs
    snapshot["wire_tags"] = wire_tags
    if hooked:
        snapshot["hooked"] = hooked

    # Framework-managed state that should persist
    snapshot["loading"] = dict(page.loading) if page.loading else {}

    # Await block states
    if hasattr(page, "_await_states") and page._await_states:
        snapshot["await_states"] = dict(page._await_states)

    # Component state snapshots (same pattern as broadcast_reload)
    component_snapshots: Dict[str, Dict[str, Any]] = {}
    components = getattr(page, "_components", {})
    for comp_key, comp in components.items():
        comp_snap: Dict[str, Any] = {}
        for attr, value in comp.__dict__.items():
            if attr.startswith("_"):
                continue
            if attr in {"request", "params", "query", "path", "url", "base_path"}:
                continue
            state = _hook_snapshot(value, attr)
            if state is not None:
                comp_snap[attr] = {"value": state, "hook": True}
                continue
            if isinstance(value, WireBase):
                if value._locked or not owned(value):
                    continue
                tag = _get_wire_tag(value)
                if tag:
                    raw = _peek_wire(value)
                    if _is_serializable(raw):
                        comp_snap[attr] = {"value": raw, "wire_tag": tag}
                continue
            if _is_serializable(value):
                comp_snap[attr] = {"value": value}
        if comp_snap:
            component_snapshots[comp_key] = comp_snap

    if component_snapshots:
        snapshot["component_snapshots"] = component_snapshots

    # Which page, and for whom: restore checks both.
    snapshot["page"] = page_identity(page)
    snapshot["route_path"] = _route(page)
    snapshot["principal"] = principal_key(getattr(page, "user", None))

    # Warn if snapshot is large
    if warn_size > 0:
        try:
            import msgpack

            size = len(msgpack.packb(snapshot))
            if size > warn_size:
                logger.warning(
                    "Session snapshot for %s is %d bytes (threshold: %d). "
                    "Large sessions increase Redis memory and persist latency. "
                    "Consider moving large data out of page attributes.",
                    type(page).__qualname__,
                    size,
                    warn_size,
                )
        except Exception:
            pass  # msgpack not available or snapshot not packable — skip check

    return snapshot


def restore_page_state(page: Any, snapshot: Dict[str, Any], *, principal: Any) -> bool:
    """Inject saved state into a fresh BasePage instance.

    The page should already be instantiated with the correct request,
    params, query, and path. This function restores user-defined state
    from a snapshot dict.

    Nothing is restored, and False returned, unless the snapshot was taken
    from this page (class and ``.wire`` file) for this ``principal`` (the
    user the current request resolved to). The page's ``user`` is never
    touched: it always comes from the request.

    Wire dependency tracking rebuilds naturally on the next render() call.
    """
    if snapshot.get("page") != page_identity(page):
        logger.debug("Not restoring a snapshot of another page into %s", page)
        return False
    if snapshot.get("principal", "") != principal_key(principal):
        logger.debug("Not restoring a snapshot taken for another user")
        return False
    attrs = snapshot.get("attrs", {})
    wire_tags = snapshot.get("wire_tags", {})
    owned = _owned_by(page)

    for name, value in attrs.items():
        # Snapshots never contain these (snapshot_page_state skips them), but a
        # stale or hand-built one must not overwrite request-bound attributes
        # such as ``query`` or reach private framework state.
        if name.startswith("_") or name in _FRAMEWORK_ATTRS:
            continue
        try:
            current = getattr(page, name, None)
            if isinstance(current, WireBase) and (
                current._locked or not owned(current)
            ):
                # Stale signed snapshot (attr locked, or now aliasing shared
                # state, after it was signed): the fresh frontmatter value
                # always wins, never the client's.
                continue
            if name in wire_tags:
                # Current page has a wire attribute — update its value
                if isinstance(current, WireBase):
                    # Restore into existing wire (preserves page registration)
                    if isinstance(current, WirePrimitive):
                        current._value = value
                    elif isinstance(current, WireList):
                        current.clear()
                        current.extend(value if isinstance(value, list) else [value])
                    elif isinstance(current, WireDict):
                        current.clear()
                        current.update(value if isinstance(value, dict) else {})
                    elif isinstance(current, WireSet):
                        current.clear()
                        current.update(set(value) if isinstance(value, list) else value)
                    elif isinstance(current, WireNamespace):
                        if isinstance(value, dict):
                            for k, v in value.items():
                                current[k] = v
                else:
                    # Page doesn't have this wire yet (new attr or class changed)
                    tag = wire_tags[name]
                    factory = _WIRE_TAG_TO_FACTORY.get(tag)
                    if factory:
                        restored_wire = factory(value)
                        restored_wire._owner = getattr(page, "_owner_token", None)
                        setattr(page, name, restored_wire)
            else:
                # Plain attribute
                setattr(page, name, value)
        except Exception:
            logger.warning(
                "Failed to restore attr '%s' on %s",
                name,
                type(page).__name__,
                exc_info=True,
            )

    for name, state in (snapshot.get("hooked") or {}).items():
        restore_hooked(getattr(page, name, None), state)

    # Restore framework-managed state
    if "loading" in snapshot:
        page.loading.update(snapshot["loading"])
    if "await_states" in snapshot:
        page._await_states.update(snapshot["await_states"])

    # Component state snapshots — set on page so _resolve_component() can
    # restore them when components are instantiated during render
    if "component_snapshots" in snapshot:
        comp_snaps = snapshot["component_snapshots"]
        # Convert back to the format expected by _component_state_snapshots:
        # Dict[str, Dict[str, Any]] where inner dict is attr -> value
        restored: Dict[str, Dict[str, Any]] = {}
        for comp_key, comp_data in comp_snaps.items():
            comp_attrs: Dict[str, Any] = {}
            for attr, info in comp_data.items():
                if isinstance(info, dict) and "value" in info:
                    if info.get("hook"):
                        comp_attrs[attr] = HookedState(info["value"])
                    elif "wire_tag" in info:
                        tag = info["wire_tag"]
                        factory = _WIRE_TAG_TO_FACTORY.get(tag)
                        if factory:
                            comp_attrs[attr] = factory(info["value"])
                        else:
                            comp_attrs[attr] = info["value"]
                    else:
                        comp_attrs[attr] = info["value"]
                else:
                    comp_attrs[attr] = info
            if comp_attrs:
                restored[comp_key] = comp_attrs
        page._component_state_snapshots.update(restored)
    return True
