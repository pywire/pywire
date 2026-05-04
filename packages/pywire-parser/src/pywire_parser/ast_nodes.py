"""AST node definitions for PyWire compiler."""

import ast
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple, Union


@dataclass
class ASTNode:
    """Base for all AST nodes."""

    line: int
    column: int


@dataclass
class Directive(ASTNode):
    """Base for directives."""

    name: str


@dataclass
class PathDirective(Directive):
    """!path { 'name': '/route/{param}' } or !path '/route'"""

    routes: Dict[str, str]  # {'name': '/route/{param}'}
    is_simple_string: bool = False

    def __str__(self) -> str:
        return f"PathDirective(routes={self.routes}, simple={self.is_simple_string})"


@dataclass
class NoSpaDirective(Directive):
    """!no_spa - disables client-side SPA navigation for this page."""

    def __str__(self) -> str:
        return "NoSpaDirective()"


@dataclass
class NoInteractiveDirective(Directive):
    """!no_interactive - render this page statically; keep WS connection alive but skip event/wire wiring for this page."""

    def __str__(self) -> str:
        return "NoInteractiveDirective()"


@dataclass
class LayoutDirective(Directive):
    """!layout "path/to/layout.pywire" """

    layout_path: str

    def __str__(self) -> str:
        return f"LayoutDirective(path={self.layout_path})"


@dataclass
class PropsDirective(Directive):
    """!props(name: type, arg=default)"""

    # List of (name, type_hint_str, default_value_str_or_None)
    args: List[Tuple[str, str, Optional[str]]]

    def __str__(self) -> str:
        return f"PropsDirective(args={self.args})"


@dataclass
class AuthDirective(Directive):
    """!auth — gate page on authentication/policy.

    Forms:
        !auth                                        # require authenticated
        !auth "PolicyName"                           # named policy
        !auth {"policy":"X","claims":[...],"redirect":"/login"}
    """

    policy: Optional[str] = None
    # Each claim is (type, value). An empty value matches any value for that type.
    claims: Optional[List[Tuple[str, str]]] = None
    redirect: Optional[str] = None

    def __str__(self) -> str:
        return (
            f"AuthDirective(policy={self.policy}, "
            f"claims={self.claims}, redirect={self.redirect})"
        )


@dataclass
class SpecialAttribute(ASTNode):
    """Base for special attributes ($, @, :)."""

    name: str
    value: str


@dataclass
class KeyAttribute(SpecialAttribute):
    """$key={unique_id}."""

    expr: str

    def __str__(self) -> str:
        return f"KeyAttribute(expr={self.expr})"


@dataclass
class IfAttribute(SpecialAttribute):
    """$if={condition}."""

    condition: str

    def __str__(self) -> str:
        return f"IfAttribute(condition={self.condition})"


@dataclass
class ShowAttribute(SpecialAttribute):
    """$show={condition}."""

    condition: str

    def __str__(self) -> str:
        return f"ShowAttribute(condition={self.condition})"


@dataclass
class ForAttribute(SpecialAttribute):
    """$for={item in items}"."""

    is_template_tag: bool  # <template $for>
    loop_vars: str  # "item" or "key, value"
    iterable: str  # "items" or "items.items()"
    key: Optional[str] = None

    def __str__(self) -> str:
        return f"ForAttribute(vars={self.loop_vars}, in={self.iterable})"


@dataclass
class ElseAttribute(SpecialAttribute):
    """$else or {$else} marker."""

    def __str__(self) -> str:
        return "ElseAttribute()"


@dataclass
class ElifAttribute(SpecialAttribute):
    """$elif={condition} or {$elif condition}."""

    condition: str

    def __str__(self) -> str:
        return f"ElifAttribute(condition={self.condition})"


@dataclass
class TryAttribute(SpecialAttribute):
    """{$try} marker."""

    def __str__(self) -> str:
        return "TryAttribute()"


@dataclass
class ExceptAttribute(SpecialAttribute):
    """{$except Exception as e} marker."""

    exception_type: Optional[str] = None
    alias: Optional[str] = None

    def __str__(self) -> str:
        return f"ExceptAttribute(type={self.exception_type}, alias={self.alias})"


@dataclass
class FinallyAttribute(SpecialAttribute):
    """{$finally} marker."""

    def __str__(self) -> str:
        return "FinallyAttribute()"


@dataclass
class AwaitAttribute(SpecialAttribute):
    """{$await expression} marker."""

    expression: str

    def __str__(self) -> str:
        return f"AwaitAttribute(expr={self.expression})"


@dataclass
class ThenAttribute(SpecialAttribute):
    """{$then result} marker."""

    variable: Optional[str] = None

    def __str__(self) -> str:
        return f"ThenAttribute(var={self.variable})"


@dataclass
class CatchAttribute(SpecialAttribute):
    """{$catch error} marker."""

    variable: Optional[str] = None

    def __str__(self) -> str:
        return f"CatchAttribute(var={self.variable})"


@dataclass
class SnippetAttribute(SpecialAttribute):
    """{$snippet name(param1, param2)}...{/snippet} — defines a named snippet.

    The body is stored in the parent TemplateNode.children.
    Params are zero-or-more positional parameter names.
    """

    snippet_name: str = ""
    params: List[str] = field(default_factory=list)

    def __str__(self) -> str:
        return f"SnippetAttribute(name={self.snippet_name}, params={self.params})"


@dataclass
class RenderAttribute(SpecialAttribute):
    """{$render name(args)} — invoke a snippet.

    Self-closing form has no fallback (has_fallback=False).
    Paired form {$render name(args)}fallback{/render} has has_fallback=True
    with fallback content in parent TemplateNode.children.
    """

    snippet_name: str = ""
    call_args: List[str] = field(default_factory=list)
    has_fallback: bool = False

    def __str__(self) -> str:
        return (
            f"RenderAttribute(name={self.snippet_name}, args={self.call_args}, "
            f"fallback={self.has_fallback})"
        )


@dataclass
class HeadAttribute(SpecialAttribute):
    """{$head}...{/head} — teleport body into document <head>.

    Body is stored in parent TemplateNode.children.
    """

    def __str__(self) -> str:
        return "HeadAttribute()"


@dataclass
class DynamicAttribute(SpecialAttribute):
    """{$dynamic}...{/dynamic} — opt the wrapped subtree out of memoization.

    Bypasses RenderUnit caching for any region/snippet/slot/component
    rendered inside the block. Body lives in parent TemplateNode.children.
    """

    def __str__(self) -> str:
        return "DynamicAttribute()"


@dataclass
class AuthAttribute(SpecialAttribute):
    """{$auth policy="X" claims=[...]} marker.

    Region-scoped auth gate. Parallel to the page-level ``!auth``
    directive but evaluates per-region and renders an "allowed" or
    "denied" branch rather than redirecting the whole page.
    """

    policy: Optional[str] = None
    claims: Optional[List[Tuple[str, Optional[str]]]] = None

    def __str__(self) -> str:
        return f"AuthAttribute(policy={self.policy}, claims={self.claims})"


@dataclass
class EventAttribute(SpecialAttribute):
    """@click={handler_name} or @click={handler(arg1)}."""

    event_type: str  # 'click', 'submit', etc.
    handler_name: str
    args: List[str] = field(
        default_factory=list
    )  # List of python expressions for arguments
    modifiers: List[str] = field(
        default_factory=list
    )  # List of modifiers (e.g. ['prevent', 'stop'])
    field_mask: Optional[Set[str]] = field(
        default=None
    )  # Set of camelCase event fields the handler accesses (None = send all)

    def __str__(self) -> str:
        return (
            f"EventAttribute(event={self.event_type}, modifiers={self.modifiers}, "
            f"handler={self.handler_name}, args={self.args})"
        )


@dataclass
class ReactiveAttribute(SpecialAttribute):
    """
    attr={expression}
    Represents a reactive attribute where the value is a python expression.
    """

    expr: str

    def __str__(self) -> str:
        return f"ReactiveAttribute(name={self.name}, expr={self.expr})"


@dataclass
class SpreadAttribute(SpecialAttribute):
    """
    {**attrs} (preprocessed to __pywire_spread__="{**attrs}")
    Represents a spread of attributes.
    """

    expr: str

    def __str__(self) -> str:
        return f"SpreadAttribute(expr={self.expr})"


@dataclass
class InterpolationNode(ASTNode):
    """Represents {variable} in text.

    Use {$html expr} syntax for raw/unescaped output.
    """

    expression: str  # Python expression to evaluate
    is_raw: bool = False  # If True, output is not HTML-escaped (use {$html expr})

    def __str__(self) -> str:
        raw_str = ", raw=True" if self.is_raw else ""
        return f"InterpolationNode(expr={self.expression}{raw_str})"


@dataclass
class TemplateNode(ASTNode):
    """HTML element or text node."""

    tag: Optional[str]  # None for text nodes
    attributes: Dict[str, str] = field(default_factory=dict)  # Regular HTML attributes
    special_attributes: List[Union[SpecialAttribute, "InterpolationNode"]] = field(
        default_factory=list
    )
    children: List["TemplateNode"] = field(default_factory=list)
    text_content: Optional[str] = None
    is_raw: bool = False

    def __str__(self) -> str:
        if self.tag:
            return (
                f"TemplateNode(tag={self.tag}, attrs={len(self.attributes)}, "
                f"special={len(self.special_attributes)}, "
                f"children={len(self.children)})"
            )
        return f"TemplateNode(text={self.text_content[:30] if self.text_content else None})"


@dataclass
class ParsedPyWire:
    """Top-level parsed document."""

    directives: List[Directive] = field(default_factory=list)
    template: List[TemplateNode] = field(default_factory=list)
    python_code: str = ""  # Raw Python section (between --- fences)
    python_ast: Optional[ast.Module] = None  # Parsed Python AST
    file_path: str = ""
    # 1-based .wire-file line where python_code begins (0 if no python section).
    # Set on the python_ast via ast.increment_lineno so traceback lines align
    # with the .wire source.
    python_start_line: int = 0

    def get_directive_by_type(self, directive_type: type) -> Optional[Directive]:
        """Get first directive of specified type."""
        for directive in self.directives:
            if isinstance(directive, directive_type):
                return directive
        return None

    def get_directives_by_type(self, directive_type: type) -> List[Directive]:
        """Get all directives of specified type."""
        return [d for d in self.directives if isinstance(d, directive_type)]

    def __str__(self) -> str:
        return (
            f"ParsedPyWire(directives={len(self.directives)}, "
            f"template_nodes={len(self.template)}, "
            f"python_lines={len(self.python_code.splitlines())})"
        )
