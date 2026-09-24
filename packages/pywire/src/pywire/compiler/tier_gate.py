"""Deployment-tier gating for template features.

``{$await}`` blocks need a server that holds the timeline between
requests; the stateless tier round-trips state in signed snapshots and
has no such server, so pages using ``{$await}`` are rejected at
compile time. ``PyWire.__init__`` sets the flag; every compile path
(dev loader, ``pywire build`` artifacts) runs the check. ``async def``
event handlers are unaffected — they are awaited inside the request.
"""

from pywire.compiler.ast_nodes import AwaitAttribute, ParsedPyWire, TemplateNode
from pywire.compiler.exceptions import PyWireSyntaxError

_stateless_tier = False


def set_stateless_tier(stateless: bool) -> None:
    global _stateless_tier
    _stateless_tier = stateless


def check_tier(parsed: ParsedPyWire) -> None:
    """Raise if the parsed page uses ``{$await}`` in a stateless app."""
    if not _stateless_tier:
        return
    attr = _find_await(parsed.template)
    if attr is None:
        return
    raise PyWireSyntaxError(
        "{$await} blocks are not available in stateless apps "
        "(PyWire(stateless=True)) — the server holds no timeline between "
        "requests. Use @poll for background work, or run the stateful "
        "tier (remove stateless=True).",
        file_path=parsed.file_path,
        line=attr.line,
        column=attr.column,
    )


def _find_await(nodes):
    for node in nodes:
        if not isinstance(node, TemplateNode):
            continue
        for attr in node.special_attributes:
            if isinstance(attr, AwaitAttribute):
                return attr
        found = _find_await(node.children)
        if found is not None:
            return found
    return None
