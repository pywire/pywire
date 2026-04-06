"""Main code generator orchestrator."""

import ast
import re
from typing import Any, Dict, List, Optional, Set, Tuple, Type, Union, cast

from pywire.compiler.ast_nodes import (
    Directive,
    EventAttribute,
    InjectDirective,
    LayoutDirective,
    NoSpaDirective,
    ParsedPyWire,
    PathDirective,
    PropsDirective,
    ProvideDirective,
    SpecialAttribute,
    TemplateNode,
)
from pywire.compiler.codegen.attributes.base import AttributeCodegen
from pywire.compiler.codegen.attributes.events import EventAttributeCodegen
from pywire.compiler.codegen.directives.base import DirectiveCodegen
from pywire.compiler.codegen.directives.path import PathDirectiveCodegen
from pywire.compiler.codegen.template import TemplateCodegen


class CodeGenerator:
    """Generates Python module from ParsedPyWire AST."""

    def __init__(self) -> None:
        self.directive_handlers: Dict[Type[Directive], DirectiveCodegen] = {
            PathDirective: PathDirectiveCodegen(),
            # Future: LayoutDirective: LayoutDirectiveCodegen(), etc.
        }

        self.attribute_handlers: Dict[Type[SpecialAttribute], AttributeCodegen] = {
            EventAttribute: EventAttributeCodegen(),
            # Future: BindAttribute: BindAttributeCodegen(), etc.
        }

        self.template_codegen = TemplateCodegen()
        self._collected_props = None

    def generate(self, parsed: ParsedPyWire) -> ast.Module:
        """Generate complete module AST."""
        self.file_path = parsed.file_path
        self._has_top_level_init = False
        self._collected_mount_hooks: List[str] = []
        self._collected_derived_hooks: List[str] = []
        self._collected_effect_hooks: List[str] = []
        self._collected_exposed_methods: List[str] = []
        self._wire_vars_from_decorators: Set[str] = set()
        self._collected_props: Optional[PropsDirective] = None
        module_body = []

        # Imports
        module_body.extend(self._generate_imports())

        # Add asyncio import for handle_event
        module_body.append(ast.Import(names=[ast.alias(name="asyncio", asname=None)]))

        # Component mapping logic
        # 1. From Imports (PascalCase convention)
        component_map = self._generate_component_map_from_imports(parsed.python_ast)

        # 2. From Legacy Directives (Removed)
        # comp_stmts = self._generate_component_loading(parsed, component_map)
        # module_body.extend(comp_stmts)

        # Layout logic
        layout_directive = parsed.get_directive_by_type(LayoutDirective)

        if layout_directive:
            layout_directive = cast(LayoutDirective, layout_directive)
            # Import load_layout
            module_body.append(
                ast.ImportFrom(
                    module="pywire.runtime.loader",
                    names=[ast.alias(name="load_layout", asname=None)],
                    level=0,
                )
            )
            # Load layout class
            # _LayoutBase = load_layout("path", __file_path__)
            module_body.append(
                ast.Assign(
                    targets=[ast.Name(id="_LayoutBase", ctx=ast.Store())],
                    value=ast.Call(
                        func=ast.Name(id="load_layout", ctx=ast.Load()),
                        args=[
                            ast.Constant(value=layout_directive.layout_path),
                            ast.Constant(
                                value=parsed.file_path
                            ),  # Pass page file path for relative resolution
                        ],
                        keywords=[],
                    ),
                )
            )
            # Extract user imports from Python section
        if parsed.python_ast:
            module_body.extend(self._extract_user_imports(parsed.python_ast))
            module_body.extend(self._extract_user_classes(parsed.python_ast))

        # Extract props from @props decorator
        self._collected_props = self._extract_props_from_ast(parsed.python_ast)

        known_methods, known_vars, async_methods = self._collect_global_names(
            parsed.python_ast
        )
        known_methods_names = set(known_methods.keys())

        if self._collected_props:
            for prop_name, _, _ in self._collected_props.args:
                known_vars.add(prop_name)

        # Include explicit variable assignments
        known_vars.update(self._extract_user_variables(parsed.python_ast))

        known_imports = self._extract_import_names(parsed.python_ast)

        # Inline handlers (with method names)
        # Note: Handlers only need to know about globals to avoid "self." prefixing if needed,
        # but _process_handlers mostly cares about wrapping logic.
        # Actually _process_handlers calls _transform_inline_code which uses known_methods.
        # Ideally it should know about all globals too.
        handlers = self._process_handlers(
            parsed, known_methods_names, known_vars, async_methods
        )

        # Extract wire variables for auto-unwrapping
        wire_vars = self._extract_wire_vars(parsed.python_ast)
        wire_vars.update(self._wire_vars_from_decorators)

        # Page class
        page_class = self._generate_page_class(
            parsed,
            handlers,
            known_methods,
            known_vars,
            known_imports,
            async_methods,
            component_map,
            wire_vars,
        )
        module_body.append(page_class)

        # Export reference to main class
        module_body.append(
            ast.Assign(
                targets=[ast.Name(id="__page_class__", ctx=ast.Store())],
                value=ast.Name(id=page_class.name, ctx=ast.Load()),
            )
        )

        module = ast.Module(body=module_body, type_ignores=[])
        ast.fix_missing_locations(module)

        return module

    def _generate_imports(self) -> List[ast.stmt]:
        """Generate framework imports."""
        imports: List[ast.stmt] = [
            ast.ImportFrom(
                module="pywire.runtime.page",
                names=[ast.alias(name="BasePage", asname=None)],
                level=0,
            ),
            ast.ImportFrom(
                module="pywire.core.wire",
                names=[
                    ast.alias(name="wire", asname=None),
                    ast.alias(name="unwrap_wire", asname=None),
                    ast.alias(name="set_render_context", asname=None),
                    ast.alias(name="reset_render_context", asname=None),
                ],
                level=0,
            ),
            ast.ImportFrom(
                module="pywire.core.signals",
                names=[
                    ast.alias(name="derived", asname=None),
                    ast.alias(name="effect", asname=None),
                ],
                level=0,
            ),
            ast.ImportFrom(
                module="pywire.core.props",
                names=[ast.alias(name="props", asname=None)],
                level=0,
            ),
            ast.ImportFrom(
                module="pywire.core.expose",
                names=[ast.alias(name="expose", asname=None)],
                level=0,
            ),
            ast.ImportFrom(
                module="starlette.responses",
                names=[ast.alias(name="Response", asname=None)],
                level=0,
            ),
            ast.Import(names=[ast.alias(name="json", asname=None)]),
            ast.ImportFrom(
                module="pywire.core.refs",
                names=[ast.alias(name="ref", asname=None)],
                level=0,
            ),
            ast.ImportFrom(
                module="pywire.runtime.pydantic_integration",
                names=[ast.alias(name="validate_with_model", asname=None)],
                level=0,
            ),
            ast.ImportFrom(
                module="pywire.runtime.loader",
                names=[ast.alias(name="load_component", asname=None)],
                level=0,
            ),
            ast.ImportFrom(
                module="pywire.runtime.helpers",
                names=[
                    ast.alias(name="render_attrs", asname=None),
                ],
                level=0,
            ),
        ]
        return imports

    def _extract_wire_vars(self, python_ast: Optional[ast.AST]) -> Set[str]:
        """Extract variables that are assigned to wire() calls."""
        wire_vars = set()
        if not python_ast:
            return wire_vars

        class WireVisitor(ast.NodeVisitor):
            def visit_Assign(self, node: ast.Assign) -> None:
                # Check if value is wire(...)
                is_wire = False
                if isinstance(node.value, ast.Call):
                    if isinstance(node.value.func, ast.Name) and node.value.func.id in (
                        "wire",
                        "derived",
                    ):
                        is_wire = True

                if is_wire:
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            wire_vars.add(target.id)

                # Continue visiting to find nested assignments?
                # Ideally top-level wires are what we care about most.
                self.generic_visit(node)

        WireVisitor().visit(python_ast)
        return wire_vars

    def _generate_component_map_from_imports(
        self, python_ast: Optional[ast.Module]
    ) -> Dict[str, str]:
        """Populate component_map from Python imports based on PascalCase convention."""
        component_map = {}
        if not python_ast:
            return component_map

        for node in python_ast.body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    name = alias.asname or alias.name
                    # PascalCase starts with uppercase
                    if name and name[0].isupper():
                        component_map[name] = name
        return component_map

    def _generate_component_imports(self, parsed: ParsedPyWire):
        # Deprecated: use _generate_component_map_from_imports instead
        pass

    def _extract_user_imports(self, python_ast: ast.Module) -> List[ast.stmt]:
        """Extract import statements from user Python code."""
        imports: List[ast.stmt] = []
        for node in python_ast.body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                imports.append(node)
        return imports

    def _extract_user_classes(self, python_ast: ast.Module) -> List[ast.stmt]:
        """Extract class definitions from user Python code."""
        classes: List[ast.stmt] = []
        for node in python_ast.body:
            if isinstance(node, ast.ClassDef):
                is_props = any(
                    isinstance(dec, ast.Name) and dec.id == "props"
                    for dec in node.decorator_list
                )
                if not is_props:
                    classes.append(node)
        return classes

    def _extract_props_from_ast(
        self, python_ast: Optional[ast.Module]
    ) -> Optional[PropsDirective]:
        """Extract PropsDirective from @props decorated class."""
        if not python_ast:
            return None

        from pywire.compiler.exceptions import PyWireSyntaxError

        props_classes = []
        for node in python_ast.body:
            if isinstance(node, ast.ClassDef):
                # Check for @props decorator
                is_props = any(
                    isinstance(dec, ast.Name) and dec.id == "props"
                    for dec in node.decorator_list
                )
                if is_props:
                    props_classes.append(node)

        if not props_classes:
            return None

        if len(props_classes) > 1:
            raise PyWireSyntaxError(
                "Multiple classes decorated with @props detected. Only one @props class is allowed per file.",
                file_path=self.file_path,
                line=props_classes[1].lineno,
                column=props_classes[1].col_offset,
            )

        node = props_classes[0]
        # Convert AnnAssigns to PropsDirective
        args = []
        for item in node.body:
            if isinstance(item, ast.AnnAssign):
                name = item.target.id if isinstance(item.target, ast.Name) else None
                if not name:
                    continue

                # Type hint as string
                try:
                    type_hint = ast.unparse(item.annotation)
                except AttributeError:
                    type_hint = "Any"

                # Default value
                default_val = None
                if item.value:
                    try:
                        default_val = ast.unparse(item.value)
                    except Exception:
                        default_val = "None"

                args.append((name, type_hint, default_val))

        return PropsDirective(
            name="props", args=args, line=node.lineno, column=node.col_offset
        )

    def _extract_import_names(self, python_ast: Optional[ast.Module]) -> Set[str]:
        """Extract names defined by imports."""
        names = set()
        # Add default imports
        names.add("json")
        names.add("props")
        names.add("derived")
        names.add("effect")
        names.add("expose")
        names.add("wire")
        names.add("ref")

        if python_ast:
            for node in python_ast.body:
                # with open("/tmp/pywire_debug.txt", "a") as f:
                #    f.write(f"DEBUG: EXTRACT IMPORT Node: {type(node)} {getattr(node, 'name', '')}\n")
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        names.add(alias.asname or alias.name)
                elif isinstance(node, ast.ImportFrom):
                    for alias in node.names:
                        names.add(alias.asname or alias.name)
                elif isinstance(node, ast.ClassDef):
                    # Keep frontmatter class symbols (e.g. Pydantic models) as
                    # module-level names in template expressions.
                    names.add(node.name)
        return names

    def _extract_user_variables(self, python_ast: Optional[ast.Module]) -> Set[str]:
        """Extract variable names assigned at the top level of user code."""
        vars: Set[str] = set()
        if not python_ast:
            return vars

        for node in python_ast.body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        vars.add(target.id)
            elif isinstance(node, ast.AnnAssign):
                if isinstance(node.target, ast.Name):
                    vars.add(node.target.id)
        return vars

    def _extract_route_params_from_pattern(self, pattern: str) -> Set[str]:
        params: Set[str] = set()
        if not pattern:
            return params

        for name in re.findall(r"\{([a-zA-Z_]\w*)(?::[^}]+)?\}", pattern):
            if not name.isidentifier():
                continue
            params.add(name)

        for name in re.findall(r":([a-zA-Z_]\w*)(?::[^/]+)?", pattern):
            if not name.isidentifier():
                continue
            params.add(name)

        return params

    def _extract_route_params_from_file_path(
        self, file_path: Optional[str]
    ) -> Set[str]:
        params: Set[str] = set()
        if not file_path:
            return params

        from pathlib import Path

        path = Path(file_path)

        for part in path.parts:
            if not part:
                continue
            if not (part.startswith("[") and part.endswith("]")):
                continue
            name = part[1:-1]
            if not name:
                continue
            if not name.isidentifier():
                continue
            params.add(name)

        stem = path.stem
        if stem.startswith("[") and stem.endswith("]"):
            name = stem[1:-1]
            if name and name.isidentifier():
                params.add(name)

        return params

    def _extract_route_params(self, parsed: ParsedPyWire) -> Set[str]:
        params: Set[str] = set()

        path_directive = parsed.get_directive_by_type(PathDirective)
        if path_directive:
            assert isinstance(path_directive, PathDirective)
            for pattern in path_directive.routes.values():
                params.update(self._extract_route_params_from_pattern(pattern))

        params.update(self._extract_route_params_from_file_path(parsed.file_path))

        return params

    def _generate_page_class(
        self,
        parsed: ParsedPyWire,
        handlers: List[ast.AsyncFunctionDef],
        known_methods: Dict[str, int],
        known_vars: Set[str],
        known_imports: Set[str],
        async_methods: Set[str],
        component_map: Dict[str, str],
        wire_vars: Set[str] = set(),
    ) -> ast.ClassDef:
        """Generate page class definition."""
        class_body: List[ast.stmt] = []

        # Add generated handlers
        class_body.extend(handlers)

        # Generate directive metadata (e.g. __routes__ from !path)
        for directive in parsed.directives:
            handler = self.directive_handlers.get(type(directive))
            if handler:
                class_body.extend(handler.generate(directive))

        # Generate SPA metadata
        class_body.extend(self._generate_spa_metadata(parsed))

        # Generate __allowed_handlers__ for security (prevents arbitrary method invocation)

        # Transform user Python code to class methods (Must run before __init__ to set flags)
        route_params = self._extract_route_params(parsed)
        all_globals = set(known_methods.keys()).union(known_vars).union(route_params)
        user_code_stmts: List[ast.stmt] = []
        if parsed.python_ast:
            user_code_stmts = self._transform_user_code(parsed.python_ast, all_globals)

        # Track exposed methods
        initial_exposed = ast.Assign(
            targets=[ast.Name(id="__exposed_methods__", ctx=ast.Store())],
            value=ast.Set(
                elts=[
                    ast.Constant(value=m)
                    for m in sorted(self._collected_exposed_methods)
                ]
            )
            if self._collected_exposed_methods
            else ast.Call(
                func=ast.Name(id="set", ctx=ast.Load()), args=[], keywords=[]
            ),
        )
        class_body.append(initial_exposed)

        # Generate __init__ method
        class_body.append(self._generate_init_method(parsed))

        # Add user code
        class_body.extend(user_code_stmts)

        # Generate _render_template method AND binding methods
        # Pass ALL globals to avoid auto-calling variables and prefixing imports
        all_globals = set(known_methods.keys()).union(known_vars).union(route_params)

        render_func, binding_funcs = self._generate_render_template_method(
            parsed,
            known_methods,
            all_globals,
            known_imports,
            async_methods,
            component_map,
            wire_vars=wire_vars,
        )
        if render_func:
            class_body.append(render_func)
        class_body.extend(binding_funcs)

        # Inject __has_uploads__ flag if file inputs were detected
        if self.template_codegen.has_file_inputs:
            class_body.append(
                ast.Assign(
                    targets=[ast.Name(id="__has_uploads__", ctx=ast.Store())],
                    value=ast.Constant(value=True),
                )
            )

        # Determine base class
        base_id = "BasePage"
        if parsed.get_directive_by_type(LayoutDirective):
            base_id = "_LayoutBase"

        # Inject LAYOUT_ID if we determined one is needed
        # We need to calculate it here too or pass it back from _generate_render_template_method
        # Since we need it for class attribute, let's calculate it early.
        layout_id_to_inject = None
        if parsed.file_path:
            import hashlib

            layout_id_hash = hashlib.md5(str(parsed.file_path).encode()).hexdigest()
            # Recursive check for slots
            has_slots = self._has_slots_recursive(parsed.template)
            if has_slots:
                layout_id_to_inject = layout_id_hash

        if layout_id_to_inject:
            class_body.append(
                ast.Assign(
                    targets=[ast.Name(id="LAYOUT_ID", ctx=ast.Store())],
                    value=ast.Constant(value=layout_id_to_inject),
                )
            )

        # Lifecycle hooks calculation
        init_hooks = []
        # If we found @mount decorated methods
        if hasattr(self, "_collected_mount_hooks") and self._collected_mount_hooks:
            init_hooks.extend(self._collected_mount_hooks)

        # Ensure 'on_before_load' and 'on_load' are present
        final_init_hooks = []

        # Standard hooks - REMOVED per user request
        # final_init_hooks.append('on_before_load')
        # final_init_hooks.append('on_load')

        # Add mount hooks
        if hasattr(self, "_collected_mount_hooks") and self._collected_mount_hooks:
            final_init_hooks.extend(self._collected_mount_hooks)

        class_body.append(
            ast.Assign(
                targets=[ast.Name(id="INIT_HOOKS", ctx=ast.Store())],
                value=ast.List(
                    elts=[ast.Constant(value=h) for h in final_init_hooks],
                    ctx=ast.Load(),
                ),
            )
        )
        cls_def = ast.ClassDef(
            name=self._get_class_name(parsed),
            bases=[ast.Name(id=base_id, ctx=ast.Load())],
            keywords=[],
            body=class_body,
            decorator_list=[],
        )
        cls_def.lineno = 1
        cls_def.col_offset = 0
        return cls_def

    def _collect_global_names(
        self, python_ast: Optional[ast.Module]
    ) -> Tuple[Dict[str, int], Set[str], Set[str]]:
        """Collect defined function names and variables, and identify async functions.
        Returns: (method_info_dict, variable_names, async_method_names)
        """
        methods: Dict[str, int] = {}
        variables = {
            "path",
            "params",
            "query",
            "url",
            "request",
            "error_code",
            "error_detail",
            "error_trace",
            "navigate",
        }
        async_methods = set()

        if python_ast:
            # First pass: Collect method names (shallow)
            for node in python_ast.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    # Count non-self arguments
                    arg_count = len(node.args.args)
                    if arg_count > 0 and node.args.args[0].arg == "self":
                        arg_count -= 1

                    # Add varargs/kwargs count if needed?
                    # For now, if it has any args, we don't auto-call.
                    methods[node.name] = arg_count

                    if isinstance(node, ast.AsyncFunctionDef):
                        async_methods.add(node.name)

            # Second pass: recursively collect assignments, stopping at function/class boundaries
            class GlobalVarCollector(ast.NodeVisitor):
                def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
                    # Do not recurse into functions (new scope)
                    pass

                def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
                    # Do not recurse into functions (new scope)
                    pass

                def visit_ClassDef(self, node: ast.ClassDef) -> None:
                    # Do not recurse into classes
                    pass

                def visit_Name(self, node: ast.Name) -> None:
                    if isinstance(node.ctx, ast.Store):
                        variables.add(node.id)

                # We need to handle other assignment targets that might not be just Name
                # But visit_Name handles the Name nodes inside them (e.g. Tuple unpacking) automatically
                # because NodeVisitor recurses by default for generic nodes.

            collector = GlobalVarCollector()
            for node in python_ast.body:
                collector.visit(node)

        # Add implicit params from filename if available
        if hasattr(self, "file_path") and self.file_path:
            import re
            from pathlib import Path

            path_obj = Path(self.file_path)
            # Check current file name and parent directories for [param] syntax
            for part in path_obj.parts:
                match = re.match(r"^\[(.*?)\]$", part.replace(".pywire", ""))
                if match:
                    variables.add(match.group(1))
        return methods, variables, async_methods

    def _process_handlers(
        self,
        parsed: "ParsedPyWire",
        known_methods: Set[str],
        known_vars: Set[str],
        async_methods: Set[str],
    ) -> List[ast.AsyncFunctionDef]:
        """Extract inline handlers and wrap handlers for bindings.

        Returns:
            Tuple of (handler_methods, allowed_handler_names)
        """
        handlers = []
        handler_count = 0
        from pywire.compiler.ast_nodes import EventAttribute

        def visit_nodes(nodes: List[TemplateNode]) -> None:
            nonlocal handler_count
            for node in nodes:
                # Check for events
                for attr in node.special_attributes:
                    if isinstance(attr, EventAttribute):
                        # Pre-processing: Strip wrapping braces if present (e.g. from {code} syntax)
                        # This ensures code inside is processed correctly whether quoted or not in
                        # source
                        raw = attr.handler_name.strip()
                        if raw.startswith("{") and raw.endswith("}"):
                            attr.handler_name = raw[1:-1].strip()

                        is_identifier = attr.handler_name.isidentifier()
                        # If it's an identifier but NOT a user-defined method, it's likely
                        # a builtin or import, so we need to wrap it to pass the event correctly.
                        needs_wrapper = (
                            not is_identifier or attr.handler_name not in known_methods
                        )

                        if needs_wrapper:
                            # Create distinct handler methods
                            method_name = f"_handler_{handler_count}"
                            handler_count += 1

                            try:
                                # Transform body logic
                                code_to_transform = attr.handler_name
                                if is_identifier:
                                    # If it's a bare identifier (like 'print'), transform it to call with event
                                    code_to_transform = f"{code_to_transform}(event)"

                                body, args = self._transform_inline_code(
                                    code_to_transform,
                                    known_methods,
                                    known_vars,
                                    async_methods,
                                )

                                # Store extracted args
                                attr.args = args

                                # Create handler method
                                # async def _handler_X(self, arg0, arg1..., *, event=None):
                                arg_definitions = [ast.arg(arg="self")]
                                for i in range(len(args)):
                                    arg_definitions.append(ast.arg(arg=f"arg{i}"))

                                kwonly_args = [ast.arg(arg="event")]
                                kw_defaults = [ast.Constant(value=None)]

                                handlers.append(
                                    ast.AsyncFunctionDef(
                                        name=method_name,
                                        args=ast.arguments(
                                            posonlyargs=[],
                                            args=arg_definitions,
                                            vararg=None,
                                            kwonlyargs=kwonly_args,
                                            kw_defaults=kw_defaults,
                                            defaults=[],
                                        ),
                                        body=body,
                                        decorator_list=[],
                                        returns=None,
                                    )
                                )

                                attr.handler_name = method_name

                            except Exception as e:
                                print(
                                    f"Error compiling handler '{attr.handler_name}': {e}"
                                )

                visit_nodes(node.children)

        visit_nodes(parsed.template)
        return handlers

    def _transform_inline_code(
        self,
        code: str,
        known_methods: Set[str] = set(),
        known_vars: Set[str] = set(),
        async_methods: Set[str] = set(),
    ) -> Tuple[List[ast.stmt], List[str]]:
        """Transform inline code: lift arguments and prefix globals with self."""
        import builtins

        # Map $event to event for Alpine compatibility
        code = code.replace("$event", "event")

        from pywire.compiler.preprocessor import preprocess_python_code

        code = preprocess_python_code(code)
        tree = ast.parse(code)
        extracted_args: List[str] = []

        # Pre-pass: if body is a single Call, lift whole argument expressions (not just
        # unbound names) so we serialize expr results (e.g. item.get('id','')) not vars.
        if len(tree.body) == 1:
            stmt = tree.body[0]
            if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
                call = stmt.value
                for i, arg in enumerate(call.args):
                    if isinstance(arg, ast.Starred):
                        continue

                    # Only lift if it's not a known name
                    arg_str = ast.unparse(arg).strip()
                    if arg_str.isidentifier() and (
                        arg_str in known_vars
                        or arg_str in known_methods
                        or arg_str in dir(builtins)
                        or arg_str in ("self", "event")
                    ):
                        continue

                    extracted_args.append(arg_str)
                    call.args[i] = ast.Name(id=f"arg{i}", ctx=ast.Load())

        class ArgumentLifter(ast.NodeTransformer):
            def __init__(self):
                self.local_names = set()
                # 'self' and 'event' are special implicit locals in handlers
                self.local_names.add("self")
                self.local_names.add("event")
                # arg0, arg1, ... from pre-pass must not be re-lifted
                for i in range(32):
                    self.local_names.add(f"arg{i}")

            def visit_Name(self, node: ast.Name) -> Any:
                # 1. Locally defined or event - keep as is
                if node.id in self.local_names:
                    return node

                # 2. Known method - transform to self.X
                if node.id in known_methods:
                    return ast.Attribute(
                        value=ast.Name(id="self", ctx=ast.Load()),
                        attr=node.id,
                        ctx=node.ctx,
                    )

                # 3. Builtin - keep as is
                if node.id in dir(builtins):
                    return node

                # 4. Known instance variable - transform to self.X
                if node.id in known_vars:
                    return ast.Attribute(
                        value=ast.Name(id="self", ctx=ast.Load()),
                        attr=node.id,
                        ctx=node.ctx,
                    )

                # 5. Handle Store context (e.g. assignments in handler)
                if isinstance(node.ctx, ast.Store):
                    self.local_names.add(node.id)
                    return node

                # 5. Otherwise, if Load/Del and not in local_names, it's unbound!
                # Lift it as a handler argument.
                arg_index = len(extracted_args)
                extracted_args.append(node.id)
                return ast.Name(id=f"arg{arg_index}", ctx=node.ctx)

            def visit_Assign(self, node: ast.Assign) -> Any:
                # Process targets first to register locals
                node.targets = [self.visit(t) for t in node.targets]
                node.value = self.visit(node.value)
                return node

            def visit_AnnAssign(self, node: ast.AnnAssign) -> Any:
                node.target = self.visit(node.target)
                if node.value:
                    node.value = self.visit(node.value)
                return node

            def visit_For(self, node: ast.For) -> Any:
                node.target = self.visit(node.target)
                node.iter = self.visit(node.iter)
                node.body = [self.visit(s) for s in node.body]
                node.orelse = [self.visit(s) for s in node.orelse]
                return node

            def visit_ListComp(self, node: ast.ListComp) -> Any:
                # Generators/Comprehensions introduce their own scopes, but for simplicity
                # let's just visit everything. Unbound names inside should still be lifted.
                return self.generic_visit(node)

        # Run transformer
        transformer = ArgumentLifter()
        new_tree = transformer.visit(tree)

        if async_methods:

            class AsyncCallTransformer(ast.NodeTransformer):
                def visit_Call(self, node: ast.Call) -> Any:
                    # Check if call to self.async_method
                    # The func is now (after ArgumentLifter/Name visit) self.method_name
                    if (
                        isinstance(node.func, ast.Attribute)
                        and isinstance(node.func.value, ast.Name)
                        and node.func.value.id == "self"
                        and node.func.attr in async_methods
                    ):
                        return ast.Await(value=node)
                    return self.generic_visit(node)

            AsyncCallTransformer().visit(new_tree)

        ast.fix_missing_locations(new_tree)

        return new_tree.body, extracted_args

    def _generate_spa_metadata(self, parsed: ParsedPyWire) -> List[ast.stmt]:
        """Generate __spa_enabled__ and __sibling_paths__ class attributes."""
        stmts: List[ast.stmt] = []

        # Get path directive
        path_directive = cast(
            Optional[PathDirective], parsed.get_directive_by_type(PathDirective)
        )
        if path_directive:
            # assert isinstance(path_directive, PathDirective)
            pass
        is_multi_path = path_directive and not path_directive.is_simple_string

        # Check for !no_spa directive
        no_spa = parsed.get_directive_by_type(NoSpaDirective) is not None

        # SPA is enabled for multi-path pages unless !no_spa is present
        spa_enabled = is_multi_path and not no_spa

        # __spa_enabled__ = True/False
        stmts.append(
            ast.Assign(
                targets=[ast.Name(id="__spa_enabled__", ctx=ast.Store())],
                value=ast.Constant(value=bool(spa_enabled)),
            )
        )
        stmts.append(
            ast.Assign(
                targets=[ast.Name(id="__no_spa__", ctx=ast.Store())],
                value=ast.Constant(value=bool(no_spa)),
            )
        )

        # __sibling_paths__ = ['/path1', '/path2', ...]
        if path_directive and not path_directive.is_simple_string:
            paths = list(path_directive.routes.values())
        else:
            paths = []

        stmts.append(
            ast.Assign(
                targets=[ast.Name(id="__sibling_paths__", ctx=ast.Store())],
                value=ast.List(
                    elts=[ast.Constant(value=p) for p in paths], ctx=ast.Load()
                ),
            )
        )

        # Inject __file_path__ for hot reload route cleanup
        if parsed.file_path:
            stmts.append(
                ast.Assign(
                    targets=[ast.Name(id="__file_path__", ctx=ast.Store())],
                    value=ast.Constant(value=str(parsed.file_path)),
                )
            )

        return stmts

    def _get_class_name(self, parsed: ParsedPyWire) -> str:
        """Generate class name from file path."""
        if not parsed.file_path:
            return "Page"

        from pathlib import Path

        path = Path(parsed.file_path)
        # Convert pages/index.pywire -> IndexPage
        name = path.stem
        return "".join(word.capitalize() for word in name.split("_")) + "Page"

    def _generate_init_method(self, parsed: ParsedPyWire) -> ast.FunctionDef:
        """Generate __init__ method."""
        # Base init args
        init_args = [
            ast.arg(arg="self"),
            ast.arg(arg="request"),
            ast.arg(arg="params"),
            ast.arg(arg="query"),
            ast.arg(arg="path"),
            ast.arg(arg="url"),
        ]
        defaults: List[ast.expr] = [ast.Constant(value=None), ast.Constant(value=None)]
        props_assigns: List[ast.stmt] = []

        # Handle Props directive
        props_directive = self._collected_props or parsed.get_directive_by_type(
            PropsDirective
        )
        if props_directive:
            assert isinstance(props_directive, PropsDirective)
            # !props(name: type, arg=default)
            # Implementation: Use kwonlyargs for props to avoid mess with positional defaults
            kwonlyargs: List[ast.arg] = []
            kw_defaults: List[Optional[ast.expr]] = []

            for name, type_hint, default_val in props_directive.args:
                annotation = (
                    ast.parse(type_hint, mode="eval").body if type_hint else None
                )
                kwonlyargs.append(ast.arg(arg=name, annotation=annotation))

                if default_val is not None:
                    kw_defaults.append(ast.parse(default_val, mode="eval").body)
                else:
                    kw_defaults.append(None)  # Required kwarg

                # Assign to self
                # self.name = name
                props_assigns.append(
                    ast.Assign(
                        targets=[
                            ast.Attribute(
                                value=ast.Name(id="self", ctx=ast.Load()),
                                attr=name,
                                ctx=ast.Store(),
                            )
                        ],
                        value=ast.Name(id=name, ctx=ast.Load()),
                    )
                )

        else:
            kwonlyargs = []
            kw_defaults = []

        body: List[ast.stmt] = [
            ast.Expr(
                value=ast.Call(
                    func=ast.Attribute(
                        value=ast.Call(
                            func=ast.Name(id="super", ctx=ast.Load()),
                            args=[],
                            keywords=[],
                        ),
                        attr="__init__",
                        ctx=ast.Load(),
                    ),
                    args=[
                        ast.Name(id="request", ctx=ast.Load()),
                        ast.Name(id="params", ctx=ast.Load()),
                        ast.Name(id="query", ctx=ast.Load()),
                        ast.Name(id="path", ctx=ast.Load()),
                        ast.Name(id="url", ctx=ast.Load()),
                    ],
                    keywords=[
                        ast.keyword(
                            arg=None, value=ast.Name(id="kwargs", ctx=ast.Load())
                        )
                    ],
                )
            ),
        ]

        # Add prop assignments
        body.extend(props_assigns)

        # NOTE: !provide is now handled in _generate_render_template_method to ensure reactivity

        # Handle !inject - retrieve values from context
        inject_directive = parsed.get_directive_by_type(InjectDirective)
        if inject_directive:
            assert isinstance(inject_directive, InjectDirective)
            # self.local_var = self.context.get('GLOBAL_KEY')
            for local_var, global_key in inject_directive.mapping.items():
                body.append(
                    ast.Assign(
                        targets=[
                            ast.Attribute(
                                value=ast.Name(id="self", ctx=ast.Load()),
                                attr=local_var,
                                ctx=ast.Store(),
                            )
                        ],
                        value=ast.Call(
                            func=ast.Attribute(
                                value=ast.Attribute(
                                    value=ast.Name(id="self", ctx=ast.Load()),
                                    attr="context",
                                    ctx=ast.Load(),
                                ),
                                attr="get",
                                ctx=ast.Load(),
                            ),
                            args=[ast.Constant(value=global_key)],
                            keywords=[],
                        ),
                    )
                )

        # Call _init_slots
        body.append(
            ast.Expr(
                value=ast.Call(
                    func=ast.Attribute(
                        value=ast.Name(id="self", ctx=ast.Load()),
                        attr="_init_slots",
                        ctx=ast.Load(),
                    ),
                    args=[],
                    keywords=[],
                )
            )
        )

        # Call __top_level_init__ if it exists (for wire() and mutable init)
        if hasattr(self, "_has_top_level_init") and self._has_top_level_init:
            body.append(
                ast.Expr(
                    value=ast.Call(
                        func=ast.Attribute(
                            value=ast.Name(id="self", ctx=ast.Load()),
                            attr="__top_level_init__",
                            ctx=ast.Load(),
                        ),
                        args=[],
                        keywords=[],
                    )
                )
            )

        return ast.FunctionDef(
            name="__init__",
            args=ast.arguments(
                posonlyargs=[],
                args=init_args,
                vararg=None,
                kwonlyargs=kwonlyargs,
                kw_defaults=kw_defaults,
                kwarg=ast.arg(arg="kwargs", annotation=None),
                defaults=defaults,
            ),
            body=body,
            decorator_list=[],
            returns=None,
        )

    def _transform_user_code(
        self, python_ast: ast.Module, known_globals: Optional[Set[str]] = None
    ) -> List[ast.stmt]:
        """Transform user Python code to class methods/attributes."""
        transformed: List[ast.stmt] = []
        if known_globals is None:
            known_globals = set()

        # Collect hooks
        self._collected_mount_hooks = []
        self._collected_derived_hooks = []
        self._collected_effect_hooks = []
        self._collected_exposed_methods = []
        self._wire_vars_from_decorators = set()
        self._has_top_level_init = False

        top_level_statements: List[ast.stmt] = []

        for node in python_ast.body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                # Skip imports - already handled at module level
                continue
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # Check for decorators
                new_decorators = []
                for dec in node.decorator_list:
                    if isinstance(dec, ast.Name):
                        if dec.id == "mount":
                            self._collected_mount_hooks.append(node.name)
                            continue
                        if dec.id == "unmount":
                            # Placeholder for future unmount
                            continue
                        if dec.id == "derived":
                            self._collected_derived_hooks.append(node.name)
                            self._wire_vars_from_decorators.add(node.name)
                            continue
                        if dec.id == "effect":
                            self._collected_effect_hooks.append(node.name)
                            continue
                        if dec.id == "expose":
                            self._collected_exposed_methods.append(node.name)
                            continue
                    new_decorators.append(dec)

                node.decorator_list = new_decorators

                # Functions become methods - transform them
                transformed.append(self._transform_to_method(node, known_globals))
            elif isinstance(node, ast.ClassDef):
                # Check for @props
                is_props = False
                for dec in node.decorator_list:
                    if isinstance(dec, ast.Name) and dec.id == "props":
                        is_props = True
                        break

                if is_props:
                    self._collected_props = self._extract_props_from_class(node)
                    # Add prop names to known_globals so they are correctly transformed in methods
                    for name, _, _ in self._collected_props.args:
                        known_globals.add(name)
                    continue

                # Standard classes are moved to module level (handled by UserCodeTransformer in some versions,
                # but currently we just skip them as they don't belong in the page class body).
                continue
            else:
                # ALL other statements (Assign, AnnAssign, AugAssign, Expr, If, For, While, Try, etc.)
                # are moved to __top_level_init__ for consistent instance-scope execution.
                # This ensures that dependent code (e.g., conn = ...; conn.row_factory = ...)
                # all runs in the same scope at instance creation time.
                top_level_statements.append(node)

        # Inject derived and effect assignments into top-level init
        for name in self._collected_derived_hooks:
            # self.name = derived(self.name)
            top_level_statements.append(
                ast.Assign(
                    targets=[
                        ast.Attribute(
                            value=ast.Name(id="self", ctx=ast.Load()),
                            attr=name,
                            ctx=ast.Store(),
                        )
                    ],
                    value=ast.Call(
                        func=ast.Name(id="derived", ctx=ast.Load()),
                        args=[
                            ast.Attribute(
                                value=ast.Name(id="self", ctx=ast.Load()),
                                attr=name,
                                ctx=ast.Load(),
                            )
                        ],
                        keywords=[],
                    ),
                )
            )

        for name in self._collected_effect_hooks:
            # self._effect_name = effect(self.name)
            top_level_statements.append(
                ast.Assign(
                    targets=[
                        ast.Attribute(
                            value=ast.Name(id="self", ctx=ast.Load()),
                            attr=f"_effect_{name}",
                            ctx=ast.Store(),
                        )
                    ],
                    value=ast.Call(
                        func=ast.Name(id="effect", ctx=ast.Load()),
                        args=[
                            ast.Attribute(
                                value=ast.Name(id="self", ctx=ast.Load()),
                                attr=name,
                                ctx=ast.Load(),
                            )
                        ],
                        keywords=[],
                    ),
                )
            )

        if top_level_statements:
            self._has_top_level_init = True
            transformed.append(
                self._generate_top_level_init(top_level_statements, known_globals)
            )

        return transformed

    def _extract_props_from_class(self, node: ast.ClassDef) -> PropsDirective:
        """Extract props from a @props decorated class."""
        args: List[Tuple[str, str, Optional[str]]] = []
        for item in node.body:
            if isinstance(item, ast.AnnAssign):
                if isinstance(item.target, ast.Name):
                    name = item.target.id
                    type_hint = ast.unparse(item.annotation)
                    default = ast.unparse(item.value) if item.value else None
                    args.append((name, type_hint, default))
            elif isinstance(item, ast.Assign):
                for target in item.targets:
                    if isinstance(target, ast.Name):
                        name = target.id
                        type_hint = "Any"
                        default = ast.unparse(item.value)
                        args.append((name, type_hint, default))

        return PropsDirective(
            name="props", line=node.lineno, column=node.col_offset, args=args
        )

    def _generate_top_level_init(
        self, statements: List[ast.stmt], known_globals: Set[str]
    ) -> ast.FunctionDef:
        """Generate __top_level_init__ method from top-level statements."""

        # 1. Collect all variables assigned in this scope to promote them to instance attributes.
        # This ensures 'x = 1' inside match/if/for becomes 'self.x = 1'.
        local_assignments = set()

        class AssignmentCollector(ast.NodeVisitor):
            def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
                # Do not recurse into nested functions
                pass

            def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
                pass

            def visit_ClassDef(self, node: ast.ClassDef) -> None:
                pass

            def visit_Name(self, node: ast.Name) -> None:
                # If name is being stored (assigned to), collect it
                if isinstance(node.ctx, ast.Store):
                    local_assignments.add(node.id)

        collector = AssignmentCollector()
        for stmt in statements:
            collector.visit(stmt)

        # Combine with explicit known globals
        # We start with a copy to avoid mutating the passed set if it's used elsewhere
        # (though it seems local usually)
        combined_globals = set(known_globals)
        combined_globals.update(local_assignments)

        # Wrap statements in sync method (must be sync for __init__)
        # Transform variables to self.X

        wrapper = ast.FunctionDef(
            name="__top_level_init__",
            args=ast.arguments(
                posonlyargs=[],
                args=[ast.arg(arg="self")],
                vararg=None,
                kwonlyargs=[],
                kw_defaults=[],
                defaults=[],
            ),
            body=statements,
            decorator_list=[],
            returns=None,
        )

        return cast(
            ast.FunctionDef, self._transform_to_method(wrapper, combined_globals)
        )

    def _transform_to_method(
        self, node: Any, known_methods: Optional[Set[str]] = None
    ) -> Any:
        """Transform a function into a method (add self, handle globals)."""
        # 1. Add self argument if not present
        if not (node.args.args and node.args.args[0].arg == "self"):
            node.args.args.insert(0, ast.arg(arg="self"))

        # 2. Find global declarations and include known methods
        global_vars = set()
        if known_methods:
            global_vars.update(known_methods)

        new_body = []
        for stmt in node.body:
            if isinstance(stmt, ast.Global):
                global_vars.update(stmt.names)
            else:
                new_body.append(stmt)

        node.body = new_body

        # 3. Transform variable access
        if global_vars:

            class GlobalToSelf(ast.NodeTransformer):
                def visit_Name(self, node: ast.Name) -> ast.AST:
                    if node.id in global_vars:
                        return ast.Attribute(
                            value=ast.Name(id="self", ctx=ast.Load()),
                            attr=node.id,
                            ctx=node.ctx,
                        )
                    return node

            # Apply transformation
            transformer = GlobalToSelf()
            for i, stmt in enumerate(node.body):
                node.body[i] = transformer.visit(stmt)

            # Fix locations
            for stmt in node.body:
                ast.fix_missing_locations(stmt)

        return node

    def _generate_render_method(self) -> ast.AsyncFunctionDef:
        """Generate render method."""
        return ast.AsyncFunctionDef(
            name="render",
            args=ast.arguments(
                posonlyargs=[],
                args=[ast.arg(arg="self")],
                vararg=None,
                kwonlyargs=[],
                kw_defaults=[],
                defaults=[],
            ),
            body=[
                ast.Return(
                    value=ast.Call(
                        func=ast.Name(id="Response", ctx=ast.Load()),
                        args=[
                            ast.Await(
                                value=ast.Call(
                                    func=ast.Attribute(
                                        value=ast.Name(id="self", ctx=ast.Load()),
                                        attr="_render_template",
                                        ctx=ast.Load(),
                                    ),
                                    args=[],
                                    keywords=[],
                                )
                            )
                        ],
                        keywords=[
                            ast.keyword(
                                arg="media_type", value=ast.Constant(value="text/html")
                            )
                        ],
                    )
                )
            ],
            decorator_list=[],
            returns=None,
        )

    def _generate_render_template_method(
        self,
        parsed: ParsedPyWire,
        known_methods: Optional[Dict[str, int]] = None,
        known_globals: Optional[Set[str]] = None,
        known_imports: Optional[Set[str]] = None,
        async_methods: Optional[Set[str]] = None,
        component_map: Optional[Dict[str, str]] = None,
        wire_vars: Set[str] = set(),
    ) -> Tuple[
        Optional[Union[ast.FunctionDef, ast.AsyncFunctionDef]],
        List[ast.stmt],
    ]:
        """Generate _render_template method and binding/slot handlers."""
        if component_map is None:
            component_map = {}
        # Check for layout
        layout_directive = parsed.get_directive_by_type(LayoutDirective)
        if layout_directive:
            # assert isinstance(layout_directive, LayoutDirective) # Mypy narrowing issue
            pass

        binding_funcs: List[ast.stmt] = []
        render_func = None

        if layout_directive:
            layout_directive = cast(LayoutDirective, layout_directive)
            # === Layout Mode ===
            import hashlib

            file_id = parsed.file_path or ""
            file_hash = hashlib.md5(file_id.encode()).hexdigest()[:8] if file_id else ""

            # Ensure layout_id is generated for intermediate layouts
            layout_id = (
                hashlib.md5(str(parsed.file_path).encode()).hexdigest()
                if parsed.file_path
                else None
            )

            slot_funcs_methods, aux_funcs = self.template_codegen.generate_slot_methods(
                parsed.template,
                file_id=file_id,
                known_globals=known_globals,
                known_imports=known_imports,
                layout_id=layout_id,
                component_map=component_map,
                wire_vars=wire_vars,
            )

            file_hash = hashlib.md5(file_id.encode()).hexdigest()[:8] if file_id else ""

            # Add slot methods directly (they are ASTs now)
            for slot_name, func_ast in slot_funcs_methods.items():
                binding_funcs.append(func_ast)

            # Add aux funcs
            binding_funcs.extend(aux_funcs)

            # Generate _init_slots

            # Resolve parent layout path
            from pathlib import Path

            parent_layout_path = layout_directive.layout_path
            if not Path(parent_layout_path).is_absolute():
                base_dir = (
                    Path(parsed.file_path).parent if parsed.file_path else Path.cwd()
                )
                parent_layout_path = str((base_dir / parent_layout_path).resolve())
            else:
                parent_layout_path = str(Path(parent_layout_path).resolve())

            def make_parent_layout_id() -> ast.Constant:
                import hashlib

                parent_hash = hashlib.md5(parent_layout_path.encode()).hexdigest()
                return ast.Constant(value=parent_hash)

            init_slots_body: List[ast.stmt] = []

            # Chain super
            super_check = ast.If(
                test=ast.Call(
                    func=ast.Name(id="hasattr", ctx=ast.Load()),
                    args=[
                        ast.Call(
                            func=ast.Name(id="super", ctx=ast.Load()),
                            args=[],
                            keywords=[],
                        ),
                        ast.Constant(value="_init_slots"),
                    ],
                    keywords=[],
                ),
                body=[
                    ast.Expr(
                        value=ast.Call(
                            func=ast.Attribute(
                                value=ast.Call(
                                    func=ast.Name(id="super", ctx=ast.Load()),
                                    args=[],
                                    keywords=[],
                                ),
                                attr="_init_slots",
                                ctx=ast.Load(),
                            ),
                            args=[],
                            keywords=[],
                        )
                    )
                ],
                orelse=[],
            )
            init_slots_body.append(super_check)

            for slot_name in slot_funcs_methods.keys():
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

                if slot_name == "$head":
                    reg_call = ast.Expr(
                        value=ast.Call(
                            func=ast.Attribute(
                                value=ast.Name(id="self", ctx=ast.Load()),
                                attr="register_head_slot",
                                ctx=ast.Load(),
                            ),
                            args=[
                                make_parent_layout_id(),
                                ast.Attribute(
                                    value=ast.Name(id="self", ctx=ast.Load()),
                                    attr=func_name,
                                    ctx=ast.Load(),
                                ),
                            ],
                            keywords=[],
                        )
                    )
                else:
                    reg_call = ast.Expr(
                        value=ast.Call(
                            func=ast.Attribute(
                                value=ast.Name(id="self", ctx=ast.Load()),
                                attr="register_slot",
                                ctx=ast.Load(),
                            ),
                            args=[
                                make_parent_layout_id(),
                                ast.Constant(value=slot_name),
                                ast.Attribute(
                                    value=ast.Name(id="self", ctx=ast.Load()),
                                    attr=func_name,
                                    ctx=ast.Load(),
                                ),
                            ],
                            keywords=[],
                        )
                    )
                init_slots_body.append(reg_call)

            init_slots_func = ast.FunctionDef(
                name="_init_slots",
                args=ast.arguments(
                    posonlyargs=[],
                    args=[ast.arg(arg="self")],
                    vararg=None,
                    kwonlyargs=[],
                    kw_defaults=[],
                    defaults=[],
                ),
                body=init_slots_body,
                decorator_list=[],
                returns=None,
            )
            binding_funcs.append(init_slots_func)

            # Handle !provide - Override render() to update context before layout rendering
            provide_directive = cast(
                Optional[ProvideDirective],
                parsed.get_directive_by_type(ProvideDirective),
            )
            if provide_directive:
                provide_body: List[ast.stmt] = []
                for key, val_expr in provide_directive.mapping.items():
                    val_ast = self.template_codegen._transform_expr(
                        val_expr, set(), known_globals
                    )
                    provide_body.append(
                        ast.Assign(
                            targets=[
                                ast.Subscript(
                                    value=ast.Attribute(
                                        value=ast.Name(id="self", ctx=ast.Load()),
                                        attr="context",
                                        ctx=ast.Load(),
                                    ),
                                    slice=ast.Constant(value=key),
                                    ctx=ast.Store(),
                                )
                            ],
                            value=cast(ast.expr, val_ast),
                        )
                    )

                # return await super().render(init)
                render_call = ast.Call(
                    func=ast.Attribute(
                        value=ast.Call(
                            func=ast.Name(id="super", ctx=ast.Load()),
                            args=[],
                            keywords=[],
                        ),
                        attr="render",
                        ctx=ast.Load(),
                    ),
                    args=[ast.Name(id="init", ctx=ast.Load())],
                    keywords=[],
                )
                provide_body.append(ast.Return(value=ast.Await(value=render_call)))

                render_override = ast.AsyncFunctionDef(
                    name="render",
                    args=ast.arguments(
                        posonlyargs=[],
                        args=[
                            ast.arg(arg="self"),
                            ast.arg(
                                arg="init",
                                annotation=ast.Name(id="bool", ctx=ast.Load()),
                            ),
                        ],
                        vararg=None,
                        kwonlyargs=[],
                        kw_defaults=[],
                        defaults=[ast.Constant(value=True)],
                    ),
                    body=provide_body,
                    decorator_list=[],
                    returns=None,
                )
                binding_funcs.append(render_override)

            # Generate _render_template override to bypass layout when used as a component
            default_slot_method = (
                f"_render_slot_fill_default_{file_hash}"
                if file_hash
                else "_render_slot_fill_default"
            )

            # Check if default slot method was actually generated
            has_default_slot = "default" in slot_funcs_methods

            if has_default_slot:
                component_render_body = [
                    ast.Return(
                        value=ast.Await(
                            value=ast.Call(
                                func=ast.Attribute(
                                    value=ast.Name(id="self", ctx=ast.Load()),
                                    attr=default_slot_method,
                                    ctx=ast.Load(),
                                ),
                                args=[],
                                keywords=[],
                            )
                        )
                    )
                ]
            else:
                component_render_body = [ast.Return(value=ast.Constant(value=""))]

            render_func = ast.AsyncFunctionDef(
                name="_render_template",
                args=ast.arguments(
                    posonlyargs=[],
                    args=[ast.arg(arg="self")],
                    vararg=None,
                    kwonlyargs=[],
                    kw_defaults=[],
                    defaults=[],
                ),
                body=[
                    ast.If(
                        test=ast.Attribute(
                            value=ast.Name(id="self", ctx=ast.Load()),
                            attr="__is_component__",
                            ctx=ast.Load(),
                        ),
                        body=component_render_body,
                        orelse=[
                            ast.Return(
                                value=ast.Await(
                                    value=ast.Call(
                                        func=ast.Attribute(
                                            value=ast.Call(
                                                func=ast.Name(
                                                    id="super", ctx=ast.Load()
                                                ),
                                                args=[],
                                                keywords=[],
                                            ),
                                            attr="_render_template",
                                            ctx=ast.Load(),
                                        ),
                                        args=[],
                                        keywords=[],
                                    )
                                )
                            )
                        ],
                    )
                ],
                decorator_list=[],
                returns=None,
            )

        else:
            # === Standard Mode ===
            # We no longer aggressively generate layout_id/scope_id for everything
            # to avoid breaking existing tests.
            layout_id = None
            scope_id = None

            if parsed.file_path:
                import hashlib

                layout_id_hash = hashlib.md5(str(parsed.file_path).encode()).hexdigest()
                # Use as layout_id if we have slots to fill for ourselves (as a component)
                # Or for scoping if <style scoped> is present
                has_scoped_style = any(
                    n.tag == "style" and "scoped" in n.attributes
                    for n in parsed.template
                )
                if has_scoped_style:
                    scope_id = layout_id_hash[:8]

                # If we are a layout (referenced by others), we should have a LAYOUT_ID.
                # But we don't know if we ARE a layout here.
                # We'll assume if there are <slot> tags, we might be a layout.
                has_slots = self._has_slots_recursive(parsed.template)
                if has_slots:
                    layout_id = layout_id_hash

            # Extract Props to Unpack

            prop_names = set()
            props_unpack_stmts = []

            # Using imported PropsDirective from earlier context or get it again
            # We are inside the method, 'parsed' is available.
            props_directive = cast(
                Optional[PropsDirective],
                self._collected_props or parsed.get_directive_by_type(PropsDirective),
            )
            if props_directive:
                for name, _, _ in props_directive.args:
                    prop_names.add(name)
                    # prop = self.prop
                    props_unpack_stmts.append(
                        ast.Assign(
                            targets=[ast.Name(id=name, ctx=ast.Store())],
                            value=ast.Attribute(
                                value=ast.Name(id="self", ctx=ast.Load()),
                                attr=name,
                                ctx=ast.Load(),
                            ),
                        )
                    )

            render_func, aux_funcs = self.template_codegen.generate_render_method(
                parsed.template,
                layout_id=layout_id or "",
                known_methods=known_methods,
                known_globals=known_globals,
                known_imports=known_imports,
                async_methods=async_methods,
                component_map=component_map,
                scope_id=scope_id,
                initial_locals=prop_names,
                wire_vars=wire_vars,
            )

            # Prepend unpack statements to render_func body
            if render_func and props_unpack_stmts:
                render_func.body[0:0] = props_unpack_stmts

            # Handle !provide - Update context values at start of render to catch state changes
            provide_directive = cast(
                Optional[ProvideDirective],
                parsed.get_directive_by_type(ProvideDirective),
            )
            if provide_directive and render_func:
                provide_stmts = []
                for key, val_expr in provide_directive.mapping.items():
                    # Transform expression using known globals for this page scope
                    # Note: val_expr is string. We need to parse it or use transform helper.

                    val_ast = self.template_codegen._transform_expr(
                        val_expr, set(), known_globals
                    )

                    provide_stmts.append(
                        ast.Assign(
                            targets=[
                                ast.Subscript(
                                    value=ast.Attribute(
                                        value=ast.Name(id="self", ctx=ast.Load()),
                                        attr="context",
                                        ctx=ast.Load(),
                                    ),
                                    slice=ast.Constant(value=key),
                                    ctx=ast.Store(),
                                )
                            ],
                            value=cast(ast.expr, val_ast),
                        )
                    )

                # Insert after props unpacking (if any)
                insert_idx = len(props_unpack_stmts) if props_unpack_stmts else 0
                render_func.body[insert_idx:insert_idx] = provide_stmts

            binding_funcs.extend(aux_funcs)

            # Add no-op _init_slots
            binding_funcs.append(
                ast.FunctionDef(
                    name="_init_slots",
                    args=ast.arguments(
                        posonlyargs=[],
                        args=[ast.arg(arg="self")],
                        vararg=None,
                        kwonlyargs=[],
                        kw_defaults=[],
                        defaults=[],
                    ),
                    body=[ast.Pass()],
                    decorator_list=[],
                    returns=None,
                )
            )

        if self.template_codegen.region_renderers:
            region_keys: List[ast.expr | None] = []
            region_vals: List[ast.expr] = []
            for (
                region_id,
                method_name,
            ) in self.template_codegen.region_renderers.items():
                region_keys.append(ast.Constant(value=region_id))
                region_vals.append(ast.Constant(value=method_name))
            binding_funcs.append(
                ast.Assign(
                    targets=[ast.Name(id="__region_renderers__", ctx=ast.Store())],
                    value=ast.Dict(keys=region_keys, values=region_vals),
                )
            )

        return render_func, binding_funcs

    def _has_slots_recursive(self, nodes: List[TemplateNode]) -> bool:
        """Check recursively if the template contains any <slot> elements."""
        for node in nodes:
            if node.tag == "slot":
                return True
            if self._has_slots_recursive(node.children):
                return True
        return False
