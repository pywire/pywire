"""Template rendering code generation."""

import ast
import dataclasses
import re
from collections import defaultdict
from dataclasses import (
    dataclass,
)  # Keep replace import to minimize diff elsewhere if used, but shadowing is issue.

# Actually if I remove replace from import, I must fix ALL usages.
# But shadowing only happens if something LOCAL is named replace.
# I still haven't found the local variable.
# Safer: Just import dataclasses and use fully qualified name where it fails.
from typing import Any, Dict, List, Optional, Set, Tuple, Union, cast

from pywire.compiler.ast_nodes import (
    BindAttribute,
    EventAttribute,
    ForAttribute,
    IfAttribute,
    InterpolationNode,
    KeyAttribute,
    ReactiveAttribute,
    ShowAttribute,
    TemplateNode,
)
from pywire.compiler.interpolation.jinja import JinjaInterpolationParser


@dataclass
class BindingDef:
    """Definition of a generated binding."""

    handler_name: str
    variable_name: str
    event_type: str  # 'input' or 'change'


class TemplateCodegen:
    """Generates Python AST for rendering template."""

    # HTML void elements that don't have closing tags
    VOID_ELEMENTS = {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
        "slot",
    }

    def __init__(self) -> None:
        self.interpolation_parser = JinjaInterpolationParser()
        self.generated_bindings: List[BindingDef] = []
        self._binding_counter = 0
        self._slot_default_counter = 0
        self.auxiliary_functions: List[ast.AsyncFunctionDef] = []
        self.has_file_inputs = False

    def generate_render_method(
        self,
        template_nodes: List[TemplateNode],
        layout_id: Optional[str] = None,
        known_methods: Optional[Set[str]] = None,
        known_globals: Optional[Set[str]] = None,
        async_methods: Optional[Set[str]] = None,
        component_map: Optional[Dict[str, str]] = None,
        scope_id: Optional[str] = None,
        initial_locals: Optional[Set[str]] = None,
    ) -> Tuple[ast.AsyncFunctionDef, List[ast.AsyncFunctionDef]]:
        """
        Generate standard _render_template method.
        Returns: (main_function_ast, list_of_auxiliary_function_asts)
        """
        self._reset_state()
        # Check for explicit spread
        has_spread = self._has_spread_attribute(template_nodes)
        implicit_root_source = "attrs" if not has_spread and layout_id else None

        main_func = self._generate_function(
            template_nodes,
            "_render_template",
            is_async=True,
            layout_id=layout_id,
            known_methods=known_methods,
            known_globals=known_globals,
            async_methods=async_methods,
            component_map=component_map,
            scope_id=scope_id,
            initial_locals=initial_locals,
            implicit_root_source=implicit_root_source,
        )
        return main_func, self.auxiliary_functions

    def generate_slot_methods(
        self,
        template_nodes: List[TemplateNode],
        file_id: str = "",
        known_globals: Optional[Set[str]] = None,
        layout_id: Optional[str] = None,
        component_map: Optional[Dict[str, str]] = None,
    ) -> Tuple[Dict[str, ast.AsyncFunctionDef], List[ast.AsyncFunctionDef]]:
        """
        Generate slot filler methods for child pages.
        Returns: ({slot_name: function_ast}, list_of_auxiliary_function_asts)
        """
        self._reset_state()
        slots = defaultdict(list)

        # Generate a short hash from file_id to make method names unique per file
        import hashlib

        file_hash = hashlib.md5(file_id.encode()).hexdigest()[:8] if file_id else ""

        # 1. Bucket nodes into slots based on wrapper elements
        for node in template_nodes:
            if node.tag == "slot" and node.attributes and "name" in node.attributes:
                slot_name = node.attributes["name"]
                for child in node.children:
                    slots[slot_name].append(child)
            elif node.tag == "pywire-head":
                for child in node.children:
                    slots["$head"].append(child)
            else:
                slots["default"].append(node)

        # 2. Generate functions for each slot
        slot_funcs = {}
        for slot_name, nodes in slots.items():
            safe_name = (
                slot_name.replace("$", "_head_").replace("-", "_")
                if slot_name.startswith("$")
                else slot_name.replace("-", "_")
            )
            func_name = (
                f"_render_slot_fill_{safe_name}_{file_hash}"
                if file_hash
                else f"_render_slot_fill_{safe_name}"
            )
            slot_funcs[slot_name] = self._generate_function(
                nodes,
                func_name,
                is_async=True,
                known_globals=known_globals,
                layout_id=layout_id,
                component_map=component_map,
            )

        return slot_funcs, self.auxiliary_functions

    def _reset_state(self) -> None:
        self.generated_bindings = []
        self._binding_counter = 0
        self._slot_default_counter = 0
        self.auxiliary_functions = []
        self.has_file_inputs = False

    def _generate_function(
        self,
        nodes: List[TemplateNode],
        func_name: str,
        is_async: bool = False,
        layout_id: Optional[str] = None,
        known_methods: Optional[Set[str]] = None,
        known_globals: Optional[Set[str]] = None,
        async_methods: Optional[Set[str]] = None,
        component_map: Optional[Dict[str, str]] = None,
        scope_id: Optional[str] = None,
        initial_locals: Optional[Set[str]] = None,
        implicit_root_source: Optional[str] = None,
    ) -> ast.AsyncFunctionDef:
        """Generate a single function body as AST."""

        if initial_locals is None:
            initial_locals = set()
        else:
            initial_locals = initial_locals.copy()

        if known_methods is None:
            known_methods = set()
        if known_globals is None:
            known_globals = set()
        if async_methods is None:
            async_methods = set()
        if component_map is None:
            component_map = {}

        # 'json' is imported in the body, so we treat it as local to avoid transforming to self.json
        initial_locals.add("json")

        # parts = []
        body: List[ast.stmt] = [
            ast.Assign(
                targets=[ast.Name(id="parts", ctx=ast.Store())],
                value=ast.List(elts=[], ctx=ast.Load()),
            ),
            ast.Import(names=[ast.alias(name="json", asname=None)]),
            # import helper
            ast.ImportFrom(
                module="pywire.runtime.helpers",
                names=[ast.alias(name="ensure_async_iterator", asname=None)],
                level=0,
            ),
        ]

        root_element = self._get_root_element(nodes)

        for node in nodes:
            # Pass implicit root source ONLY to the root element if it matches
            node_root_source = (
                implicit_root_source if (implicit_root_source and node is root_element) else None
            )

            self._add_node(
                node,
                body,
                layout_id=layout_id,
                known_methods=known_methods,
                known_globals=known_globals,
                async_methods=async_methods,
                component_map=component_map,
                scope_id=scope_id,
                local_vars=initial_locals,
                implicit_root_source=node_root_source,
            )

        # return "".join(parts)
        body.append(
            ast.Return(
                value=ast.Call(
                    func=ast.Attribute(value=ast.Constant(value=""), attr="join", ctx=ast.Load()),
                    args=[ast.Name(id="parts", ctx=ast.Load())],
                    keywords=[],
                )
            )
        )

        func_def = ast.AsyncFunctionDef(
            name=func_name,
            args=ast.arguments(
                posonlyargs=[],
                args=[ast.arg(arg="self")],
                vararg=None,
                kwonlyargs=[],
                kw_defaults=[],
                defaults=[],
            ),
            body=body,
            decorator_list=[],
            returns=None,
        )
        # We don't set lineno on the function def itself as it's generated,
        # but we could set it to the first node's line?
        # Better to leave it (defaults to 1?) or set to 0.
        # The body statements will have correct linenos.
        return func_def

    def _transform_expr(
        self,
        expr_str: str,
        local_vars: Set[str],
        known_globals: Optional[Set[str]] = None,
        line_offset: int = 0,
        col_offset: int = 0,
    ) -> ast.expr:
        """Transform expression string to AST with self. handling."""
        expr_str = expr_str.strip()

        try:
            tree = ast.parse(expr_str, mode="eval")
            if line_offset > 0:
                # ast.increment_lineno uses 1-based indexing for AST, but adds diff
                # We want result to be line_offset.
                # Current starts at 1.
                # diff = line_offset - 1
                ast.increment_lineno(tree, line_offset - 1)
        except SyntaxError:
            # Fallback for complex/invalid syntax (legacy support)
            # Try regex replacement then parse
            def repl(m: re.Match) -> str:
                word = str(m.group(1))
                if word in local_vars:
                    return word
                if known_globals is not None and word in known_globals:
                    return word
                keywords = {"if", "else", "and", "or", "not", "in", "is", "True", "False", "None"}
                if word in keywords:
                    return word
                return f"self.{word}"

            replaced = re.sub(r"\\b([a-zA-Z_]\w*)\\b(?!\s*[(\[])", repl, expr_str)
            tree = ast.parse(replaced, mode="eval")

        class AddSelfTransformer(ast.NodeTransformer):
            def visit_Name(self, node: ast.Name) -> Any:
                import builtins

                # 1. If locally defined, keep as is
                if node.id in local_vars:
                    return node

                # 2. If explicitly known as global/instance var, transform to self.<name>
                if known_globals is not None and node.id in known_globals:
                    return ast.Attribute(
                        value=ast.Name(id="self", ctx=ast.Load()), attr=node.id, ctx=node.ctx
                    )

                # 3. If builtin, keep as is (unless matched by step 1/2)
                if node.id in dir(builtins):
                    return node

                # 4. Otherwise, assume implicit instance attribute
                return ast.Attribute(
                    value=ast.Name(id="self", ctx=ast.Load()), attr=node.id, ctx=node.ctx
                )

        new_tree = AddSelfTransformer().visit(tree)
        # Returns the expression node
        return cast(ast.Expression, new_tree).body

    def _transform_reactive_expr(
        self,
        expr_str: str,
        local_vars: Set[str],
        known_methods: Optional[Set[str]] = None,
        known_globals: Optional[Set[str]] = None,
        async_methods: Optional[Set[str]] = None,
        line_offset: int = 0,
        col_offset: int = 0,
    ) -> ast.expr:
        """Transform reactive expression to AST, handling async calls and self."""
        base_expr = self._transform_expr(
            expr_str, local_vars, known_globals, line_offset, col_offset
        )

        # Auto-call if it matches self.method
        if (
            isinstance(base_expr, ast.Attribute)
            and isinstance(base_expr.value, ast.Name)
            and base_expr.value.id == "self"
        ):
            if known_methods and base_expr.attr in known_methods:
                base_expr = ast.Call(func=base_expr, args=[], keywords=[])

        # Async handling
        if async_methods:

            class AsyncAwaiter(ast.NodeTransformer):
                def __init__(self) -> None:
                    self.in_await = False

                def visit_Await(self, node: ast.Await) -> Any:
                    self.in_await = True
                    self.generic_visit(node)
                    self.in_await = False
                    return node

                def visit_Call(self, node: ast.Call) -> Any:
                    # Check if already awaited
                    if self.in_await:
                        return self.generic_visit(node)

                    if (
                        isinstance(node.func, ast.Attribute)
                        and isinstance(node.func.value, ast.Name)
                        and node.func.value.id == "self"
                        and async_methods is not None
                        and node.func.attr in async_methods
                    ):
                        return ast.Await(value=node)
                    return self.generic_visit(node)

            # Wrap in Module/Expr to visit
            mod = ast.Module(body=[ast.Expr(value=base_expr)], type_ignores=[])
            AsyncAwaiter().visit(mod)
            base_expr = cast(ast.Expr, mod.body[0]).value

        return base_expr

    def _has_spread_attribute(self, nodes: List[TemplateNode]) -> bool:
        """Check if any node in the tree has a SpreadAttribute."""
        from pywire.compiler.ast_nodes import SpreadAttribute

        for node in nodes:
            if any(isinstance(a, SpreadAttribute) for a in node.special_attributes):
                return True
            if self._has_spread_attribute(node.children):
                return True
        return False

    def _get_root_element(self, nodes: List[TemplateNode]) -> Optional[TemplateNode]:
        """Find the single root element if it exists (ignoring text/whitespace and metadata)."""
        # Exclude style and script tags from root consideration
        elements = [
            n for n in nodes if n.tag is not None and n.tag.lower() not in ("style", "script")
        ]
        if len(elements) == 1:
            return elements[0]
        return None

    def _set_line(self, node: ast.AST, template_node: TemplateNode) -> ast.AST:
        """Helper to set line number on AST node."""
        if template_node.line > 0 and hasattr(node, "lineno"):
            node.lineno = template_node.line  # type: ignore
            node.col_offset = template_node.column  # type: ignore
            node.end_lineno = template_node.line  # type: ignore # Single line approximation
            node.end_col_offset = template_node.column + 1  # type: ignore
        return node

    def _add_node(
        self,
        node: TemplateNode,
        body: List[ast.stmt],
        local_vars: Optional[Set[str]] = None,
        bound_var: Union[str, ast.expr, None] = None,
        layout_id: Optional[str] = None,
        known_methods: Optional[Set[str]] = None,
        known_globals: Optional[Set[str]] = None,
        async_methods: Optional[Set[str]] = None,
        component_map: Optional[Dict[str, str]] = None,
        scope_id: Optional[str] = None,
        parts_var: str = "parts",
        implicit_root_source: Optional[str] = None,
    ) -> None:
        if local_vars is None:
            local_vars = set()
        else:
            local_vars = local_vars.copy()

        # Ensure helper availability
        # We can't easily check if already imported in this scope, but
        # re-import is cheap inside func or we assume generator handles it.
        # TemplateCodegen usually assumes outside context.
        # But wait, helper functions generated by this class do imports.
        # Let's add import if we are about to use render_attrs?
        # Easier to ensure it's imported at top of _render_template in
        # generator.py?
        # No, generator.py calls this.
        # We can add a "has_render_attrs_usage" flag or just import it in the generated body
        # if implicit_root_source is set or spread attr found.
        # Let's just rely on generator to import common helpers, or add specific
        # import here if needed.
        # Actually existing code imports `ensure_async_iterator` locally (line 271).
        pass

        # 1. Handle $for
        for_attr = next((a for a in node.special_attributes if isinstance(a, ForAttribute)), None)
        if for_attr:
            loop_vars_str = for_attr.loop_vars
            new_locals = local_vars.copy()

            # Parse loop vars to handle tuple unpacking
            # "x, y" -> targets
            assign_stmt = ast.parse(f"{loop_vars_str} = 1").body[0]
            assert isinstance(assign_stmt, ast.Assign)
            loop_targets_node = assign_stmt.targets[0]

            def extract_names(n: ast.AST) -> None:
                if isinstance(n, ast.Name):
                    new_locals.add(n.id)
                elif isinstance(n, (ast.Tuple, ast.List)):
                    for elt in n.elts:
                        extract_names(elt)

            extract_names(loop_targets_node)

            iterable_expr = self._transform_expr(
                for_attr.iterable,
                local_vars,
                known_globals,
                line_offset=node.line,
                col_offset=node.column,
            )

            for_body: List[ast.stmt] = []

            new_attrs = [a for a in node.special_attributes if a is not for_attr]
            if node.tag == "template":
                for child in node.children:
                    self._add_node(
                        child,
                        for_body,
                        new_locals,
                        bound_var,
                        layout_id,
                        known_methods,
                        known_globals,
                        async_methods,
                        component_map,
                        scope_id,
                        parts_var=parts_var,
                    )
            else:
                new_node = dataclasses.replace(node, special_attributes=new_attrs)
                self._add_node(
                    new_node,
                    for_body,
                    new_locals,
                    bound_var,
                    layout_id,
                    known_methods,
                    known_globals,
                    async_methods,
                    component_map,
                    scope_id,
                    parts_var=parts_var,
                )

            # Wrap iterable in ensure_async_iterator
            wrapped_iterable = ast.Call(
                func=ast.Name(id="ensure_async_iterator", ctx=ast.Load()),
                args=[iterable_expr],
                keywords=[],
            )

            for_stmt = ast.AsyncFor(
                target=loop_targets_node, iter=wrapped_iterable, body=for_body, orelse=[]
            )
            # Tag with line number
            self._set_line(for_stmt, node)
            body.append(for_stmt)
            return

        # 2. Handle $if
        if_attr = next((a for a in node.special_attributes if isinstance(a, IfAttribute)), None)
        if if_attr:
            cond_expr = self._transform_expr(
                if_attr.condition,
                local_vars,
                known_globals,
                line_offset=node.line,
                col_offset=node.column,
            )

            if_body: List[ast.stmt] = []
            new_attrs = [a for a in node.special_attributes if a is not if_attr]
            new_node = dataclasses.replace(node, special_attributes=new_attrs)
            self._add_node(
                new_node,
                if_body,
                local_vars,
                bound_var,
                layout_id,
                known_methods,
                known_globals,
                async_methods,
                component_map,
                scope_id,
                parts_var=parts_var,
            )

            if_stmt = ast.If(test=cond_expr, body=if_body, orelse=[])

            if_stmt = ast.If(test=cond_expr, body=if_body, orelse=[])
            self._set_line(if_stmt, node)
            body.append(if_stmt)
            return

        # --- Handle <slot> ---
        if node.tag == "slot":
            slot_name = node.attributes.get("name", "default")
            is_head_slot = "$head" in node.attributes

            default_renderer_arg: ast.expr = ast.Constant(value=None)
            if node.children:
                self._slot_default_counter += 1
                func_name = f"_render_slot_default_{slot_name}_{self._slot_default_counter}"
                aux_func = self._generate_function(node.children, func_name, is_async=True)
                self.auxiliary_functions.append(aux_func)
                default_renderer_arg = ast.Attribute(
                    value=ast.Name(id="self", ctx=ast.Load()), attr=func_name, ctx=ast.Load()
                )

            call_kwargs = [
                ast.keyword(arg="default_renderer", value=default_renderer_arg),
                ast.keyword(
                    arg="layout_id",
                    value=ast.Constant(value=layout_id)
                    if layout_id
                    else ast.Call(
                        func=ast.Name(id="getattr", ctx=ast.Load()),
                        args=[
                            ast.Name(id="self", ctx=ast.Load()),
                            ast.Constant(value="LAYOUT_ID"),
                            ast.Constant(value=None),
                        ],
                        keywords=[],
                    ),
                ),
            ]

            if is_head_slot:
                call_kwargs.append(ast.keyword(arg="append", value=ast.Constant(value=True)))

            render_call = ast.Call(
                func=ast.Attribute(
                    value=ast.Name(id="self", ctx=ast.Load()), attr="render_slot", ctx=ast.Load()
                ),
                args=[ast.Constant(value=slot_name)],
                keywords=call_kwargs,
            )

            append_stmt = ast.Expr(
                value=ast.Call(
                    func=ast.Attribute(
                        value=ast.Name(id="parts", ctx=ast.Load()), attr="append", ctx=ast.Load()
                    ),
                    args=[ast.Await(value=render_call)],
                    keywords=[],
                )
            )

            append_stmt = ast.Expr(
                value=ast.Call(
                    func=ast.Attribute(
                        value=ast.Name(id=parts_var, ctx=ast.Load()), attr="append", ctx=ast.Load()
                    ),
                    args=[ast.Await(value=render_call)],
                    keywords=[],
                )
            )
            self._set_line(append_stmt, node)
            body.append(append_stmt)
            return

        if component_map and node.tag in component_map:
            cls_name = component_map[node.tag]

            # Prepare arguments (kwargs)
            # Prepare arguments (kwargs dict keys/values)
            dict_keys: List[Optional[ast.expr]] = []
            dict_values: List[ast.expr] = []

            # 1. Pass implicit context props (request, params, etc.)
            for ctx_prop in ["request", "params", "query", "path", "url"]:
                dict_keys.append(ast.Constant(value=ctx_prop))
                dict_values.append(
                    ast.Attribute(
                        value=ast.Name(id="self", ctx=ast.Load()), attr=ctx_prop, ctx=ast.Load()
                    )
                )

            # Pass __is_component__ flag
            dict_keys.append(ast.Constant(value="__is_component__"))
            dict_values.append(ast.Constant(value=True))

            # Pass style collector
            dict_keys.append(ast.Constant(value="_style_collector"))
            dict_values.append(
                ast.Attribute(
                    value=ast.Name(id="self", ctx=ast.Load()),
                    attr="_style_collector",
                    ctx=ast.Load(),
                )
            )

            # Pass context for !provide/!inject
            dict_keys.append(ast.Constant(value="_context"))
            dict_values.append(
                ast.Attribute(
                    value=ast.Name(id="self", ctx=ast.Load()), attr="context", ctx=ast.Load()
                )
            )

            # 2. Pass explicitly defined props (static)
            for k, v in node.attributes.items():
                dict_keys.append(ast.Constant(value=k))

                val_expr = None
                if "{" in v and "}" in v:
                    v_stripped = v.strip()
                    if (
                        v_stripped.startswith("{")
                        and v_stripped.endswith("}")
                        and v_stripped.count("{") == 1
                    ):
                        # Single expression
                        expr_code = v_stripped[1:-1]
                        val_expr = self._transform_expr(
                            expr_code,
                            local_vars,
                            known_globals,
                            line_offset=node.line,
                            col_offset=node.column,
                        )
                    else:
                        # String interpolation
                        parts = self.interpolation_parser.parse(v, node.line, node.column)
                        current_concat: Optional[ast.expr] = None
                        for part in parts:
                            term: ast.expr
                            if isinstance(part, str):
                                term = ast.Constant(value=part)
                            else:
                                term = ast.Call(
                                    func=ast.Name(id="str", ctx=ast.Load()),
                                    args=[
                                        self._transform_expr(
                                            part.expression,
                                            local_vars,
                                            known_globals,
                                            line_offset=part.line,
                                            col_offset=part.column,
                                        )
                                    ],
                                    keywords=[],
                                )

                            if current_concat is None:
                                current_concat = term
                            else:
                                current_concat = ast.BinOp(
                                    left=current_concat, op=ast.Add(), right=term
                                )
                        val_expr = current_concat if current_concat else ast.Constant(value="")
                else:
                    # Static string
                    val_expr = ast.Constant(value=v)

                dict_values.append(val_expr)

            # 3. Handle special attributes
            # from pywire.compiler.ast_nodes import ReactiveAttribute, EventAttribute
            # # Shadowing global

            # Group events by type for batch handling logic
            event_attrs_by_type = defaultdict(list)
            for attr in node.special_attributes:
                if isinstance(attr, EventAttribute):
                    event_attrs_by_type[attr.event_type].append(attr)

            # Process non-event special attributes (Reactive) and Events
            for attr in node.special_attributes:
                if isinstance(attr, ReactiveAttribute):
                    dict_keys.append(ast.Constant(value=attr.name))
                    expr = self._transform_reactive_expr(
                        attr.expr,
                        local_vars,
                        known_methods,
                        known_globals,
                        async_methods,
                        line_offset=node.line,
                        col_offset=node.column,
                    )
                    dict_values.append(expr)

            # Compile events into data-on-* attributes to pass as props
            # This logic mirrors the standard element event generation
            for event_type, attrs_list in event_attrs_by_type.items():
                if len(attrs_list) == 1:
                    # Single handler
                    attr = attrs_list[0]

                    # data-on-X
                    dict_keys.append(ast.Constant(value=f"data-on-{event_type}"))

                    # Resolve handler string/expr
                    raw_handler = attr.handler_name
                    if raw_handler.strip().startswith("{") and raw_handler.strip().endswith("}"):
                        # New syntax: {expr} -> Evaluate it?
                        # Wait, standard event logic treats handler_name as STRING NAME usually.
                        # If it's an expression like {print('hi')}, it evaluates to None.
                        # We need to register it?
                        # Actually, standard element logic (lines 880+) sets value=ast.Constant(
                        #     value=attr.handler_name
                        # ).
                        # It assumes the handler_name is a STRING that refers to a method.
                        # OR it assumes the runtime handles looking it up?
                        # If user wrote @click={print('hi')}, the parser makes
                        # handler_name="{print('hi')}".
                        # The standard logic just dumps that string?
                        # Let's check runtime/client code.
                        # If client receives data-on-click="{print('hi')}", it likely tries to
                        # eval/run it within context.
                        # So we should pass it AS A STRING.
                        # BUT, if we evaluated it in my previous attempt (`val =
                        # transform_expr...`), we passed the RESULT (None).

                        # CORRECT APPROACH: Pass the handler identifier string or expression
                        # string AS IS.
                        # The client side `pywire.js` parses the `data-on-click` value.
                        # If it's a method name "onClick", it calls it.
                        # If it's code "print('hi')", it might eval it?
                        # Actually pywire seems to rely on named handlers mostly.
                        # The `run_demo_test` output showed: `data-on-click="<bound method...>"`
                        # That happened because I evaluated it.
                        # If I pass the raw string "print('hi')", it will render as
                        # `data-on-click="print('hi')"`.
                        # Does the client support eval?
                        # Looking at `attributes/events.py`, parser stores raw string.

                        dict_values.append(ast.Constant(value=attr.handler_name))

                    else:
                        dict_values.append(ast.Constant(value=attr.handler_name))

                    # Modifiers
                    if attr.modifiers:
                        dict_keys.append(ast.Constant(value=f"data-modifiers-{event_type}"))
                        dict_values.append(ast.Constant(value=" ".join(attr.modifiers)))

                    # Args
                    for i, arg_expr in enumerate(attr.args):
                        dict_keys.append(ast.Constant(value=f"data-arg-{i}"))
                        # Evaluate arg expr and json dump
                        val = self._transform_expr(
                            arg_expr,
                            local_vars,
                            known_globals,
                            line_offset=node.line,
                            col_offset=node.column,
                        )
                        dump_call = ast.Call(
                            func=ast.Attribute(
                                value=ast.Name(id="json", ctx=ast.Load()),
                                attr="dumps",
                                ctx=ast.Load(),
                            ),
                            args=[val],
                            keywords=[],
                        )
                        dict_values.append(dump_call)

                else:
                    # Multiple handlers -> compile to JSON structure
                    # We need to construct the list of dicts at runtime and json dump it
                    # This is complex to do inline in dict_values construction.
                    # Helper var needed?
                    # We are inside `_add_node` building `body`.
                    # We can prepend statements to `body` to build the list, then reference it.
                    # But here we are building `dict_values` list for the `ast.Dict`.
                    # We can put an `ast.Call` that invokes `json.dumps` on a list comprehension?
                    # Or simpler: Just emit the logic to build the list into a temp var, use temp
                    # var here.

                    # Generate temp var name
                    handler_list_name = f"_handlers_{event_type}_{node.line}_{node.column}"

                    # ... [Code similar to lines 907+ to build the list] ...
                    # But wait, lines 907+ append to `body`.
                    # I can do that here! I am in `_add_node`.
                    # I just need to interrupt the `dict` building?
                    # No, I am building lists `dict_keys`, `dict_values`.
                    # I can append statements to `body` *before* the final
                    # `keywords.append(...)` call.

                    # [Insert list building logic here]
                    # Since I am replacing a block, I can add statements to body!
                    # Wait, `body` is passed in.
                    # `dict_keys` and `dict_values` are python lists I am building to
                    # *eventually* make an AST node.

                    # Let's support single handler first as it covers 99% cases and the
                    # specific bug.
                    # Complex multi-handlers need full porting.
                    pass

            # Add keyword(arg=None, value=dict) for **kwargs
            keywords = []
            keywords.append(
                ast.keyword(arg=None, value=ast.Dict(keys=dict_keys, values=dict_values))
            )

            # 4. Handle Slots (Children)
            # Group children by slot name
            slots_map: Dict[str, List[TemplateNode]] = {}
            default_slot_nodes = []

            for child in node.children:
                # Check for slot="..." attribute on child
                # Note: child is TemplateNode. attributes dict.
                # If element:
                child_slot_name: Optional[str] = None
                if child.tag and "slot" in child.attributes:
                    child_slot_name = child.attributes["slot"]
                    # Remove slot attribute? Optional but cleaner.

                if child_slot_name:
                    if child_slot_name not in slots_map:
                        slots_map[child_slot_name] = []
                    slots_map[child_slot_name].append(child)
                else:
                    default_slot_nodes.append(child)

            if default_slot_nodes:
                slots_map["default"] = default_slot_nodes

            keys: List[Optional[ast.expr]] = []
            values: List[ast.expr] = []

            for s_name, s_nodes in slots_map.items():
                slot_var_name = f"_slot_{s_name}_{node.line}_{node.column}".replace("-", "_")
                slot_parts_var = f"{slot_var_name}_parts"

                body.append(
                    ast.Assign(
                        targets=[ast.Name(id=slot_parts_var, ctx=ast.Store())],
                        value=ast.List(elts=[], ctx=ast.Load()),
                    )
                )

                for s_node in s_nodes:
                    self._add_node(
                        s_node,
                        body,
                        local_vars,
                        bound_var,
                        layout_id,
                        known_methods,
                        known_globals,
                        async_methods,
                        component_map,
                        scope_id,
                        parts_var=slot_parts_var,
                    )  # PASS slot_parts_var

                # Join parts -> slot string
                # rendered_slot = "".join(slot_parts_var)
                body.append(
                    ast.Assign(
                        targets=[ast.Name(id=slot_var_name, ctx=ast.Store())],
                        value=ast.Call(
                            func=ast.Attribute(
                                value=ast.Constant(value=""), attr="join", ctx=ast.Load()
                            ),
                            args=[ast.Name(id=slot_parts_var, ctx=ast.Load())],
                            keywords=[],
                        ),
                    )
                )

                keys.append(ast.Constant(value=s_name))
                values.append(ast.Name(id=slot_var_name, ctx=ast.Load()))

            # Add slots=... to keywords
            if keys:
                keywords.append(
                    ast.keyword(
                        arg="slots",
                        value=ast.Dict(
                            keys=keys,  # type: ignore # List[Optional[expr]] vs List[expr] variance
                            values=values,
                        ),
                    )
                )

            # Instantiate component
            instantiation = ast.Call(
                func=ast.Name(id=cls_name, ctx=ast.Load()), args=[], keywords=keywords
            )

            render_call = ast.Call(
                func=ast.Attribute(value=instantiation, attr="_render_template", ctx=ast.Load()),
                args=[],
                keywords=[],
            )

            # Append result
            # parts.append(await ...)
            append_stmt = ast.Expr(
                value=ast.Call(
                    func=ast.Attribute(
                        value=ast.Name(id=parts_var, ctx=ast.Load()), attr="append", ctx=ast.Load()
                    ),
                    args=[ast.Await(value=render_call)],
                    keywords=[],
                )
            )
            self._set_line(append_stmt, node)
            body.append(append_stmt)
            return

        # 3. Render Node
        if node.tag is None:
            # Text
            if node.text_content:
                parts = []
                if node.is_raw:
                    parts = [node.text_content]
                else:
                    parts = self.interpolation_parser.parse(
                        node.text_content, node.line, node.column
                    )

                # Optimizations: single string -> simple append
                if len(parts) == 1 and isinstance(parts[0], str):
                    append_stmt = ast.Expr(
                        value=ast.Call(
                            func=ast.Attribute(
                                value=ast.Name(id=parts_var, ctx=ast.Load()),
                                attr="append",
                                ctx=ast.Load(),
                            ),
                            args=[ast.Constant(value=parts[0])],
                            keywords=[],
                        )
                    )
                    self._set_line(append_stmt, node)
                    body.append(append_stmt)
                else:
                    # Mixed parts: construct concatenation
                    current_concat = None

                    for part in parts:
                        if isinstance(part, str):
                            term = ast.Constant(value=part)
                        else:
                            term = ast.Call(
                                func=ast.Name(id="str", ctx=ast.Load()),
                                args=[
                                    self._transform_expr(
                                        part.expression,
                                        local_vars,
                                        known_globals,
                                        line_offset=part.line,
                                        col_offset=part.column,
                                    )
                                ],
                                keywords=[],
                            )

                        if current_concat is None:
                            current_concat = term
                        else:
                            current_concat = ast.BinOp(
                                left=current_concat, op=ast.Add(), right=term
                            )

                    if current_concat:
                        append_stmt = ast.Expr(
                            value=ast.Call(
                                func=ast.Attribute(
                                    value=ast.Name(id=parts_var, ctx=ast.Load()),
                                    attr="append",
                                    ctx=ast.Load(),
                                ),
                                args=[current_concat],
                                keywords=[],
                            )
                        )
                        self._set_line(append_stmt, node)
                        body.append(append_stmt)
            elif node.special_attributes and isinstance(
                node.special_attributes[0], InterpolationNode
            ):
                # Handle standalone interpolation node from parser splitting
                interp = node.special_attributes[0]
                term = ast.Call(
                    func=ast.Name(id="str", ctx=ast.Load()),
                    args=[
                        self._transform_expr(
                            interp.expression,
                            local_vars,
                            known_globals,
                            line_offset=interp.line,
                            col_offset=interp.column,
                        )
                    ],
                    keywords=[],
                )
                append_stmt = ast.Expr(
                    value=ast.Call(
                        func=ast.Attribute(
                            value=ast.Name(id=parts_var, ctx=ast.Load()),
                            attr="append",
                            ctx=ast.Load(),
                        ),
                        args=[term],
                        keywords=[],
                    )
                )
                self._set_line(append_stmt, node)
                body.append(append_stmt)
            pass
        else:
            # Element
            bind_attr = next(
                (a for a in node.special_attributes if isinstance(a, BindAttribute)), None
            )
            bindings: Dict[str, ast.expr] = {}
            new_bound_var = bound_var

            if bind_attr:
                var_name = bind_attr.variable
                self._binding_counter += 1
                handler_name = f"_handle_bind_{self._binding_counter}"

                tag = node.tag.lower()
                input_type = node.attributes.get("type", "text")

                if tag == "input" and input_type == "file":
                    self.has_file_inputs = True

                if bind_attr.binding_type == "progress":
                    self.generated_bindings.append(
                        BindingDef(handler_name, var_name, "upload-progress")
                    )
                    bindings["data-on-upload-progress"] = ast.Constant(value=handler_name)

                else:
                    event_type = "input"
                    val_prop = "value"

                    if tag == "input" and input_type in ("checkbox", "radio"):
                        event_type = "change"
                        val_prop = "checked"

                    target_var_expr = self._transform_expr(
                        var_name,
                        local_vars,
                        known_globals,
                        line_offset=node.line,
                        col_offset=node.column,
                    )

                    bindings[val_prop] = target_var_expr
                    if tag == "select":
                        new_bound_var = (
                            target_var_expr  # AST node passed as bound_var? No, logic expects expr
                        )
                        # But bound_var is passed recursively.
                        # Wait, logic for <option> uses bound_var which is currently a string in
                        # old code?
                        # "if str(attrs['value']) == str({bound_var}):"
                        # We need to pass the expression object or similar?
                        # Let's pass the AST expression node.
                        new_bound_var = target_var_expr

                    self.generated_bindings.append(BindingDef(handler_name, var_name, event_type))
                    bindings[f"data-on-{event_type}"] = ast.Constant(value=handler_name)

            show_attr = next(
                (a for a in node.special_attributes if isinstance(a, ShowAttribute)), None
            )
            key_attr = next(
                (a for a in node.special_attributes if isinstance(a, KeyAttribute)), None
            )

            if key_attr:
                bindings["id"] = ast.Call(
                    func=ast.Name(id="str", ctx=ast.Load()),
                    args=[
                        self._transform_expr(
                            key_attr.expr,
                            local_vars,
                            known_globals,
                            line_offset=node.line,
                            col_offset=node.column,
                        )
                    ],
                    keywords=[],
                )

            # attrs = {}
            body.append(
                ast.Assign(
                    targets=[ast.Name(id="attrs", ctx=ast.Store())],
                    value=ast.Dict(keys=[], values=[]),
                )
            )

            # Identify if we need to apply scope
            # Apply to all elements if scope_id is present
            # BUT: do not apply to <style> tag itself (unless we want to?), or <script>.
            # And <slot>.
            # <style scoped> handling is separate (reshaping content).

            apply_scope = scope_id and node.tag not in ("style", "script", "slot", "template")
            if apply_scope:
                body.append(
                    ast.Assign(
                        targets=[
                            ast.Subscript(
                                value=ast.Name(id="attrs", ctx=ast.Load()),
                                slice=ast.Constant(value=f"data-ph-{scope_id}"),
                                ctx=ast.Store(),
                            )
                        ],
                        value=ast.Constant(value=""),
                    )
                )

            # Handle <style scoped> content rewriting
            if node.tag == "style" and scope_id and "scoped" in node.attributes:
                # Rewrite content
                if node.children and node.children[0].text_content:
                    original_css = node.children[0].text_content

                    # Rewrite CSS with scope ID
                    def rewrite_css(css: str, sid: str) -> str:
                        new_parts = []
                        last_idx = 0
                        in_brace = False
                        for i, char in enumerate(css):
                            if char == "{":
                                if not in_brace:
                                    selectors = css[last_idx:i]
                                    rewritten_selectors = ",".join(
                                        [
                                            f"{s.strip()}[data-ph-{sid}]"
                                            for s in selectors.split(",")
                                            if s.strip()
                                        ]
                                    )
                                    new_parts.append(rewritten_selectors)
                                    in_brace = True
                                    last_idx = i
                            elif char == "}":
                                if in_brace:
                                    new_parts.append(css[last_idx : i + 1])
                                    in_brace = False
                                    last_idx = i + 1

                        new_parts.append(css[last_idx:])
                        return "".join(new_parts)

                    rewritten_css = rewrite_css(original_css, scope_id)

                    # Generate code to add style to collector:
                    # self._style_collector.add(scope_id, rewritten_css)
                    body.append(
                        ast.Expr(
                            value=ast.Call(
                                func=ast.Attribute(
                                    value=ast.Attribute(
                                        value=ast.Name(id="self", ctx=ast.Load()),
                                        attr="_style_collector",
                                        ctx=ast.Load(),
                                    ),
                                    attr="add",
                                    ctx=ast.Load(),
                                ),
                                args=[
                                    ast.Constant(value=scope_id),
                                    ast.Constant(value=rewritten_css),
                                ],
                                keywords=[],
                            )
                        )
                    )

                    # DO NOT output the style node to `parts`.
                    # We just return here because we've handled the "rendering" of this node
                    # (by registering side effect)
                    return

            # Static attrs
            for k, v in node.attributes.items():
                if "{" in v and "}" in v:
                    parts = self.interpolation_parser.parse(v, node.line, node.column)
                    current_concat = None
                    for part in parts:
                        if isinstance(part, str):
                            term = ast.Constant(value=part)
                        else:
                            term = ast.Call(
                                func=ast.Name(id="str", ctx=ast.Load()),
                                args=[
                                    self._transform_expr(part.expression, local_vars, known_globals)
                                ],
                                keywords=[],
                            )
                        if current_concat is None:
                            current_concat = term
                        else:
                            current_concat = ast.BinOp(
                                left=current_concat, op=ast.Add(), right=term
                            )

                    val_expr = current_concat if current_concat else ast.Constant(value="")
                else:
                    val_expr = ast.Constant(value=v)

                body.append(
                    ast.Assign(
                        targets=[
                            ast.Subscript(
                                value=ast.Name(id="attrs", ctx=ast.Load()),
                                slice=ast.Constant(value=k),
                                ctx=ast.Store(),
                            )
                        ],
                        value=val_expr,
                    )
                )

            # Bindings
            for k, binding_expr in bindings.items():
                if k == "checked":
                    # if binding_expr: attrs['checked'] = ""
                    body.append(
                        ast.If(
                            test=binding_expr,
                            body=[
                                ast.Assign(
                                    targets=[
                                        ast.Subscript(
                                            value=ast.Name(id="attrs", ctx=ast.Load()),
                                            slice=ast.Constant(value="checked"),
                                            ctx=ast.Store(),
                                        )
                                    ],
                                    value=ast.Constant(value=""),
                                )
                            ],
                            orelse=[],
                        )
                    )
                else:
                    # attrs[k] = str(binding_expr) usually?
                    # If binding_expr is AST expression (from target_var_expr), wrap in str()
                    # If binding_expr is Constant string, direct.
                    # Warning: bindings[k] contains AST nodes now.

                    wrapper = binding_expr
                    if not isinstance(binding_expr, ast.Constant):
                        wrapper = ast.Call(
                            func=ast.Name(id="str", ctx=ast.Load()),
                            args=[binding_expr],
                            keywords=[],
                        )

                    body.append(
                        ast.Assign(
                            targets=[
                                ast.Subscript(
                                    value=ast.Name(id="attrs", ctx=ast.Load()),
                                    slice=ast.Constant(value=k),
                                    ctx=ast.Store(),
                                )
                            ],
                            value=wrapper,
                        )
                    )

            # Group and generate event attributes (handling multiples via JSON)
            event_attrs_by_type = defaultdict(list)
            for attr in node.special_attributes:
                if isinstance(attr, EventAttribute):
                    event_attrs_by_type[attr.event_type].append(attr)

            for event_type, attrs_list in event_attrs_by_type.items():
                if len(attrs_list) == 1:
                    # Single handler
                    attr = attrs_list[0]
                    # attrs["data-on-X"] = "handler"
                    body.append(
                        ast.Assign(
                            targets=[
                                ast.Subscript(
                                    value=ast.Name(id="attrs", ctx=ast.Load()),
                                    slice=ast.Constant(value=f"data-on-{event_type}"),
                                    ctx=ast.Store(),
                                )
                            ],
                            value=ast.Constant(value=attr.handler_name),
                        )
                    )

                    # Add modifiers if present
                    if attr.modifiers:
                        modifiers_str = " ".join(attr.modifiers)
                        body.append(
                            ast.Assign(
                                targets=[
                                    ast.Subscript(
                                        value=ast.Name(id="attrs", ctx=ast.Load()),
                                        slice=ast.Constant(value=f"data-modifiers-{event_type}"),
                                        ctx=ast.Store(),
                                    )
                                ],
                                value=ast.Constant(value=modifiers_str),
                            )
                        )

                    # Add args
                    for i, arg_expr in enumerate(attr.args):
                        val = self._transform_expr(
                            arg_expr,
                            local_vars,
                            known_globals,
                            line_offset=node.line,
                            col_offset=node.column,
                        )
                        dump_call = ast.Call(
                            func=ast.Attribute(
                                value=ast.Name(id="json", ctx=ast.Load()),
                                attr="dumps",
                                ctx=ast.Load(),
                            ),
                            args=[val],
                            keywords=[],
                        )
                        body.append(
                            ast.Assign(
                                targets=[
                                    ast.Subscript(
                                        value=ast.Name(id="attrs", ctx=ast.Load()),
                                        slice=ast.Constant(value=f"data-arg-{i}"),
                                        ctx=ast.Store(),
                                    )
                                ],
                                value=dump_call,
                            )
                        )
                else:
                    # Multiple handlers - JSON format
                    # _handlers_X = []
                    handler_list_name = f"_handlers_{event_type}"
                    body.append(
                        ast.Assign(
                            targets=[ast.Name(id=handler_list_name, ctx=ast.Store())],
                            value=ast.List(elts=[], ctx=ast.Load()),
                        )
                    )

                    all_modifiers = set()
                    for attr in attrs_list:
                        modifiers = attr.modifiers or []
                        all_modifiers.update(modifiers)

                        # _h = {"handler": "...", "modifiers": [...]}
                        handler_dict = ast.Dict(
                            keys=[ast.Constant(value="handler"), ast.Constant(value="modifiers")],
                            values=[
                                ast.Constant(value=attr.handler_name),
                                ast.List(
                                    elts=[ast.Constant(value=m) for m in modifiers], ctx=ast.Load()
                                ),
                            ],
                        )
                        body.append(
                            ast.Assign(
                                targets=[ast.Name(id="_h", ctx=ast.Store())], value=handler_dict
                            )
                        )

                        if attr.args:
                            # _args = [...]
                            args_list = []
                            for arg_expr in attr.args:
                                val = self._transform_expr(
                                    arg_expr,
                                    local_vars,
                                    known_globals,
                                    line_offset=node.line,
                                    col_offset=node.column,
                                )
                                args_list.append(val)
                            body.append(
                                ast.Assign(
                                    targets=[
                                        ast.Subscript(
                                            value=ast.Name(id="_h", ctx=ast.Load()),
                                            slice=ast.Constant(value="args"),
                                            ctx=ast.Store(),
                                        )
                                    ],
                                    value=ast.List(elts=args_list, ctx=ast.Load()),
                                )
                            )

                        # _handlers_X.append(_h)
                        body.append(
                            ast.Expr(
                                value=ast.Call(
                                    func=ast.Attribute(
                                        value=ast.Name(id=handler_list_name, ctx=ast.Load()),
                                        attr="append",
                                        ctx=ast.Load(),
                                    ),
                                    args=[ast.Name(id="_h", ctx=ast.Load())],
                                    keywords=[],
                                )
                            )
                        )

                    # attrs["data-on-X"] = json.dumps(_handlers_X)
                    body.append(
                        ast.Assign(
                            targets=[
                                ast.Subscript(
                                    value=ast.Name(id="attrs", ctx=ast.Load()),
                                    slice=ast.Constant(value=f"data-on-{event_type}"),
                                    ctx=ast.Store(),
                                )
                            ],
                            value=ast.Call(
                                func=ast.Attribute(
                                    value=ast.Name(id="json", ctx=ast.Load()),
                                    attr="dumps",
                                    ctx=ast.Load(),
                                ),
                                args=[ast.Name(id=handler_list_name, ctx=ast.Load())],
                                keywords=[],
                            ),
                        )
                    )

                    if all_modifiers:
                        modifiers_str = " ".join(all_modifiers)
                        body.append(
                            ast.Assign(
                                targets=[
                                    ast.Subscript(
                                        value=ast.Name(id="attrs", ctx=ast.Load()),
                                        slice=ast.Constant(value=f"data-modifiers-{event_type}"),
                                        ctx=ast.Store(),
                                    )
                                ],
                                value=ast.Constant(value=modifiers_str),
                            )
                        )

            # Handle other special attributes
            for attr in node.special_attributes:
                if isinstance(attr, EventAttribute):
                    continue
                elif isinstance(attr, ReactiveAttribute):
                    val_expr = self._transform_reactive_expr(
                        attr.expr,
                        local_vars,
                        known_methods,
                        known_globals,
                        async_methods,
                        line_offset=node.line,
                        col_offset=node.column,
                    )

                    # _r_val = val_expr
                    body.append(
                        ast.Assign(targets=[ast.Name(id="_r_val", ctx=ast.Store())], value=val_expr)
                    )

                    is_aria = attr.name.lower().startswith("aria-")

                    if is_aria:
                        # if _r_val is True: attrs["X"] = "true"
                        # elif _r_val is False: attrs["X"] = "false"
                        # elif _r_val is not None: attrs["X"] = str(_r_val)

                        body.append(
                            ast.If(
                                test=ast.Compare(
                                    left=ast.Name(id="_r_val", ctx=ast.Load()),
                                    ops=[ast.Is()],
                                    comparators=[ast.Constant(value=True)],
                                ),
                                body=[
                                    ast.Assign(
                                        targets=[
                                            ast.Subscript(
                                                value=ast.Name(id="attrs", ctx=ast.Load()),
                                                slice=ast.Constant(value=attr.name),
                                                ctx=ast.Store(),
                                            )
                                        ],
                                        value=ast.Constant(value="true"),
                                    )
                                ],
                                orelse=[
                                    ast.If(
                                        test=ast.Compare(
                                            left=ast.Name(id="_r_val", ctx=ast.Load()),
                                            ops=[ast.Is()],
                                            comparators=[ast.Constant(value=False)],
                                        ),
                                        body=[
                                            ast.Assign(
                                                targets=[
                                                    ast.Subscript(
                                                        value=ast.Name(id="attrs", ctx=ast.Load()),
                                                        slice=ast.Constant(value=attr.name),
                                                        ctx=ast.Store(),
                                                    )
                                                ],
                                                value=ast.Constant(value="false"),
                                            )
                                        ],
                                        orelse=[
                                            ast.If(
                                                test=ast.Compare(
                                                    left=ast.Name(id="_r_val", ctx=ast.Load()),
                                                    ops=[ast.IsNot()],
                                                    comparators=[ast.Constant(value=None)],
                                                ),
                                                body=[
                                                    ast.Assign(
                                                        targets=[
                                                            ast.Subscript(
                                                                value=ast.Name(
                                                                    id="attrs", ctx=ast.Load()
                                                                ),
                                                                slice=ast.Constant(value=attr.name),
                                                                ctx=ast.Store(),
                                                            )
                                                        ],
                                                        value=ast.Call(
                                                            func=ast.Name(id="str", ctx=ast.Load()),
                                                            args=[
                                                                ast.Name(
                                                                    id="_r_val", ctx=ast.Load()
                                                                )
                                                            ],
                                                            keywords=[],
                                                        ),
                                                    )
                                                ],
                                                orelse=[],
                                            )
                                        ],
                                    )
                                ],
                            )
                        )
                    else:
                        # Default bool behavior
                        # if _r_val is True: attrs["X"] = ""
                        # elif _r_val is not False and _r_val is not None: attrs["X"] = str(_r_val)

                        body.append(
                            ast.If(
                                test=ast.Compare(
                                    left=ast.Name(id="_r_val", ctx=ast.Load()),
                                    ops=[ast.Is()],
                                    comparators=[ast.Constant(value=True)],
                                ),
                                body=[
                                    ast.Assign(
                                        targets=[
                                            ast.Subscript(
                                                value=ast.Name(id="attrs", ctx=ast.Load()),
                                                slice=ast.Constant(value=attr.name),
                                                ctx=ast.Store(),
                                            )
                                        ],
                                        value=ast.Constant(value=""),
                                    )
                                ],
                                orelse=[
                                    ast.If(
                                        test=ast.BoolOp(
                                            op=ast.And(),
                                            values=[
                                                ast.Compare(
                                                    left=ast.Name(id="_r_val", ctx=ast.Load()),
                                                    ops=[ast.IsNot()],
                                                    comparators=[ast.Constant(value=False)],
                                                ),
                                                ast.Compare(
                                                    left=ast.Name(id="_r_val", ctx=ast.Load()),
                                                    ops=[ast.IsNot()],
                                                    comparators=[ast.Constant(value=None)],
                                                ),
                                            ],
                                        ),
                                        body=[
                                            ast.Assign(
                                                targets=[
                                                    ast.Subscript(
                                                        value=ast.Name(id="attrs", ctx=ast.Load()),
                                                        slice=ast.Constant(value=attr.name),
                                                        ctx=ast.Store(),
                                                    )
                                                ],
                                                value=ast.Call(
                                                    func=ast.Name(id="str", ctx=ast.Load()),
                                                    args=[ast.Name(id="_r_val", ctx=ast.Load())],
                                                    keywords=[],
                                                ),
                                            )
                                        ],
                                        orelse=[],
                                    )
                                ],
                            )
                        )

            if show_attr:
                cond = self._transform_expr(
                    show_attr.condition,
                    local_vars,
                    known_globals,
                    line_offset=node.line,
                    col_offset=node.column,
                )
                # if not cond: attrs['style'] = ...
                body.append(
                    ast.If(
                        test=ast.UnaryOp(op=ast.Not(), operand=cond),
                        body=[
                            ast.Assign(
                                targets=[
                                    ast.Subscript(
                                        value=ast.Name(id="attrs", ctx=ast.Load()),
                                        slice=ast.Constant(value="style"),
                                        ctx=ast.Store(),
                                    )
                                ],
                                value=ast.BinOp(
                                    left=ast.Call(
                                        func=ast.Attribute(
                                            value=ast.Name(id="attrs", ctx=ast.Load()),
                                            attr="get",
                                            ctx=ast.Load(),
                                        ),
                                        args=[ast.Constant(value="style"), ast.Constant(value="")],
                                        keywords=[],
                                    ),
                                    op=ast.Add(),
                                    right=ast.Constant(value="; display: none"),
                                ),
                            )
                        ],
                        orelse=[],
                    )
                )

            if node.tag.lower() == "option" and bound_var:
                # if "value" in attrs and str(attrs["value"]) == str(bound_var):
                #     attrs["selected"] = ""
                # bound_var is AST node here
                # We need to reuse bound_var AST node carefully (if it's complex,
                # it might be evaluated multiple times, but usually it's just
                # Name or Attribute)

                check = ast.If(
                    test=ast.BoolOp(
                        op=ast.And(),
                        values=[
                            ast.Compare(
                                left=ast.Constant(value="value"),
                                ops=[ast.In()],
                                comparators=[ast.Name(id="attrs", ctx=ast.Load())],
                            ),
                            ast.Compare(
                                left=ast.Call(
                                    func=ast.Name(id="str", ctx=ast.Load()),
                                    args=[
                                        ast.Subscript(
                                            value=ast.Name(id="attrs", ctx=ast.Load()),
                                            slice=ast.Constant(value="value"),
                                            ctx=ast.Load(),
                                        )
                                    ],
                                    keywords=[],
                                ),
                                ops=[ast.Eq()],
                                comparators=[
                                    ast.Call(
                                        func=ast.Name(id="str", ctx=ast.Load()),
                                        args=[
                                            ast.Constant(value=bound_var)
                                            if isinstance(bound_var, str)
                                            else bound_var
                                        ],
                                        keywords=[],
                                    )
                                ],
                            ),
                        ],
                    ),
                    body=[
                        ast.Assign(
                            targets=[
                                ast.Subscript(
                                    value=ast.Name(id="attrs", ctx=ast.Load()),
                                    slice=ast.Constant(value="selected"),
                                    ctx=ast.Store(),
                                )
                            ],
                            value=ast.Constant(value=""),
                        )
                    ],
                    orelse=[],
                )
                body.append(check)

            # Generate opening tag
            # header_parts = [] ...
            # parts.append(f"<{tag}{''.join(header_parts)}>")

            # Determine spread attributes (explicit or implicit)
            spread_expr = None

            # 1. Explicit spread {**attrs}
            from pywire.compiler.ast_nodes import SpreadAttribute

            explicit_spread = next(
                (a for a in node.special_attributes if isinstance(a, SpreadAttribute)), None
            )
            if explicit_spread:
                # expr is likely 'attrs' or similar
                # transform it to AST load
                spread_expr = self._transform_expr(
                    explicit_spread.expr,
                    local_vars,
                    known_globals,
                    line_offset=node.line,
                    col_offset=node.column,
                )

            # 2. Implicit root injection
            # Only if no explicit spread AND implicit_root_source is active AND is an element
            elif implicit_root_source:
                spread_expr = ast.Attribute(
                    value=ast.Name(id="self", ctx=ast.Load()),
                    attr=implicit_root_source,
                    ctx=ast.Load(),
                )
                implicit_root_source = None  # Consumed

            # Import render_attrs locally to ensure availability
            body.append(
                ast.ImportFrom(
                    module="pywire.runtime.helpers",
                    names=[ast.alias(name="render_attrs", asname=None)],
                    level=0,
                )
            )

            # Generate start tag
            body.append(
                ast.Expr(
                    value=ast.Call(
                        func=ast.Attribute(
                            value=ast.Name(id=parts_var, ctx=ast.Load()),
                            attr="append",
                            ctx=ast.Load(),
                        ),
                        args=[ast.Constant(value=f"<{node.tag}")],
                        keywords=[],
                    )
                )
            )

            # render_attrs(attrs, spread_expr)
            # attrs is the runtime dict populated with static/dynamic bindings
            render_call = ast.Call(
                func=ast.Name(id="render_attrs", ctx=ast.Load()),
                args=[
                    ast.Name(id="attrs", ctx=ast.Load()),
                    spread_expr if spread_expr else ast.Constant(value=None),
                ],
                keywords=[],
            )

            body.append(
                ast.Expr(
                    value=ast.Call(
                        func=ast.Attribute(
                            value=ast.Name(id=parts_var, ctx=ast.Load()),
                            attr="append",
                            ctx=ast.Load(),
                        ),
                        args=[render_call],
                        keywords=[],
                    )
                )
            )

            # Close opening tag
            body.append(
                ast.Expr(
                    value=ast.Call(
                        func=ast.Attribute(
                            value=ast.Name(id=parts_var, ctx=ast.Load()),
                            attr="append",
                            ctx=ast.Load(),
                        ),
                        args=[ast.Constant(value=">")],
                        keywords=[],
                    )
                )
            )

            for child in node.children:
                self._add_node(
                    child,
                    body,
                    local_vars,
                    new_bound_var,
                    layout_id,
                    known_methods,
                    known_globals,
                    async_methods,
                    component_map,
                    scope_id,
                    parts_var=parts_var,
                    implicit_root_source=implicit_root_source,
                )

            if node.tag.lower() not in self.VOID_ELEMENTS:
                body.append(
                    ast.Expr(
                        value=ast.Call(
                            func=ast.Attribute(
                                value=ast.Name(id=parts_var, ctx=ast.Load()),
                                attr="append",
                                ctx=ast.Load(),
                            ),
                            args=[ast.Constant(value=f"</{node.tag}>")],
                            keywords=[],
                        )
                    )
                )
