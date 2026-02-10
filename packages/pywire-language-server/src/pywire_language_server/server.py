"""PyWire Language Server"""

import ast
import json
import logging
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import attrs
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
    InsertTextFormat,
    Location,
    MarkupContent,
    Position,
    PublishDiagnosticsParams,
    Range,
    ReferenceParams,
    SemanticTokens,
    SemanticTokensLegend,
    SemanticTokensParams,
    TextDocumentSyncKind,
)
from pygls.lsp.server import LanguageServer

from . import __version__
from .pyright import PyrightClient
from .transpiler import Transpiler


class ShadowFileManager:
    """
    Manages generation of shadow .py files for Pyright consumption.
    This mimics the behavior of the VS Code extension but on the server side.
    """

    def __init__(self, root_uri: str):
        self.root_uri = root_uri
        self.root_path = self._uri_to_path(root_uri)
        if self.root_path:
            self.pywire_dir = os.path.join(self.root_path, ".pywire")
        else:
            self.pywire_dir = ""  # Disable if no root path

    def _uri_to_path(self, uri: str) -> Optional[str]:
        # Simple parsing, in real world might need urllib
        if uri.startswith("file://"):
            return uri[7:]
        # If no file:// scheme, assume it is strict file path or invalid
        # But LSP URIs should be file://
        return None

    def ensure_init(self) -> bool:
        """Ensure .pywire directory exists and is ignored."""
        if not self.pywire_dir:
            return False

        if not os.path.exists(self.pywire_dir):
            try:
                os.makedirs(self.pywire_dir, exist_ok=True)
                gitignore = os.path.join(self.pywire_dir, ".gitignore")
                with open(gitignore, "w") as f:
                    f.write("*\n")
            except Exception as e:
                logger.error(f"Failed to init shadow dir: {e}")
                return False
        return True

    def update_shadow_file(self, doc_uri: str, content: str) -> Optional[str]:
        """Write content to shadow file and return its path."""
        if not self.pywire_dir:
            return None

        try:
            doc_path = self._uri_to_path(doc_uri)
            if not doc_path:
                return None

            if not self.root_path:
                return None

            # Simple containment check
            if not doc_path.startswith(self.root_path):
                # Outside workspace??
                return None

            rel_path = os.path.relpath(doc_path, self.root_path)

            shadow_rel_path = rel_path + ".py"
            shadow_path = os.path.join(self.pywire_dir, shadow_rel_path)

            # Ensure parent dir
            os.makedirs(os.path.dirname(shadow_path), exist_ok=True)

            with open(shadow_path, "w") as f:
                f.write(content)

            return f"file://{shadow_path}"
        except Exception as e:
            logger.error(f"Failed to update shadow file for {doc_uri}: {e}")
            return None

    def get_shadow_uri(self, doc_uri: str) -> Optional[str]:
        doc_path = self._uri_to_path(doc_uri)
        try:
            if not doc_path or not self.root_path:
                return None
            rel_path = os.path.relpath(doc_path, self.root_path)
            shadow_path = os.path.join(self.pywire_dir, rel_path + ".py")
            return f"file://{shadow_path}"
        except ValueError:
            return None

    def get_source_uri_from_shadow(self, shadow_uri: str) -> Optional[str]:
        if not shadow_uri.startswith("file://"):
            return None
        if not self.root_path or not self.pywire_dir:
            return None
        shadow_path = shadow_uri[7:]
        try:
            rel_path = os.path.relpath(shadow_path, self.pywire_dir)
        except ValueError:
            return None
        if not rel_path.endswith(".py"):
            return None
        source_path = os.path.join(self.root_path, rel_path[:-3])
        return f"file://{source_path}"


# Setup logging for debugging
# Setup logging for debugging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("/tmp/pywire-language-server.log"),
        logging.StreamHandler(sys.stderr),
    ],
)
logger = logging.getLogger(__name__)

# Semantic token types and modifiers (must be defined before server creation)
SEMANTIC_TOKEN_TYPES = [
    "namespace",
    "type",
    "class",
    "enum",
    "interface",
    "struct",
    "typeParameter",
    "parameter",
    "variable",
    "property",
    "enumMember",
    "event",
    "function",
    "method",
    "macro",
    "keyword",
    "modifier",
    "comment",
    "string",
    "number",
    "regexp",
    "operator",
    "decorator",
]

SEMANTIC_TOKEN_MODIFIERS = [
    "declaration",
    "definition",
    "readonly",
    "static",
    "deprecated",
    "async",
    "modification",
    "documentation",
    "defaultLibrary",
]

SEMANTIC_TOKENS_LEGEND = SemanticTokensLegend(
    token_types=SEMANTIC_TOKEN_TYPES, token_modifiers=SEMANTIC_TOKEN_MODIFIERS
)

# Create the language server
server = LanguageServer(
    "pywire-language-server",
    __version__,
    text_document_sync_kind=TextDocumentSyncKind.Full,
)


# Global state for Pyright fallback
pyright_client: Optional[PyrightClient] = None
shadow_manager: Optional[ShadowFileManager] = None
pyright_diagnostics: dict[str, List[Diagnostic]] = {}


@server.feature("initialize")
def initialize(ls: LanguageServer, params: Any):
    """Initialize the server."""
    global pyright_client, shadow_manager

    # Check if client capabilities suggest we need fallback?
    # Or maybe we just always try to start if configured?

    # We need root URI
    root_uri = params.root_uri or (
        f"file://{params.root_path}" if params.root_path else None
    )

    if root_uri:
        shadow_manager = ShadowFileManager(root_uri)
        if shadow_manager.ensure_init():
            # Check initialization options
            init_opts = getattr(params, "initialization_options", {}) or {}
            # Default to True for standalone clients (NeoVim, etc.), but VS Code sends explicit False
            use_bundled_pyright = init_opts.get("useBundledPyright", True)

            logger.info(f"Use Bundled Pyright: {use_bundled_pyright}")

            if use_bundled_pyright:
                # Try start pyright
                client = PyrightClient()
                if client.start():
                    pyright_client = client
                    logger.info("Pyright fallback started successfully")
                    pyright_client.set_diagnostics_callback(
                        lambda params: publish_pyright_diagnostics(ls, params)
                    )

                    # Perform async init in a task
                    import asyncio

                    asyncio.create_task(_init_pyright(ls, params))
                else:
                    logger.error(
                        "Pyright failed to start. Language server features will be limited."
                    )
            else:
                logger.info("Pyright bundling disabled by client (Middleware Mode).")
        else:
            logger.error(
                "Failed to init shadow manager. Language server features will be limited."
            )


async def _init_pyright(ls: LanguageServer, params: Any):
    if pyright_client:
        try:
            logger.info(f"Checking for node: {shutil.which('node')}")

            # lsprotocol models use attrs
            init_dict = attrs.asdict(params, recurse=True)

            # Important: Set processId to None or our PID
            init_dict["processId"] = os.getpid()

            logger.debug(
                f"Sending initialize to Pyright: {json.dumps(init_dict)[:200]}..."
            )

            await pyright_client.send_request("initialize", init_dict)

            # Send initialized notification
            pyright_client.send_notification("initialized", {})

        except Exception as e:
            logger.error(f"Failed to initialize pyright interaction: {e}")


class PyWireDocument:
    """Represents a parsed .pywire document using Virtual Document architecture"""

    def __init__(self, uri: str, text: str):
        self.uri = uri
        self.text = text

        # Transpile to virtual python
        self.transpiler = Transpiler(text)
        self.virtual_python, self.source_map = self.transpiler.transpile()

        # Compatibility layers while refactoring
        self.lines = text.split("\n")
        # Old properties like routes and diagnostics should now be derived/validated differently.
        # But for now, let's keep the structure and just cache the transpilation result.
        self.diagnostics: List[Diagnostic] = []
        self.directive_ranges = self.transpiler.directive_ranges

    def get_python_source(self) -> str:
        """Return the virtual python source code."""
        return self.virtual_python

    def update(self, text: str):
        self.text = text
        self.transpiler = Transpiler(text)
        self.virtual_python, self.source_map = self.transpiler.transpile()
        self.directive_ranges = self.transpiler.directive_ranges
        self.lines = text.split("\n")

    def map_to_original(self, line: int, col: int) -> Optional[Tuple[int, int]]:
        """Map virtual python position to original .wire position"""
        return self.source_map.to_original(line, col)

    def map_to_generated(self, line: int, col: int) -> Optional[Tuple[int, int]]:
        """Map original .wire position to virtual python position"""
        return self.source_map.to_generated(line, col)

    # Legacy validation and helpers removed.


# Document cache
documents: dict[str, PyWireDocument] = {}


def _uri_to_path(uri: str) -> Optional[str]:
    if uri.startswith("file://"):
        return uri[7:]
    return None


def _find_fences(lines: List[str]) -> Tuple[Optional[int], Optional[int]]:
    fence_re = re.compile(r"^\s*-{3,}\s*$")
    start: Optional[int] = None
    end: Optional[int] = None
    for i, line in enumerate(lines):
        if fence_re.match(line):
            if start is None:
                start = i
            elif end is None:
                end = i
                break
    return start, end


def _scan_directives_end(lines: List[str], end_idx: int) -> int:
    i = 0
    pending_blank_start: Optional[int] = None
    while i < end_idx:
        stripped = lines[i].strip()
        if not stripped:
            if pending_blank_start is None:
                pending_blank_start = i
            i += 1
            continue
        if stripped.startswith("!"):
            pending_blank_start = None
            i += 1
            continue
        break
    if pending_blank_start is not None:
        return pending_blank_start
    return i


def _extract_first_string_literal(line: str) -> Optional[Tuple[int, int, str]]:
    match = re.search(r"(['\"])(?P<val>(?:\\.|(?!\1).)*)\1", line)
    if not match:
        return None
    return match.start("val"), match.end("val"), match.group("val")


def _parse_path_routes(routes_text: str) -> Optional[Dict[str, str]]:
    try:
        expr_ast = ast.parse(routes_text, mode="eval")
    except SyntaxError:
        return None

    if isinstance(expr_ast.body, ast.Dict):
        routes: Dict[str, str] = {}
        for key_node, value_node in zip(expr_ast.body.keys, expr_ast.body.values):
            if not isinstance(key_node, ast.Constant) or not isinstance(
                key_node.value, str
            ):
                return None
            if not isinstance(value_node, ast.Constant) or not isinstance(
                value_node.value, str
            ):
                return None
            routes[key_node.value] = value_node.value
        return routes

    if isinstance(expr_ast.body, ast.Constant) and isinstance(expr_ast.body.value, str):
        return {"main": expr_ast.body.value}

    return None


def _collect_path_block(lines: List[str], start_idx: int) -> Tuple[str, int]:
    line = lines[start_idx]
    if "{" in line and "}" not in line:
        current_idx = start_idx
        content_accum = []
        while current_idx < len(lines):
            line_text = lines[current_idx]
            content_accum.append(line_text)
            if "}" in line_text:
                break
            current_idx += 1
        return ("".join(content_accum), current_idx)
    return (line, start_idx)


def _get_word_at_position(line_text: str, char: int) -> str:
    start = char
    while start > 0 and (
        line_text[start - 1].isalnum() or line_text[start - 1] in "@$._"
    ):
        start -= 1
    end = char
    while end < len(line_text) and (
        line_text[end].isalnum() or line_text[end] in "@$._"
    ):
        end += 1
    return line_text[start:end]


def _is_inside_opening_tag(line_text: str, character: int) -> bool:
    """Check if the cursor is inside an opening HTML tag (after tag name, before >)."""
    # Find the last < before cursor
    before_cursor = line_text[:character]
    last_open = before_cursor.rfind("<")
    if last_open == -1:
        return False

    # Check if there's a > between < and cursor
    between = before_cursor[last_open:]
    if ">" in between:
        return False

    # Check it's not a closing tag
    if between.startswith("</"):
        return False

    return True


def _get_section(lines: List[str], line_number: int) -> str:
    start_fence, end_fence = _find_fences(lines)

    if start_fence is not None and end_fence is not None:
        if line_number == start_fence or line_number == end_fence:
            return "separator"
        if start_fence < line_number < end_fence:
            return "python"
        if line_number > end_fence:
            return "html"
        # Before start fence: could be directives or empty
    elif start_fence is not None:
        # Open fence but no close: unbalanced
        if line_number == start_fence:
            return "separator"
        if line_number > start_fence:
            return "python"

    # Fallback / Directives
    line_text = lines[line_number].strip() if line_number < len(lines) else ""
    if (
        line_text.startswith("!")
        or line_text.startswith("# !")
        or line_text.startswith("#!")
    ):
        return "directive"

    # If no fences, it's HTML unless it's a directive
    return "html"


def _path_param_at(value: str, rel_col: int) -> Optional[Tuple[str, Optional[str]]]:
    pattern = (
        r":(?P<name>\w+)(?::(?P<type>\w+))?|\{(?P<name2>\w+)(?::(?P<type2>\w+))?\}"
    )
    for match in re.finditer(pattern, value):
        if match.start() <= rel_col < match.end():
            name = match.group("name") or match.group("name2")
            type_hint = match.group("type") or match.group("type2")
            return name, type_hint
    return None


def _path_entry_hover(doc: PyWireDocument, position: Position) -> Optional[Hover]:
    if "path" not in doc.directive_ranges:
        return None
    start_line, end_line = doc.directive_ranges["path"]
    if position.line < start_line or position.line > end_line:
        return None

    line = doc.lines[position.line]
    stripped = line.strip()

    # Single-line !path "/route"
    if stripped.startswith("!path") and "{" not in line:
        literal = _extract_first_string_literal(line)
        if not literal:
            return None
        start_col, end_col, route_value = literal
        if start_col <= position.character <= end_col:
            return Hover(contents=f"**Route pattern**\n\n`{route_value}`")
        return None

    # Dict entries: 'name': '/route/:id'
    for match in re.finditer(
        r"(['\"])(?P<key>[^'\"]+)\1\s*:\s*(['\"])(?P<val>[^'\"]+)\3", line
    ):
        key_start, key_end = match.start("key"), match.end("key")
        val_start, val_end = match.start("val"), match.end("val")
        if key_start <= position.character <= key_end:
            return Hover(contents=f"**Route name**\n\n`{match.group('key')}`")
        if val_start <= position.character <= val_end:
            rel_col = position.character - val_start
            param = _path_param_at(match.group("val"), rel_col)
            if param:
                name, type_hint = param
                type_label = type_hint or "string"
                return Hover(contents=f"**Path parameter**\n\n`{name}` ({type_label})")
            return Hover(contents=f"**Route pattern**\n\n`{match.group('val')}`")

    return None


def validate(ls: LanguageServer, uri: str):
    """Sends diagnostics for the given URI."""
    doc = documents.get(uri)
    if doc:
        diagnostics: List[Diagnostic] = []
        lines = doc.lines

        # Validate !path directives
        i = 0
        while i < len(lines):
            stripped = lines[i].strip()
            if stripped.startswith("!path"):
                block_text, end_idx = _collect_path_block(lines, i)
                match = re.search(r"!path\s*(.+)", block_text, re.DOTALL)
                if not match:
                    diagnostics.append(
                        Diagnostic(
                            range=Range(
                                start=Position(line=i, character=0),
                                end=Position(
                                    line=end_idx, character=len(lines[end_idx])
                                ),
                            ),
                            message="Invalid path directive syntax",
                            severity=DiagnosticSeverity.Error,
                        )
                    )
                    i = end_idx + 1
                    continue

                routes_text = match.group(1).strip()
                parsed = _parse_path_routes(routes_text)
                if parsed is None:
                    diagnostics.append(
                        Diagnostic(
                            range=Range(
                                start=Position(line=i, character=0),
                                end=Position(
                                    line=end_idx, character=len(lines[end_idx])
                                ),
                            ),
                            message="Invalid path directive syntax",
                            severity=DiagnosticSeverity.Error,
                        )
                    )
                i = end_idx + 1
                continue
            i += 1

        # Validate !layout paths
        for idx, line in enumerate(lines):
            stripped = line.strip()
            if not stripped.startswith("!layout"):
                continue
            literal = _extract_first_string_literal(line)
            if not literal:
                continue
            start_col, end_col, layout_path = literal
            doc_path = _uri_to_path(uri)
            if not doc_path:
                continue
            base_dir = Path(doc_path).parent
            target = Path(layout_path)
            if not target.is_absolute():
                target = (base_dir / target).resolve()
            if not target.exists():
                diagnostics.append(
                    Diagnostic(
                        range=Range(
                            start=Position(line=idx, character=start_col),
                            end=Position(line=idx, character=end_col),
                        ),
                        message=f"Layout file not found: {layout_path}",
                        severity=DiagnosticSeverity.Error,
                    )
                )

        # Validate fences
        start_fence, end_fence = _find_fences(lines)
        if start_fence is not None and end_fence is None:
            diagnostics.append(
                Diagnostic(
                    range=Range(
                        start=Position(line=start_fence, character=0),
                        end=Position(
                            line=start_fence,
                            character=len(lines[start_fence]),
                        ),
                    ),
                    message="Missing closing fence '---'",
                    severity=DiagnosticSeverity.Error,
                )
            )

        doc.diagnostics = diagnostics
        _publish_diagnostics(ls, uri)


def _map_generated_position(
    doc: PyWireDocument, line: int, col: int
) -> Optional[Tuple[int, int]]:
    mapped = doc.map_to_original(line, col)
    if mapped:
        return mapped

    best: Optional[Tuple[int, int]] = None
    best_distance = 10**9
    for mapping in doc.source_map.mappings:
        if mapping.generated_line != line:
            continue
        if col < mapping.generated_col:
            distance = mapping.generated_col - col
            candidate_col = mapping.original_col
        elif col > mapping.generated_col + mapping.length:
            distance = col - (mapping.generated_col + mapping.length)
            candidate_col = mapping.original_col + mapping.length
        else:
            distance = 0
            candidate_col = mapping.original_col + (col - mapping.generated_col)
        if distance < best_distance:
            best_distance = distance
            best = (mapping.original_line, candidate_col)
            if distance == 0:
                break
    return best


def _publish_diagnostics(ls: LanguageServer, uri: str) -> None:
    doc = documents.get(uri)
    if not doc:
        return
    diagnostics = list(doc.diagnostics)
    diagnostics.extend(pyright_diagnostics.get(uri, []))
    ls.text_document_publish_diagnostics(
        PublishDiagnosticsParams(uri=uri, diagnostics=diagnostics)
    )


def _coerce_diagnostic_severity(
    value: Optional[int | DiagnosticSeverity],
) -> Optional[DiagnosticSeverity]:
    if value is None:
        return None
    if isinstance(value, DiagnosticSeverity):
        return value
    try:
        return DiagnosticSeverity(value)
    except ValueError:
        return None


def publish_pyright_diagnostics(ls: LanguageServer, params: Dict[str, Any]) -> None:
    if not shadow_manager:
        return
    shadow_uri = params.get("uri")
    if not shadow_uri:
        return
    source_uri = shadow_manager.get_source_uri_from_shadow(shadow_uri)
    if not source_uri:
        return
    doc = documents.get(source_uri)
    if not doc:
        return

    raw_diagnostics = params.get("diagnostics") or []
    mapped: List[Diagnostic] = []
    for diag in raw_diagnostics:
        diag_range = diag.get("range")
        if not diag_range:
            continue
        start = diag_range.get("start")
        end = diag_range.get("end")
        if not start or not end:
            continue
        mapped_start = _map_generated_position(
            doc, start.get("line", 0), start.get("character", 0)
        )
        if not mapped_start:
            continue
        mapped_end = _map_generated_position(
            doc, end.get("line", 0), end.get("character", 0)
        )
        if not mapped_end:
            mapped_end = mapped_start

        mapped_range = Range(
            start=Position(line=mapped_start[0], character=mapped_start[1]),
            end=Position(line=mapped_end[0], character=mapped_end[1]),
        )
        mapped.append(
            Diagnostic(
                range=mapped_range,
                message=diag.get("message", ""),
                severity=_coerce_diagnostic_severity(diag.get("severity")),
                source=diag.get("source"),
                code=diag.get("code"),
            )
        )

    pyright_diagnostics[source_uri] = mapped
    _publish_diagnostics(ls, source_uri)


@server.feature("textDocument/didOpen")
def did_open(ls: LanguageServer, params: DidOpenTextDocumentParams):
    """Text document did open notification."""
    uri = params.text_document.uri
    # Validate URI scheme
    if not uri.startswith("file://"):
        return

    doc = PyWireDocument(uri, params.text_document.text)
    documents[uri] = doc

    # Sync with Shadow/Pyright
    if shadow_manager:
        shadow_path = shadow_manager.update_shadow_file(uri, doc.get_python_source())

        if pyright_client and shadow_path:
            # We must open the SHADOW file in Pyright
            # Construct params
            # We need to send textDocument/didOpen for the shadow file
            try:
                shadow_doc_item = {
                    "uri": shadow_path,
                    "languageId": "python",
                    "version": params.text_document.version,
                    "text": doc.get_python_source(),
                }
                pyright_client.send_notification(
                    "textDocument/didOpen", {"textDocument": shadow_doc_item}
                )
            except Exception as e:
                logger.error(f"Failed to notify pyright didOpen: {e}")

    # Initial diagnostics
    validate(ls, uri)


@server.feature("textDocument/didChange")
def did_change(ls: LanguageServer, params: DidChangeTextDocumentParams):
    """Text document did change notification."""
    uri = params.text_document.uri
    doc = documents.get(uri)
    if not doc:
        return

    # Update document text
    # Simple full text replacement for now, assuming client sends full text
    # NOTE: In reality, params.content_changes might be incremental.
    # But PyWireDocument expects full text.
    # LSP says if syncKind is Full, we get full text in content_changes[0].text
    if params.content_changes:
        new_text = params.content_changes[-1].text
        doc.update(new_text)

        # Sync with Shadow/Pyright
        if shadow_manager:
            shadow_path = shadow_manager.update_shadow_file(
                uri, doc.get_python_source()
            )

            if pyright_client and shadow_path:
                try:
                    shadow_change_params = {
                        "textDocument": {
                            "uri": shadow_path,
                            "version": params.text_document.version,
                        },
                        "contentChanges": [{"text": doc.get_python_source()}],
                    }
                    pyright_client.send_notification(
                        "textDocument/didChange", shadow_change_params
                    )
                except Exception as e:
                    logger.error(f"Failed to notify pyright didChange: {e}")

    validate(ls, uri)

    logger.info(f"Document changed: {uri}")


@server.feature("textDocument/hover")
async def hover(ls: LanguageServer, params: HoverParams) -> Optional[Hover]:
    """Provide hover information"""
    uri = params.text_document.uri
    position = params.position

    doc = documents.get(uri)
    if not doc:
        return None

    # Check if hovering over !path directive (single-line or multi-line)
    line_text = doc.lines[position.line].strip()
    in_path_directive = line_text.startswith("!path")

    # Also check if within multi-line !path range
    if not in_path_directive and "path" in doc.directive_ranges:
        start, end = doc.directive_ranges["path"]
        if start <= position.line <= end:
            in_path_directive = True

    if in_path_directive:
        entry_hover = _path_entry_hover(doc, position)
        if entry_hover:
            return entry_hover
        return Hover(
            contents="""**!path Directive**

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
- `path` - dict of route names to booleans
- `params` - dict of captured parameters
- `query` - dict of query string parameters
- `url` - helper to generate URLs
"""
        )

    # Check for word at cursor to detect $ shorthand or directives
    line_text = doc.lines[position.line]
    word = _get_word_at_position(line_text, position.character)
    is_shorthand = word.startswith("$") and len(word) > 1 and word[1].isalpha()

    # Direct mapping approach
    gen_pos = doc.map_to_generated(position.line, position.character)

    if gen_pos:
        gen_line, gen_col = gen_pos

        # 1. Try Pyright Fallback
        if pyright_client and shadow_manager:
            shadow_uri = shadow_manager.get_shadow_uri(uri)
            if shadow_uri:
                try:
                    # Construct params for Pyright
                    # We need to translate the position to the shadow file
                    shadow_params = {
                        "textDocument": {"uri": shadow_uri},
                        "position": {"line": gen_line, "character": gen_col},
                    }

                    result = await pyright_client.send_request(
                        "textDocument/hover", shadow_params
                    )
                    if result and "contents" in result:
                        # Success!
                        # We might needed to map range?
                        # For now, just return contents

                        contents = result["contents"]

                        # Add shorthand hint if needed
                        # Pyright returns MarkdownString usually
                        if is_shorthand:
                            prefix = f"**Reactive Shorthand**\n\nAccessor for `{word}`. Equivalent to `{word[1:]}.value`.\n\n---\n\n"
                            if isinstance(contents, dict) and "value" in contents:
                                contents["value"] = prefix + contents["value"]
                            elif isinstance(contents, str):
                                contents = prefix + contents

                        if isinstance(contents, dict):
                            return Hover(
                                contents=MarkupContent(
                                    kind=contents.get("kind", "markdown"),
                                    value=contents.get("value", ""),
                                )
                            )
                        return Hover(contents=contents)
                except Exception as e:
                    logger.error(f"Pyright hover failed: {e}")

                except Exception as e:
                    logger.error(f"Pyright hover failed: {e}")

        # Fallback checks (if no mapping or Pyright failed)

    # Fallback checks (if no mapping or Jedi failed)

    framework_hovers = {
        "path": "**path**\n\nRoute matcher dict. Keys are route names from `!path`, values are `True` when that route matched.",
        "url": "**url**\n\nURL helper dict. Keys are route names from `!path`, values are URL templates.",
        "params": "**params**\n\nURL path parameters extracted from the matched route.",
        "query": "**query**\n\nQuery string parameters from the URL.",
    }

    if word in framework_hovers:
        return Hover(contents=framework_hovers[word])

    # Check for scoped attribute on <style> tag
    if word == "scoped":
        # Check if we're in a <style> tag context
        line_text = doc.lines[position.line] if position.line < len(doc.lines) else ""
        if "<style" in line_text.lower():
            return Hover(
                contents="""**Scoped Styles**

Styles in this block are automatically scoped to this component/page/layout.

- CSS rules are prefixed to only apply within this component's DOM subtree
- Styles are merged and auto-updated during development
- Prevents style leakage between components

Example:
```html
<style scoped>
  .button { color: blue; }
</style>
```"""
            )

    hover_docs = {
        "@click": "**@click**\n\nClick event handler. Value can be a function name or Python expression.\n\nExample: `@click={change_name}` or `@click={count += 1}`",
        "@submit": "**@submit**\n\nForm submit event handler. Value can be a function name or Python expression.",
        "@change": "**@change**\n\nChange event handler. Value can be a function name or Python expression.",
        "@input": "**@input**\n\nInput event handler. Value can be a function name or Python expression.",
        "$if": "**$if**\n\nConditional rendering. Element is excluded from DOM when condition is falsy.\n\nExample: `$if={is_admin}`",
        "$show": "**$show**\n\nConditional visibility. Element stays in DOM but is hidden via CSS when condition is falsy.\n\nExample: `$show={is_visible}`",
        "$for": "**$for**\n\nLoop directive. Repeats the element for each item in a collection.\n\n**Syntax:**\n- `$for={item in items}`\n- `$for={index, item in enumerate(items)}`\n- `$for={key, value in dict.items()}`",
        "$key": "**$key**\n\nStable key for loops. Provides a unique identifier for efficient DOM diffing.\n\nExample: `$key={item.id}`",
    }

    if word in hover_docs:
        return Hover(contents=hover_docs[word])
    elif word.startswith("@"):
        parts = word.split(".")
        if parts[0] in hover_docs:
            base = hover_docs[parts[0]]
            if len(parts) > 1:
                base += f"\n\n**Modifiers:** {', '.join(parts[1:])}"
            return Hover(contents=base)
        return Hover(contents=f"**{word}**\n\nEvent handler.")
    elif is_shorthand:
        return Hover(
            contents=f"**Reactive Shorthand**\n\nAccessor for `{word}`. Equivalent to `{word[1:]}.value`."
        )
    elif word.startswith("$"):
        return Hover(contents=f"**{word}**\n\nDirective.")

    return None


@server.feature("textDocument/references")
async def references(
    ls: LanguageServer, params: ReferenceParams
) -> Optional[List[Location]]:
    """Provide find references"""
    uri = params.text_document.uri
    position = params.position

    doc = documents.get(uri)
    if not doc:
        return None

    # Map to virtual python
    gen_pos = doc.map_to_generated(position.line, position.character)
    if not gen_pos:
        return None

    gen_line, gen_col = gen_pos

    if pyright_client and shadow_manager:
        shadow_uri = shadow_manager.get_shadow_uri(uri)
        if shadow_uri:
            try:
                shadow_params = {
                    "textDocument": {"uri": shadow_uri},
                    "position": {"line": gen_line, "character": gen_col},
                    "context": {
                        "includeDeclaration": True
                    },  # params.context might be present
                }

                # We need to handle params.context if it exists
                if hasattr(params, "context"):
                    # lsprotocol object to dict... or just manual
                    shadow_params["context"] = {
                        "includeDeclaration": params.context.include_declaration
                    }

                result = await pyright_client.send_request(
                    "textDocument/references", shadow_params
                )

                if result:
                    # Result is List[Location] (dicts)
                    # We need to map them back
                    locations = []
                    for loc in result:
                        loc_uri = loc.get("uri")
                        loc_range = loc.get("range")

                        # If reference is in shadow file, map back
                        # If external, keep as is
                        if loc_uri == shadow_uri:
                            # Map back to .wire
                            start = loc_range["start"]
                            end = loc_range["end"]

                            orig_start = doc.map_to_original(
                                start["line"], start["character"]
                            )
                            orig_end = doc.map_to_original(
                                end["line"], end["character"]
                            )

                            if orig_start and orig_end:
                                locations.append(
                                    Location(
                                        uri=uri,
                                        range=Range(
                                            start=Position(
                                                line=orig_start[0],
                                                character=orig_start[1],
                                            ),
                                            end=Position(
                                                line=orig_end[0], character=orig_end[1]
                                            ),
                                        ),
                                    )
                                )
                        else:
                            # External reference
                            locations.append(
                                Location(
                                    uri=loc_uri,
                                    range=Range(
                                        start=Position(
                                            line=loc_range["start"]["line"],
                                            character=loc_range["start"]["character"],
                                        ),
                                        end=Position(
                                            line=loc_range["end"]["line"],
                                            character=loc_range["end"]["character"],
                                        ),
                                    ),
                                )
                            )
                    return locations

            except Exception as e:
                logger.error(f"Pyright references error: {e}")

    return None


@server.feature("textDocument/definition")
async def definition(
    ls: LanguageServer, params: DefinitionParams
) -> Optional[List[Location]]:
    """Provide go-to-definition"""
    uri = params.text_document.uri
    position = params.position

    doc = documents.get(uri)
    if not doc:
        return None

    # Handle !layout directive path
    line_text = doc.lines[position.line]
    if line_text.strip().startswith("!layout"):
        literal = _extract_first_string_literal(line_text)
        if literal:
            start_col, end_col, layout_path = literal
            if start_col <= position.character <= end_col:
                doc_path = _uri_to_path(uri)
                if doc_path:
                    base_dir = Path(doc_path).parent
                    target = Path(layout_path)
                    if not target.is_absolute():
                        target = (base_dir / target).resolve()
                    if target.exists():
                        return [
                            Location(
                                uri=f"file://{target}",
                                range=Range(
                                    start=Position(line=0, character=0),
                                    end=Position(line=0, character=0),
                                ),
                            )
                        ]

    # Go-to-definition for path variable
    word = _get_word_at_position(line_text, position.character)
    if word == "path" and "path" in doc.directive_ranges:
        start_line, _ = doc.directive_ranges["path"]
        return [
            Location(
                uri=uri,
                range=Range(
                    start=Position(line=start_line, character=0),
                    end=Position(line=start_line, character=0),
                ),
            )
        ]

    # Map to virtual python
    gen_pos = doc.map_to_generated(position.line, position.character)
    if not gen_pos:
        return None

    gen_line, gen_col = gen_pos

    if pyright_client and shadow_manager:
        shadow_uri = shadow_manager.get_shadow_uri(uri)
        if shadow_uri:
            try:
                shadow_params = {
                    "textDocument": {"uri": shadow_uri},
                    "position": {"line": gen_line, "character": gen_col},
                }

                result = await pyright_client.send_request(
                    "textDocument/definition", shadow_params
                )

                if result:
                    # Result is Location | Location[] | LocationLink[] | None
                    # Normalize to list
                    if not isinstance(result, list):
                        result = [result]

                    locations = []
                    for loc in result:
                        # Handle LocationLink? Pyright usually returns Location for basic definition
                        if "targetUri" in loc:
                            # It's a LocationLink
                            loc_uri = loc["targetUri"]
                            loc_range = loc["targetSelectionRange"]
                        else:
                            # It's a Location
                            loc_uri = loc["uri"]
                            loc_range = loc["range"]

                        if loc_uri == shadow_uri:
                            # Map back
                            start = loc_range["start"]
                            end = loc_range["end"]

                            orig_start = doc.map_to_original(
                                start["line"], start["character"]
                            )
                            # For definitions, end might not handle well if we map purely points
                            # Just map start

                            if orig_start:
                                # Start is valid.
                                # Hack: use end same as start or +length?
                                # Ideally map end too.
                                orig_end = doc.map_to_original(
                                    end["line"], end["character"]
                                )
                                if not orig_end:
                                    orig_end = orig_start

                                locations.append(
                                    Location(
                                        uri=uri,
                                        range=Range(
                                            start=Position(
                                                line=orig_start[0],
                                                character=orig_start[1],
                                            ),
                                            end=Position(
                                                line=orig_end[0], character=orig_end[1]
                                            ),
                                        ),
                                    )
                                )
                        else:
                            locations.append(
                                Location(
                                    uri=loc_uri,
                                    range=Range(
                                        start=Position(
                                            line=loc_range["start"]["line"],
                                            character=loc_range["start"]["character"],
                                        ),
                                        end=Position(
                                            line=loc_range["end"]["line"],
                                            character=loc_range["end"]["character"],
                                        ),
                                    ),
                                )
                            )

                    return locations
            except Exception as e:
                logger.error(f"Pyright definition error: {e}")

    return None


@server.feature("textDocument/completion")
async def completions(ls: LanguageServer, params: CompletionParams) -> CompletionList:
    """Provide completions"""
    uri = params.text_document.uri
    position = params.position

    doc = documents.get(uri)
    if not doc:
        return CompletionList(is_incomplete=False, items=[])

    section = _get_section(doc.lines, position.line)

    # Map to virtual python
    gen_pos = doc.map_to_generated(position.line, position.character)
    if not gen_pos:
        gen_pos = doc.source_map.nearest_generated_on_line(
            position.line, position.character
        )

    if section == "python":
        if not gen_pos:
            return CompletionList(is_incomplete=False, items=[])
    elif section == "separator":
        return CompletionList(is_incomplete=False, items=[])

    if gen_pos:
        gen_line, gen_col = gen_pos

        if pyright_client and shadow_manager:
            shadow_uri = shadow_manager.get_shadow_uri(uri)
            if shadow_uri:
                try:
                    shadow_params = {
                        "textDocument": {"uri": shadow_uri},
                        "position": {"line": gen_line, "character": gen_col},
                        "context": attrs.asdict(params.context)
                        if params.context
                        else None,
                    }

                    result = await pyright_client.send_request(
                        "textDocument/completion", shadow_params
                    )

                    if result:
                        # Result can be CompletionList (dict) or List[CompletionItem]
                        if isinstance(result, list):
                            items = result
                            is_incomplete = False
                        else:
                            items = result.get("items", [])
                            is_incomplete = result.get("isIncomplete", False)

                        # No mapping needed for completions usually,
                        # unless insertText/textEdit has ranges?
                        # For now assume insertText/label is good.

                        comp_items = []
                        for item in items:
                            # Convert dict to CompletionItem
                            # Be careful with data field serialization if it's complex
                            # Just passing minimal for now?
                            # Or relying on pygls validation?
                            # Let's try to pass raw dicts? No, return type expects object
                            # Actually pygls 1.0+ might accept dicts if types allow?
                            # But type hint says CompletionList.

                            # Safest: Use attrs.from_dict or manual
                            # Let's try manual simple copy for safety
                            new_item = CompletionItem(
                                label=item["label"],
                                kind=item.get("kind"),
                                detail=item.get("detail"),
                                documentation=item.get("documentation"),
                                sort_text=item.get("sortText"),
                                filter_text=item.get("filterText"),
                                insert_text=item.get("insertText"),
                                # Skip textEdit/additionalTextEdits as they involve ranges we might need to map
                            )
                            comp_items.append(new_item)

                        return CompletionList(
                            is_incomplete=is_incomplete, items=comp_items
                        )

                except Exception as e:
                    logger.error(f"Pyright completion error: {e}")

    if section == "python":
        return CompletionList(is_incomplete=False, items=[])

    # Get line text and check context
    line_text = doc.lines[position.line] if position.line < len(doc.lines) else ""
    in_tag = _is_inside_opening_tag(line_text, position.character)

    # Suggest control flow tags if prefix is {$
    before_cursor = line_text[: position.character]
    if "{$" in before_cursor:
        match = re.search(r"\{\$([\w]*)$", before_cursor)
        if match:
            tag_prefix = match.group(1).lower()
            tags = [
                "if",
                "elif",
                "else",
                "for",
                "await",
                "then",
                "catch",
                "try",
                "except",
                "finally",
            ]
            items = []
            for tag in tags:
                if tag.startswith(tag_prefix):
                    items.append(
                        CompletionItem(
                            label=tag,
                            kind=CompletionItemKind.Keyword,
                            detail=f"PyWire control flow tag: {{$ {tag} }}",
                            insert_text=tag,
                        )
                    )
            if items:
                return CompletionList(is_incomplete=False, items=items)

    # Only suggest directives and event handlers when inside an opening tag
    if not in_tag:
        return CompletionList(is_incomplete=False, items=[])

    # Get the prefix to filter suggestions
    before_cursor = line_text[: position.character]
    prefix_match = re.search(r"[@$][\w.]*$", before_cursor)
    prefix = prefix_match.group(0) if prefix_match else ""

    suggestion_items: List[CompletionItem] = []

    # Add directive suggestions when prefix starts with $ or is empty and user might want them
    if prefix.startswith("$") or not prefix:
        suggestion_items.extend(
            [
                CompletionItem(
                    label="$if",
                    kind=CompletionItemKind.Keyword,
                    documentation="Conditional rendering. Element is excluded from DOM when condition is falsy.",
                    insert_text="$if={$1}",
                    insert_text_format=InsertTextFormat.Snippet,
                ),
                CompletionItem(
                    label="$show",
                    kind=CompletionItemKind.Keyword,
                    documentation="Conditional visibility. Element stays in DOM but is hidden via CSS when condition is falsy.",
                    insert_text="$show={$1}",
                    insert_text_format=InsertTextFormat.Snippet,
                ),
                CompletionItem(
                    label="$for",
                    kind=CompletionItemKind.Keyword,
                    documentation="Loop directive. Repeats the element for each item in a collection.",
                    insert_text="$for={$1 in $2}",
                    insert_text_format=InsertTextFormat.Snippet,
                ),
                CompletionItem(
                    label="$key",
                    kind=CompletionItemKind.Keyword,
                    documentation="Stable key for loops. Provides a unique identifier for efficient DOM diffing.",
                    insert_text="$key={$1}",
                    insert_text_format=InsertTextFormat.Snippet,
                ),
            ]
        )

    # Add event handler suggestions when prefix starts with @ or is empty
    if prefix.startswith("@") or not prefix:
        suggestion_items.extend(
            [
                CompletionItem(
                    label="@click",
                    kind=CompletionItemKind.Event,
                    documentation="Click event handler.",
                    insert_text="@click={$1}",
                    insert_text_format=InsertTextFormat.Snippet,
                ),
                CompletionItem(
                    label="@submit",
                    kind=CompletionItemKind.Event,
                    documentation="Form submit event handler.",
                    insert_text="@submit={$1}",
                    insert_text_format=InsertTextFormat.Snippet,
                ),
                CompletionItem(
                    label="@change",
                    kind=CompletionItemKind.Event,
                    documentation="Change event handler.",
                    insert_text="@change={$1}",
                    insert_text_format=InsertTextFormat.Snippet,
                ),
                CompletionItem(
                    label="@input",
                    kind=CompletionItemKind.Event,
                    documentation="Input event handler.",
                    insert_text="@input={$1}",
                    insert_text_format=InsertTextFormat.Snippet,
                ),
                CompletionItem(
                    label="@keydown",
                    kind=CompletionItemKind.Event,
                    documentation="Keydown event handler.",
                    insert_text="@keydown={$1}",
                    insert_text_format=InsertTextFormat.Snippet,
                ),
                CompletionItem(
                    label="@keyup",
                    kind=CompletionItemKind.Event,
                    documentation="Keyup event handler.",
                    insert_text="@keyup={$1}",
                    insert_text_format=InsertTextFormat.Snippet,
                ),
                CompletionItem(
                    label="@focus",
                    kind=CompletionItemKind.Event,
                    documentation="Focus event handler.",
                    insert_text="@focus={$1}",
                    insert_text_format=InsertTextFormat.Snippet,
                ),
                CompletionItem(
                    label="@blur",
                    kind=CompletionItemKind.Event,
                    documentation="Blur event handler.",
                    insert_text="@blur={$1}",
                    insert_text_format=InsertTextFormat.Snippet,
                ),
            ]
        )

    return CompletionList(is_incomplete=False, items=suggestion_items)


def _get_semantic_token_type(name_type: str) -> int:
    """Map Jedi name type to semantic token type index"""
    type_map = {
        "function": SEMANTIC_TOKEN_TYPES.index("function"),
        "class": SEMANTIC_TOKEN_TYPES.index("class"),
        "module": SEMANTIC_TOKEN_TYPES.index("namespace"),
        "keyword": SEMANTIC_TOKEN_TYPES.index("keyword"),
        "statement": SEMANTIC_TOKEN_TYPES.index("variable"),
        "param": SEMANTIC_TOKEN_TYPES.index("parameter"),
    }
    return type_map.get(name_type, SEMANTIC_TOKEN_TYPES.index("variable"))


@server.feature("textDocument/semanticTokens/full")
def semantic_tokens(ls: LanguageServer, params: SemanticTokensParams) -> SemanticTokens:
    """Provide semantic tokens for Python syntax highlighting using virtual python AST"""
    uri = params.text_document.uri
    doc = documents.get(uri)

    if not doc:
        return SemanticTokens(data=[])

    try:
        source = doc.get_python_source()
        if not source:
            return SemanticTokens(data=[])

        # Parse virtual python
        tree = ast.parse(source)

        # Collect tokens
        tokens_data = []  # (line, start_col, length, type, modifiers)

        # Helper to process nodes
        for node in ast.walk(tree):
            token_type_idx = -1
            length = 0

            # Identify token type
            if isinstance(node, ast.Name):
                # We could improve this by inferring type with Jedi,
                # but for speed AST matching is okay for basic highlighting
                token_type_idx = SEMANTIC_TOKEN_TYPES.index("variable")
                length = len(node.id)
                # Heuristics for keywords/builtins could be added here
            elif isinstance(node, ast.FunctionDef):
                token_type_idx = SEMANTIC_TOKEN_TYPES.index("function")
                length = len(node.name)
                # Map the function name position
                # node.lineno is 1-based start of 'def'
                # node.col_offset is start of 'def'
                # We need exact location of the name
                # AST doesn't give name location easily, usually it's def <name>
                # Let's skip definitions for now if complex, or handle simple cases
                pass

            # Better approach: Use Jedi for semantic tokens if we want high quality
            # But let's stick to simple AST node mapping first

            if token_type_idx != -1:
                # Map variables
                # node.lineno is 1-based, node.col_offset is 0-based
                if not hasattr(node, "lineno") or not hasattr(node, "col_offset"):
                    continue
                gen_line = getattr(node, "lineno")
                gen_col = getattr(node, "col_offset")

                # Verify location mapping
                orig_pos = doc.map_to_original(gen_line - 1, gen_col)
                if orig_pos:
                    orig_line, orig_col = orig_pos
                    tokens_data.append((orig_line, orig_col, length, token_type_idx, 0))

        # Sort tokens by line, then column
        tokens_data.sort()

        # Flatten to delta encoding
        final_tokens = []
        prev_line = 0
        prev_char = 0

        for t in tokens_data:
            line, col, length, type_idx, mod = t

            delta_line = line - prev_line
            delta_start = col - prev_char if delta_line == 0 else col

            final_tokens.extend([delta_line, delta_start, length, type_idx, mod])

            prev_line = line
            prev_char = col

        return SemanticTokens(data=final_tokens)

    except Exception as e:
        logger.error(f"Semantic tokens error: {e}")
        return SemanticTokens(data=[])


@server.feature("pywire/virtualCode")
def virtual_code(ls: LanguageServer, params: Any) -> Optional[Dict[str, Any]]:
    """Return the generated virtual python code for a document."""
    # Params is just { uri: str } usually, or list? pygls passes the raw params object if not typed
    # We expect params to be a dict or object with 'uri'

    # Check if params is a dict or object
    uri = None
    text = None
    if isinstance(params, dict):
        uri = params.get("uri")
        text = params.get("text")
    elif hasattr(params, "uri"):
        uri = params.uri
        text = getattr(params, "text", None)

    if not uri:
        return None

    if text is not None:
        doc = documents.get(uri)
        if doc:
            doc.update(text)
        else:
            doc = PyWireDocument(uri, text)
            documents[uri] = doc
    else:
        doc = documents.get(uri)
    if not doc:
        return None

    return {
        "uri": uri,
        "content": doc.get_python_source(),
    }


@server.feature("pywire/mapToGenerated")
def map_to_generated(ls: LanguageServer, params: Any) -> Optional[Dict[str, Any]]:
    """Map a position in the source .wire file to the generated .py file."""
    uri = None
    position = None

    # Handle various param structures
    if isinstance(params, dict):
        uri = params.get("uri")
        pos_dict = params.get("position")
        if pos_dict:
            position = Position(line=pos_dict["line"], character=pos_dict["character"])
    elif hasattr(params, "uri") and hasattr(params, "position"):
        uri = params.uri
        position = params.position

    if not uri or not position:
        return None

    doc = documents.get(uri)
    if not doc:
        return None

    gen_pos = doc.map_to_generated(position.line, position.character)
    if not gen_pos:
        gen_pos = doc.source_map.nearest_generated_on_line(
            position.line, position.character
        )
        if not gen_pos:
            return None

    gen_line, gen_col = gen_pos
    return {"line": gen_line, "character": gen_col}


@server.feature("pywire/mapFromGenerated")
def map_from_generated(ls: LanguageServer, params: Any) -> Optional[Dict[str, Any]]:
    """Map a position in the generated .py file back to the source .wire file."""
    uri = None
    position = None

    # Handle various param structures
    if isinstance(params, dict):
        uri = params.get("uri")
        pos_dict = params.get("position")
        if pos_dict:
            position = Position(line=pos_dict["line"], character=pos_dict["character"])
    elif hasattr(params, "uri") and hasattr(params, "position"):
        uri = params.uri
        position = params.position

    if not uri or not position:
        return None

    # URI might be the shadow URI; we need the original URI
    # Shadow manager can help us find the original if needed,
    # but the client usually sends the original URI and expects us to know it.
    # Actually, the middleware sends the ORIGINAL .wire URI
    # but asks to map a position that it thinks corresponds to the generated code.
    # Wait, the middleware knows the original URI.

    doc = documents.get(uri)
    if not doc:
        return None

    orig_pos = doc.map_to_original(position.line, position.character)
    if not orig_pos:
        return None

    orig_line, orig_col = orig_pos
    return {"line": orig_line, "character": orig_col}


def start():
    """Start the language server"""
    logger.info("PyWire Language Server starting...")
    try:
        server.start_io()
    except Exception:
        logger.exception("Server crashed")
        raise


if __name__ == "__main__":
    start()
