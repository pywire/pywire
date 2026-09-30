"""Static analysis of event handler functions to determine which event fields they access."""

import ast
from typing import Dict, Optional, Set

from pywire.runtime.events import EVENT_PARAMS

# FormEventData reads like a mapping of the submitted fields.
FORM_MAPPING_METHODS = frozenset({"keys", "values", "items"})


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
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            visitor.parents[child] = parent
    visitor.visit(tree)

    if visitor.needs_full_event:
        return None

    return visitor.fields


class _EventFieldVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.fields: Set[str] = set()
        self.needs_full_event = False
        self._event_names = {"event", "event_data"}
        self._seen_handler = False
        self.parents: Dict[ast.AST, ast.AST] = {}

    def visit_Assign(self, node: ast.Assign) -> None:
        # Track aliases: `e = event` adds 'e' to _event_names
        if isinstance(node.value, ast.Name) and node.value.id in self._event_names:
            for target in node.targets:
                if isinstance(target, ast.Name):
                    self._event_names.add(target.id)
                else:
                    # a, *b = event: unpacks it, so send everything
                    self.needs_full_event = True
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
            if node.attr == "get":
                # event.get(name): a dynamic lookup, send everything
                self.needs_full_event = True
            if node.attr in FORM_MAPPING_METHODS:
                # data.items() and friends read the submitted fields
                self.fields.add("formData")
            else:
                snake = node.attr
                camel = EVENT_PARAMS.get(snake, snake)
                self.fields.add(camel)
        self.generic_visit(node)

    def visit_For(self, node: ast.For) -> None:
        # for name in data: iterates the submitted field names
        if isinstance(node.iter, ast.Name) and node.iter.id in self._event_names:
            self.fields.add("formData")
        self.generic_visit(node)

    def visit_comprehension(self, node: ast.comprehension) -> None:
        if isinstance(node.iter, ast.Name) and node.iter.id in self._event_names:
            self.fields.add("formData")
        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        # event['key'], event_data['client_x'], etc.
        if isinstance(node.value, ast.Name) and node.value.id in self._event_names:
            if isinstance(node.slice, ast.Constant) and isinstance(
                node.slice.value, str
            ):
                snake = node.slice.value
                camel = EVENT_PARAMS.get(snake, snake)
                self.fields.add(camel)
                # Submit handlers subscript form fields: data["title"].
                self.fields.add("formData")
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

    def visit_Compare(self, node: ast.Compare) -> None:
        # "title" in event: a form-field membership test
        for op, right in zip(node.ops, node.comparators):
            if (
                isinstance(op, (ast.In, ast.NotIn))
                and isinstance(right, ast.Name)
                and right.id in self._event_names
            ):
                self.fields.add("formData")
        self.generic_visit(node)

    def visit_Dict(self, node: ast.Dict) -> None:
        # {**data}: unpacks the submitted fields
        for key, value in zip(node.keys, node.values):
            if (
                key is None
                and isinstance(value, ast.Name)
                and value.id in self._event_names
            ):
                self.fields.add("formData")
        self.generic_visit(node)

    def visit_Starred(self, node: ast.Starred) -> None:
        # **event or *event
        if isinstance(node.value, ast.Name) and node.value.id in self._event_names:
            self.needs_full_event = True
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        # Any use not handled above (return event, f"{event}", a tuple of
        # it...) lets the whole event escape, so send everything.
        if node.id in self._event_names and isinstance(node.ctx, ast.Load):
            if not _understood(node, self.parents.get(node)):
                self.needs_full_event = True

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_handler(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_handler(node)

    def _visit_handler(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        # Check if handler has **kwargs
        if node.args.kwarg:
            self.needs_full_event = True
        if not self._seen_handler:
            # The runtime passes the event to the first required parameter
            # whatever it is called (see BasePage dispatch), so `def
            # handle(data)` reads the event through `data`.
            self._seen_handler = True
            event_param = _first_required_param(node.args)
            if event_param:
                self._event_names.add(event_param)
        self.generic_visit(node)


def _understood(node: ast.Name, parent: Optional[ast.AST]) -> bool:
    """Whether the visitor above accounts for this use of the event name."""
    if isinstance(parent, (ast.Attribute, ast.Subscript)):
        return parent.value is node
    if isinstance(parent, (ast.For, ast.comprehension)):
        return parent.iter is node
    if isinstance(parent, ast.Compare):
        return any(
            right is node and isinstance(op, (ast.In, ast.NotIn))
            for op, right in zip(parent.ops, parent.comparators)
        )
    if isinstance(parent, ast.Dict):
        return any(k is None and v is node for k, v in zip(parent.keys, parent.values))
    if isinstance(parent, (ast.Assign, ast.AnnAssign)):
        return parent.value is node
    return False


def _first_required_param(args: ast.arguments) -> Optional[str]:
    positional = [*args.posonlyargs, *args.args]
    if positional and positional[0].arg == "self":
        positional = positional[1:]
    required = positional[: len(positional) - len(args.defaults)]
    if required:
        return required[0].arg
    for arg, default in zip(args.kwonlyargs, args.kw_defaults):
        if default is None:
            return arg.arg
    return None
