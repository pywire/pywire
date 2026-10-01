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
from typing import Any, Collection, Dict, List, Optional, Tuple

from pywire.core.wire import WireBase, WireDict, WireList, WireNamespace

logger = logging.getLogger(__name__)

# A wire's address: [page attribute, *steps]. A step is a list index or a
# dict key; both are msgpack-native.
_Path = List[Any]
_Entry = List[Any]  # [path, field, sorted regions]


def _index_wires(page: Any, restored: Collection[str]) -> Dict[int, _Path]:
    """``id(wire)`` -> address, for every wire the snapshot restores (the
    ``restored`` page attributes) and every row proxy under one.

    Any other wire (locked, shared, a producer or ref, a value the snapshot
    could not serialize) is rebuilt by the frontmatter, not the snapshot, so
    an address into it might name something else on the next request.
    """
    paths: Dict[int, _Path] = {}
    pending: List[Tuple[WireBase, _Path]] = []
    for name in restored:
        value = page.__dict__.get(name)
        if isinstance(value, WireBase):
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


def export_subscriptions(
    page: Any, restored: Collection[str]
) -> Optional[List[_Entry]]:
    """The page's subscription map, or None when it can't be restored.

    ``restored`` names the wire attributes the snapshot carries.
    """
    subscribers = getattr(page, "_wire_subscribers", None)
    if not subscribers or not _simple(page):
        return None
    paths = _index_wires(page, restored)
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
