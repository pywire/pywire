"""Wire -> region subscriptions a stateless snapshot carries.

A stateless event rebuilds the page from the client's snapshot. Region diffs
need each wire mapped to the regions that read it, and only a render
registers that, so every event used to start with a render whose HTML was
thrown away. The snapshot now carries the map instead, and the endpoint
skips the render when it can restore the map.

Most of a list page's map is one entry per row. Two rules state those rows
once per list instead:

- a row rule: row ``j`` is shown by region ``<site>#<key j>`` of a keyed
  ``{$for}``, the key being ``j`` itself or a field of the row;
- an each rule: some regions read every row (a sorted or filtered loop, a
  "3 done" count).

The restored page resolves a rule only when a handler writes a row
(``RowSubscriptions``), so neither the snapshot nor the restore grows with
the list. A list write reaches its container as a write to field ``str(j)``,
which is what the rules answer.

Only pages whose reads are all of wires the snapshot rebuilds qualify, and
whose components (a layout, say) read no wires at all, so that skipping
their render changes nothing. A page with refs, snippets, dynamic regions,
await blocks, shared state or a component that reads state still takes the
discard render. The map is bound to the page's source, so a deploy that
edits the template renders once to learn the new one.
"""

import hashlib
import logging
import os
from typing import Any, Collection, Dict, Iterable, List, Optional, Set, Tuple

from pywire.core.wire import WireBase, WireDict, WireList, WireNamespace

logger = logging.getLogger(__name__)

# A wire's address: [page attribute, *steps]. A step is a list index or a
# dict key; both are msgpack-native.
_Path = List[Any]
# Snapshot wire entry: [path, field, regions] or [path, field, regions, rows],
# where ``rows`` are indexes of row rules whose every region reads the wire.
_Entry = List[Any]
_Region = Optional[str]  # None is the page root

# A rule over one event:
_ACTIVE = 0  # describes the page's map
_STALE = 1  # its list was reshaped; rows no longer match what was read
_RERENDERED = 2  # its readers all re-rendered, registering the rows anew


class _Rule:
    """Rows of ``container``. ``readers`` are the regions whose render reads
    every row: once they have all re-rendered, the page's own map holds the
    rows as they are now (or no longer shows them), and the rule is learned
    anew from it."""

    __slots__ = ("path", "container", "readers", "state", "_pending")

    def __init__(
        self, path: _Path, container: WireBase, readers: Collection[_Region]
    ) -> None:
        self.path = path
        self.container = container
        self.readers = readers
        self.state = _ACTIVE
        self._pending: Set[_Region] = set(readers)

    def reshaped(self) -> None:
        if self.state == _ACTIVE:
            self.state = _STALE

    def rendered(self, region: _Region) -> None:
        self._pending.discard(region)
        if not self._pending:
            self.state = _RERENDERED

    def regions_for(self, child: str) -> Iterable[_Region]:
        raise NotImplementedError

    def covers(self, child: str) -> Set[_Region]:
        """What this rule says about the subtree of ``child``."""
        return set(self.regions_for(child))


class _RowRule(_Rule):
    """Child ``j`` is shown by region ``<site>#<key j>``, which re-renders on
    any write under it. ``field`` names the row field holding the key; None
    means the key is the child's list index or dict key. ``readers`` read
    the list's shape: it is their render that lays out the rows."""

    __slots__ = ("site", "field", "keys")

    def __init__(
        self,
        path: _Path,
        container: WireBase,
        readers: Collection[_Region],
        site: str,
        field: Optional[str],
        keys: Optional[Dict[str, str]],
    ) -> None:
        super().__init__(path, container, readers)
        self.site = site
        self.field = field
        # Child -> key, taken at restore: a handler may write the key field
        # before the write that needs the old key's region.
        self.keys = keys

    def region(self, child: str) -> Optional[str]:
        key = child if self.keys is None else self.keys.get(child)
        return None if key is None else f"{self.site}#{key}"

    def regions_for(self, child: str) -> Iterable[_Region]:
        if self.state != _ACTIVE:
            # Positions moved; the readers re-render every row.
            return ()
        region = self.region(child)
        return () if region is None else (region,)

    def size(self) -> int:
        return len(self.keys) if self.keys is not None else _size(self.container)

    def regions(self) -> Set[str]:
        prefix = self.site + "#"
        if self.keys is not None:
            return {prefix + key for key in self.keys.values()}
        return {prefix + str(child) for child, _row in _children(self.container)}


class _EachRule(_Rule):
    """``shared`` regions read every row; a write under any of them dirties them
    all. They are their own readers: their render re-reads every row."""

    __slots__ = ("shared",)

    def __init__(self, path: _Path, container: WireBase, shared: frozenset) -> None:
        super().__init__(path, container, shared)
        self.shared = shared

    def regions_for(self, child: str) -> Iterable[_Region]:
        return self.shared


class RowSubscriptions:
    """A restored page's rules, resolved when a handler writes a row.

    ``BasePage._invalidate_wire`` asks ``regions`` for the regions a write
    dirties beyond the page's own map, and ``_begin_region_render`` reports
    renders so ``export_subscriptions`` knows which rules still hold.
    """

    def __init__(
        self,
        rules: List[_Rule],
        wildcards: Dict[Tuple[WireBase, str], List[_RowRule]],
    ) -> None:
        self.rules = rules
        # (wire, field) -> row rules whose every region reads that wire.
        self.wildcards = wildcards
        self._by_container: Dict[int, List[_Rule]] = {}
        self._by_reader: Dict[_Region, List[_Rule]] = {}
        for rule in rules:
            self._by_container.setdefault(id(rule.container), []).append(rule)
            for region in rule.readers:
                self._by_reader.setdefault(region, []).append(rule)

    def regions(self, wire: Any, field: str) -> Set[_Region]:
        found: Set[_Region] = set()
        for rule in self._by_container.get(id(wire), ()):
            if rule.container is not wire:
                continue
            if field == "value":
                # Reshaped (append, delete, sort, replace...). Whoever read
                # its shape is dirty now, as the page's own map says.
                rule.reshaped()
            else:
                found.update(rule.regions_for(field))
        for rule in self.wildcards.get((wire, field), ()):
            if rule.state == _ACTIVE:
                found |= rule.regions()
        return found

    def region_rendered(self, region_id: _Region) -> None:
        for rule in self._by_reader.get(region_id, ()):
            rule.rendered(region_id)


def _children(container: Any) -> Iterable[Tuple[Any, Any]]:
    if isinstance(container, WireList):
        return enumerate(list.__iter__(container))
    return dict.items(container)


def _size(container: Any) -> int:
    if isinstance(container, WireList):
        return list.__len__(container)
    return dict.__len__(container)


def _row_keys(container: Any, field: str) -> Optional[Dict[str, str]]:
    """Child -> ``str(row[field])`` for every row, or None if a row has no
    such scalar field."""
    keys: Dict[str, str] = {}
    for child, row in _children(container):
        if not isinstance(row, dict):
            return None
        value = dict.get(row, field)
        if not isinstance(value, (str, int, float)):
            return None
        keys[str(child)] = str(value)
    return keys


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


def _detached(wire: WireBase, page: Any, restored: Collection[str]) -> bool:
    """True when ``wire`` was cut from a restored wire's tree (a deleted row,
    a slice copy). No later event can reach it, so its reads don't matter."""
    chain = [wire]
    while chain[-1]._parent is not None:
        chain.append(chain[-1]._parent)  # type: ignore[arg-type]
    root = chain[-1]
    if not any(page.__dict__.get(name) is root for name in restored):
        return False
    for node, parent in zip(chain, chain[1:]):
        if isinstance(parent, WireList):
            held = any(child is node for child in list.__iter__(parent))
        elif isinstance(parent, WireDict):
            held = any(child is node for child in dict.values(parent))
        else:
            return False
        if not held:
            return True
    return False


def _lookup(page: Any, path: _Path) -> Optional[WireBase]:
    """The wire at ``path``, without creating row proxies."""
    node = page.__dict__.get(path[0])
    for step in path[1:]:
        if isinstance(node, WireList):
            if not isinstance(step, int) or not 0 <= step < list.__len__(node):
                return None
            node = list.__getitem__(node, step)
        elif isinstance(node, WireDict):
            if not dict.__contains__(node, step):
                return None
            node = dict.__getitem__(node, step)
        else:
            return None
    return node if isinstance(node, WireBase) else None


def _quiet(node: Any) -> bool:
    """Nothing a render left on ``node`` that an event could need."""
    return not (
        node._refs_by_id
        or node._await_states
        or node._auth_states
        or node._background_tasks
        or node._pending_dispatches
        or node._pw_has_uploads
        or getattr(node, "__dynamic_regions__", None)
    )


def _inert(component: Any) -> bool:
    """A component (a layout, say) that reads no wires and guards nothing:
    an event that skips rendering it can't change what it shows."""
    return (
        _quiet(component)
        and not component._wire_subscribers
        and not getattr(type(component), "__auth_required__", False)
        and all(_inert(child) for child in component._components.values())
    )


def _simple(page: Any) -> bool:
    """True when a render leaves nothing behind but the subscription map."""
    return (
        _quiet(page)
        and not page._snippet_invocations
        and all(_inert(component) for component in page._components.values())
    )


_digests: Dict[str, Tuple[int, str]] = {}


def _source(page: Any) -> str:
    """Digest of the page's ``.wire`` source, which numbers its regions."""
    path = getattr(type(page), "__file_path__", None)
    if not path:
        return ""
    try:
        mtime = os.stat(path).st_mtime_ns
    except OSError:
        return ""
    cached = _digests.get(path)
    if cached is None or cached[0] != mtime:
        with open(path, "rb") as f:
            digest = hashlib.blake2b(f.read(), digest_size=8).hexdigest()
        cached = _digests[path] = (mtime, digest)
    return cached[1]


def _sort_regions(regions: Iterable[_Region]) -> List[_Region]:
    return sorted(regions, key=lambda r: (r is None, r or ""))


class _Draft:
    """One wire entry on its way into the snapshot."""

    __slots__ = ("path", "field", "regions", "rows")

    def __init__(self, path: _Path, field: str) -> None:
        self.path = path
        self.field = field
        self.regions: Set[_Region] = set()
        self.rows: Set[int] = set()  # id() of row rules every region reads


def _under(draft: _Draft, rule: _Rule) -> Optional[str]:
    """The child of ``rule``'s list whose subtree holds ``draft``'s wire."""
    depth = len(rule.path)
    path = draft.path
    if len(path) > depth and path[:depth] == rule.path:
        return str(path[depth])
    return None


def _apply(rule: _Rule, drafts: List[_Draft]) -> None:
    """Drop from ``drafts`` what ``rule`` already says."""
    row = rule if isinstance(rule, _RowRule) else None
    size = row.size() if row is not None else 0
    every: Optional[Set[str]] = None
    for draft in drafts:
        child = _under(draft, rule)
        if child is not None:
            draft.regions -= rule.covers(child)
        if row is not None and len(draft.regions) >= size:
            if every is None:
                every = row.regions()
            if every <= draft.regions:
                draft.regions -= every
                draft.rows.add(id(row))


def _learn_rows(
    page: Any,
    drafts: List[_Draft],
    subscribers: Dict[Tuple[Any, str], Any],
    known: Set[Tuple[Tuple[Any, ...], str]],
) -> List[_RowRule]:
    """Row rules the map satisfies exactly, beyond ``known``.

    A candidate comes from an entry whose path passes through child ``j`` of
    a list and whose regions include ``<site>#<key>`` of a keyed loop, where
    ``key`` is ``j`` itself or a field of row ``j``. It holds when every
    child of that list is read under its own region that way, and some
    region reads the list's shape (and so lays out the rows).
    """
    sites = set(getattr(page, "__keyed_region_renderers__", None) or ())
    if not sites:
        return []
    candidates: Dict[Tuple[Tuple[Any, ...], str, Optional[str]], None] = {}
    by_field: Set[str] = set()  # sites a row field already explains
    for draft in drafts:
        path = draft.path
        if len(path) < 2:
            continue
        for region in _sort_regions(draft.regions):
            if region is None:
                continue
            site, sep, key = region.partition("#")
            if not sep or site not in sites:
                continue
            matched = False
            for m in range(1, len(path)):
                if str(path[m]) == key:
                    matched = True
                    candidates[(tuple(path[:m]), site, None)] = None
            if matched or site in by_field:
                continue
            # Keyed by a row field? Try this row's fields. (Not every entry
            # names its own row: a region may read its neighbour too.)
            for m in range(1, len(path)):
                row = _lookup(page, path[: m + 1])
                if not isinstance(row, dict):
                    continue
                for name, value in dict.items(row):
                    if (
                        isinstance(name, str)
                        and isinstance(value, (str, int, float))
                        and str(value) == key
                    ):
                        candidates[(tuple(path[:m]), site, name)] = None
                        by_field.add(site)

    rules: List[_RowRule] = []
    for cpath, site, field in candidates:
        if (cpath, site) in known:
            continue
        rule = _verify_rows(page, list(cpath), site, field, drafts, subscribers)
        if rule is not None:
            rules.append(rule)
            known.add((cpath, site))
    return rules


def _verify_rows(
    page: Any,
    cpath: _Path,
    site: str,
    field: Optional[str],
    drafts: List[_Draft],
    subscribers: Dict[Tuple[Any, str], Any],
) -> Optional[_RowRule]:
    container = _lookup(page, cpath)
    if not isinstance(container, (WireList, WireDict)):
        return None
    readers = subscribers.get((container, "value"))
    if not readers:
        return None
    keys = None if field is None else _row_keys(container, field)
    if field is not None and keys is None:
        return None
    rule = _RowRule(cpath, container, readers, site, field, keys)
    expected = {
        str(child): rule.region(str(child)) for child, _ in _children(container)
    }
    size = _size(container)
    if not size or len(expected) != size or len(set(expected.values())) != size:
        return None
    witnessed = {
        child
        for draft in drafts
        if (child := _under(draft, rule)) is not None
        and expected.get(child) in draft.regions
    }
    return rule if len(witnessed) == size else None


def _learn_each(page: Any, drafts: List[_Draft]) -> List[_EachRule]:
    """Each rules the map satisfies exactly: regions that some entry under
    every child of a list names."""
    seen: Dict[Tuple[Tuple[Any, ...], _Region], Set[str]] = {}
    for draft in drafts:
        path = draft.path
        for m in range(1, len(path)):
            prefix, child = tuple(path[:m]), str(path[m])
            for region in draft.regions:
                seen.setdefault((prefix, region), set()).add(child)
    by_list: Dict[Tuple[Any, ...], Tuple[WireBase, Set[_Region]]] = {}
    for (prefix, region), children in seen.items():
        container = _lookup(page, list(prefix))
        if not isinstance(container, (WireList, WireDict)):
            continue
        if len(children) == _size(container) and children == {
            str(child) for child, _ in _children(container)
        }:
            by_list.setdefault(prefix, (container, set()))[1].add(region)
    return [
        _EachRule(list(prefix), container, frozenset(regions))
        for prefix, (container, regions) in by_list.items()
    ]


def export_subscriptions(
    page: Any, restored: Collection[str]
) -> Optional[Dict[str, Any]]:
    """The page's subscription map, or None when it can't be restored.

    ``restored`` names the wire attributes the snapshot carries.
    """
    subscribers = getattr(page, "_wire_subscribers", None)
    if not subscribers or not _simple(page):
        return None
    lazy: Optional[RowSubscriptions] = getattr(page, "_row_subscriptions", None)
    kept: List[_Rule] = []
    if lazy is not None:
        for rule in lazy.rules:
            if rule.state == _STALE:
                # Reshaped, and the regions that read its rows never
                # re-rendered: nothing describes the rows.
                return None
            if rule.state == _ACTIVE:
                if _lookup(page, rule.path) is not rule.container:
                    return None
                kept.append(rule)
            # _RERENDERED: those renders registered every row; learn anew.

    paths = _index_wires(page, restored)
    drafts: Dict[Tuple[int, str], _Draft] = {}

    def draft_for(source: Any, field: Any) -> Optional[_Draft]:
        # Namespace reads register on the namespace by field name; their
        # children are replaced by raw values on restore, so only the
        # namespace itself is addressable.
        if not isinstance(source, WireBase) or isinstance(
            source._parent, WireNamespace
        ):
            raise LookupError
        path = paths.get(id(source))
        if path is None or not isinstance(field, str):
            if path is None and _detached(source, page, restored):
                return None
            raise LookupError
        draft = drafts.get((id(source), field))
        if draft is None:
            draft = drafts[(id(source), field)] = _Draft(path, field)
        return draft

    try:
        for (source, field), regions in subscribers.items():
            draft = draft_for(source, field)
            if draft is not None:
                draft.regions |= regions
        if lazy is not None:
            for (source, field), wild in lazy.wildcards.items():
                active = [id(rule) for rule in wild if rule.state == _ACTIVE]
                if active:
                    draft = draft_for(source, field)
                    if draft is not None:
                        draft.rows.update(active)
    except LookupError:
        return None

    entries = list(drafts.values())
    rows = [rule for rule in kept if isinstance(rule, _RowRule)]
    each = [rule for rule in kept if isinstance(rule, _EachRule)]
    rows += _learn_rows(
        page, entries, subscribers, {(tuple(r.path), r.site) for r in rows}
    )
    for rule in [*rows, *each]:
        _apply(rule, entries)
    learned = _learn_each(page, entries)
    for rule in learned:
        _apply(rule, entries)
    each += learned

    index = {id(rule): i for i, rule in enumerate(rows)}
    wires: List[_Entry] = []
    for draft in entries:
        if not draft.regions and not draft.rows:
            continue
        entry: _Entry = [draft.path, draft.field, _sort_regions(draft.regions)]
        if draft.rows:
            entry.append(sorted(index[r] for r in draft.rows))
        wires.append(entry)
    subs: Dict[str, Any] = {"src": _source(page), "wires": wires}
    if rows:
        subs["rows"] = [[rule.path, rule.site, rule.field] for rule in rows]
    if each:
        subs["each"] = [[rule.path, _sort_regions(rule.shared)] for rule in each]
    return subs


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


def _resolve_list(page: Any, path: Any) -> WireBase:
    container = _resolve(page, path)
    if not isinstance(container, (WireList, WireDict)):
        raise LookupError(path)
    return container


def restore_subscriptions(page: Any, subs: Any) -> bool:
    """Rebuild ``page``'s subscription map from ``export_subscriptions``.

    False, with the page untouched, when the page can't take it (a snapshot
    from before the page's source changed, a map naming rows it no longer
    has): the caller renders instead.
    """
    if not isinstance(subs, dict) or not _simple(page):
        return False
    if subs.get("src") != _source(page):
        return False
    rows: List[Tuple[_Path, WireBase, str, Optional[str], Optional[Dict]]] = []
    each: List[Tuple[_Path, WireBase, frozenset]] = []
    wires: List[Tuple[WireBase, str, frozenset, List[int]]] = []
    try:
        for cpath, site, field in subs.get("rows", ()):
            container = _resolve_list(page, cpath)
            keys = None
            if field is not None:
                keys = _row_keys(container, field)
                if keys is None:
                    return False
            rows.append((cpath, container, str(site), field, keys))
        for cpath, regions in subs.get("each", ()):
            each.append((cpath, _resolve_list(page, cpath), frozenset(regions)))
        for entry in subs["wires"]:
            path, field, regions = entry[:3]
            wild = entry[3] if len(entry) > 3 else []
            wire = _resolve(page, path)
            if wire is None or not isinstance(field, str):
                return False
            if not all(isinstance(i, int) and 0 <= i < len(rows) for i in wild):
                return False
            wires.append((wire, field, frozenset(regions), wild))
    except Exception:
        logger.debug("stateless: subscription map unusable", exc_info=True)
        return False

    for wire, field, regions, _wild in wires:
        if regions:
            key = (wire, field)
            page._wire_subscribers[key] = page._shared_regions(regions)
            for region in regions:
                page._region_dependencies[region].add(key)
        wire._add_page(page)
    if not rows and not each:
        return True
    row_rules = [
        _RowRule(
            cpath,
            container,
            page._wire_subscribers.get((container, "value"), frozenset()),
            site,
            field,
            keys,
        )
        for cpath, container, site, field, keys in rows
    ]
    rules: List[_Rule] = [
        *row_rules,
        *(_EachRule(cpath, c, regions) for cpath, c, regions in each),
    ]
    for rule in rules:
        rule.container._add_page(page)
    wildcards = {
        (wire, field): [row_rules[i] for i in wild]
        for wire, field, _regions, wild in wires
        if wild
    }
    page._row_subscriptions = RowSubscriptions(rules, wildcards)
    return True
