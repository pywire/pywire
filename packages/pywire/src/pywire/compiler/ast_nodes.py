"""AST node definitions for PyWire compiler."""

import ast
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Union


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
class LayoutDirective(Directive):
    """!layout "path/to/layout.pywire" """

    layout_path: str

    def __str__(self) -> str:
        return f"LayoutDirective(path={self.layout_path})"


@dataclass
class ComponentDirective(Directive):
    """!component 'path/to/component' as Name"""

    path: str
    component_name: str  # PascalCase name (e.g. 'Badge')

    def __str__(self) -> str:
        return f"ComponentDirective(name={self.component_name}, path={self.path})"


@dataclass
class PropsDirective(Directive):
    """!props(name: type, arg=default)"""

    # List of (name, type_hint_str, default_value_str_or_None)
    args: List[Tuple[str, str, Optional[str]]]

    def __str__(self) -> str:
        return f"PropsDirective(args={self.args})"


@dataclass
class InjectDirective(Directive):
    """!inject { local: 'GLOBAL' }"""

    mapping: Dict[str, str]  # {local_var: global_key}

    def __str__(self) -> str:
        return f"InjectDirective(mapping={self.mapping})"


@dataclass
class ProvideDirective(Directive):
    """!provide { 'GLOBAL': local }"""

    mapping: Dict[str, str]  # {global_key: local_var_expr}

    def __str__(self) -> str:
        return f"ProvideDirective(mapping={self.mapping})"


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
class BindAttribute(SpecialAttribute):
    """$bind={variable}."""

    variable: str
    binding_type: Optional[str] = None

    def __str__(self) -> str:
        return f"BindAttribute(var={self.variable}, type={self.binding_type})"


@dataclass
class FieldValidationRules:
    """Validation rules for a single form field."""

    name: str
    required: bool = False
    required_expr: Optional[str] = None  # For required={condition}
    pattern: Optional[str] = None
    minlength: Optional[int] = None
    maxlength: Optional[int] = None
    min_value: Optional[str] = None  # String to support dates
    min_expr: Optional[str] = None  # For min={expr}
    max_value: Optional[str] = None
    max_expr: Optional[str] = None  # For max={expr}
    step: Optional[str] = None
    input_type: str = "text"  # email, url, number, date, etc.
    title: Optional[str] = None  # Custom error message
    max_size: Optional[int] = None  # Max file size in bytes
    allowed_types: Optional[List[str]] = None  # Allowed MIME types or extensions

    def __str__(self) -> str:
        return f"FieldValidationRules(name={self.name}, required={self.required})"


@dataclass
class FormValidationSchema:
    """Schema containing all validation rules for a form."""

    fields: Dict[str, FieldValidationRules] = field(default_factory=dict)
    model_name: Optional[str] = None  # For $model={ClassName}

    def __str__(self) -> str:
        return f"FormValidationSchema(fields={len(self.fields)}, model={self.model_name})"


@dataclass
class ModelAttribute(SpecialAttribute):
    """$model={ModelClassName} - Pydantic model binding."""

    model_name: str

    def __str__(self) -> str:
        return f"ModelAttribute(model={self.model_name})"


@dataclass
class EventAttribute(SpecialAttribute):
    """@click={handler_name} or @click={handler(arg1)}."""

    event_type: str  # 'click', 'submit', etc.
    handler_name: str
    args: List[str] = field(default_factory=list)  # List of python expressions for arguments
    modifiers: List[str] = field(
        default_factory=list
    )  # List of modifiers (e.g. ['prevent', 'stop'])
    # Form-specific fields
    validation_schema: Optional[FormValidationSchema] = None  # Set for @submit handlers

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
    """Represents {variable} in text."""

    expression: str  # Python expression to evaluate

    def __str__(self) -> str:
        return f"InterpolationNode(expr={self.expression})"


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
    python_code: str = ""  # Raw Python section (below ---)
    python_ast: Optional[ast.Module] = None  # Parsed Python AST
    file_path: str = ""

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
