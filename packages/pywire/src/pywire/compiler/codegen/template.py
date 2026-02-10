"""Template rendering code generation."""

import ast
import dataclasses
import re
from collections import defaultdict

from typing import Any, Dict, List, Optional, Set, Tuple, Union, cast

from pywire.compiler.ast_nodes import (
    AwaitAttribute,
    CatchAttribute,
    ElifAttribute,
    ElseAttribute,
    EventAttribute,
    ExceptAttribute,
    FinallyAttribute,
    ForAttribute,
    IfAttribute,
    InterpolationNode,
    KeyAttribute,
    ReactiveAttribute,
    ShowAttribute,
    TemplateNode,
    ThenAttribute,
    TryAttribute,
)
from pywire.compiler.interpolation.jinja import JinjaInterpolationParser


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
        self._slot_default_counter = 0
        self.auxiliary_functions: List[ast.AsyncFunctionDef] = []
        self.has_file_inputs = False
        self._region_counter = 0
        self.region_renderers: Dict[str, str] = {}
        self._expr_id_counter = 0

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
        known_imports: Optional[Set[str]] = None,
        wire_vars: Set[str] = set(),
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
            known_imports=known_imports,
            async_methods=async_methods,
            component_map=component_map,
            scope_id=scope_id,
            initial_locals=initial_locals,
            implicit_root_source=implicit_root_source,
            wire_vars=wire_vars,
        )
        return main_func, self.auxiliary_functions

    def generate_slot_methods(
        self,
        template_nodes: List[TemplateNode],
        file_id: str = "",
        known_globals: Optional[Set[str]] = None,
        known_imports: Optional[Set[str]] = None,
        layout_id: Optional[str] = None,
        component_map: Optional[Dict[str, str]] = None,
        wire_vars: Set[str] = set(),
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
            elif node.tag == "head":
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
                known_imports=known_imports,
                layout_id=layout_id,
                component_map=component_map,
                wire_vars=wire_vars,
            )

        return slot_funcs, self.auxiliary_functions

    def _reset_state(self) -> None:
        self._slot_default_counter = 0
        self.auxiliary_functions = []
        self.has_file_inputs = False
        self._region_counter = 0
        self.region_renderers = {}
        self._expr_id_counter = 0
        self._slot_default_counter = 0
        self.auxiliary_functions = []
        self.has_file_inputs = False
        self._region_counter = 0
        self.region_renderers = {}

    def _generate_function(
        self,
        nodes: List[TemplateNode],
        func_name: str,
        is_async: bool = False,
        layout_id: Optional[str] = None,
        known_methods: Optional[Set[str]] = None,
        known_globals: Optional[Set[str]] = None,
        known_imports: Optional[Set[str]] = None,
        async_methods: Optional[Set[str]] = None,
        component_map: Optional[Dict[str, str]] = None,
        scope_id: Optional[str] = None,
        initial_locals: Optional[Set[str]] = None,
        implicit_root_source: Optional[str] = None,
        enable_regions: bool = True,
        root_region_id: Optional[str] = None,
        wire_vars: Set[str] = set(),
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
        if known_imports is None:
            known_imports = set()
        if async_methods is None:
            async_methods = set()
        if component_map is None:
            component_map = {}

        # 'json' is imported in the body, so we treat it as local to avoid transforming to self.json
        # parts = []
        body: List[ast.stmt] = []

        body.append(
            ast.Assign(
                targets=[ast.Name(id="parts", ctx=ast.Store())],
                value=ast.List(elts=[], ctx=ast.Load()),
            )
        )
        body.append(ast.Import(names=[ast.alias(name="json", asname=None)]))
        # import helper
        body.append(
            ast.ImportFrom(
                module="pywire.runtime.helpers",
                names=[ast.alias(name="ensure_async_iterator", asname=None)],
                level=0,
            )
        )
        # import escape_html for XSS prevention
        body.append(
            ast.ImportFrom(
                module="pywire.runtime.escape",
                names=[ast.alias(name="escape_html", asname=None)],
                level=0,
            )
        )

        root_element = self._get_root_element(nodes)

        prev_node = None
        for node in nodes:
            # Add whitespace if there is a gap between this node and the previous one
            self._add_gap_whitespace(prev_node, node, body, parts_var="parts")

            # Pass implicit root source ONLY to the root element if it matches
            node_root_source = (
                implicit_root_source
                if (implicit_root_source and node is root_element)
                else None
            )
            node_region_id = (
                root_region_id if (root_region_id and node is root_element) else None
            )

            self._add_node(
                node,
                body,
                layout_id=layout_id,
                known_methods=known_methods,
                known_globals=known_globals,
                known_imports=known_imports,
                async_methods=async_methods,
                component_map=component_map,
                scope_id=scope_id,
                local_vars=initial_locals,
                implicit_root_source=node_root_source,
                enable_regions=enable_regions,
                region_id=node_region_id,
                wire_vars=wire_vars,
            )
            prev_node = node

        # return "".join(parts)
        body.append(
            ast.Return(
                value=ast.Call(
                    func=ast.Attribute(
                        value=ast.Constant(value=""), attr="join", ctx=ast.Load()
                    ),
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
        known_imports: Optional[Set[str]] = None,
        line_offset: int = 0,
        col_offset: int = 0,
        cached: bool = False,
        wire_vars: Set[str] = set(),
        no_unwrap: bool = False,
    ) -> ast.expr:
        """Transform expression string to AST with self. handling."""
        expr_str = expr_str.strip()

        try:
            from pywire.compiler.preprocessor import preprocess_python_code

            expr_str = preprocess_python_code(expr_str)
            try:
                tree = ast.parse(expr_str, mode="eval")
            except SyntaxError:
                print(
                    f"DEBUG: FAILED TO PARSE EXPR: '{expr_str}' at line {line_offset}"
                )
                raise
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
                keywords = {
                    "if",
                    "else",
                    "and",
                    "or",
                    "not",
                    "in",
                    "is",
                    "True",
                    "False",
                    "None",
                }
                if word in keywords:
                    return word
                return f"self.{word}"

            replaced = re.sub(r"\\b([a-zA-Z_]\w*)\\b(?!\s*[(\[])", repl, expr_str)
            tree = ast.parse(replaced, mode="eval")

        class AddSelfTransformer(ast.NodeTransformer):
            def visit_Name(self, node: ast.Name) -> Any:
                import builtins

                # 1. If locally defined, keep as is
                if node.id in local_vars or node.id in ("json", "escape_html"):
                    # print(f"DEBUG: KEEP LOCAL {node.id}")
                    return node

                # 2. If explicitly known as import, keep as is
                if known_imports is not None and node.id in known_imports:
                    # print(f"DEBUG: KEEP IMPORT {node.id}")
                    return node

                # 3. If explicitly known as global/instance var, transform to self.<name>
                if known_globals is not None and node.id in known_globals:
                    # Check if it's a wire variable and unwrap it
                    if node.id in wire_vars and not no_unwrap:
                        # print(f"DEBUG: UNWRAP WIRE {node.id}")
                        return ast.Call(
                            func=ast.Name(id="unwrap_wire", ctx=ast.Load()),
                            args=[
                                ast.Attribute(
                                    value=ast.Name(id="self", ctx=ast.Load()),
                                    attr=node.id,
                                    ctx=node.ctx,
                                )
                            ],
                            keywords=[],
                        )

                    # print(f"DEBUG: SELF GLOBAL {node.id}")
                    return ast.Attribute(
                        value=ast.Name(id="self", ctx=ast.Load()),
                        attr=node.id,
                        ctx=node.ctx,
                    )

                # 3. If builtin, keep as is (unless matched by step 1/2)
                if node.id in dir(builtins):
                    # print(f"DEBUG: KEEP BUILTIN {node.id}")
                    return node

                # 4. Otherwise, assume implicit instance attribute
                # with open("/tmp/pywire_debug.txt", "a") as f:
                #    f.write(f"DEBUG: OOPS IMPLICIT {node.id}\n")

                return ast.Attribute(
                    value=ast.Name(id="self", ctx=ast.Load()),
                    attr=node.id,
                    ctx=node.ctx,
                )

            def visit_NamedExpr(self, node: ast.NamedExpr) -> Any:
                # The target of a walrus operator must be a Name node.
                # We should NOT transform it to self.Attribute.
                if isinstance(node.target, ast.Name):
                    local_vars.add(node.target.id)

                # Visit the value (the expression on the right)
                node.value = self.visit(node.value)
                # Ensure the target itself is not transformed to self.Target
                # (visit_Name would normally do that if not in local_vars)
                node.target = self.visit(node.target)
                return node

        new_tree = AddSelfTransformer().visit(tree)

        # Check if we should disable caching based on content
        if cached:
            # 1. Local variable usage
            class LocalVarChecker(ast.NodeVisitor):
                def __init__(self) -> None:
                    self.found = False

                def visit_Name(self, node: ast.Name) -> None:
                    if node.id in local_vars:
                        self.found = True
                    self.generic_visit(node)

                def visit_Await(self, node: ast.Await) -> None:
                    self.found = True
                    self.generic_visit(node)

                def visit_Yield(self, node: ast.Yield) -> None:
                    self.found = True
                    self.generic_visit(node)

                def visit_YieldFrom(self, node: ast.YieldFrom) -> None:
                    self.found = True
                    self.generic_visit(node)

            checker = LocalVarChecker()
            checker.visit(new_tree)
            if checker.found:
                cached = False

        if cached:
            # Wrap in _render_expr(id, lambda: expr)
            expr_id = f"expr_{self._expr_id_counter}"
            self._expr_id_counter += 1

            # Extract expression body
            expr_body = cast(ast.Expression, new_tree).body

            lambda_node = ast.Lambda(
                args=ast.arguments(
                    posonlyargs=[],
                    args=[],
                    vararg=None,
                    kwonlyargs=[],
                    kw_defaults=[],
                    defaults=[],
                ),
                body=expr_body,
            )

            return ast.Call(
                func=ast.Attribute(
                    value=ast.Name(id="self", ctx=ast.Load()),
                    attr="_render_expr",
                    ctx=ast.Load(),
                ),
                args=[ast.Constant(value=expr_id), lambda_node],
                keywords=[],
            )

        # Returns the expression node
        return cast(ast.Expression, new_tree).body

    def _transform_reactive_expr(
        self,
        expr_str: str,
        local_vars: Set[str],
        known_methods: Optional[Set[str]] = None,
        known_globals: Optional[Set[str]] = None,
        known_imports: Optional[Set[str]] = None,
        async_methods: Optional[Set[str]] = None,
        line_offset: int = 0,
        col_offset: int = 0,
        cached: bool = True,
        wire_vars: Set[str] = set(),
        no_unwrap: bool = False,
    ) -> ast.expr:
        """Transform reactive expression to AST, handling async calls and self."""
        # For reactive expressions (attributes), we typically prefer caching
        # unless async is involved.
        # But wait, async handling happens AFTER _transform_expr via AsyncAwaiter below.
        # AsyncAwaiter adds Await nodes. _transform_expr returns the sync base.
        # If we cache the sync base, we get a coroutine back from _render_expr (if it was async).
        # We need to await that.

        # We must check if async_methods are used in the expression string
        # before we decide to cache.

        # Just use defaults - _transform_expr will disable cache if it sees explicit Await.
        # But if it sees `self.async_call()`, it doesn't know it's async yet (AsyncAwaiter runs later).
        # So we must inform _transform_expr to disable cache if we detect async method usage.

        # We'll rely on local_vars logic in _transform_expr.
        # For async methods, we can just pass cached=False if any async methods are known?
        # That's too aggressive (disables caching for everything if page has 1 async method).

        # Let's just disable caching for reactive attrs to be safe?
        # Requires complex logic to safely cache async calls.
        # Given "Regular variables interpolated", those are usually sync.
        # So we can pass cached=True, but we need to ensure we don't break async.

        # If we wrap `lambda: self.async_method()`, it returns coroutine.
        # `base_expr` is `_render_expr(...)`.
        # `AsyncAwaiter` visits `base_expr`. It sees `Call(_render_expr)`.
        # It does NOT verify `async_method`.
        # So `Await` is NOT added.

        # Result: we return coroutine object to template. Template renders string representation of coroutine.
        # BUG.

        # Fix: We must not cache if async methods are involved.
        # We can implement a check here strings.

        has_async_usage = False
        if async_methods is not None:
            # simple regex check?
            for method in async_methods:
                if method in expr_str:
                    has_async_usage = True
                    break

        # Pre-process: If it's a simple method name, add parens to ensure it gets called
        # This is needed because `_transform_expr` with cached=True wraps the result,
        # preventing the post-transform auto-call logic from seeing the Attribute node.
        stripped = expr_str.strip()
        if known_methods and stripped in known_methods:
            # Verify it's a valid identifier (sanity check)
            if stripped.isidentifier():
                expr_str = f"{stripped}()"

        base_expr = self._transform_expr(
            expr_str,
            local_vars,
            known_globals,
            known_imports,
            line_offset,
            col_offset,
            cached=cached and not has_async_usage,
            wire_vars=wire_vars,
            no_unwrap=no_unwrap,
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

        # Check for Await nodes in the final expression (explicit or added by AsyncAwaiter)
        class AwaitDetector(ast.NodeVisitor):
            def __init__(self) -> None:
                self.found = False

            def visit_Await(self, node: ast.Await) -> None:
                self.found = True
                # No need to visit children if we found one, but consistent to do so
                self.generic_visit(node)

            def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
                self.found = True
                self.generic_visit(node)

            def visit_AsyncWith(self, node: ast.AsyncWith) -> None:
                self.found = True
                self.generic_visit(node)

        detector = AwaitDetector()
        # Wrap in expression to visit (NodeVisitor needs node)
        # base_expr is ast.expr
        detector.visit(base_expr)
        if detector.found:
            has_async_usage = True

        # Cache the final expression (including auto-call if added)
        if cached and not has_async_usage:
            expr_id = f"expr_{self._expr_id_counter}"
            self._expr_id_counter += 1

            lambda_node = ast.Lambda(
                args=ast.arguments(
                    posonlyargs=[],
                    args=[],
                    vararg=None,
                    kwonlyargs=[],
                    kw_defaults=[],
                    defaults=[],
                ),
                body=base_expr,
            )

            return ast.Call(
                func=ast.Attribute(
                    value=ast.Name(id="self", ctx=ast.Load()),
                    attr="_render_expr",
                    ctx=ast.Load(),
                ),
                args=[ast.Constant(value=expr_id), lambda_node],
                keywords=[],
            )

        return base_expr

    def _wrap_unwrap_wire(self, expr: ast.expr) -> ast.expr:
        return ast.Call(
            func=ast.Name(id="unwrap_wire", ctx=ast.Load()),
            args=[expr],
            keywords=[],
        )

    def _next_region_id(self) -> str:
        self._region_counter += 1
        return f"r{self._region_counter}"

    def _node_is_dynamic(
        self, node: TemplateNode, known_globals: Optional[Set[str]] = None
    ) -> bool:
        # Check special attributes (Interpolation, If, For, Show, Reactive, etc.)
        for attr in node.special_attributes:
            if isinstance(attr, EventAttribute):
                continue
            return True

        if node.tag is None:
            # Check text content for interpolations
            if node.text_content and not node.is_raw:
                parts = self.interpolation_parser.parse(
                    node.text_content, node.line, node.column
                )
                return any(isinstance(part, InterpolationNode) for part in parts)
            return False

        return any(
            self._node_is_dynamic(child, known_globals) for child in node.children
        )

    def _generate_region_method(
        self,
        node: TemplateNode,
        func_name: str,
        region_id: str,
        layout_id: Optional[str],
        known_methods: Optional[Set[str]],
        known_globals: Optional[Set[str]],
        known_imports: Optional[Set[str]],
        async_methods: Optional[Set[str]],
        component_map: Optional[Dict[str, str]],
        scope_id: Optional[str],
        implicit_root_source: Optional[str],
    ) -> ast.AsyncFunctionDef:
        func_def = self._generate_function(
            [node],
            func_name,
            is_async=True,
            layout_id=layout_id,
            known_methods=known_methods,
            known_globals=known_globals,
            known_imports=known_imports,
            async_methods=async_methods,
            component_map=component_map,
            scope_id=scope_id,
            implicit_root_source=implicit_root_source,
            enable_regions=False,
            root_region_id=region_id,
        )

        if len(func_def.body) < 3:
            return func_def

        setup = func_def.body[:3]
        render_body = func_def.body[3:]

        begin_render = ast.Expr(
            value=ast.Call(
                func=ast.Attribute(
                    value=ast.Name(id="self", ctx=ast.Load()),
                    attr="_begin_region_render",
                    ctx=ast.Load(),
                ),
                args=[ast.Constant(value=region_id)],
                keywords=[],
            )
        )
        render_body.insert(0, begin_render)

        token_assign = ast.Assign(
            targets=[ast.Name(id="_render_token", ctx=ast.Store())],
            value=ast.Call(
                func=ast.Name(id="set_render_context", ctx=ast.Load()),
                args=[
                    ast.Name(id="self", ctx=ast.Load()),
                    ast.Constant(value=region_id),
                ],
                keywords=[],
            ),
        )

        reset_stmt = ast.Expr(
            value=ast.Call(
                func=ast.Name(id="reset_render_context", ctx=ast.Load()),
                args=[ast.Name(id="_render_token", ctx=ast.Load())],
                keywords=[],
            )
        )

        func_def.body = setup + [
            token_assign,
            ast.Try(body=render_body, orelse=[], finalbody=[reset_stmt], handlers=[]),
        ]
        return func_def

    def _generate_await_renderer(
        self,
        nodes: List[TemplateNode],
        func_name: str,
        region_id: str,
        await_attr: AwaitAttribute,
        pending_nodes: List[TemplateNode],
        then_nodes: List[TemplateNode],
        then_var: Optional[str],
        catch_nodes: List[TemplateNode],
        catch_var: Optional[str],
        layout_id: Optional[str],
        known_methods: Optional[Set[str]],
        known_globals: Optional[Set[str]],
        known_imports: Optional[Set[str]],
        async_methods: Optional[Set[str]],
        component_map: Optional[Dict[str, str]],
        scope_id: Optional[str],
        wire_vars: Set[str] = set(),
    ) -> ast.AsyncFunctionDef:
        """Generate a renderer for an await block region."""
        body: List[ast.stmt] = []
        body.append(
            ast.Assign(
                targets=[ast.Name(id="parts", ctx=ast.Store())],
                value=ast.List(elts=[], ctx=ast.Load()),
            )
        )
        # Import helpers
        body.append(
            ast.ImportFrom(
                module="pywire.runtime.escape",
                names=[ast.alias(name="escape_html", asname=None)],
                level=0,
            )
        )
        body.append(
            ast.ImportFrom(
                module="pywire.runtime.helpers",
                names=[ast.alias(name="ensure_async_iterator", asname=None)],
                level=0,
            )
        )
        body.append(ast.Import(names=[ast.alias(name="json", asname=None)]))

        # state = self._await_states.get(region_id, {"status": "pending"})
        body.append(
            ast.Assign(
                targets=[ast.Name(id="state", ctx=ast.Store())],
                value=ast.Call(
                    func=ast.Attribute(
                        value=ast.Attribute(
                            value=ast.Name(id="self", ctx=ast.Load()),
                            attr="_await_states",
                            ctx=ast.Load(),
                        ),
                        attr="get",
                        ctx=ast.Load(),
                    ),
                    args=[
                        ast.Constant(value=region_id),
                        ast.Dict(
                            keys=[ast.Constant(value="status")],
                            values=[ast.Constant(value="pending")],
                        ),
                    ],
                    keywords=[],
                ),
            )
        )

        # 1. Pending branch
        pending_ast: List[ast.stmt] = []
        for n in pending_nodes:
            self._add_node(
                n,
                pending_ast,
                layout_id=layout_id,
                known_methods=known_methods,
                known_globals=known_globals,
                known_imports=known_imports,
                async_methods=async_methods,
                component_map=component_map,
                scope_id=scope_id,
                enable_regions=False,
                wire_vars=wire_vars,
            )

        # 2. Then branch
        then_ast: List[ast.stmt] = []
        then_locals = set()
        if then_var:
            then_locals.add(then_var)
            then_ast.append(
                ast.Assign(
                    targets=[ast.Name(id=then_var, ctx=ast.Store())],
                    value=ast.Subscript(
                        value=ast.Name(id="state", ctx=ast.Load()),
                        slice=ast.Constant(value="result"),
                        ctx=ast.Load(),
                    ),
                )
            )

        for n in then_nodes:
            self._add_node(
                n,
                then_ast,
                local_vars=then_locals,
                layout_id=layout_id,
                known_methods=known_methods,
                known_globals=known_globals,
                known_imports=known_imports,
                async_methods=async_methods,
                component_map=component_map,
                scope_id=scope_id,
                enable_regions=False,
                wire_vars=wire_vars,
            )

        # 3. Catch branch
        catch_ast: List[ast.stmt] = []
        catch_locals = set()
        if catch_var:
            catch_locals.add(catch_var)
            catch_ast.append(
                ast.Assign(
                    targets=[ast.Name(id=catch_var, ctx=ast.Store())],
                    value=ast.Subscript(
                        value=ast.Name(id="state", ctx=ast.Load()),
                        slice=ast.Constant(value="error"),
                        ctx=ast.Load(),
                    ),
                )
            )

        for n in catch_nodes:
            self._add_node(
                n,
                catch_ast,
                local_vars=catch_locals,
                layout_id=layout_id,
                known_methods=known_methods,
                known_globals=known_globals,
                known_imports=known_imports,
                async_methods=async_methods,
                component_map=component_map,
                scope_id=scope_id,
                enable_regions=False,
                wire_vars=wire_vars,
            )

        # if state["status"] == "pending": ...
        if_stmt = ast.If(
            test=ast.Compare(
                left=ast.Subscript(
                    value=ast.Name(id="state", ctx=ast.Load()),
                    slice=ast.Constant(value="status"),
                    ctx=ast.Load(),
                ),
                ops=[ast.Eq()],
                comparators=[ast.Constant(value="pending")],
            ),
            body=pending_ast if pending_ast else [ast.Pass()],
            orelse=[
                ast.If(
                    test=ast.Compare(
                        left=ast.Subscript(
                            value=ast.Name(id="state", ctx=ast.Load()),
                            slice=ast.Constant(value="status"),
                            ctx=ast.Load(),
                        ),
                        ops=[ast.Eq()],
                        comparators=[ast.Constant(value="success")],
                    ),
                    body=then_ast if then_ast else [ast.Pass()],
                    orelse=catch_ast if catch_ast else [ast.Pass()],
                )
            ],
        )
        body.append(if_stmt)

        body.append(
            ast.Return(
                value=ast.Call(
                    func=ast.Attribute(
                        value=ast.Constant(value=""), attr="join", ctx=ast.Load()
                    ),
                    args=[ast.Name(id="parts", ctx=ast.Load())],
                    keywords=[],
                )
            )
        )

        return ast.AsyncFunctionDef(
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
            n
            for n in nodes
            if n.tag is not None and n.tag.lower() not in ("style", "script")
        ]
        if len(elements) == 1:
            return elements[0]
        return None

    def _set_line(self, node: ast.AST, template_node: TemplateNode) -> ast.AST:
        """Helper to set line number on AST node."""
        if template_node.line > 0 and hasattr(node, "lineno"):
            setattr(node, "lineno", template_node.line)
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
        known_imports: Optional[Set[str]] = None,
        async_methods: Optional[Set[str]] = None,
        component_map: Optional[Dict[str, str]] = None,
        scope_id: Optional[str] = None,
        parts_var: str = "parts",
        implicit_root_source: Optional[str] = None,
        enable_regions: bool = True,
        region_id: Optional[str] = None,
        wire_vars: Set[str] = set(),
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
        for_attr = next(
            (a for a in node.special_attributes if isinstance(a, ForAttribute)), None
        )
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
                known_imports,
                line_offset=node.line,
                col_offset=node.column,
                cached=False,
                wire_vars=wire_vars,
            )

            for_body: List[ast.stmt] = []
            else_body: List[ast.stmt] = []
            has_else = False

            new_attrs = [a for a in node.special_attributes if a is not for_attr]

            # Check if we should split children for for-else
            if node.tag == "template" or (not node.tag and not node.text_content):
                current_body = for_body
                prev_child = None
                for child in node.children:
                    # Add whitespace if there is a gap between this child and the previous one
                    self._add_gap_whitespace(
                        prev_child, child, current_body, parts_var=parts_var
                    )

                    # Check for $else attribute in child
                    else_attr = next(
                        (
                            a
                            for a in child.special_attributes
                            if isinstance(a, ElseAttribute)
                        ),
                        None,
                    )
                    if else_attr:
                        has_else = True
                        current_body = else_body
                        # Reset prev_child for the new body section
                        prev_child = None
                        # If child is JUST the marker, skip it, otherwise process it without the else_attr
                        if (
                            child.tag is None
                            and not child.text_content
                            and len(child.special_attributes) == 1
                        ):
                            continue

                    self._add_node(
                        child,
                        current_body,
                        new_locals if current_body is for_body else local_vars,
                        bound_var,
                        layout_id,
                        known_methods,
                        known_globals,
                        known_imports,
                        async_methods,
                        component_map,
                        scope_id,
                        parts_var=parts_var,
                        enable_regions=enable_regions,
                        wire_vars=wire_vars,
                    )
                    prev_child = child
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
                    known_imports,
                    async_methods,
                    component_map,
                    scope_id,
                    parts_var=parts_var,
                    enable_regions=enable_regions,
                    wire_vars=wire_vars,
                )

            # Wrap iterable in ensure_async_iterator
            wrapped_iterable = ast.Call(
                func=ast.Name(id="ensure_async_iterator", ctx=ast.Load()),
                args=[iterable_expr],
                keywords=[],
            )

            if has_else:
                # Flag to track if loop ran
                loop_any_var = f"_loop_any_{node.line}_{node.column}".replace("-", "_")
                body.append(
                    ast.Assign(
                        targets=[ast.Name(id=loop_any_var, ctx=ast.Store())],
                        value=ast.Constant(value=False),
                    )
                )
                # Inside loop, set flag to True
                for_body.insert(
                    0,
                    ast.Assign(
                        targets=[ast.Name(id=loop_any_var, ctx=ast.Store())],
                        value=ast.Constant(value=True),
                    ),
                )

                for_stmt = ast.AsyncFor(
                    target=loop_targets_node,
                    iter=wrapped_iterable,
                    body=for_body if for_body else [ast.Pass()],
                    orelse=[],
                )
                self._set_line(for_stmt, node)
                body.append(for_stmt)

                # If block for else body
                else_if_stmt = ast.If(
                    test=ast.UnaryOp(
                        op=ast.Not(), operand=ast.Name(id=loop_any_var, ctx=ast.Load())
                    ),
                    body=else_body if else_body else [ast.Pass()],
                    orelse=[],
                )
                body.append(else_if_stmt)
            else:
                for_stmt = ast.AsyncFor(
                    target=loop_targets_node,
                    iter=wrapped_iterable,
                    body=for_body if for_body else [ast.Pass()],
                    orelse=[],
                )
                # Tag with line number
                self._set_line(for_stmt, node)
                body.append(for_stmt)
            return

        # 2. Handle $if
        if_attr = next(
            (a for a in node.special_attributes if isinstance(a, IfAttribute)), None
        )
        if if_attr:
            # We need to handle branches (elif, else)
            # Strategy: Partition children into list of (condition_expr, body_nodes)
            branches: List[Tuple[Optional[ast.expr], List[TemplateNode]]] = []
            current_branch_nodes: List[TemplateNode] = []
            branches.append(
                (None, current_branch_nodes)
            )  # First branch (the 'if' content)

            prev_child = None
            for child in node.children:
                # If there's a gap between prev_child and child, we should insert a text node into current_branch_nodes!
                if prev_child and child.line == prev_child.line:
                    end_line, end_col = self._get_node_end_pos(prev_child)
                    if child.column > end_col:
                        gap_size = child.column - end_col
                        if gap_size > 0:
                            current_branch_nodes.append(
                                TemplateNode(
                                    tag=None,
                                    text_content=" " * gap_size,
                                    line=child.line,
                                    column=end_col,
                                )
                            )

                elif_attr = next(
                    (
                        a
                        for a in child.special_attributes
                        if isinstance(a, ElifAttribute)
                    ),
                    None,
                )
                else_attr = next(
                    (
                        a
                        for a in child.special_attributes
                        if isinstance(a, ElseAttribute)
                    ),
                    None,
                )

                if elif_attr:
                    current_branch_nodes = []
                    # Reset gap tracking for new branch
                    prev_child = None
                    cond = self._transform_expr(
                        elif_attr.condition,
                        local_vars,
                        known_globals,
                        known_imports,
                        line_offset=child.line,
                        cached=False,
                    )
                    branches.append((cond, current_branch_nodes))
                elif else_attr:
                    current_branch_nodes = []
                    # Reset gap tracking for new branch
                    prev_child = None
                    branches.append(
                        (ast.Constant(value=True), current_branch_nodes)
                    )  # else is test=True in the orelse chain
                else:
                    # If there's a gap between prev_child and child, we should insert a text node into current_branch_nodes!
                    if prev_child and child.line == prev_child.line:
                        end_line, end_col = self._get_node_end_pos(prev_child)
                        if child.column > end_col:
                            gap_size = child.column - end_col
                            if gap_size > 0:
                                current_branch_nodes.append(
                                    TemplateNode(
                                        tag=None,
                                        text_content=" " * gap_size,
                                        line=child.line,
                                        column=end_col,
                                    )
                                )
                    current_branch_nodes.append(child)
                    prev_child = child

            # Build the if/elif/else tree from branches
            # branches[0] is the 'if' body.
            # branches[1:] are elifs/else.

            # 1. Main IF body
            main_cond = self._transform_expr(
                if_attr.condition,
                local_vars,
                known_globals,
                known_imports,
                line_offset=node.line,
                cached=False,
            )
            main_body: List[ast.stmt] = []
            for b_node in branches[0][1]:
                self._add_node(
                    b_node,
                    main_body,
                    local_vars,
                    bound_var,
                    layout_id,
                    known_methods,
                    known_globals,
                    known_imports,
                    async_methods,
                    component_map,
                    scope_id,
                    parts_var=parts_var,
                    enable_regions=enable_regions,
                )

            # 2. Build orelse chain from back to front
            orelse: List[ast.stmt] = []
            for i in range(len(branches) - 1, 0, -1):
                raw_cond, body_nodes = branches[i]
                assert raw_cond is not None
                cond = raw_cond
                branch_ast_body: List[ast.stmt] = []
                for b_node in body_nodes:
                    self._add_node(
                        b_node,
                        branch_ast_body,
                        local_vars,
                        bound_var,
                        layout_id,
                        known_methods,
                        known_globals,
                        known_imports,
                        async_methods,
                        component_map,
                        scope_id,
                        parts_var=parts_var,
                        enable_regions=enable_regions,
                    )

                if isinstance(cond, ast.Constant) and cond.value is True:
                    # pure else (always at end)
                    orelse = branch_ast_body
                else:
                    # elif
                    nested_if = ast.If(
                        test=cond,
                        body=branch_ast_body if branch_ast_body else [ast.Pass()],
                        orelse=orelse,
                    )
                    orelse = [nested_if]

            if_stmt = ast.If(
                test=main_cond,
                body=main_body if main_body else [ast.Pass()],
                orelse=orelse,
            )
            self._set_line(if_stmt, node)
            body.append(if_stmt)
            return

        # 2a. Handle $try
        try_attr = next(
            (a for a in node.special_attributes if isinstance(a, TryAttribute)), None
        )
        if try_attr:
            # Partition children into try_block_nodes, handlers (except), try_else_nodes, try_finally_nodes
            try_block_nodes: List[TemplateNode] = []
            handlers: List[ast.ExceptHandler] = []
            try_else_nodes: List[TemplateNode] = []
            try_finally_nodes: List[TemplateNode] = []

            current_try_section: List[TemplateNode] = try_block_nodes

            prev_child = None
            for child in node.children:
                # Add whitespace gap node if needed
                if prev_child and child.line == prev_child.line:
                    end_line, end_col = self._get_node_end_pos(prev_child)
                    if child.column > end_col:
                        gap_size = child.column - end_col
                        if gap_size > 0:
                            current_try_section.append(
                                TemplateNode(
                                    tag=None,
                                    text_content=" " * gap_size,
                                    line=child.line,
                                    column=end_col,
                                )
                            )

                exc_attr = next(
                    (
                        a
                        for a in child.special_attributes
                        if isinstance(a, ExceptAttribute)
                    ),
                    None,
                )
                fin_attr = next(
                    (
                        a
                        for a in child.special_attributes
                        if isinstance(a, FinallyAttribute)
                    ),
                    None,
                )
                else_marker = next(
                    (
                        a
                        for a in child.special_attributes
                        if isinstance(a, ElseAttribute)
                    ),
                    None,
                )  # reuse ElseAttribute for try/else

                if exc_attr:
                    exc_block_body: List[TemplateNode] = []
                    # Transform type and name if present
                    type_node = None
                    if exc_attr.exception_type:
                        type_node = self._transform_expr(
                            exc_attr.exception_type,
                            local_vars,
                            known_globals,
                            known_imports,
                            line_offset=child.line,
                            cached=False,
                        )

                    handler = ast.ExceptHandler(
                        type=type_node,
                        name=exc_attr.alias,
                        body=cast(Any, exc_block_body),
                    )
                    handlers.append(handler)
                    current_try_section = exc_block_body
                    prev_child = None  # Reset gap tracking for new section
                elif else_marker:
                    current_try_section = try_else_nodes
                    prev_child = None  # Reset gap tracking for new section
                elif fin_attr:
                    current_try_section = try_finally_nodes
                    prev_child = None  # Reset gap tracking for new section
                else:
                    current_try_section.append(child)
                    prev_child = child

            # Generate AST for bodies
            try_ast_body: List[ast.stmt] = []
            for b_node in try_block_nodes:
                self._add_node(
                    b_node,
                    try_ast_body,
                    local_vars,
                    bound_var,
                    layout_id,
                    known_methods,
                    known_globals,
                    known_imports,
                    async_methods,
                    component_map,
                    scope_id,
                    parts_var=parts_var,
                )

            for h in handlers:
                real_nodes = cast(
                    List[TemplateNode], h.body[:]
                )  # Copy of TemplateNodes
                h.body = []  # Reset to ast.stmt

                # Add exception alias to local vars for children of this handler
                handler_locals = local_vars.copy()
                if h.name:
                    handler_locals.add(h.name)

                for b_node in real_nodes:
                    self._add_node(
                        b_node,
                        h.body,
                        handler_locals,
                        bound_var,
                        layout_id,
                        known_methods,
                        known_globals,
                        known_imports,
                        async_methods,
                        component_map,
                        scope_id,
                        parts_var=parts_var,
                        wire_vars=wire_vars,
                    )
                if not h.body:
                    h.body = [ast.Pass()]

            else_ast_body: List[ast.stmt] = []
            for b_node in try_else_nodes:
                self._add_node(
                    b_node,
                    else_ast_body,
                    local_vars,
                    bound_var,
                    layout_id,
                    known_methods,
                    known_globals,
                    known_imports,
                    async_methods,
                    component_map,
                    scope_id,
                    parts_var=parts_var,
                    wire_vars=wire_vars,
                )

            finally_ast_body: List[ast.stmt] = []
            for b_node in try_finally_nodes:
                self._add_node(
                    b_node,
                    finally_ast_body,
                    local_vars,
                    bound_var,
                    layout_id,
                    known_methods,
                    known_globals,
                    known_imports,
                    async_methods,
                    component_map,
                    scope_id,
                    parts_var=parts_var,
                    wire_vars=wire_vars,
                )

            try_stmt = ast.Try(
                body=try_ast_body,
                handlers=handlers,
                orelse=else_ast_body,
                finalbody=finally_ast_body,
            )
            self._set_line(try_stmt, node)
            body.append(try_stmt)
            return

        # 2b. Handle $await
        await_attr = next(
            (a for a in node.special_attributes if isinstance(a, AwaitAttribute)), None
        )
        if await_attr:
            # Handle await blocks: pending, then, catch
            pending_body: List[TemplateNode] = []
            then_body: List[TemplateNode] = []
            catch_body: List[TemplateNode] = []

            then_var = None
            catch_var = None

            current_await_section: List[TemplateNode] = pending_body
            prev_child = None
            for child in node.children:
                # Add whitespace gap node if needed
                if prev_child and child.line == prev_child.line:
                    end_line, end_col = self._get_node_end_pos(prev_child)
                    if child.column > end_col:
                        gap_size = child.column - end_col
                        if gap_size > 0:
                            current_await_section.append(
                                TemplateNode(
                                    tag=None,
                                    text_content=" " * gap_size,
                                    line=child.line,
                                    column=end_col,
                                )
                            )

                then_attr = next(
                    (
                        a
                        for a in child.special_attributes
                        if isinstance(a, ThenAttribute)
                    ),
                    None,
                )
                catch_attr = next(
                    (
                        a
                        for a in child.special_attributes
                        if isinstance(a, CatchAttribute)
                    ),
                    None,
                )

                if then_attr:
                    current_await_section = then_body
                    then_var = then_attr.variable
                    prev_child = None  # Reset gap tracking for new section
                elif catch_attr:
                    current_await_section = catch_body
                    catch_var = catch_attr.variable
                    prev_child = None  # Reset gap tracking for new section
                else:
                    current_await_section.append(child)
                    prev_child = child

            # Generate region ID and method name
            region_id = f"await_{node.line}_{node.column}".replace("-", "_")
            method_name = f"_render_await_{region_id}"
            self.region_renderers[region_id] = method_name

            # Generate the region renderer function
            aux_func = self._generate_await_renderer(
                node.children,
                method_name,
                region_id,
                await_attr,
                pending_body,
                then_body,
                then_var,
                catch_body,
                catch_var,
                layout_id,
                known_methods,
                known_globals,
                known_imports,
                async_methods,
                component_map,
                scope_id,
                wire_vars=wire_vars,
            )
            self.auxiliary_functions.append(aux_func)

            awaitable_expr = self._transform_expr(
                await_attr.expression,
                local_vars,
                known_globals,
                known_imports,
                line_offset=node.line,
                cached=False,
                wire_vars=wire_vars,
            )

            # In main render:
            # 1. parts.append('<div data-pw-region="...">')
            body.append(
                ast.Expr(
                    value=ast.Call(
                        func=ast.Attribute(
                            value=ast.Name(id=parts_var, ctx=ast.Load()),
                            attr="append",
                            ctx=ast.Load(),
                        ),
                        args=[
                            ast.Constant(
                                value=f'<div data-pw-region="{region_id}" style="display: contents;">'
                            )
                        ],
                        keywords=[],
                    )
                )
            )

            # 2. Start resolution task if not already started
            # if region_id not in self._await_states:
            #    _task = asyncio.create_task(self._resolve_await(region_id, expr))
            #    self._background_tasks.add(_task)
            #    _task.add_done_callback(self._background_tasks.discard)
            start_task_stmt = ast.If(
                test=ast.Compare(
                    left=ast.Constant(value=region_id),
                    ops=[ast.NotIn()],
                    comparators=[
                        ast.Attribute(
                            value=ast.Name(id="self", ctx=ast.Load()),
                            attr="_await_states",
                            ctx=ast.Load(),
                        )
                    ],
                ),
                body=[
                    ast.Assign(
                        targets=[ast.Name(id="_await_task", ctx=ast.Store())],
                        value=ast.Call(
                            func=ast.Attribute(
                                value=ast.Name(id="asyncio", ctx=ast.Load()),
                                attr="create_task",
                                ctx=ast.Load(),
                            ),
                            args=[
                                ast.Call(
                                    func=ast.Attribute(
                                        value=ast.Name(id="self", ctx=ast.Load()),
                                        attr="_resolve_await",
                                        ctx=ast.Load(),
                                    ),
                                    args=[
                                        ast.Constant(value=region_id),
                                        awaitable_expr,
                                    ],
                                    keywords=[],
                                )
                            ],
                            keywords=[],
                        ),
                    ),
                    ast.Expr(
                        value=ast.Call(
                            func=ast.Attribute(
                                value=ast.Attribute(
                                    value=ast.Name(id="self", ctx=ast.Load()),
                                    attr="_background_tasks",
                                    ctx=ast.Load(),
                                ),
                                attr="add",
                                ctx=ast.Load(),
                            ),
                            args=[ast.Name(id="_await_task", ctx=ast.Load())],
                            keywords=[],
                        )
                    ),
                    ast.Expr(
                        value=ast.Call(
                            func=ast.Attribute(
                                value=ast.Name(id="_await_task", ctx=ast.Load()),
                                attr="add_done_callback",
                                ctx=ast.Load(),
                            ),
                            args=[
                                ast.Attribute(
                                    value=ast.Attribute(
                                        value=ast.Name(id="self", ctx=ast.Load()),
                                        attr="_background_tasks",
                                        ctx=ast.Load(),
                                    ),
                                    attr="discard",
                                    ctx=ast.Load(),
                                )
                            ],
                            keywords=[],
                        )
                    ),
                ],
                orelse=[],
            )
            body.append(start_task_stmt)

            # 3. parts.append(await self._render_await_...())
            body.append(
                ast.Expr(
                    value=ast.Call(
                        func=ast.Attribute(
                            value=ast.Name(id=parts_var, ctx=ast.Load()),
                            attr="append",
                            ctx=ast.Load(),
                        ),
                        args=[
                            ast.Await(
                                value=ast.Call(
                                    func=ast.Attribute(
                                        value=ast.Name(id="self", ctx=ast.Load()),
                                        attr=method_name,
                                        ctx=ast.Load(),
                                    ),
                                    args=[],
                                    keywords=[],
                                )
                            )
                        ],
                        keywords=[],
                    )
                )
            )

            # 4. parts.append('</div>')
            body.append(
                ast.Expr(
                    value=ast.Call(
                        func=ast.Attribute(
                            value=ast.Name(id=parts_var, ctx=ast.Load()),
                            attr="append",
                            ctx=ast.Load(),
                        ),
                        args=[ast.Constant(value="</div>")],
                        keywords=[],
                    )
                )
            )
            return

        # --- Handle <slot> ---
        if node.tag == "slot":
            slot_name = node.attributes.get("name", "default")
            is_head_slot = "$head" in node.attributes

            default_renderer_arg: ast.expr = ast.Constant(value=None)
            if node.children:
                self._slot_default_counter += 1
                func_name = (
                    f"_render_slot_default_{slot_name}_{self._slot_default_counter}"
                )
                aux_func = self._generate_function(
                    node.children, func_name, is_async=True
                )
                self.auxiliary_functions.append(aux_func)
                default_renderer_arg = ast.Attribute(
                    value=ast.Name(id="self", ctx=ast.Load()),
                    attr=func_name,
                    ctx=ast.Load(),
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
                call_kwargs.append(
                    ast.keyword(arg="append", value=ast.Constant(value=True))
                )

            render_call = ast.Call(
                func=ast.Attribute(
                    value=ast.Name(id="self", ctx=ast.Load()),
                    attr="render_slot",
                    ctx=ast.Load(),
                ),
                args=[ast.Constant(value=slot_name)],
                keywords=call_kwargs,
            )

            append_stmt = ast.Expr(
                value=ast.Call(
                    func=ast.Attribute(
                        value=ast.Name(id="parts", ctx=ast.Load()),
                        attr="append",
                        ctx=ast.Load(),
                    ),
                    args=[ast.Await(value=render_call)],
                    keywords=[],
                )
            )

            append_stmt = ast.Expr(
                value=ast.Call(
                    func=ast.Attribute(
                        value=ast.Name(id=parts_var, ctx=ast.Load()),
                        attr="append",
                        ctx=ast.Load(),
                    ),
                    args=[ast.Await(value=render_call)],
                    keywords=[],
                )
            )
            self._set_line(append_stmt, node)
            body.append(append_stmt)
            return

        if node.tag and (
            (component_map and node.tag in component_map) or node.tag[0].isupper()
        ):
            cls_name = (
                component_map[node.tag]
                if component_map and node.tag in component_map
                else node.tag
            )

            # Prepare arguments (kwargs)
            # Prepare arguments (kwargs dict keys/values)
            dict_keys: List[Optional[ast.expr]] = []
            dict_values: List[ast.expr] = []

            # 1. Pass implicit context props (request, params, etc.)
            for ctx_prop in ["request", "params", "query", "path", "url"]:
                dict_keys.append(ast.Constant(value=ctx_prop))
                dict_values.append(
                    ast.Attribute(
                        value=ast.Name(id="self", ctx=ast.Load()),
                        attr=ctx_prop,
                        ctx=ast.Load(),
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
                    value=ast.Name(id="self", ctx=ast.Load()),
                    attr="context",
                    ctx=ast.Load(),
                )
            )

            # 2. Pass explicitly defined props (static)
            ref_expr = None
            for k, v in node.attributes.items():
                if k == "ref":
                    # Extract ref expression
                    if "{" in v and "}" in v:
                        v_stripped = v.strip()
                        if (
                            v_stripped.startswith("{")
                            and v_stripped.endswith("}")
                            and v_stripped.count("{") == 1
                        ):
                            expr_code = v_stripped[1:-1]
                            ref_expr = self._transform_expr(
                                expr_code,
                                local_vars,
                                known_globals,
                                line_offset=node.line,
                                col_offset=node.column,
                                no_unwrap=True,
                            )
                    continue

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
                        parts = self.interpolation_parser.parse(
                            v, node.line, node.column
                        )
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
                        val_expr = (
                            current_concat if current_concat else ast.Constant(value="")
                        )
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
                    if attr.name == "ref":
                        # Groundwork for component refs
                        expr = self._transform_reactive_expr(
                            attr.expr,
                            local_vars,
                            known_methods=known_methods,
                            known_globals=known_globals,
                            known_imports=known_imports,
                            async_methods=async_methods,
                            line_offset=node.line,
                            col_offset=node.column,
                            cached=False,  # Don't cache ref expressions? Usually they are simple wires
                            wire_vars=wire_vars,
                            no_unwrap=True,
                        )
                        ref_expr = expr
                        continue

                    dict_keys.append(ast.Constant(value=attr.name))
                    expr = self._transform_reactive_expr(
                        attr.expr,
                        local_vars,
                        known_methods=known_methods,
                        known_globals=known_globals,
                        known_imports=known_imports,
                        async_methods=async_methods,
                        line_offset=node.line,
                        col_offset=node.column,
                        wire_vars=wire_vars,
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
                    if raw_handler.strip().startswith(
                        "{"
                    ) and raw_handler.strip().endswith("}"):
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
                        dict_keys.append(
                            ast.Constant(value=f"data-modifiers-{event_type}")
                        )
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
                    handler_list_name = (
                        f"_handlers_{event_type}_{node.line}_{node.column}"
                    )

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
                ast.keyword(
                    arg=None, value=ast.Dict(keys=dict_keys, values=dict_values)
                )
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
                slot_var_name = f"_slot_{s_name}_{node.line}_{node.column}".replace(
                    "-", "_"
                )
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
                        known_imports,
                        async_methods,
                        component_map,
                        scope_id,
                        parts_var=slot_parts_var,
                        enable_regions=enable_regions,
                        wire_vars=wire_vars,
                    )  # PASS slot_parts_var

                # Join parts -> slot string
                # rendered_slot = "".join(slot_parts_var)
                body.append(
                    ast.Assign(
                        targets=[ast.Name(id=slot_var_name, ctx=ast.Store())],
                        value=ast.Call(
                            func=ast.Attribute(
                                value=ast.Constant(value=""),
                                attr="join",
                                ctx=ast.Load(),
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
                            keys=keys,
                            values=values,
                        ),
                    )
                )

            # Instantiate component
            comp_var = f"_comp_{node.line}_{node.column}"
            body.append(
                ast.Assign(
                    targets=[ast.Name(id=comp_var, ctx=ast.Store())],
                    value=ast.Call(
                        func=ast.Name(id=cls_name, ctx=ast.Load()),
                        args=[],
                        keywords=keywords,
                    ),
                )
            )

            if ref_expr:
                # Groundwork for component refs
                # comp._ref = ref_expr
                body.append(
                    ast.Assign(
                        targets=[
                            ast.Attribute(
                                value=ast.Name(id=comp_var, ctx=ast.Load()),
                                attr="_ref",
                                ctx=ast.Store(),
                            )
                        ],
                        value=ref_expr,
                    )
                )

            render_call = ast.Call(
                func=ast.Attribute(
                    value=ast.Name(id=comp_var, ctx=ast.Load()),
                    attr="_render_template",
                    ctx=ast.Load(),
                ),
                args=[],
                keywords=[],
            )

            # Append result
            # parts.append(await ...)
            append_stmt = ast.Expr(
                value=ast.Call(
                    func=ast.Attribute(
                        value=ast.Name(id=parts_var, ctx=ast.Load()),
                        attr="append",
                        ctx=ast.Load(),
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
            # Text or Fragment
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
                            expr = self._transform_expr(
                                part.expression,
                                local_vars,
                                known_globals,
                                line_offset=part.line,
                                col_offset=part.column,
                            )
                            # Check if this is a raw (unescaped) interpolation
                            is_raw = getattr(part, "is_raw", False)
                            if is_raw:
                                # Raw HTML - no escaping
                                term = ast.Call(
                                    func=ast.Name(id="str", ctx=ast.Load()),
                                    args=[self._wrap_unwrap_wire(expr)],
                                    keywords=[],
                                )
                            else:
                                # Default: escape HTML for XSS prevention
                                term = ast.Call(
                                    func=ast.Name(id="escape_html", ctx=ast.Load()),
                                    args=[self._wrap_unwrap_wire(expr)],
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
                expr = self._transform_expr(
                    interp.expression,
                    local_vars,
                    known_globals,
                    line_offset=interp.line,
                    col_offset=interp.column,
                )
                # Check if this is a raw (unescaped) interpolation
                is_raw = getattr(interp, "is_raw", False)
                if is_raw:
                    # Raw HTML - no escaping
                    term = ast.Call(
                        func=ast.Name(id="str", ctx=ast.Load()),
                        args=[self._wrap_unwrap_wire(expr)],
                        keywords=[],
                    )
                else:
                    # Default: escape HTML for XSS prevention
                    term = ast.Call(
                        func=ast.Name(id="escape_html", ctx=ast.Load()),
                        args=[self._wrap_unwrap_wire(expr)],
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
            elif node.children:
                # Fragment support: render all children sequentially
                for child in node.children:
                    self._add_node(
                        child,
                        body,
                        local_vars,
                        bound_var,
                        layout_id,
                        known_methods,
                        known_globals,
                        known_imports,
                        async_methods,
                        component_map,
                        scope_id,
                        parts_var=parts_var,
                        enable_regions=enable_regions,
                        wire_vars=wire_vars,
                    )
        else:
            # Element
            if (
                enable_regions
                and not local_vars
                and self._node_is_dynamic(node, known_globals)
            ):
                region_id = self._next_region_id()
                method_name = f"_render_region_{region_id}"
                self.region_renderers[region_id] = method_name
                self.auxiliary_functions.append(
                    self._generate_region_method(
                        node,
                        method_name,
                        region_id,
                        layout_id,
                        known_methods,
                        known_globals,
                        known_imports,
                        async_methods,
                        component_map,
                        scope_id,
                        implicit_root_source,
                    )
                )

                append_stmt = ast.Expr(
                    value=ast.Call(
                        func=ast.Attribute(
                            value=ast.Name(id=parts_var, ctx=ast.Load()),
                            attr="append",
                            ctx=ast.Load(),
                        ),
                        args=[
                            ast.Await(
                                value=ast.Call(
                                    func=ast.Attribute(
                                        value=ast.Name(id="self", ctx=ast.Load()),
                                        attr=method_name,
                                        ctx=ast.Load(),
                                    ),
                                    args=[],
                                    keywords=[],
                                )
                            )
                        ],
                        keywords=[],
                    )
                )
                self._set_line(append_stmt, node)
                body.append(append_stmt)
                return

            bindings: Dict[str, ast.expr] = {}
            new_bound_var = bound_var
            if region_id:
                bindings["data-pw-region"] = ast.Constant(value=region_id)

            show_attr = next(
                (a for a in node.special_attributes if isinstance(a, ShowAttribute)),
                None,
            )
            key_attr = next(
                (a for a in node.special_attributes if isinstance(a, KeyAttribute)),
                None,
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
                            cached=False,
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

            apply_scope = scope_id and node.tag not in (
                "style",
                "script",
                "slot",
                "template",
            )
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
                                    self._transform_expr(
                                        part.expression, local_vars, known_globals
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

                    val_expr = (
                        current_concat if current_concat else ast.Constant(value="")
                    )
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
                            args=[self._wrap_unwrap_wire(binding_expr)],
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
                                        slice=ast.Constant(
                                            value=f"data-modifiers-{event_type}"
                                        ),
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
                            keys=[
                                ast.Constant(value="handler"),
                                ast.Constant(value="modifiers"),
                            ],
                            values=[
                                ast.Constant(value=attr.handler_name),
                                ast.List(
                                    elts=[ast.Constant(value=m) for m in modifiers],
                                    ctx=ast.Load(),
                                ),
                            ],
                        )
                        body.append(
                            ast.Assign(
                                targets=[ast.Name(id="_h", ctx=ast.Store())],
                                value=handler_dict,
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
                                        value=ast.Name(
                                            id=handler_list_name, ctx=ast.Load()
                                        ),
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
                                        slice=ast.Constant(
                                            value=f"data-modifiers-{event_type}"
                                        ),
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
                        known_methods=known_methods,
                        known_globals=known_globals,
                        known_imports=known_imports,
                        async_methods=async_methods,
                        line_offset=node.line,
                        col_offset=node.column,
                    )
                    val_expr = self._wrap_unwrap_wire(val_expr)

                    # _r_val = val_expr
                    body.append(
                        ast.Assign(
                            targets=[ast.Name(id="_r_val", ctx=ast.Store())],
                            value=val_expr,
                        )
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
                                                value=ast.Name(
                                                    id="attrs", ctx=ast.Load()
                                                ),
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
                                                        value=ast.Name(
                                                            id="attrs", ctx=ast.Load()
                                                        ),
                                                        slice=ast.Constant(
                                                            value=attr.name
                                                        ),
                                                        ctx=ast.Store(),
                                                    )
                                                ],
                                                value=ast.Constant(value="false"),
                                            )
                                        ],
                                        orelse=[
                                            ast.If(
                                                test=ast.Compare(
                                                    left=ast.Name(
                                                        id="_r_val", ctx=ast.Load()
                                                    ),
                                                    ops=[ast.IsNot()],
                                                    comparators=[
                                                        ast.Constant(value=None)
                                                    ],
                                                ),
                                                body=[
                                                    ast.Assign(
                                                        targets=[
                                                            ast.Subscript(
                                                                value=ast.Name(
                                                                    id="attrs",
                                                                    ctx=ast.Load(),
                                                                ),
                                                                slice=ast.Constant(
                                                                    value=attr.name
                                                                ),
                                                                ctx=ast.Store(),
                                                            )
                                                        ],
                                                        value=ast.Call(
                                                            func=ast.Name(
                                                                id="str", ctx=ast.Load()
                                                            ),
                                                            args=[
                                                                ast.Name(
                                                                    id="_r_val",
                                                                    ctx=ast.Load(),
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
                                                value=ast.Name(
                                                    id="attrs", ctx=ast.Load()
                                                ),
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
                                                    left=ast.Name(
                                                        id="_r_val", ctx=ast.Load()
                                                    ),
                                                    ops=[ast.IsNot()],
                                                    comparators=[
                                                        ast.Constant(value=False)
                                                    ],
                                                ),
                                                ast.Compare(
                                                    left=ast.Name(
                                                        id="_r_val", ctx=ast.Load()
                                                    ),
                                                    ops=[ast.IsNot()],
                                                    comparators=[
                                                        ast.Constant(value=None)
                                                    ],
                                                ),
                                            ],
                                        ),
                                        body=[
                                            ast.Assign(
                                                targets=[
                                                    ast.Subscript(
                                                        value=ast.Name(
                                                            id="attrs", ctx=ast.Load()
                                                        ),
                                                        slice=ast.Constant(
                                                            value=attr.name
                                                        ),
                                                        ctx=ast.Store(),
                                                    )
                                                ],
                                                value=ast.Call(
                                                    func=ast.Name(
                                                        id="str", ctx=ast.Load()
                                                    ),
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
                        )

            if show_attr:
                cond = self._transform_expr(
                    show_attr.condition,
                    local_vars,
                    known_globals,
                    line_offset=node.line,
                    col_offset=node.column,
                    cached=False,
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
                                        args=[
                                            ast.Constant(value="style"),
                                            ast.Constant(value=""),
                                        ],
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
                (a for a in node.special_attributes if isinstance(a, SpreadAttribute)),
                None,
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
                    wire_vars=wire_vars,
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

            prev_child = None
            for child in node.children:
                # Add whitespace if there is a gap between this child and the previous one
                self._add_gap_whitespace(prev_child, child, body, parts_var=parts_var)

                self._add_node(
                    child,
                    body,
                    local_vars,
                    new_bound_var,
                    layout_id,
                    known_methods,
                    known_globals,
                    known_imports,
                    async_methods,
                    component_map,
                    scope_id,
                    parts_var=parts_var,
                    implicit_root_source=implicit_root_source,
                    enable_regions=enable_regions,
                    wire_vars=wire_vars,
                )
                prev_child = child

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

    def _get_node_end_pos(self, node: TemplateNode) -> Tuple[int, int]:
        """Estimate the end line/column of a node for gap detection."""
        if node.tag is None and node.text_content:
            # Text node
            lines = node.text_content.splitlines()
            if not lines:
                return node.line, node.column
            if len(lines) == 1:
                return node.line, node.column + len(lines[0])
            return node.line + len(lines) - 1, len(lines[-1])

        # If it's a tag, we estimate the size of the opening tag.
        # This helps detect gaps after <p> etc.
        if node.tag:
            # Estimation: <tag ...>
            # We don't know the exact end of the opening tag easily,
            # but we mostly care about gaps between siblings.
            return node.line, node.column + len(node.tag) + 2

        # Look for interpolation nodes
        from pywire.compiler.ast_nodes import InterpolationNode

        for attr in node.special_attributes:
            if isinstance(attr, InterpolationNode):
                return node.line, node.column + len(attr.expression) + 2
            # Handle block markers {/if} etc. if they appear here
            if (
                node.tag is None
                and not node.text_content
                and getattr(attr, "keyword", "")
            ):
                kw = getattr(attr, "keyword", "")
                return node.line, node.column + len(kw) + 3

        return node.line, node.column

    def _add_gap_whitespace(
        self,
        prev_node: Optional[TemplateNode],
        curr_node: TemplateNode,
        body: List[ast.stmt],
        parts_var: str = "parts",
    ) -> None:
        """Add whitespace to parts if there is a gap between nodes on the same line."""
        if not prev_node:
            return

        if curr_node.line == prev_node.line:
            prev_end_line, prev_end_col = self._get_node_end_pos(prev_node)
            if curr_node.line == prev_end_line and curr_node.column > prev_end_col:
                gap_size = curr_node.column - prev_end_col
                if gap_size > 0:
                    whitespace = " " * gap_size
                    body.append(
                        ast.Expr(
                            value=ast.Call(
                                func=ast.Attribute(
                                    value=ast.Name(id=parts_var, ctx=ast.Load()),
                                    attr="append",
                                    ctx=ast.Load(),
                                ),
                                args=[ast.Constant(value=whitespace)],
                                keywords=[],
                            )
                        )
                    )
