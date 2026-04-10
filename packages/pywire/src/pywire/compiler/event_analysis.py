"""Static analysis of event handler functions to determine which event fields they access."""

import ast
from typing import Optional, Set

# Mapping from Python snake_case field names to JS camelCase field names.
# This must stay in sync with the field names used in runtime/events.py
# and client/src/events/handler.ts.
SNAKE_TO_CAMEL = {
    "client_x": "clientX",
    "client_y": "clientY",
    "offset_x": "offsetX",
    "offset_y": "offsetY",
    "page_x": "pageX",
    "page_y": "pageY",
    "screen_x": "screenX",
    "screen_y": "screenY",
    "alt_key": "altKey",
    "ctrl_key": "ctrlKey",
    "meta_key": "metaKey",
    "shift_key": "shiftKey",
    "key_code": "keyCode",
    "input_type": "inputType",
    "form_data": "formData",
    "target_id": "id",
    "target_name": "name",
    "target_tag": "tagName",
}


def analyze_event_fields(handler_source: str) -> Optional[Set[str]]:
    """Analyze a handler function to determine which event fields it accesses.

    Returns a set of camelCase field names the handler uses, or None if
    static analysis cannot determine usage (e.g. handler uses **kwargs,
    passes the event object to another function, or has a syntax error).
    When None is returned, all fields should be sent (no filtering).
    """
    try:
        tree = ast.parse(handler_source)
    except SyntaxError:
        return None  # Can't analyze, send everything

    visitor = _EventFieldVisitor()
    visitor.visit(tree)

    if visitor.needs_full_event:
        return None

    return visitor.fields


class _EventFieldVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.fields: Set[str] = set()
        self.needs_full_event = False
        self._event_names = {"event", "event_data"}

    def visit_Assign(self, node: ast.Assign) -> None:
        # Track aliases: `e = event` adds 'e' to _event_names
        if isinstance(node.value, ast.Name) and node.value.id in self._event_names:
            for target in node.targets:
                if isinstance(target, ast.Name):
                    self._event_names.add(target.id)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        # Track annotated aliases: `e: EventData = event`
        if (
            node.value
            and isinstance(node.value, ast.Name)
            and node.value.id in self._event_names
            and isinstance(node.target, ast.Name)
        ):
            self._event_names.add(node.target.id)
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        # event.key, event_data.client_x, etc.
        if isinstance(node.value, ast.Name) and node.value.id in self._event_names:
            snake = node.attr
            camel = SNAKE_TO_CAMEL.get(snake, snake)
            self.fields.add(camel)
        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        # event['key'], event_data['client_x'], etc.
        if isinstance(node.value, ast.Name) and node.value.id in self._event_names:
            if isinstance(node.slice, ast.Constant) and isinstance(
                node.slice.value, str
            ):
                snake = node.slice.value
                camel = SNAKE_TO_CAMEL.get(snake, snake)
                self.fields.add(camel)
            else:
                # event[some_var] — dynamic, can't determine field
                self.needs_full_event = True
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        # getattr(event, ...) or event passed to another function
        for arg in node.args:
            if isinstance(arg, ast.Name) and arg.id in self._event_names:
                self.needs_full_event = True
        for kw in node.keywords:
            if isinstance(kw.value, ast.Name) and kw.value.id in self._event_names:
                self.needs_full_event = True
        self.generic_visit(node)

    def visit_Starred(self, node: ast.Starred) -> None:
        # **event or *event
        if isinstance(node.value, ast.Name) and node.value.id in self._event_names:
            self.needs_full_event = True
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        # Check if handler has **kwargs
        if node.args.kwarg:
            self.needs_full_event = True
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        # Same check for async handlers
        if node.args.kwarg:
            self.needs_full_event = True
        self.generic_visit(node)
