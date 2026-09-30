"""Wire -> region subscriptions a stateless snapshot carries.

A stateless event rebuilds the page from the client's snapshot. Region diffs
need each wire mapped to the regions that read it, and only a render
registers that, so every event used to start with a render whose HTML was
thrown away. The snapshot now carries the map instead, and the endpoint
skips the render when it can restore the map.

Only pages whose reads are all of wires the snapshot rebuilds qualify. A page
with components, refs, snippets, dynamic regions, await blocks or shared
state still takes the discard render.
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

from pywire.core.wire import WireBase, WireDict, WireList, WireNamespace

logger = logging.getLogger(__name__)

# A wire's address: [page attribute, *steps]. A step is a list index or a
# dict key; both are msgpack-native.
_Path = List[Any]
_Entry = List[Any]  # [path, field, sorted regions]


def _attr_roots(page: Any) -> Dict[int, str]:
    """``id(wire)`` -> attribute name, for the wires the snapshot restores."""
    from pywire.runtime.session_serializer import _FRAMEWORK_ATTRS, _owned_by

    owned = _owned_by(page)
    roots: Dict[int, str] = {}
    for name, value in page.__dict__.items():
        if name.startswith("_") or name in _FRAMEWORK_ATTRS:
            continue
        if isinstance(value, WireBase) and not value._locked and owned(value):
            roots[id(value)] = name
    return roots


def _index_wires(page: Any, roots: Dict[int, str]) -> Dict[int, _Path]:
    """``id(wire)`` -> address, for every root wire and row proxy under it."""
    paths: Dict[int, _Path] = {}
    pending: List[Tuple[WireBase, _Path]] = []
    for name, value in page.__dict__.items():
        if roots.get(id(value)) == name:
            pending.append((value, [name]))
    while pending:
        node, path = pending.pop()
        paths[id(node)] = path
        if isinstance(node, WireList):
            for i, child in enumerate(list.__iter__(node)):
                if isinstance(child, WireBase):
                    pending.append((child, path + [i]))
        elif isinstance(node, WireDict):
            for key, child in dict.items(node):
                if isinstance(child, WireBase):
                    if not isinstance(key, (str, int)):
                        continue
                    pending.append((child, path + [key]))
    return paths


def _simple(page: Any) -> bool:
    """True when a render leaves nothing behind but the subscription map."""
    return not (
        page._components
        or page._refs_by_id
        or page._snippet_invocations
        or page._await_states
        or page._auth_states
        or page._background_tasks
        or page._pending_dispatches
        or page._pw_has_uploads
        or getattr(page, "__dynamic_regions__", None)
    )


def export_subscriptions(page: Any) -> Optional[List[_Entry]]:
    """The page's subscription map, or None when it can't be restored."""
    subscribers = getattr(page, "_wire_subscribers", None)
    if not subscribers or not _simple(page):
        return None
    roots = _attr_roots(page)
    paths = _index_wires(page, roots)
    entries: List[_Entry] = []
    for (source, field), regions in subscribers.items():
        # Namespace reads register on the namespace by field name; their
        # children are replaced by raw values on restore, so only the
        # namespace itself is addressable.
        if not isinstance(source, WireBase) or isinstance(
            source._parent, WireNamespace
        ):
            return None
        path = paths.get(id(source))
        if path is None or not isinstance(field, str):
            return None
        entries.append(
            [path, field, sorted(regions, key=lambda r: (r is None, r or ""))]
        )
    return entries


def _resolve(page: Any, path: Any) -> Optional[WireBase]:
    if not isinstance(path, list) or not path or not isinstance(path[0], str):
        return None
    node = getattr(page, path[0], None)
    if not isinstance(node, WireBase):
        return None
    for step in path[1:]:
        if isinstance(node, WireList):
            if not isinstance(step, int) or not 0 <= step < list.__len__(node):
                return None
            child = node._proxy_slot(step)
        elif isinstance(node, WireDict):
            if not dict.__contains__(node, step):
                return None
            child = node._proxy_entry(step)
        else:
            return None
        if not isinstance(child, WireBase):
            return None
        node = child
    return node


def restore_subscriptions(page: Any, entries: Any) -> bool:
    """Rebuild ``page``'s subscription map from ``export_subscriptions``.

    False, with the page untouched, when the page can't take it (a stale
    snapshot, or a page that has since gained components, refs, ...): the
    caller renders instead.
    """
    if not isinstance(entries, list) or not _simple(page):
        return False
    resolved: List[Tuple[WireBase, str, frozenset]] = []
    try:
        for entry in entries:
            path, field, regions = entry
            wire = _resolve(page, path)
            if wire is None or not isinstance(field, str):
                return False
            resolved.append((wire, field, frozenset(regions)))
    except Exception:
        logger.debug("stateless: subscription map unusable", exc_info=True)
        return False
    for wire, field, regions in resolved:
        key = (wire, field)
        page._wire_subscribers[key] = page._shared_regions(regions)
        for region in regions:
            page._region_dependencies[region].add(key)
        wire._add_page(page)
    return True
