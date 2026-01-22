"""PyHTML Language Server"""
import ast
import logging
import re
from typing import Dict, List, Optional

import jedi
from pygls.lsp.server import LanguageServer
from lsprotocol.types import (
    CompletionItem,
    CompletionItemKind,
    CompletionList,
    CompletionParams,
    DefinitionParams,
    Diagnostic,
    DiagnosticSeverity,
    DidChangeTextDocumentParams,
    DidOpenTextDocumentParams,
    Hover,
    HoverParams,
    InitializeParams,
    Location,
    Position,
    PublishDiagnosticsParams,
    Range,
    SemanticTokens,
    SemanticTokensLegend,
    SemanticTokensOptions,
    SemanticTokensParams,
    TextDocumentSyncKind,
)

# Setup logging for debugging
logging.basicConfig(
    filename='/tmp/pyhtml-lsp.log',
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Semantic token types and modifiers (must be defined before server creation)
SEMANTIC_TOKEN_TYPES = [
    'namespace', 'type', 'class', 'enum', 'interface', 'struct', 'typeParameter',
    'parameter', 'variable', 'property', 'enumMember', 'event', 'function',
    'method', 'macro', 'keyword', 'modifier', 'comment', 'string', 'number',
    'regexp', 'operator', 'decorator'
]

SEMANTIC_TOKEN_MODIFIERS = [
    'declaration', 'definition', 'readonly', 'static', 'deprecated', 'async',
    'modification', 'documentation', 'defaultLibrary'
]

SEMANTIC_TOKENS_LEGEND = SemanticTokensLegend(
    token_types=SEMANTIC_TOKEN_TYPES,
    token_modifiers=SEMANTIC_TOKEN_MODIFIERS
)

# Create the language server
server = LanguageServer('pyhtml-lsp', 'v0.1', text_document_sync_kind=TextDocumentSyncKind.Full)


class PyHTMLDocument:
    """Represents a parsed .pyhtml document"""
    
    def __init__(self, uri: str, text: str):
        self.uri = uri
        self.text = text
        self.lines = text.split('\n')
        
        # Parse sections
        self.separator_line = self._find_separator()
        self.diagnostics = self._validate()
        # Add event handler validation
        self.diagnostics.extend(self._validate_event_handlers())
        
        # Track directive ranges (for multi-line directives)
        self.directive_ranges = self._find_directive_ranges()
        
        # Extract routes info
        self.routes = self._extract_routes()

    def _find_separator(self) -> Optional[int]:
        """Find the --- separator line"""
        for i, line in enumerate(self.lines):
            if line.strip() == '---':
                return i
        return None
        
    def _find_directive_ranges(self) -> Dict[str, tuple]:
        """Find start/end lines for multi-line directives."""
        ranges = {}
        i = 0
        while i < len(self.lines):
            stripped = self.lines[i].strip()
            if stripped.startswith('!path'):
                start = i
                # Check if opens a brace but doesn't close it
                if '{' in stripped and '}' not in stripped:
                    # Multi-line: find closing brace
                    while i < len(self.lines) and '}' not in self.lines[i]:
                        i += 1
                ranges['path'] = (start, i)
                break
            i += 1
        return ranges

    def _extract_routes(self) -> Dict[str, str]:
        """Extract route names and patterns from !path directive, handling multi-line dicts."""
        routes = {}
        collecting = False
        content_lines = []
        
        for line in self.lines:
            stripped = line.strip()
            if stripped.startswith('!path '):
                rest = stripped[6:].strip()
                if '{' in rest:
                    collecting = True
                    content_lines.append(rest)
                    if '}' in rest:
                        # Single-line dict
                        collecting = False
                        break
                else:
                    # Single string path
                    content_lines.append(rest)
                    break
            elif collecting:
                content_lines.append(stripped)
                if '}' in stripped:
                    break
        
        if content_lines:
            content = ' '.join(content_lines)
            try:
                tree = ast.parse(content, mode='eval')
                if isinstance(tree.body, ast.Dict):
                    for k, v in zip(tree.body.keys, tree.body.values):
                        if isinstance(k, ast.Constant):
                            routes[k.value] = v.value if isinstance(v, ast.Constant) else ''
                elif isinstance(tree.body, ast.Constant):
                    routes['main'] = tree.body.value
            except:
                pass
        return routes

    def _validate(self) -> List[Diagnostic]:
        """Basic validation"""
        diagnostics = []
        
        # Check for --- separator
        if self.separator_line is None:
            diagnostics.append(Diagnostic(
                range=Range(
                    start=Position(line=0, character=0),
                    end=Position(line=0, character=0)
                ),
                message='Missing --- separator between HTML and Python sections',
                severity=DiagnosticSeverity.Warning,
                source='pyhtml'
            ))
        
        # Check for !path directive
        has_path = any(line.strip().startswith('!path') for line in self.lines)
        if not has_path:
            diagnostics.append(Diagnostic(
                range=Range(
                    start=Position(line=0, character=0),
                    end=Position(line=0, character=0)
                ),
                message='Missing !path directive',
                severity=DiagnosticSeverity.Information,
                source='pyhtml'
            ))
        
        return diagnostics

    def _validate_event_handlers(self) -> List[Diagnostic]:
        """Validate Python syntax in event handler and directive attributes"""
        diagnostics = []
        for i, line in enumerate(self.lines):
            if self.separator_line and i >= self.separator_line:
                break
            # Update regex to support dots in attribute names (for modifiers)
            for m in re.finditer(r'([@$][\w\.]+)="([^"]*)"', line):
                full_attr_name = m.group(1)
                value = m.group(2)
                value_start = m.start(2)
                value_end = m.end(2)
                
                if not value:
                    # Some attributes require a value
                    if full_attr_name in ('$if', '$show', '$for', '$bind'):
                        diagnostics.append(Diagnostic(
                            range=Range(
                                start=Position(line=i, character=m.start(1)),
                                end=Position(line=i, character=m.end(1))
                            ),
                            message=f"{full_attr_name} requires a value",
                            severity=DiagnosticSeverity.Error,
                            source='pyhtml'
                        ))
                    continue
                
                # Check for event handlers with modifiers
                if full_attr_name.startswith('@'):
                    parts = full_attr_name[1:].split('.')
                    event_name = parts[0]
                    modifiers = parts[1:]
                    
                    # Validate modifiers
                    valid_modifiers = {
                        'prevent', 'stop', 'self',  # Logic
                        'enter', 'escape', 'space', 'tab', 'up', 'down', 'left', 'right',  # Keys
                        'shift', 'alt', 'ctrl', 'meta', 'cmd',  # System
                        'debounce', 'throttle',  # Performance
                        'window', 'outside'  # Global/Outside
                    }
                    
                    for mod in modifiers:
                        # Handle modifiers with arguments (e.g. debounce.500ms)
                        # Actually the current spec says syntax is .debounce.500ms
                        # So '500ms' would be a separate part in the split if we split by dot.
                        # Wait, the prompt says: ".debounce" or ".debounce.500ms"
                        # If we split '@click.debounce.500ms' by '.', we get ['click', 'debounce', '500ms']
                        
                        if mod in valid_modifiers:
                            continue
                            
                        # Check if it's a time argument (e.g. 500ms, 1s)
                        if re.match(r'^\d+(ms|s)$', mod):
                            continue
                            
                        # Check if it is a key alias or fallback
                        # The spec says: "Fallback: If a modified key ... doesn't match ... falls back to e.code"
                        # This implies we can use key names.
                        # For now, let's warn on unknown modifiers unless it looks like a key or time
                        
                        # Warning for unknown modifier
                        diagnostics.append(Diagnostic(
                            range=Range(
                                start=Position(line=i, character=m.start(1) + 1 + full_attr_name.index(mod)),
                                end=Position(line=i, character=m.start(1) + 1 + full_attr_name.index(mod) + len(mod))
                            ),
                            message=f"Unknown modifier '{mod}'",
                            severity=DiagnosticSeverity.Warning,
                            source='pyhtml'
                        ))

                    # Event handler - validate as expression or statement
                    try:
                        ast.parse(value, mode='eval')
                    except SyntaxError:
                        try:
                            ast.parse(value, mode='exec')
                        except SyntaxError as e:
                            diagnostics.append(Diagnostic(
                                range=Range(
                                    start=Position(line=i, character=value_start),
                                    end=Position(line=i, character=value_end)
                                ),
                                message=f"Invalid Python syntax in event handler: {e.msg}",
                                severity=DiagnosticSeverity.Error,
                                source='pyhtml'
                            ))
                    continue

                attr_name = full_attr_name
                # Validate based on attribute type
                if attr_name == '$for':
                    # Validate $for="item in items" syntax
                    if ' in ' not in value:
                        diagnostics.append(Diagnostic(
                            range=Range(
                                start=Position(line=i, character=value_start),
                                end=Position(line=i, character=value_end)
                            ),
                            message="$for syntax error: expected 'item in collection'",
                            severity=DiagnosticSeverity.Error,
                            source='pyhtml'
                        ))
                    else:
                        # Validate the iterable part is valid Python
                        parts = value.split(' in ', 1)
                        if len(parts) == 2:
                            try:
                                ast.parse(parts[1], mode='eval')
                            except SyntaxError as e:
                                diagnostics.append(Diagnostic(
                                    range=Range(
                                        start=Position(line=i, character=value_start),
                                        end=Position(line=i, character=value_end)
                                    ),
                                    message=f"Invalid iterable expression: {e.msg}",
                                    severity=DiagnosticSeverity.Error,
                                    source='pyhtml'
                                ))
                
                elif attr_name == '$bind':
                    # Validate $bind value is an assignable target
                    try:
                        # Try to parse as assignment target
                        ast.parse(f"{value} = None", mode='exec')
                    except SyntaxError:
                        diagnostics.append(Diagnostic(
                            range=Range(
                                start=Position(line=i, character=value_start),
                                end=Position(line=i, character=value_end)
                            ),
                            message="$bind value must be an assignable target (variable name)",
                            severity=DiagnosticSeverity.Error,
                            source='pyhtml'
                        ))
                
                elif attr_name in ('$if', '$show', '$key'):
                    # Validate as Python expression
                    try:
                        ast.parse(value, mode='eval')
                    except SyntaxError as e:
                        diagnostics.append(Diagnostic(
                            range=Range(
                                start=Position(line=i, character=value_start),
                                end=Position(line=i, character=value_end)
                            ),
                            message=f"Invalid Python expression: {e.msg}",
                            severity=DiagnosticSeverity.Error,
                            source='pyhtml'
                        ))
                
                elif attr_name.startswith('@'):
                    # Event handler - validate as expression or statement
                    try:
                        ast.parse(value, mode='eval')
                    except SyntaxError:
                        try:
                            ast.parse(value, mode='exec')
                        except SyntaxError as e:
                            diagnostics.append(Diagnostic(
                                range=Range(
                                    start=Position(line=i, character=value_start),
                                    end=Position(line=i, character=value_end)
                                ),
                                message=f"Invalid Python syntax in event handler: {e.msg}",
                                severity=DiagnosticSeverity.Error,
                                source='pyhtml'
                            ))
        return diagnostics
    
    def get_section(self, line: int) -> str:
        """Determine which section a line is in"""
        if line >= len(self.lines):
            return 'python'  # Default to python for new lines at end
            
        if self.separator_line is None:
            if self.lines[line].strip().startswith('!'):
                return 'directive'
            return 'html'
        
        if line < self.separator_line:
            if self.lines[line].strip().startswith('!'):
                return 'directive'
            return 'html'
        elif line == self.separator_line:
            return 'separator'
        else:
            return 'python'

    def get_python_source(self) -> str:
        """Extract the Python code from the document"""
        if self.separator_line is None:
            return ""
        return "\n".join(self.lines[self.separator_line + 1:])

    def pyhtml_to_python_line(self, line: int) -> int:
        """Convert a line number in the .pyhtml file to a line number in the extracted Python source"""
        if self.separator_line is None:
            return 0
        return line - self.separator_line - 1

    def get_event_attr_at(self, line: int, char: int) -> Optional[dict]:
        """Return event attr info if cursor is on one: {type, name, value, col_offset, char_in_value}"""
        if line >= len(self.lines):
            return None
        line_text = self.lines[line]
        for m in re.finditer(r'([@$][\w\.]+)="([^"]*)"', line_text):
            attr_start = m.start(1)
            attr_end = m.end(1)
            value_start = m.start(2)
            value_end = m.end(2)
            if attr_start <= char <= attr_end:
                return {'type': 'name', 'name': m.group(1), 'value': m.group(2)}
            if value_start <= char <= value_end:
                return {
                    'type': 'value',
                    'name': m.group(1),
                    'value': m.group(2),
                    'col_offset': value_start,
                    'char_in_value': char - value_start
                }
        return None

    def get_interpolation_at(self, line: int, char: int) -> Optional[dict]:
        """Return interpolation info if cursor is on one: {type, name, value, col_offset, char_in_value}
        
        Uses balanced brace matching to handle nested braces in f-strings.
        """
        if line >= len(self.lines):
            return None
        line_text = self.lines[line]
        
        # Find all balanced brace pairs using stack-based matching
        interpolations = []
        i = 0
        while i < len(line_text):
            if line_text[i] == '{':
                # Start of potential interpolation
                start = i
                depth = 1
                i += 1
                in_string = None  # Track if we're inside a string
                
                while i < len(line_text) and depth > 0:
                    c = line_text[i]
                    
                    # Handle string literals (ignore braces inside strings)
                    if c in ('"', "'") and (i == 0 or line_text[i-1] != '\\'):
                        if in_string is None:
                            in_string = c
                        elif in_string == c:
                            in_string = None
                    elif in_string is None:
                        if c == '{':
                            depth += 1
                        elif c == '}':
                            depth -= 1
                    i += 1
                
                if depth == 0:
                    # Found balanced braces
                    end = i  # Points after closing }
                    value_start = start + 1
                    value_end = end - 1
                    interpolations.append({
                        'start': start,
                        'end': end,
                        'value_start': value_start,
                        'value_end': value_end,
                        'value': line_text[value_start:value_end]
                    })
            else:
                i += 1
        
        # Find which interpolation contains the cursor
        for interp in interpolations:
            if interp['value_start'] <= char <= interp['value_end']:
                return {
                    'type': 'interpolation',
                    'name': interp['value'],
                    'value': interp['value'],
                    'col_offset': interp['value_start'],
                    'char_in_value': char - interp['value_start']
                }
        return None


def find_best_definitions(doc: PyHTMLDocument, expression: str, char_in_expr: int) -> List:
    """Find the best definitions for an expression using Jedi"""
    try:
        python_source = doc.get_python_source()
        # Create virtual Python document with context
        virtual_python = python_source + "\n# Event handler expression\n" + expression
        
        # Calculate line number in virtual document (where expression starts)
        python_lines = python_source.split('\n')
        # Line 1-based: len(python_lines) lines of code + 1 line comment + 1 line expression
        virtual_line = len(python_lines) + 2
        
        script = jedi.Script(virtual_python)
        
        # Try goto() first
        definitions = script.goto(virtual_line, char_in_expr)
        
        # If goto finds nothing or only self-references, try infer()
        if not definitions or all(d.line and d.line >= virtual_line for d in definitions):
            inferred = script.infer(virtual_line, char_in_expr)
            if inferred:
                definitions.extend(inferred)
        
        # If still nothing useful, synthesize a usage for assignment targets (e.g., count += 1)
        if not definitions:
            try:
                target_names = []
                expr_ast = ast.parse(expression, mode='exec')
                for node in ast.walk(expr_ast):
                    if isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
                        target_names.append(node.target.id)
                    if isinstance(node, ast.Assign):
                        for tgt in node.targets:
                            if isinstance(tgt, ast.Name):
                                target_names.append(tgt.id)
                for name in target_names:
                    synthetic = virtual_python + f"\n{name}\n"
                    synthetic_script = jedi.Script(synthetic)
                    synthetic_line = virtual_line + 1  # line of synthetic usage
                    defs = synthetic_script.goto(synthetic_line, 0)
                    if defs:
                        definitions.extend(defs)
                        break
            except Exception:
                pass
        
        # Filter definitions
        valid_defs = []
        seen_locations = set()
        
        for d in definitions:
            # Skip if definition is in the virtual expression itself (recursive)
            if d.line and d.line >= virtual_line:
                continue
                
            # Skip if definition is 'global count' etc.
            if d.line and d.line <= len(python_lines):
                line_text = python_lines[d.line - 1].strip()
                if line_text.startswith('global '):
                    continue
            
            # Avoid duplicates
            loc = (d.module_path, d.line, d.column)
            if loc in seen_locations:
                continue
            seen_locations.add(loc)
            
            valid_defs.append(d)
            
        # Sort to prioritize module-level assignments (column 0)
        # Then by line number to get the first one
        valid_defs.sort(key=lambda d: (1 if d.column > 0 else 0, d.line or 0))
        
        return valid_defs
    except Exception as e:
        logger.error(f"Jedi definition error: {e}")
        return []


# Document cache
documents: dict[str, PyHTMLDocument] = {}


@server.feature('textDocument/didOpen')
def did_open(ls: LanguageServer, params: DidOpenTextDocumentParams):
    """Handle document open"""
    uri = params.text_document.uri
    text = params.text_document.text
    
    logger.info(f"Document opened: {uri}")
    
    # Parse and cache
    doc = PyHTMLDocument(uri, text)
    documents[uri] = doc
    
    # Send diagnostics
    ls.text_document_publish_diagnostics(
        PublishDiagnosticsParams(
            uri=uri,
            diagnostics=doc.diagnostics
        )
    )


@server.feature('textDocument/didChange')
def did_change(ls: LanguageServer, params: DidChangeTextDocumentParams):
    """Handle document changes"""
    uri = params.text_document.uri
    
    # Get updated text
    text = params.content_changes[0].text
    
    # Re-parse
    doc = PyHTMLDocument(uri, text)
    documents[uri] = doc
    
    # Send updated diagnostics
    ls.text_document_publish_diagnostics(
        PublishDiagnosticsParams(
            uri=uri,
            diagnostics=doc.diagnostics
        )
    )
    
    logger.info(f"Document changed: {uri}")


@server.feature('textDocument/definition')
def definition(ls: LanguageServer, params: DefinitionParams) -> Optional[List[Location]]:
    """Provide go-to-definition"""
    uri = params.text_document.uri
    position = params.position
    
    doc = documents.get(uri)
    if not doc:
        return None
        
    section = doc.get_section(position.line)
    
    # Handle HTML section - check for event handler attributes or interpolations
    if section == 'html':
        attr = doc.get_event_attr_at(position.line, position.character)
        interp = doc.get_interpolation_at(position.line, position.character)
        
        target = None
        if attr and attr['type'] == 'value':
            target = attr
        elif interp:
            target = interp
            
        if target:
            # Go-to-definition for event handler value or interpolation
            try:
                definitions = find_best_definitions(doc, target['value'], target['char_in_value'])
                
                if not definitions:
                    return None
                    
                locations = []
                python_source = doc.get_python_source()
                python_lines = python_source.split('\n')
                
                for d in definitions:
                    if d.line <= len(python_lines):
                        # Definition is in Python section
                        if doc.separator_line is not None:
                            line = d.line - 1 + doc.separator_line + 1
                        else:
                            line = d.line - 1
                        target_uri = uri
                    else:
                        # External definition
                        line = d.line - 1
                        target_uri = d.module_path.as_uri() if d.module_path else uri
                    
                    locations.append(Location(
                        uri=target_uri,
                        range=Range(
                            start=Position(line=line, character=d.column),
                            end=Position(line=line, character=d.column + len(d.name))
                        )
                    ))
                
                return locations
            except Exception as e:
                logger.error(f"Jedi definition error for HTML expression: {e}")
        
        return None
    
    # Handle Python section
    if section != 'python':
        return None
        
    try:
        python_source = doc.get_python_source()
        python_line = doc.pyhtml_to_python_line(position.line)
        
        # Don't pass path to avoid caching issues
        script = jedi.Script(python_source)
        definitions = script.goto(python_line + 1, position.character)
        
        locations = []
        for d in definitions:
            # Map back to .pyhtml coordinates
            # For local definitions, offset by separator line
            if doc.separator_line is not None:
                line = d.line + doc.separator_line
            else:
                line = d.line - 1
            
            target_uri = d.module_path.as_uri() if d.module_path else uri
            
            locations.append(Location(
                uri=target_uri,
                range=Range(
                    start=Position(line=line, character=d.column),
                    end=Position(line=line, character=d.column + len(d.name))
                )
            ))
            
        return locations
    except Exception as e:
        logger.error(f"Jedi definition error: {e}")
        return None


@server.feature('textDocument/hover')
def hover(ls: LanguageServer, params: HoverParams) -> Optional[Hover]:
    """Provide hover information"""
    uri = params.text_document.uri
    position = params.position
    
    doc = documents.get(uri)
    if not doc:
        return None
    
    # Check if hovering over !path directive (single-line or multi-line)
    line_text = doc.lines[position.line].strip()
    in_path_directive = line_text.startswith('!path')
    
    # Also check if within multi-line !path range
    if not in_path_directive and 'path' in doc.directive_ranges:
        start, end = doc.directive_ranges['path']
        if start <= position.line <= end:
            in_path_directive = True
    
    if in_path_directive:
        return Hover(contents="""**!path Directive**

Define routes for this page.

**Syntax:**
```python
# Single route (string)
!path '/route'

# Multiple routes (dictionary)
!path {
    'home': '/',
    'detail': '/posts/:id',
    'edit': '/posts/:id/edit'
}
```

**Path Parameters:**
- `:name` - captures a parameter
- `:name:int` - captures and validates as integer
- `:name:str` - captures as string (default)

**Injected Variables:**
- `self.path` - dict of route names to booleans
- `self.params` - dict of captured parameters  
- `self.query` - dict of query string parameters
- `self.url` - helper to generate URLs
""")
        
    section = doc.get_section(position.line)
    
    # Handle HTML section - check for event handler attributes
    if section == 'html':
        attr = doc.get_event_attr_at(position.line, position.character)
        interp = doc.get_interpolation_at(position.line, position.character)
        
        if attr and attr['type'] == 'name':
            # Hover on attribute name - provide documentation
            hover_docs = {
                '@click': "**@click**\n\nClick event handler. Value can be a function name or Python expression.\n\nExample: `@click=\"change_name\"` or `@click=\"count += 1\"`",
                '@submit': "**@submit**\n\nForm submit event handler. Value can be a function name or Python expression.",
                '@change': "**@change**\n\nChange event handler. Value can be a function name or Python expression.",
                '@input': "**@input**\n\nInput event handler. Value can be a function name or Python expression.",
                '$if': "**$if**\n\nConditional rendering. Element is excluded from DOM when condition is falsy.\n\nExample: `$if=\"is_admin\"`",
                '$show': "**$show**\n\nConditional visibility. Element stays in DOM but is hidden via CSS when condition is falsy.\n\nExample: `$show=\"is_visible\"`",
                '$for': "**$for**\n\nLoop directive. Repeats the element for each item in a collection.\n\n**Syntax:**\n- `$for=\"item in items\"`\n- `$for=\"index, item in enumerate(items)\"`\n- `$for=\"key, value in dict.items()\"`",
                '$key': "**$key**\n\nStable key for loops. Provides a unique identifier for efficient DOM diffing.\n\nExample: `$key=\"item.id\"`",
                '$bind': "**$bind**\n\nTwo-way data binding. Binds an input element's value to a Python variable.\n\nExample: `$bind=\"username\"`"
            }
            if attr['name'] in hover_docs:
                return Hover(contents=hover_docs[attr['name']])
            elif attr['name'].startswith('@'):
                # Handle modifiers in hover
                parts = attr['name'].split('.')
                base_event = parts[0]
                if base_event in hover_docs:
                    base_docs = hover_docs[base_event]
                    # Append modifier info
                    if len(parts) > 1:
                        mods = ', '.join(f"`.{m}`" for m in parts[1:])
                        base_docs += f"\n\n**Modifiers used:** {mods}"
                    return Hover(contents=base_docs)
                
                return Hover(contents=f"**{attr['name']}**\n\nEvent handler attribute.")
            elif attr['name'].startswith('$'):
                return Hover(contents=f"**{attr['name']}**\n\nDirective attribute.")
        
        target = None
        if attr and attr['type'] == 'value':
            target = attr
        elif interp:
            target = interp
            
        if target:
            # Hover on attribute value or interpolation
            try:
                definitions = find_best_definitions(doc, target['value'], target['char_in_value'])
                
                if definitions:
                    best = definitions[0]
                    # Show definition info
                    type_info = best.type or 'unknown'
                    
                    # Get the assignment line content if available
                    assignment_info = ""
                    python_source = doc.get_python_source()
                    python_lines = python_source.split('\n')
                    if best.line and best.line <= len(python_lines):
                        line_content = python_lines[best.line - 1].strip()
                        if line_content and len(line_content) < 100:  # Reasonable length limit
                            assignment_info = f"\n```python\n{line_content}\n```"
                    
                    desc = best.description or best.name
                    docstring = best.docstring()
                    
                    content = f"**{best.name}** ({type_info}){assignment_info}\n\n{docstring or desc}"
                    return Hover(contents=content)
                
                # No Jedi definitions found - check for injected framework variables
                variable_docs = {
                    'params': "**params**\n\nDictionary containing URL path parameters captured from the route. For example, if route is `/user/:id`, `params['id']` will be available.",
                    'query': "**query**\n\nDictionary containing URL query parameters. For example value of `/page?q=search` is in `query['q']`.",
                    'path': "**path**\n\nDictionary mapping route names to booleans, indicating which route is currently active. E.g. `path['main']` is True.",
                    'url': "**url**\n\nURL Helper object. Use `url['name'].format(...)` to generate URLs for defined routes."
                }
                
                # Extract the word at cursor position from the expression
                expr = target['value']
                char_pos = target['char_in_value']
                # Find word boundaries
                word_start = char_pos
                while word_start > 0 and (expr[word_start-1].isidentifier() or expr[word_start-1] == '_'):
                    word_start -= 1
                word_end = char_pos
                while word_end < len(expr) and (expr[word_end].isidentifier() or expr[word_end] == '_'):
                    word_end += 1
                word = expr[word_start:word_end]
                
                if word in variable_docs:
                    return Hover(contents=variable_docs[word])
                
                # Fallback to help() if no definition found
                python_source = doc.get_python_source()
                virtual_python = python_source + "\n# Event handler expression\n" + target['value']
                virtual_line = len(python_source.split('\n')) + 2
                
                script = jedi.Script(virtual_python)
                help_info = script.help(virtual_line, target['char_in_value'])
                if help_info:
                    doc_string = help_info[0].docstring()
                    if doc_string:
                        return Hover(contents=doc_string)
            except Exception as e:
                logger.error(f"Jedi hover error for HTML expression: {e}")
        
        return None
    
    # Handle Python section
    if section != 'python':
        return None
        
    try:
        python_source = doc.get_python_source()
        python_line = doc.pyhtml_to_python_line(position.line)
        
        # Don't pass path to avoid caching issues
        script = jedi.Script(python_source)
        help_info = script.help(python_line + 1, position.character)
        
        if not help_info:
            # Check for injected variables
            variable_docs = {
                'params': "**params**\n\nDictionary containing URL path parameters captured from the route. For example, if route is `/user/:id`, `params['id']` will be available.",
                'query': "**query**\n\nDictionary containing URL query parameters. For example value of `/page?q=search` is in `query['q']`.",
                'path': "**path**\n\nDictionary mapping route names to booleans, indicating which route is currently active. E.g. `path['main']` is True.",
                'url': "**url**\n\nURL Helper object. Use `url['name'].format(...)` to generate URLs for defined routes."
            }
            
            # Simple check if cursor is on one of these words
            # This is naive but works for demonstration
            line_text = doc.lines[position.line]
            word_start = position.character
            while word_start > 0 and line_text[word_start-1].isidentifier():
                word_start -= 1
            word_end = position.character
            while word_end < len(line_text) and line_text[word_end].isidentifier():
                word_end += 1
                
            word = line_text[word_start:word_end]
            if word in variable_docs:
                return Hover(contents=variable_docs[word])

            return None
            
        doc_string = help_info[0].docstring()
        if not doc_string:
            return None
            
        return Hover(contents=doc_string)
    except Exception as e:
        logger.error(f"Jedi hover error: {e}")
        return None


@server.feature('textDocument/completion')
def completions(ls: LanguageServer, params: CompletionParams) -> CompletionList:
    """Provide completions"""
    uri = params.text_document.uri
    position = params.position
    
    doc = documents.get(uri)
    if not doc:
        return CompletionList(is_incomplete=False, items=[])
    
    section = doc.get_section(position.line)
    logger.info(f"Completion in {section} section at line {position.line}")
    
    items = []
    
    if section == 'directive':
        items = [
            CompletionItem(
                label='!path',
                kind=CompletionItemKind.Keyword,
                detail='Define route mapping',
                documentation="Example: !path { 'home': '/' }"
            ),
            CompletionItem(
                label='!layout',
                kind=CompletionItemKind.Keyword,
                detail='Use a layout template'
            ),
        ]
    
    elif section == 'html':
        # Get current line to check context
        line_text = doc.lines[position.line][:position.character]
        
        # Check if we're in a tag (simplified)
        if '<' in line_text and '>' not in line_text.split('<')[-1]:
            items = [
                CompletionItem(
                    label='$if',
                    kind=CompletionItemKind.Property,
                    detail='Conditional rendering',
                    documentation='Render element only if condition is true.\n\nExample: `$if="is_admin"`'
                ),
                CompletionItem(
                    label='$show',
                    kind=CompletionItemKind.Property,
                    detail='Conditional visibility',
                    documentation='Show/hide element with CSS (stays in DOM).\n\nExample: `$show="is_visible"`'
                ),
                CompletionItem(
                    label='$for',
                    kind=CompletionItemKind.Property,
                    detail='Loop over collection',
                    documentation='Repeat element for each item.\n\nExamples:\n- `$for="item in items"`\n- `$for="item, idx in items"`\n- `$for="k, v in dict.items()"`'
                ),
                CompletionItem(
                    label='$key',
                    kind=CompletionItemKind.Property,
                    detail='Stable key for loops',
                    documentation='Unique key for efficient DOM diffing in loops.\n\nExample: `$key="item.id"`'
                ),
                CompletionItem(
                    label='$bind',
                    kind=CompletionItemKind.Property,
                    detail='Two-way data binding',
                    documentation='Bind input value to a variable.\n\nExample: `$bind="username"`'
                ),
                CompletionItem(
                    label='@click',
                    kind=CompletionItemKind.Event,
                    detail='Click event handler',
                    documentation='Example: `@click="handle_click"` or `@click="count += 1"`'
                ),
                CompletionItem(
                    label='@submit',
                    kind=CompletionItemKind.Event,
                    detail='Form submit handler',
                    documentation='Example: `@submit="handle_submit"`'
                ),
                CompletionItem(
                    label='@change',
                    kind=CompletionItemKind.Event,
                    detail='Change event handler',
                    documentation='Example: `@change="on_select_change"`'
                ),
                CompletionItem(
                    label='@input',
                    kind=CompletionItemKind.Event,
                    detail='Input event handler',
                    documentation='Example: `@input="on_input"`'
                ),
            ]
    
    elif section == 'python':
        # Use Jedi for Python completions
        python_source = doc.get_python_source()
        python_line = doc.pyhtml_to_python_line(position.line)
        
        try:
            # Don't pass path to avoid caching issues
            script = jedi.Script(python_source)
            jedi_completions = script.complete(python_line + 1, position.character)
            
            for c in jedi_completions:
                kind = CompletionItemKind.Text
                if c.type == 'function':
                    kind = CompletionItemKind.Function
                elif c.type == 'class':
                    kind = CompletionItemKind.Class
                elif c.type == 'module':
                    kind = CompletionItemKind.Module
                elif c.type == 'keyword':
                    kind = CompletionItemKind.Keyword
                elif c.type == 'statement':
                    kind = CompletionItemKind.Variable
                
                items.append(CompletionItem(
                    label=c.name,
                    kind=kind,
                    detail=c.description,
                    documentation=c.docstring()
                ))
        except Exception as e:
            logger.error(f"Jedi completion error: {e}")
            
        # Add our custom snippets/injected variables
        items.extend([
            CompletionItem(
                label='async def __on_load',
                kind=CompletionItemKind.Snippet,
                insert_text='async def __on_load():\n    pass',
                detail='Lifecycle hook',
                documentation='Called before every render'
            ),
            CompletionItem(
                label='params',
                kind=CompletionItemKind.Variable,
                detail='URL parameters',
                documentation='Dictionary of URL path parameters (e.g. {"id": "123"})'
            ),
            CompletionItem(
                label='query',
                kind=CompletionItemKind.Variable,
                detail='Query parameters',
                documentation='Dictionary of query string parameters'
            ),
            CompletionItem(
                label='path',
                kind=CompletionItemKind.Variable,
                detail='Path info',
                documentation='Dictionary indicating which route matched (e.g. {"main": True})'
            ),
            CompletionItem(
                label='url',
                kind=CompletionItemKind.Variable,
                detail='URL Helper',
                documentation='Helper to generate URLs for routes'
            ),
        ])
    
    return CompletionList(is_incomplete=False, items=items)


def _get_semantic_token_type(name_type: str) -> int:
    """Map Jedi name type to semantic token type index"""
    type_map = {
        'function': SEMANTIC_TOKEN_TYPES.index('function'),
        'class': SEMANTIC_TOKEN_TYPES.index('class'),
        'module': SEMANTIC_TOKEN_TYPES.index('namespace'),
        'keyword': SEMANTIC_TOKEN_TYPES.index('keyword'),
        'statement': SEMANTIC_TOKEN_TYPES.index('variable'),
        'param': SEMANTIC_TOKEN_TYPES.index('parameter'),
    }
    return type_map.get(name_type, SEMANTIC_TOKEN_TYPES.index('variable'))


@server.feature('textDocument/semanticTokens/full')
def semantic_tokens(ls: LanguageServer, params: SemanticTokensParams) -> SemanticTokens:
    """Provide semantic tokens for Python syntax highlighting in @click values"""
    uri = params.text_document.uri
    doc = documents.get(uri)
    
    if not doc:
        return SemanticTokens(data=[])
    
    tokens = []
    prev_line = 0
    prev_char = 0
    
    # Scan HTML section for event handler attributes
    for line_num, line_text in enumerate(doc.lines):
        if doc.separator_line and line_num >= doc.separator_line:
            break
        
        # Find all @click="..." patterns
        for m in re.finditer(r'([@$][\w\.]+)="([^"]*)"', line_text):
            value = m.group(2)
            value_start = m.start(2)
            
            if not value:
                continue
            
            # Tokenize the Python expression using AST parsing
            try:
                tree = ast.parse(value, mode='eval')
                
                # Use Jedi to get type information for names
                python_source = doc.get_python_source()
                virtual_python = python_source + "\n# Event handler expression\n" + value
                virtual_line = len(python_source.split('\n')) + 1
                
                script = jedi.Script(virtual_python)
                names_dict = {}
                try:
                    jedi_names = script.get_names(line=virtual_line + 1)
                    for name in jedi_names:
                        if name.name not in names_dict:
                            names_dict[name.name] = name.type
                except:
                    pass
                
                # Walk AST and create tokens
                for node in ast.walk(tree):
                    if isinstance(node, ast.Name):
                        # Variable/function name
                        delta_line = line_num - prev_line
                        char_pos = value_start + node.col_offset
                        delta_start = char_pos - prev_char if delta_line == 0 else char_pos
                        
                        name_type = names_dict.get(node.id, 'statement')
                        token_type = _get_semantic_token_type(name_type)
                        
                        tokens.append(delta_line)
                        tokens.append(delta_start)
                        tokens.append(len(node.id))
                        tokens.append(token_type)
                        tokens.append(0)  # No modifiers
                        
                        prev_line = line_num
                        prev_char = char_pos
                    elif isinstance(node, ast.Constant):
                        delta_line = line_num - prev_line
                        char_pos = value_start + node.col_offset
                        delta_start = char_pos - prev_char if delta_line == 0 else char_pos
                        
                        if isinstance(node.value, str):
                            token_type_idx = SEMANTIC_TOKEN_TYPES.index('string')
                            length = len(str(node.value)) + 2  # +2 for quotes
                        elif isinstance(node.value, (int, float)):
                            token_type_idx = SEMANTIC_TOKEN_TYPES.index('number')
                            length = len(str(node.value))
                        else:
                            continue
                        
                        tokens.append(delta_line)
                        tokens.append(delta_start)
                        tokens.append(length)
                        tokens.append(token_type_idx)
                        tokens.append(0)
                        
                        prev_line = line_num
                        prev_char = char_pos
                    elif isinstance(node, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod, ast.Pow,
                                          ast.LShift, ast.RShift, ast.BitOr, ast.BitXor, ast.BitAnd,
                                          ast.FloorDiv, ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt,
                                          ast.GtE, ast.Is, ast.IsNot, ast.In, ast.NotIn)):
                        # Operators
                        delta_line = line_num - prev_line
                        char_pos = value_start + node.col_offset
                        delta_start = char_pos - prev_char if delta_line == 0 else char_pos
                        
                        # Get operator string from source
                        op_str = value[node.col_offset:node.end_col_offset] if hasattr(node, 'end_col_offset') else ''
                        if not op_str:
                            continue
                        
                        tokens.append(delta_line)
                        tokens.append(delta_start)
                        tokens.append(len(op_str))
                        tokens.append(SEMANTIC_TOKEN_TYPES.index('operator'))
                        tokens.append(0)
                        
                        prev_line = line_num
                        prev_char = char_pos
                        
            except SyntaxError:
                # If parsing fails, skip semantic tokens for this expression
                pass
            except Exception:
                # Skip semantic tokens for this expression on error
                pass
    
    return SemanticTokens(data=tokens)


def start():
    """Start the language server"""
    logger.info("PyHTML Language Server starting...")
    try:
        server.start_io()
    except Exception as e:
        logger.exception("Server crashed")
        raise


if __name__ == '__main__':
    start()