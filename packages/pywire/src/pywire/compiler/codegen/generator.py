"""Main code generator orchestrator."""

import ast
import re
from typing import Any, Dict, List, Optional, Set, Tuple, Type, Union, cast

from pywire.compiler.ast_nodes import (
    ComponentDirective,
    Directive,
    EventAttribute,
    FormValidationSchema,
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

    def _generate_component_loading(
        self, parsed: ParsedPyWire
    ) -> Tuple[List[ast.stmt], Dict[str, str]]:
        """
        Generate code to load components and return Tag -> ClassName map.
        Returns: (stmts, component_map)
        """
        stmts: List[ast.stmt] = []
        component_map = {}

        for directive in parsed.directives:
            if isinstance(directive, ComponentDirective):
                # Name = load_component("path", __file_path__)

                # Check for "as Name" collision with imports or other components?
                # Python handles it (overwrite), but maybe warn?

                target_name = directive.component_name
                path = directive.path

                # component_map[target_name] = target_name (class is assigned to this var)
                # Parse lowercases HTML tags, so we map lowercase name to actual class name
                component_map[target_name.lower()] = target_name

                stmts.append(
                    ast.Assign(
                        targets=[ast.Name(id=target_name, ctx=ast.Store())],
                        value=ast.Call(
                            func=ast.Name(id="load_component", ctx=ast.Load()),
                            args=[
                                ast.Constant(value=path),
                                ast.Constant(value=parsed.file_path),
                            ],
                            keywords=[],
                        ),
                    )
                )

        return stmts, component_map

    def generate(self, parsed: ParsedPyWire) -> ast.Module:
        """Generate complete module AST."""
        self.file_path = parsed.file_path
        self._has_top_level_init = False
        self._collected_mount_hooks: List[str] = []
        module_body = []

        # Imports
        module_body.extend(self._generate_imports())

        # Add asyncio import for handle_event
        module_body.append(ast.Import(names=[ast.alias(name="asyncio", asname=None)]))

        # Component loading (early, so they are available)
        comp_stmts, component_map = self._generate_component_loading(parsed)
        module_body.extend(comp_stmts)

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
            # Extract user classes to module level (Pydantic models, etc.)
            module_body.extend(self._extract_user_classes(parsed.python_ast))

        # Extract method names early for binding logic
        known_methods, known_vars, async_methods = self._collect_global_names(
            parsed.python_ast
        )

        # Include explicit variable assignments
        known_vars.update(self._extract_user_variables(parsed.python_ast))

        known_imports = self._extract_import_names(parsed.python_ast)
        all_globals = known_methods.union(known_vars).union(known_imports)

        # Inline handlers (with method names)
        # Note: Handlers only need to know about globals to avoid "self." prefixing if needed,
        # but _process_handlers mostly cares about wrapping logic.
        # Actually _process_handlers calls _transform_inline_code which uses known_methods.
        # Ideally it should know about all globals too.
        handlers, allowed_handlers = self._process_handlers(
            parsed, all_globals, async_methods
        )

        # Page class
        page_class = self._generate_page_class(
            parsed,
            handlers,
            known_methods,
            known_vars,
            known_imports,
            async_methods,
            component_map,
            allowed_handlers,
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
                names=[ast.alias(name="wire", asname=None)],
                level=0,
            ),
            ast.ImportFrom(
                module="starlette.responses",
                names=[ast.alias(name="Response", asname=None)],
                level=0,
            ),
            ast.Import(names=[ast.alias(name="json", asname=None)]),
            # Form validation imports
            ast.ImportFrom(
                module="pywire.runtime.validation",
                names=[
                    ast.alias(name="form_validator", asname=None),
                    ast.alias(name="FieldRules", asname=None),
                    ast.alias(name="FormValidationSchema", asname=None),
                ],
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
                    ast.alias(name="unwrap_wire", asname=None),
                    ast.alias(name="set_render_context", asname=None),
                    ast.alias(name="reset_render_context", asname=None),
                ],
                level=0,
            ),
        ]
        return imports

    def _generate_component_imports(
        self, parsed: ParsedPyWire
    ) -> Tuple[List[ast.stmt], Dict[str, str]]:
        """
        Generate imports for components and return a map of TagName -> ClassName.
        Returns: (import_stmts, component_map)
        """
        imports: List[ast.stmt] = []
        component_map: Dict[str, str] = {}

        from pywire.compiler.ast_nodes import ComponentDirective

        for directive in parsed.directives:
            if isinstance(directive, ComponentDirective):
                # !component 'path' as Name
                # We need to resolve 'path' to a python module path.
                # Assuming 'path' is relative to project root or use loader helper?
                # Actually, generated code will run in server context.
                # Better to use our dynamic loader:
                # Name = load_component('path', __file_path__)

                # Import load_component if not already
                # (handled in _generate_imports? No, let's assume we import a loader helper)

                # We'll generate:
                # Name = load_component("path", __file_path__)
                # But imports are usually at module level.
                # If we use load_component, it's an assignment, not an import.
                # That's fine, we can add it to module body.

                # However, cleaner if we can generate `from x import Y`.
                # But we don't know the exact class name inside the file (it's generated).
                # The dynamic loader `load_component` is robust.

                # Let's add `load_component` to imports
                pass

        return imports, component_map

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
                classes.append(node)
        return classes

    def _extract_import_names(self, python_ast: Optional[ast.Module]) -> Set[str]:
        """Extract names defined by imports."""
        names = set()
        # Add default imports
        names.add("json")
        names.add("form_validator")
        names.add("FieldRules")

        if python_ast:
            for node in python_ast.body:
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        names.add(alias.asname or alias.name)
                elif isinstance(node, ast.ImportFrom):
                    for alias in node.names:
                        names.add(alias.asname or alias.name)
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
        known_methods: Set[str],
        known_vars: Set[str],
        known_imports: Set[str],
        async_methods: Set[str],
        component_map: Dict[str, str],
        allowed_handlers: Optional[Set[str]] = None,
    ) -> ast.ClassDef:
        """Generate page class definition."""
        class_body: List[ast.stmt] = []

        # Add generated handlers
        class_body.extend(handlers)

        # Generate __allowed_handlers__ for security (prevents arbitrary method invocation)
        if allowed_handlers is None:
            allowed_handlers = set()
        # Include _handle_bind_* handlers that may be generated later
        # These will be added dynamically, but we pre-allow the pattern
        class_body.append(
            ast.Assign(
                targets=[ast.Name(id="__allowed_handlers__", ctx=ast.Store())],
                value=ast.Set(
                    elts=[ast.Constant(value=h) for h in sorted(allowed_handlers)]
                )
                if allowed_handlers
                else ast.Call(
                    func=ast.Name(id="set", ctx=ast.Load()), args=[], keywords=[]
                ),
            )
        )

        # Generate directive assignments (e.g., __routes__)
        for directive in parsed.directives:
            handler = self.directive_handlers.get(type(directive))
            if handler:
                class_body.extend(handler.generate(directive))

        # Generate SPA navigation metadata
        class_body.extend(self._generate_spa_metadata(parsed))

        # Inject __no_spa__ flag if !no_spa was detected
        if parsed.get_directive_by_type(NoSpaDirective):
            class_body.append(
                ast.Assign(
                    targets=[ast.Name(id="__no_spa__", ctx=ast.Store())],
                    value=ast.Constant(value=True),
                )
            )

        # Transform user Python code to class methods (Must run before __init__ to set flags)
        route_params = self._extract_route_params(parsed)
        all_globals = known_methods.union(known_vars).union(route_params)
        user_code_stmts: List[ast.stmt] = []
        if parsed.python_ast:
            user_code_stmts = self._transform_user_code(parsed.python_ast, all_globals)

        # Generate __init__ method
        class_body.append(self._generate_init_method(parsed))

        # Add user code
        class_body.extend(user_code_stmts)

        # Generate form validation schemas and wrappers
        # MUST happen before render generation as it updates EventAttributes to point to wrappers
        form_validation_methods = self._generate_form_validation_methods(
            parsed, all_globals
        )
        class_body.extend(form_validation_methods)
        # Generate _render_template method AND binding methods
        # Pass ALL globals to avoid auto-calling variables and prefixing imports
        all_globals = (
            known_methods.union(known_vars).union(route_params).union(known_imports)
        )

        render_func, binding_funcs = self._generate_render_template_method(
            parsed, known_methods, all_globals, async_methods, component_map
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
    ) -> Tuple[Set[str], Set[str], Set[str]]:
        """Collect defined function names and variables, and identify async functions.
        Returns: (method_names, variable_names, async_method_names)
        """
        methods = set()
        variables = {
            "path",
            "params",
            "query",
            "url",
            "request",
            "error_code",
            "error_detail",
            "error_trace",
        }
        async_methods = set()

        if python_ast:
            for node in python_ast.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    methods.add(node.name)
                    if isinstance(node, ast.AsyncFunctionDef):
                        async_methods.add(node.name)
                elif isinstance(node, ast.Assign):
                    for target in node.targets:
                        for child in ast.walk(target):
                            if isinstance(child, ast.Name) and isinstance(
                                child.ctx, ast.Store
                            ):
                                variables.add(child.id)
                elif isinstance(node, ast.AnnAssign):
                    if isinstance(node.target, ast.Name):
                        variables.add(node.target.id)

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
        self, parsed: ParsedPyWire, known_methods: Set[str], async_methods: Set[str]
    ) -> Tuple[List[ast.AsyncFunctionDef], Set[str]]:
        """Extract inline handlers and wrap handlers for bindings.

        Returns:
            Tuple of (handler_methods, allowed_handler_names)
        """
        handlers = []
        allowed_handlers: Set[str] = set()
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
                        needs_wrapper = not is_identifier

                        if needs_wrapper:
                            # Create distinct handler methods
                            method_name = f"_handler_{handler_count}"
                            handler_count += 1

                            try:
                                # Transform body logic
                                code_to_transform = attr.handler_name

                                body, args = self._transform_inline_code(
                                    code_to_transform, known_methods, async_methods
                                )

                                # Store extracted args
                                attr.args = args

                                # Create handler method
                                # async def _handler_X(self, arg0, arg1...):
                                arg_definitions = [ast.arg(arg="self")]
                                for i in range(len(args)):
                                    arg_definitions.append(ast.arg(arg=f"arg{i}"))

                                handlers.append(
                                    ast.AsyncFunctionDef(
                                        name=method_name,
                                        args=ast.arguments(
                                            posonlyargs=[],
                                            args=arg_definitions,
                                            vararg=None,
                                            kwonlyargs=[],
                                            kw_defaults=[],
                                            defaults=[],
                                        ),
                                        body=body,
                                        decorator_list=[],
                                        returns=None,
                                    )
                                )

                                attr.handler_name = method_name
                                # Add generated handler to allowlist
                                allowed_handlers.add(method_name)

                            except Exception as e:
                                print(
                                    f"Error compiling handler '{attr.handler_name}': {e}"
                                )
                        else:
                            # Simple identifier handler - add to allowlist
                            allowed_handlers.add(attr.handler_name)

                visit_nodes(node.children)

        visit_nodes(parsed.template)
        return handlers, allowed_handlers

    def _transform_inline_code(
        self,
        code: str,
        known_methods: Set[str] = set(),
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

        class ArgumentLifter(ast.NodeTransformer):
            def __init__(self):
                self.local_names = set()
                # 'event' is a special implicit local in handlers
                self.local_names.add("event")

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

                # 4. Handle Store context (e.g. assignments in handler)
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

    def _generate_form_validation_methods(
        self, parsed: ParsedPyWire, known_globals: Set[str]
    ) -> List[ast.stmt]:
        """Generate validation schema and wrapper methods for forms with @submit."""
        methods: List[ast.stmt] = []
        form_count = 0

        def visit_nodes(nodes: List[TemplateNode]) -> None:
            nonlocal form_count
            for node in nodes:
                # Check for form with @submit that has validation schema
                if node.tag and node.tag.lower() == "form":
                    for attr in node.special_attributes:
                        if (
                            isinstance(attr, EventAttribute)
                            and attr.event_type == "submit"
                        ):
                            if attr.validation_schema and attr.validation_schema.fields:
                                form_id = form_count
                                form_count += 1

                                # Generate validation schema as class attribute
                                schema_name = f"_form_schema_{form_id}"
                                original_handler = attr.handler_name

                                # Build dict literal for schema fields
                                schema_methods = self._generate_form_schema_literal(
                                    attr.validation_schema, schema_name, known_globals
                                )
                                methods.extend(schema_methods)

                                # Generate wrapper handler
                                wrapper = self._generate_form_wrapper(
                                    form_id,
                                    original_handler,
                                    schema_name,
                                    attr.validation_schema,
                                    known_globals,
                                )
                                methods.append(wrapper)

                                # Update handler name to point to wrapper
                                attr.handler_name = f"_form_submit_{form_id}"

                # Recurse
                visit_nodes(node.children)

        visit_nodes(parsed.template)
        return methods

    def _generate_form_schema_literal(
        self, schema: FormValidationSchema, schema_name: str, known_globals: Set[str]
    ) -> List[ast.stmt]:
        """Generate validation schema as a class attribute."""
        field_items = []
        for field_name, rules in schema.fields.items():
            keywords = []

            if rules.required:
                keywords.append(
                    ast.keyword(arg="required", value=ast.Constant(value=True))
                )
            if rules.required_expr:
                expr_ast = self.template_codegen._transform_expr(
                    rules.required_expr, set(), known_globals
                )
                expr_str = ast.unparse(expr_ast)
                keywords.append(
                    ast.keyword(arg="required_expr", value=ast.Constant(value=expr_str))
                )
            if rules.pattern:
                keywords.append(
                    ast.keyword(arg="pattern", value=ast.Constant(value=rules.pattern))
                )
            if rules.minlength is not None:
                keywords.append(
                    ast.keyword(
                        arg="minlength", value=ast.Constant(value=rules.minlength)
                    )
                )
            if rules.maxlength is not None:
                keywords.append(
                    ast.keyword(
                        arg="maxlength", value=ast.Constant(value=rules.maxlength)
                    )
                )
            if rules.min_value:
                keywords.append(
                    ast.keyword(
                        arg="min_value", value=ast.Constant(value=rules.min_value)
                    )
                )
            if rules.min_expr:
                expr_ast = self.template_codegen._transform_expr(
                    rules.min_expr, set(), known_globals
                )
                expr_str = ast.unparse(expr_ast)
                keywords.append(
                    ast.keyword(arg="min_expr", value=ast.Constant(value=expr_str))
                )
            if rules.max_value:
                keywords.append(
                    ast.keyword(
                        arg="max_value", value=ast.Constant(value=rules.max_value)
                    )
                )
            if rules.max_expr:
                expr_ast = self.template_codegen._transform_expr(
                    rules.max_expr, set(), known_globals
                )
                expr_str = ast.unparse(expr_ast)
                keywords.append(
                    ast.keyword(arg="max_expr", value=ast.Constant(value=expr_str))
                )
            if rules.step:
                keywords.append(
                    ast.keyword(arg="step", value=ast.Constant(value=rules.step))
                )
            if rules.input_type != "text":
                keywords.append(
                    ast.keyword(
                        arg="input_type", value=ast.Constant(value=rules.input_type)
                    )
                )
            if rules.title:
                keywords.append(
                    ast.keyword(arg="title", value=ast.Constant(value=rules.title))
                )
            if rules.max_size is not None:
                keywords.append(
                    ast.keyword(
                        arg="max_size", value=ast.Constant(value=rules.max_size)
                    )
                )
            if rules.allowed_types:
                keywords.append(
                    ast.keyword(
                        arg="allowed_types",
                        value=ast.List(
                            elts=[ast.Constant(value=t) for t in rules.allowed_types],
                            ctx=ast.Load(),
                        ),
                    )
                )

            field_rules_call = ast.Call(
                func=ast.Name(id="FieldRules", ctx=ast.Load()),
                args=[],
                keywords=keywords,
            )

            field_items.append((ast.Constant(value=field_name), field_rules_call))

        schema_dict = ast.Dict(
            keys=[k for k, v in field_items], values=[v for k, v in field_items]
        )

        schema_call = ast.Call(
            func=ast.Name(id="FormValidationSchema", ctx=ast.Load()),
            args=[],
            keywords=[ast.keyword(arg="fields", value=schema_dict)],
        )

        if schema.model_name:
            schema_call.keywords.append(
                ast.keyword(
                    arg="model_name", value=ast.Constant(value=schema.model_name)
                )
            )

        return [
            ast.Assign(
                targets=[ast.Name(id=schema_name, ctx=ast.Store())], value=schema_call
            )
        ]

    def _generate_form_wrapper(
        self,
        form_id: int,
        original_handler: str,
        schema_name: str,
        schema: FormValidationSchema,
        known_globals: Set[str],
    ) -> ast.AsyncFunctionDef:
        """Generate wrapper handler that validates then calls original handler."""
        wrapper_name = f"_form_submit_{form_id}"

        # Generate:
        # async def _form_submit_0(self, **kwargs):
        #     form_data = kwargs.get('formData', {})
        #
        #     # Build state getter for conditional validation
        #     def get_state(expr):
        #         return eval(expr, {'self': self})
        #
        #     # Validate
        #     self.errors = form_validator.validate_form(form_data, self._form_schema_0, get_state)
        #     if self.errors:
        #         return
        #
        #     # Call original handler
        #     await self.original_handler(form_data)

        body: List[ast.stmt] = []

        # form_data = kwargs.get('formData', {})
        body.append(
            ast.Assign(
                targets=[ast.Name(id="form_data", ctx=ast.Store())],
                value=ast.Call(
                    func=ast.Attribute(
                        value=ast.Name(id="kwargs", ctx=ast.Load()),
                        attr="get",
                        ctx=ast.Load(),
                    ),
                    args=[ast.Constant(value="formData"), ast.Dict(keys=[], values=[])],
                    keywords=[],
                ),
            )
        )

        # Define state getter for conditional validation
        # def get_state(expr):
        #     return eval(expr, {'self': self})
        state_getter = ast.FunctionDef(
            name="get_state",
            args=ast.arguments(
                posonlyargs=[],
                args=[ast.arg(arg="expr")],
                vararg=None,
                kwonlyargs=[],
                kw_defaults=[],
                defaults=[],
            ),
            body=[
                ast.Return(
                    value=ast.Call(
                        func=ast.Name(id="eval", ctx=ast.Load()),
                        args=[
                            ast.Name(id="expr", ctx=ast.Load()),
                            # Use module globals (imports, classes)
                            ast.Call(
                                func=ast.Name(id="globals", ctx=ast.Load()),
                                args=[],
                                keywords=[],
                            ),
                            # Locals: just self, because _transform_expr converts other names
                            # to self.x
                            ast.Dict(
                                keys=[ast.Constant(value="self")],
                                values=[ast.Name(id="self", ctx=ast.Load())],
                            ),
                        ],
                        keywords=[],
                    )
                )
            ],
            decorator_list=[],
            returns=None,
        )
        body.append(state_getter)

        # cleaned_data, self.errors = form_validator.validate_form(
        #     form_data, self._form_schema_X.fields, get_state
        # )
        # Note: pass .fields from the schema object
        body.append(
            ast.Assign(
                targets=[
                    ast.Tuple(
                        elts=[
                            ast.Name(id="cleaned_data", ctx=ast.Store()),
                            ast.Attribute(
                                value=ast.Name(id="self", ctx=ast.Load()),
                                attr="errors",
                                ctx=ast.Store(),
                            ),
                        ],
                        ctx=ast.Store(),
                    )
                ],
                value=ast.Call(
                    func=ast.Attribute(
                        value=ast.Name(id="form_validator", ctx=ast.Load()),
                        attr="validate_form",
                        ctx=ast.Load(),
                    ),
                    args=[
                        ast.Name(id="form_data", ctx=ast.Load()),
                        ast.Attribute(
                            value=ast.Attribute(
                                value=ast.Name(id="self", ctx=ast.Load()),
                                attr=schema_name,
                                ctx=ast.Load(),
                            ),
                            attr="fields",
                            ctx=ast.Load(),
                        ),
                        ast.Name(id="get_state", ctx=ast.Load()),
                    ],
                    keywords=[],
                ),
            )
        )

        # If Pydantic model is used:
        # if not self.errors and self._form_schema_X.model_name:
        #    model_instance, pydantic_errors = validate_with_model(
        #        cleaned_data, globals()[self._form_schema_X.model_name]
        #    )
        #    if pydantic_errors:
        #        self.errors.update(pydantic_errors)
        #    else:
        #        cleaned_data = model_instance # Replace dict with model instance

        if schema.model_name:
            pydantic_block: List[ast.stmt] = []

            # model_instance, pydantic_errors = validate_with_model(cleaned_data, ModelClass)

            # PARSE NESTED DATA FIRST
            # nested_data = form_validator.parse_nested_data(cleaned_data)
            pydantic_block.append(
                ast.Assign(
                    targets=[ast.Name(id="nested_data", ctx=ast.Store())],
                    value=ast.Call(
                        func=ast.Attribute(
                            value=ast.Name(id="form_validator", ctx=ast.Load()),
                            attr="parse_nested_data",
                            ctx=ast.Load(),
                        ),
                        args=[ast.Name(id="cleaned_data", ctx=ast.Load())],
                        keywords=[],
                    ),
                )
            )

            validate_call = ast.Call(
                func=ast.Name(id="validate_with_model", ctx=ast.Load()),
                args=[
                    ast.Name(id="nested_data", ctx=ast.Load()),
                    ast.Name(id=schema.model_name, ctx=ast.Load()),
                ],
                keywords=[],
            )

            pydantic_block.append(
                ast.Assign(
                    targets=[
                        ast.Tuple(
                            elts=[
                                ast.Name(id="model_instance", ctx=ast.Store()),
                                ast.Name(id="pydantic_errors", ctx=ast.Store()),
                            ],
                            ctx=ast.Store(),
                        )
                    ],
                    value=validate_call,
                )
            )

            # if pydantic_errors: self.errors.update(pydantic_errors)
            # else: cleaned_data = model_instance
            pydantic_block.append(
                ast.If(
                    test=ast.Name(id="pydantic_errors", ctx=ast.Load()),
                    body=[
                        ast.Expr(
                            value=ast.Call(
                                func=ast.Attribute(
                                    value=ast.Attribute(
                                        value=ast.Name(id="self", ctx=ast.Load()),
                                        attr="errors",
                                        ctx=ast.Load(),
                                    ),
                                    attr="update",
                                    ctx=ast.Load(),
                                ),
                                args=[ast.Name(id="pydantic_errors", ctx=ast.Load())],
                                keywords=[],
                            )
                        )
                    ],
                    orelse=[
                        ast.Assign(
                            targets=[ast.Name(id="cleaned_data", ctx=ast.Store())],
                            value=ast.Name(id="model_instance", ctx=ast.Load()),
                        )
                    ],
                )
            )

            # Wrap in check: if not self.errors:
            body.append(
                ast.If(
                    test=ast.UnaryOp(
                        op=ast.Not(),
                        operand=ast.Attribute(
                            value=ast.Name(id="self", ctx=ast.Load()),
                            attr="errors",
                            ctx=ast.Load(),
                        ),
                    ),
                    body=pydantic_block,
                    orelse=[],
                )
            )

        # if self.errors: return
        body.append(
            ast.If(
                test=ast.Attribute(
                    value=ast.Name(id="self", ctx=ast.Load()),
                    attr="errors",
                    ctx=ast.Load(),
                ),
                body=[ast.Return(value=None)],
                orelse=[],
            )
        )

        # Call original handler - need to check if it's async
        handler_call = ast.Call(
            func=ast.Attribute(
                value=ast.Name(id="self", ctx=ast.Load()),
                attr=original_handler,
                ctx=ast.Load(),
            ),
            args=[ast.Name(id="cleaned_data", ctx=ast.Load())],
            keywords=[],
        )

        # Assume async for safety - await it
        body.append(ast.Expr(value=ast.Await(value=handler_call)))

        return ast.AsyncFunctionDef(
            name=wrapper_name,
            args=ast.arguments(
                posonlyargs=[],
                args=[ast.arg(arg="self")],
                vararg=None,
                kwonlyargs=[],
                kw_defaults=[],
                kwarg=ast.arg(arg="kwargs"),
                defaults=[],
            ),
            body=body,
            decorator_list=[],
            returns=None,
        )

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
        props_directive = parsed.get_directive_by_type(PropsDirective)
        if props_directive:
            assert isinstance(props_directive, PropsDirective)
            # !props(name: type, arg=default)
            # Add to init_args
            for name, type_hint, default_val in props_directive.args:
                # Annotation
                annotation = (
                    ast.parse(type_hint, mode="eval").body if type_hint else None
                )

                # Default
                if default_val is not None:
                    # Parse default value expr
                    defaults.append(ast.parse(default_val, mode="eval").body)
                else:
                    # No default: must come before args with defaults?
                    # Standard python rules: non-default args first.
                    # But we are appending AFTER request/params etc which DON'T have defaults
                    # (except path/url which do)
                    # Wait, request, params, query don't have defaults in base method signature
                    # we generated before:
                    # args=[arg('self'), arg('request')...]
                    # defaults=[None, None] (for path/url?)

                    # Actually standard signature above was:
                    # args: self, request, params, query, path, url
                    # defaults: path=None, url=None

                    # So if we add a non-default prop after 'url=None', it's invalid syntax.
                    # "non-default argument follows default argument"

                    # Strategy: Make ALL props keyword-only or ensure order?
                    # Components are instantiated with kwargs mostly?
                    # Or we just add them to the end and expect users to provide defaults if we
                    # have defaults before?
                    # Simpler: Make them keyword arguments (kwonlyargs).
                    pass

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
            )
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
                    if isinstance(dec, ast.Name) and dec.id == "mount":
                        self._collected_mount_hooks.append(node.name)
                    elif isinstance(dec, ast.Name) and dec.id == "unmount":
                        # Placeholder for future unmount
                        pass
                    else:
                        new_decorators.append(dec)

                node.decorator_list = new_decorators

                # Functions become methods - transform them
                transformed.append(self._transform_to_method(node, known_globals))
            elif isinstance(node, ast.ClassDef):
                # Classes are moved to module level, skip here
                continue
            else:
                # ALL other statements (Assign, AnnAssign, AugAssign, Expr, If, For, While, Try, etc.)
                # are moved to __top_level_init__ for consistent instance-scope execution.
                # This ensures that dependent code (e.g., conn = ...; conn.row_factory = ...)
                # all runs in the same scope at instance creation time.
                top_level_statements.append(node)

        if top_level_statements:
            self._has_top_level_init = True
            transformed.append(
                self._generate_top_level_init(top_level_statements, known_globals)
            )

        return transformed

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
        known_methods: Optional[Set[str]] = None,
        known_globals: Optional[Set[str]] = None,
        async_methods: Optional[Set[str]] = None,
        component_map: Optional[Dict[str, str]] = None,
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
            file_id = parsed.file_path or ""

            # Ensure layout_id is generated for intermediate layouts
            import hashlib

            layout_id = (
                hashlib.md5(str(parsed.file_path).encode()).hexdigest()
                if parsed.file_path
                else None
            )

            slot_funcs_methods, aux_funcs = self.template_codegen.generate_slot_methods(
                parsed.template,
                file_id=file_id,
                known_globals=known_globals,
                layout_id=layout_id,
                component_map=component_map,
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
                            value=val_ast,
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
                Optional[PropsDirective], parsed.get_directive_by_type(PropsDirective)
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
                async_methods=async_methods,
                component_map=component_map,
                scope_id=scope_id,
                initial_locals=prop_names,
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
                            value=val_ast,
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
