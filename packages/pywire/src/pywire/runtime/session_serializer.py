"""Session state serialization for PyWire.

Converts live BasePage instances to/from plain dicts suitable for
storage in a SessionStore (memory or Redis). Generalizes the
hot-reload state migration pattern from websocket.py broadcast_reload.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Set

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
    "slots",
    "errors",
    "loading",
    "user",
    "attrs",
    "head_slots",
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
    "primitive": lambda v: wire(v),
    "list": lambda v: wire(v),
    "dict": lambda v: wire(v),
    "set": lambda v: wire(set(v) if isinstance(v, list) else v),
    "namespace": lambda v: wire(**v) if isinstance(v, dict) else wire(v),
}


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


def snapshot_page_state(
    page: Any, *, warn_size: int = 0
) -> Dict[str, Any]:
    """Extract serializable user state from a BasePage instance.

    Args:
        page: The BasePage instance to snapshot.
        warn_size: If > 0, log a warning when the snapshot exceeds this
            many bytes. Set via ``PyWire(session_warn_size=...)``.

    Returns a dict with:
    - "attrs": user-defined attributes (wire values peeked to raw)
    - "wire_tags": maps attr name to wire type tag for reconstruction
    - "errors": page.errors dict
    - "loading": page.loading dict
    - "user": page.user (if serializable)
    - "await_states": page._await_states
    - "component_snapshots": nested component state
    - "page_class": qualified class name for lookup
    - "route_path": current URL path
    """
    snapshot: Dict[str, Any] = {}
    attrs: Dict[str, Any] = {}
    wire_tags: Dict[str, str] = {}

    for name, value in page.__dict__.items():
        # Skip private/framework attributes
        if name.startswith("_"):
            continue
        if name in _FRAMEWORK_ATTRS:
            continue

        # Handle wire types
        if isinstance(value, WireBase):
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
            logger.warning(
                "Skipping non-serializable attr '%s' (%s) on %s",
                name,
                type(value).__name__,
                type(page).__name__,
            )

    snapshot["attrs"] = attrs
    snapshot["wire_tags"] = wire_tags

    # Framework-managed state that should persist
    snapshot["errors"] = dict(page.errors) if page.errors else {}
    snapshot["loading"] = dict(page.loading) if page.loading else {}

    # User identity
    if hasattr(page, "user") and page.user is not None:
        if _is_serializable(page.user):
            snapshot["user"] = page.user
        else:
            # Try to serialize just the user's serializable attributes
            logger.debug("User object not directly serializable, skipping")

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
            if attr in {"request", "params", "query", "path", "url"}:
                continue
            if isinstance(value, WireBase):
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

    # Page identification for restoration
    snapshot["page_class"] = type(page).__qualname__
    if hasattr(page, "request") and hasattr(page.request, "url"):
        snapshot["route_path"] = str(page.request.url.path)

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


def restore_page_state(page: Any, snapshot: Dict[str, Any]) -> None:
    """Inject saved state into a fresh BasePage instance.

    The page should already be instantiated with the correct request,
    params, query, and path. This function restores user-defined state
    from a snapshot dict.

    Wire dependency tracking rebuilds naturally on the next render() call.
    """
    attrs = snapshot.get("attrs", {})
    wire_tags = snapshot.get("wire_tags", {})

    for name, value in attrs.items():
        try:
            current = getattr(page, name, None)
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
                        setattr(page, name, factory(value))
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

    # Restore framework-managed state
    if "errors" in snapshot:
        page.errors.update(snapshot["errors"])
    if "loading" in snapshot:
        page.loading.update(snapshot["loading"])
    if "user" in snapshot:
        page.user = snapshot["user"]
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
                    if "wire_tag" in info:
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
