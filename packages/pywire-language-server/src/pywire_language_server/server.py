"""PyWire Language Server"""

import ast
import asyncio
import cattrs
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
    Command,
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
    MessageType,
    Position,
    PublishDiagnosticsParams,
    Range,
    ReferenceParams,
    RenameParams,
    SemanticTokens,
    SemanticTokensLegend,
    SemanticTokensParams,
    ShowMessageParams,
    TextDocumentSyncKind,
    TextEdit,
    WorkspaceEdit,
)
from pygls.lsp.server import LanguageServer

from . import __version__
from .ty import TyClient
from .transpiler import Transpiler
from .sourcemap import SourceMap
try:
    import pywire
    HAS_PYWIRE = True
except ImportError:
    HAS_PYWIRE = False

# Valid block keywords: used in {$keyword ...} and {/keyword}
KNOWN_BLOCKS = {"if", "elif", "else", "for", "await", "then", "catch", "try", "except", "finally"}
# Block keywords that start a block (require a closing {/tag})
BLOCK_OPENERS = {"if", "for", "await", "try"}
# Block keywords that are continuations (must appear inside an opener)
BLOCK_CONTINUATIONS = {"elif", "else", "then", "catch", "except", "finally"}
# Closing tags that are valid
BLOCK_CLOSERS = {"if", "for", "await", "try"}  # {/if}, {/for}, etc.

# Valid attribute keywords: used as $keyword on HTML elements
KNOWN_ATTRIBUTES = {"if", "show", "for", "key", "ref", "permanent", "reload"}

KNOWN_DIRECTIVES = {"!layout", "!path", "!no_spa"}


class VirtualFileManager:
    """
    Manages virtual .py documents for Ty consumption.
    Does not write anything to disk.
    """

    def __init__(self, root_uri: str):
        self.root_uri = root_uri
        self.root_path = self._uri_to_path(root_uri)
        # Store source maps for active documents
        self.source_maps: Dict[str, SourceMap] = {}

    def _uri_to_path(self, uri: str) -> Optional[str]:
        if uri.startswith("file://"):
            return uri[7:]
        return None

    def get_shadow_uri(self, doc_uri: str) -> Optional[str]:
        """
        Map a .wire URI to a virtual .py URI.
        """
        doc_path = self._uri_to_path(doc_uri)
        if not doc_path:
            return None
        if doc_path.endswith(".wire"):
            return f"file://{doc_path[:-5]}_wire.py"
        return f"file://{doc_path}.py"

    def get_stub_uri(self, doc_uri: str) -> Optional[str]:
        """
        Map a .wire URI to a virtual .pyi URI.
        """
        doc_path = self._uri_to_path(doc_uri)
        if not doc_path:
            return None
        if doc_path.endswith(".wire"):
             return f"file://{doc_path[:-5]}_wire.pyi"
        return f"file://{doc_path}.pyi"

    def get_original_uri(self, shadow_uri: str) -> Optional[str]:
        """Map back from virtual .py or .pyi URI to original .wire URI."""
        # Handle both file:// and raw paths
        uri = shadow_uri if shadow_uri.startswith("file://") else f"file://{shadow_uri}"
        
        # 1. Direct shadow matches (_wire.py)
        if uri.endswith("_wire.py"):
             return uri[:-8] + ".wire"
        if uri.endswith("_wire.pyi"):
             return uri[:-9] + ".wire"

        # 2. Stub matches (foo.pyi -> foo.wire)
        if uri.endswith(".pyi"):
             path = self._uri_to_path(uri)
             if path:
                 # Check for foo.pyi -> foo.wire
                 wire_path = path[:-4] + ".wire"
                 if os.path.exists(wire_path):
                     return f"file://{wire_path}"
        
        # 3. Fallback: Check if it's a known shadow file in our source_maps
        # Ty might return lowercase or slightly different URIs
        norm_uri = uri.lower()
        if norm_uri in [k.lower() for k in self.source_maps.keys()]:
             # If it's a known shadow, we can try to guess back
             if uri.endswith(".py"):
                  # For our new pattern, if it got here and ends with .py but wasn't _wire.py
                  return uri[:-3]
             if uri.endswith(".pyi"):
                  return uri[:-4] + ".wire"
                  
        return None

    def set_source_map(self, shadow_uri: str, source_map: SourceMap):
        """Store source map for a virtual file."""
        self.source_maps[shadow_uri] = source_map

    def get_source_map(self, shadow_uri: str) -> Optional[SourceMap]:
        """Retrieve source map for a virtual file."""
        if shadow_uri in self.source_maps:
            return self.source_maps[shadow_uri]
        
        # Robust lookup for casing mismatch
        norm_shadow = shadow_uri.lower()
        for key, sm in self.source_maps.items():
            if key.lower() == norm_shadow:
                return sm
        return None


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


# Global state for Ty client
virtual_manager: Optional[VirtualFileManager] = None
ty_client: Optional[TyClient] = None

ty_diagnostics: dict[str, List[Diagnostic]] = {}


@server.feature("initialize")
async def initialize(ls: LanguageServer, params: Any):
    global virtual_manager, ty_client
    logger.info("PyWire Language Server initializing...")
    
    if not HAS_PYWIRE:
        ls.window_show_message(ShowMessageParams(
            message="PyWire Language Server: 'pywire' package not found in current environment. Please install it for full functionality.",
            type=MessageType.Error
        ))
        logger.error("pywire package not found. Tree-sitter parsing will be unavailable.")
    
    root_uri = params.root_uri or (
        params.workspace_folders[0].uri if params.workspace_folders else None
    )

    if root_uri:
        virtual_manager = VirtualFileManager(root_uri)
        # Always use Ty
        init_opts = getattr(params, "initializationOptions", {}) or {}
        ty_path = init_opts.get("tyPath", None)
        
        client = TyClient()
        if client.start(ty_path=ty_path):
            ty_client = client
            
            # Hook up diagnostics
            def handle_diagnostics(params):
                uri = params.get("uri")
                diagnostics = params.get("diagnostics", [])
                logger.info(f"[Server] Received diagnostics for {uri}: {len(diagnostics)} items")

                # Check if this URI matches a shadow file we know about
                if not uri: return
                
                # If usage of shadow file is internal to this server, we should
                # map the URI back to the original .wire file
                wire_uri = virtual_manager.get_original_uri(uri)
                if wire_uri:
                    # Robust lookup: Find the actual key in documents that matches this URI
                    # because casing or path normalization might differ.
                    target_uri = wire_uri
                    if wire_uri not in documents:
                        # Try case-insensitive scan
                        norm_wire = wire_uri.lower()
                        for doc_uri in documents:
                            if doc_uri.lower() == norm_wire:
                                target_uri = doc_uri
                                break
                    
                    logger.info(f"[Server] Mapped {uri} -> {wire_uri} (Target: {target_uri})")
                    
                    # Map diagnostics back
                    mapped_diagnostics = []
                    source_map = virtual_manager.get_source_map(uri)
                    if source_map:
                        for diag in diagnostics:
                            mapped = _map_diagnostic(diag, source_map)
                            if mapped:
                                mapped_diagnostics.append(mapped)
                    
                    # Store and publish using the found TARGET URI
                    ty_diagnostics[target_uri] = mapped_diagnostics
                    _publish_diagnostics(ls, target_uri)

            ty_client.set_diagnostics_callback(handle_diagnostics)
            
            # Initialize Ty and wait for it
            await _init_ty(ls, params)

            # Eager load all .wire files in the workspace
            await _eager_load_workspace(ls)
        else:
            logger.error("Failed to start Ty. Python features will be disabled.")

    return {
        "capabilities": {
            "textDocumentSync": {
                "openClose": True,
                "change": 1,  # Full sync
            },
            "completionProvider": {
                "triggerCharacters": [".", "/", "@", "$", "{"],
                "resolveProvider": False,
            },
            "hoverProvider": True,
            "definitionProvider": True,
            "referencesProvider": True,
            "semanticTokensProvider": {
                "legend": SEMANTIC_TOKENS_LEGEND,
                "full": True,
            },
            "renameProvider": True,
        }
    }


async def _init_ty(ls: LanguageServer, params: Any):
    # Wait for Ty to be ready?
    # Send initialize request to Ty
    if not ty_client:
        return

    root_uri = params.root_uri or ""
    init_params = {
        "processId": os.getpid(),
        "rootUri": root_uri,
        "capabilities": cattrs.unstructure(params.capabilities),
        "initializationOptions": cattrs.unstructure(getattr(params, "initializationOptions", {})) or {},
    }
    
    # Ty might need workspace folders too
    if hasattr(params, "workspace_folders") and params.workspace_folders:
        init_params["workspaceFolders"] = cattrs.unstructure(params.workspace_folders)

    logger.info("Sending initialize to Ty...")
    try:
        # We don't await the result blocking the whole server init? 
        # But we need to know if Ty accepted.
        # Let's await it.
        res = await ty_client.send_request("initialize", init_params)
        logger.info(f"Ty initialized: {res}")

        # Send initialized notification
        ty_client.send_notification("initialized", {})
    except Exception as e:
        logger.error(f"Failed to initialize Ty: {e}")


async def _eager_load_workspace(ls: LanguageServer):
    """Scan root_path for .wire files and open them in Ty."""
    if not virtual_manager or not virtual_manager.root_path or not ty_client:
        return

    root = Path(virtual_manager.root_path)
    logger.info(f"Eager loading workspace: {root}")
    
    # Simple recursive scan
    for wire_file in root.rglob("*.wire"):
        # Skip common ignored dirs
        if any(part in wire_file.parts for part in [".venv", "node_modules", ".git", ".pywire", "__pycache__"]):
            continue
            
        uri = wire_file.as_uri()
        if uri in documents:
            continue
            
        try:
            content = wire_file.read_text(encoding="utf-8")
            doc = PyWireDocument(uri, content)
            documents[uri] = doc
            
            shadow_uri = virtual_manager.get_shadow_uri(uri)
            if shadow_uri:
                virtual_manager.set_source_map(shadow_uri, doc.source_map)
                
                # Notify Ty of the shadow file
                shadow_doc_item = {
                    "uri": shadow_uri,
                    "languageId": "python",
                    "version": 0,
                    "text": doc.get_python_source(),
                }
                ty_client.send_notification(
                    "textDocument/didOpen", {"textDocument": shadow_doc_item}
                )

                # Also notify Ty of the STUB file for import resolution
                stub_uri = virtual_manager.get_stub_uri(uri)
                if stub_uri:
                    stub_content, stub_map = doc.transpiler.generate_stub(str(wire_file))
                    virtual_manager.set_source_map(stub_uri, stub_map)
                    
                    stub_doc_item = {
                        "uri": stub_uri,
                        "languageId": "python",
                        "version": 0,
                        "text": stub_content,
                    }
                    ty_client.send_notification(
                        "textDocument/didOpen", {"textDocument": stub_doc_item}
                    )
        except Exception as e:
            logger.error(f"Failed to eager load {wire_file}: {e}")


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
    if not line_text:
        return ""
    start = min(char, len(line_text))
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


def _is_inside_script_or_style(lines: List[str], position: Position) -> bool:
    """Check if the cursor is inside a <script> or <style> block."""
    row = position.line
    col = position.character

    while row >= 0:
        line = lines[row]
        # Check current line up to col (if it's the start line) or full line
        limit = col if row == position.line else len(line)
        text_to_check = line[:limit]

        # Look for last relevant tag
        matches = []
        for tag in ["<script", "</script", "<style", "</style"]:
            idx = text_to_check.rfind(tag)
            if idx != -1:
                matches.append((idx, tag))

        if not matches:
            row -= 1
            continue

        # Get last tag
        matches.sort(key=lambda x: x[0], reverse=True)
        _, last_tag = matches[0]

        if last_tag.startswith("<script") or last_tag.startswith("<style"):
            return True
        else:
            return False

    return False


def _get_imported_components(doc: "PyWireDocument") -> Dict[str, str]:
    """
    Parse python source to find imported components and filter out implicit imports.
    Returns dict mapping {ComponentName: ModulePath}.
    """
    components = {}
    try:
        source = doc.get_python_source()
        if not source:
            return {}
        
        tree = ast.parse(source)
        for node in ast.walk(tree):
            # Check if this node corresponds to a line in the original file
            # If not, it's likely an implicit import added by the transpiler
            if hasattr(node, "lineno"):
                # map_to_original returns (line, col) or None
                # node.lineno is 1-based, map_to_original expects 0-based?
                # doc.map_to_original uses 0-based.
                orig_pos = doc.map_to_original(node.lineno - 1, 0)
                if not orig_pos:
                    continue

            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if node.level > 0:
                    module = "." * node.level + module
                    
                for alias in node.names:
                    # Filter out internal types used in Type Hints (like InputElement)
                    check_module = node.module or ""
                    if "web_types" in check_module or check_module.endswith("client"):
                        continue
                        
                    # Heuristic: Components are typically PascalCase
                    if alias.name[0].isupper():
                        name = alias.asname or alias.name
                        components[name] = module
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    # Less common for components, but possible (import MyComponent)
                     if alias.name[0].isupper():
                        name = alias.asname or alias.name
                        components[name] = alias.name
    except Exception:
        pass
    return components


def _resolve_import_path(base_uri: str, module_path: str) -> Optional[str]:
    """
    Resolve a python module path (e.g. .components.my_component) to a file URI.
    """
    base_path = _uri_to_path(base_uri)
    if not base_path:
        return None
        
    start_dir = Path(base_path).parent
    
    # Handle relative imports
    dots = 0
    while module_path.startswith("."):
        dots += 1
        module_path = module_path[1:]
        
    if dots > 0:
        # Relative import
        current_dir = start_dir
        for _ in range(dots - 1):
            current_dir = current_dir.parent
            
        parts = module_path.split(".") if module_path else []
        target = current_dir.joinpath(*parts)
    else:
        # Absolute import - try to find from root
        # Check virtual manager root
        if virtual_manager and virtual_manager.root_path:
             target = Path(virtual_manager.root_path).joinpath(*module_path.split("."))
        else:
             # Fallback: assume src/ or similar structure if we can find it
             # For now, just return None if not relative and no root path
             return None

    # Try extensions
    options = [
        target.with_suffix(".py"),
        target.with_suffix(".wire"),
        target / "__init__.py"
    ]
    
    for opt in options:
        if opt.exists():
            return opt.as_uri()
            
    return None


@attrs.define
class PropInfo:
    name: str
    line: int
    doc: str = ""


def _extract_props_from_file(file_uri: str, component_name: str) -> List[PropInfo]:
    """
    Parse a component file (python or wire) to find its @props class and fields.
    """
    path = _uri_to_path(file_uri)
    if not path or not os.path.exists(path):
        return []

    try:
        with open(path, "r") as f:
            source = f.read()
            
        # If .wire, extract python block
        if path.endswith(".wire"):
            parts = source.split("---")
            if len(parts) >= 3:
                source = parts[1] # Python block
            else:
                return [] # No python block?

        tree = ast.parse(source)

        # 1. Look for all classes with @props decorator
        props_classes = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                is_props = any(
                    (isinstance(dec, ast.Name) and dec.id == "props") or
                    (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Name) and dec.func.id == "props")
                    for dec in node.decorator_list
                )
                if is_props:
                    props_classes.append(node)
        
        # Artificial error if multiple @props detected
        if len(props_classes) > 1:
            # For now, we'll log it and maybe return empty or just the first one.
            # True "diagnostic" error would require a different flow, 
            # but we can at least detect it here.
            logger.error(f"Multiple @props classes detected in {path}")
            # We'll use the first one but it's an invalid state
        
        props_class = props_classes[0] if props_classes else None
        
        # 2. If no @props decorator, fallback to searching inside component class if specified
        if not props_class and component_name:
            comp_class = None
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef) and node.name == component_name:
                    comp_class = node
                    break
            
            if comp_class:
                for node in comp_class.body:
                     if isinstance(node, ast.ClassDef) and (node.name == "Props" or "Props" in [b.id for b in node.bases if isinstance(b, ast.Name)]):
                         props_class = node
                         break
        
        # 3. Final fallback: look for top-level class named "Props" (Legacy)
        if not props_class:
            for node in ast.walk(tree):
                 if isinstance(node, ast.ClassDef) and node.name == "Props":
                     props_class = node
                     break
        
        if not props_class:
            return []
            
        props = []
        for node in props_class.body:
             if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                 # annotated assignment: x: int
                 line = node.lineno - 1 # 0-indexed
                 # Adjust line number if it was from a .wire file (add fence offset)
                 if path.endswith(".wire"):
                      # Re-read to find fence offset
                      with open(path, "r") as f:
                          full = f.read()
                          if "---" in full:
                              preamble = full.split("---")[0]
                              line += preamble.count("\n")
                              
                 props.append(PropInfo(name=node.target.id, line=line))
                 
        return props

    except Exception:
        return []


def _get_section(lines: List[str], line_number: int) -> str:
    start_fence, end_fence = _find_fences(lines)

    if start_fence is not None:
        if line_number < start_fence:
            return "directive"
        if line_number == start_fence or (end_fence is not None and line_number == end_fence):
            return "separator"
        if end_fence is not None and start_fence < line_number < end_fence:
            return "python"
        if end_fence is not None and line_number > end_fence:
            return "html"
        # Open fence fallback
        if line_number > start_fence:
            return "python"

    # Fallback / Directives
    line_text = lines[line_number].strip() if line_number < len(lines) else ""
    if (
        line_text.startswith("!")
        or line_text.startswith("#")
    ):
        return "directive"
        
    # If at the very top and empty, assume directive to help with new files
    if line_number == 0 and not line_text:
        return "directive"

    # If no fences, it's HTML unless it's a directive
    return "html"

    # If no fences, it's HTML unless it's a directive
    return "html"


def _validate_path_route(route: str) -> Optional[str]:
    """Return error message if invalid."""
    if not route.startswith("/"):
        return "Path route must be absolute (start with '/')"
    
    # Check segments
    parts = route.split("/")
    for part in parts:
        if not part: continue
        
        # Check for dynamic param
        name = None
        type_nt = "str"
        
        if part.startswith(":"):
            content = part[1:]
            if ":" in content:
                name, type_nt = content.split(":", 1)
            else:
                name = content
        elif part.startswith("{") and part.endswith("}"):
            content = part[1:-1]
            if ":" in content:
                name, type_nt = content.split(":", 1)
            else:
                name = content
        
        if name:
            if not name.isidentifier():
                 return f"Invalid parameter name '{name}'"
            if type_nt not in ("str", "int"):
                 return f"Unsupported parameter type '{type_nt}'. Supported: str, int"
             
    return None


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
            return Hover(contents=MarkupContent(kind="markdown", value=f"**Route pattern**\n\n`{route_value}`"))
        return None

    # Dict entries: 'name': '/route/:id'
    for match in re.finditer(
        r"(['\"])(?P<key>[^'\"]+)\1\s*:\s*(['\"])(?P<val>[^'\"]+)\3", line
    ):
        key_start, key_end = match.start("key"), match.end("key")
        val_start, val_end = match.start("val"), match.end("val")
        if key_start <= position.character <= key_end:
            return Hover(contents=MarkupContent(kind="markdown", value=f"**Route name**\n\n`{match.group('key')}`"))
        if val_start <= position.character <= val_end:
            rel_col = position.character - val_start
            param = _path_param_at(match.group("val"), rel_col)
            if param:
                name, type_hint = param
                type_label = type_hint or "string"
                return Hover(contents=MarkupContent(kind="markdown", value=f"**Path parameter**\n\n`{name}` ({type_label})"))
            return Hover(contents=MarkupContent(kind="markdown", value=f"**Route pattern**\n\n`{match.group('val')}`"))

    return None


def validate(ls: LanguageServer, uri: str):
    """Sends diagnostics for the given URI."""
    doc = documents.get(uri)
    if doc:
        diagnostics: List[Diagnostic] = []
        diagnostics: List[Diagnostic] = []
        lines = doc.lines

        # Validate unknown directives
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("!"):
                # Extract directive name
                match = re.match(r"^(![a-zA-Z0-9_]+)", stripped)
                if match:
                    directive = match.group(1)
                    if directive not in KNOWN_DIRECTIVES:
                        diagnostics.append(
                            Diagnostic(
                                range=Range(
                                    start=Position(line=i, character=stripped.find(directive)),
                                    end=Position(line=i, character=stripped.find(directive) + len(directive)),
                                ),
                                message=f"Unknown directive '{directive}'. Known directives: {', '.join(sorted(KNOWN_DIRECTIVES))}",
                                severity=DiagnosticSeverity.Error,
                            )
                        )

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
                try:
                    expr_ast = ast.parse(routes_text, mode="eval")
                    parsed = _parse_path_routes(routes_text)
                    if parsed is None:
                        # Specific error for structure
                        diagnostics.append(
                            Diagnostic(
                                range=Range(
                                    start=Position(line=i, character=stripped.find("!path") + 5),
                                    end=Position(line=end_idx, character=len(lines[end_idx])),
                                ),
                                message="!path directive expects a string literal or a flat Dict[str, str]",
                                severity=DiagnosticSeverity.Error,
                            )
                        )
                    else:
                        # Validate routes structure and content
                        if isinstance(parsed, str):
                            error = _validate_path_route(parsed)
                            if error:
                                diagnostics.append(
                                    Diagnostic(
                                        range=Range(
                                            start=Position(line=i, character=stripped.find("!path") + 5),
                                            end=Position(line=end_idx, character=len(lines[end_idx])),
                                        ),
                                        message=error,
                                        severity=DiagnosticSeverity.Error,
                                    )
                                )
                        elif isinstance(parsed, dict):
                            for route_path in parsed.values():
                                error = _validate_path_route(route_path)
                                if error:
                                    diagnostics.append(
                                        Diagnostic(
                                            range=Range(
                                                start=Position(line=i, character=stripped.find("!path") + 5),
                                                end=Position(line=end_idx, character=len(lines[end_idx])),
                                            ),
                                            message=f"Invalid route '{route_path}': {error}",
                                            severity=DiagnosticSeverity.Error,
                                        )
                                    )

                except SyntaxError:
                    diagnostics.append(
                        Diagnostic(
                            range=Range(
                                start=Position(line=i, character=stripped.find("!path") + 5),
                                end=Position(line=end_idx, character=len(lines[end_idx])),
                            ),
                            message="Invalid Python syntax in !path directive",
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
                diagnostics.append(
                    Diagnostic(
                        range=Range(
                            start=Position(line=idx, character=stripped.find("!layout") + 7),
                            end=Position(line=idx, character=len(line)),
                        ),
                        message="Layout path must be a string literal (single or double quotes)",
                        severity=DiagnosticSeverity.Error,
                    )
                )
                continue
            start_col, end_col, layout_path = literal
            doc_path = _uri_to_path(uri)
            if not doc_path:
                continue
            base_dir = Path(doc_path).parent
            target = Path(layout_path)
            if not target.is_absolute():
                target = (base_dir / target).resolve()
            if target.suffix != ".wire":
                diagnostics.append(
                    Diagnostic(
                        range=Range(
                            start=Position(line=idx, character=start_col),
                            end=Position(line=idx, character=end_col),
                        ),
                        message="Layout file must have .wire extension",
                        severity=DiagnosticSeverity.Error,
                    )
                )
            elif not target.exists():
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

        # Validate !no_spa
        for idx, line in enumerate(lines):
            stripped = line.strip()
            if not stripped.startswith("!no_spa"):
                continue
            
            # Check if any non-whitespace, non-comment content follows !no_spa
            remainder = stripped[7:].strip()
            if remainder and not remainder.startswith("#"):
                diagnostics.append(
                    Diagnostic(
                        range=Range(
                            start=Position(line=idx, character=stripped.find("!no_spa") + 7),
                            end=Position(line=idx, character=len(line)),
                        ),
                        message="!no_spa directive does not accept arguments",
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

        # Validate Python block (e.g. multiple @props)
        if start_fence is not None and end_fence is not None:
            py_code = "\n".join(lines[start_fence + 1 : end_fence])
            try:
                tree = ast.parse(py_code)
                props_classes = []
                for node in ast.walk(tree):
                    if isinstance(node, ast.ClassDef):
                        is_props = any(
                            (isinstance(dec, ast.Name) and dec.id == "props") or
                            (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Name) and dec.func.id == "props")
                            for dec in node.decorator_list
                        )
                        if is_props:
                            props_classes.append(node)
                
                if len(props_classes) > 1:
                    for i in range(1, len(props_classes)):
                        cls = props_classes[i]
                        diagnostics.append(
                            Diagnostic(
                                range=Range(
                                    start=Position(line=start_fence + cls.lineno, character=0),
                                    end=Position(line=start_fence + cls.lineno, character=len(cls.name) + 6),
                                ),
                                message="Multiple @props classes detected. Only one is allowed per component.",
                                severity=DiagnosticSeverity.Error,
                            )
                        )
            except Exception:
                pass

        # Validate blocks {$if}, {/if}, etc and $attributes
        # Only in HTML section
        html_start = end_fence + 1 if end_fence is not None else 0
        if start_fence is not None and end_fence is None:
            html_start = len(lines) # Skip if python fence unclosed
        
        block_stack = [] # (keyword, line, col)
        
        for idx in range(html_start, len(lines)):
            line = lines[idx]
            
            # 1. Validate unknown $attributes in opening tags
            # Regex for $word not inside {} or quoted attribute value
            # This is complex without a real parser, so we use a simpler approach:
            # Check if we are inside an opening tag
            tag_matches = re.finditer(r'<([a-zA-Z0-9:-]+)', line)
            for tag_match in tag_matches:
                tag_start = tag_match.start()
                # Find end of this tag (simple approach)
                tag_end = line.find('>', tag_start)
                if tag_end == -1:
                    # Multi-line tag, let's scan subsequent lines if needed?
                    # For now just handle single-line tags for $attributes
                    tag_content = line[tag_start:]
                else:
                    tag_content = line[tag_start:tag_end]
                
                # Scan for $attributes
                attr_matches = re.finditer(r'\$([a-zA-Z0-9_-]+)', tag_content)
                for attr_match in attr_matches:
                    attr_name = attr_match.group(1)
                    if attr_name not in KNOWN_ATTRIBUTES:
                        diagnostics.append(
                            Diagnostic(
                                range=Range(
                                    start=Position(line=idx, character=tag_start + attr_match.start()),
                                    end=Position(line=idx, character=tag_start + attr_match.end()),
                                ),
                                message=f"Unknown framework attribute: ${attr_name}",
                                severity=DiagnosticSeverity.Error,
                            )
                        )

            # 2. Validate {$blocks} and {/blocks}
            # Patterns: {$keyword ...} or {/keyword}
            block_pattern = re.finditer(r'\{([$/])([a-zA-Z0-9_-]+)', line)
            for match in block_pattern:
                prefix = match.group(1) # '$' or '/'
                keyword = match.group(2)
                start_col = match.start()
                
                # Find the end of this tag on the same line if possible
                end_col = line.find('}', match.end())
                if end_col != -1:
                    end_col += 1 # Include the trailing }
                else:
                    end_col = match.end()
                
                if prefix == '$':
                    # Opening or continuation
                    if keyword not in KNOWN_BLOCKS:
                        diagnostics.append(
                            Diagnostic(
                                range=Range(
                                    start=Position(line=idx, character=start_col),
                                    end=Position(line=idx, character=end_col),
                                ),
                                message=f"Unknown block keyword: {{${keyword}}}",
                                severity=DiagnosticSeverity.Error,
                            )
                        )
                    elif keyword in BLOCK_OPENERS:
                        block_stack.append((keyword, idx, start_col))
                    elif keyword in BLOCK_CONTINUATIONS:
                        if not block_stack:
                            diagnostics.append(
                                Diagnostic(
                                    range=Range(
                                        start=Position(line=idx, character=start_col),
                                        end=Position(line=idx, character=end_col),
                                    ),
                                    message=f"Block keyword '{{${keyword}}}' must be inside an opening block",
                                    severity=DiagnosticSeverity.Error,
                                )
                            )
                        else:
                            # Check if it matches the current opener? 
                            # e.g. {$elif} inside {$if}
                            parent, _, _ = block_stack[-1]
                            valid_parent = False
                            if keyword in ["elif", "else"] and parent == "if":
                                valid_parent = True
                            elif keyword in ["then", "catch"] and parent == "await":
                                valid_parent = True
                            elif keyword in ["except", "finally"] and parent == "try":
                                valid_parent = True
                            
                            if not valid_parent:
                                diagnostics.append(
                                    Diagnostic(
                                        range=Range(
                                            start=Position(line=idx, character=start_col),
                                            end=Position(line=idx, character=end_col),
                                        ),
                                        message=f"Block keyword '{{${keyword}}}' is not valid inside '{{${parent}}}'",
                                        severity=DiagnosticSeverity.Error,
                                    )
                                )
                else:
                    # Closing {/keyword}
                    if keyword not in BLOCK_CLOSERS:
                        diagnostics.append(
                            Diagnostic(
                                range=Range(
                                    start=Position(line=idx, character=start_col),
                                    end=Position(line=idx, character=end_col),
                                ),
                                message=f"Invalid closing tag: {{/{keyword}}}",
                                severity=DiagnosticSeverity.Error,
                            )
                        )
                    elif not block_stack:
                        diagnostics.append(
                            Diagnostic(
                                range=Range(
                                    start=Position(line=idx, character=start_col),
                                    end=Position(line=idx, character=end_col),
                                ),
                                message=f"Unexpected closing tag: {{/{keyword}}}",
                                severity=DiagnosticSeverity.Error,
                            )
                        )
                    else:
                        top_keyword, _, _ = block_stack.pop()
                        if top_keyword != keyword:
                            diagnostics.append(
                                Diagnostic(
                                    range=Range(
                                        start=Position(line=idx, character=start_col),
                                        end=Position(line=idx, character=end_col),
                                    ),
                                    message=f"Mismatched closing tag: expected {{/{top_keyword}}}, got {{/{keyword}}}",
                                    severity=DiagnosticSeverity.Error,
                                )
                            )

        # Unclosed blocks remaining in stack
        for keyword, line_idx, start_col in block_stack:
            # Re-scan to find full tag range for opener
            line = lines[line_idx]
            match_start = line.find(f'{{${keyword}', start_col)
            if match_start != -1:
                end_idx = line.find('}', match_start)
                end_col = end_idx + 1 if end_idx != -1 else match_start + len(keyword) + 2
            else:
                end_col = start_col + len(keyword) + 2

            diagnostics.append(
                Diagnostic(
                    range=Range(
                        start=Position(line=line_idx, character=start_col),
                        end=Position(line=line_idx, character=end_col),
                    ),
                    message=f"Unclosed block: '{{${keyword}}}' requires a matching '{{/{keyword}}}'",
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
    diagnostics.extend(ty_diagnostics.get(uri, []))
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


def _map_diagnostic(diag: Dict[str, Any], source_map: SourceMap) -> Optional[Diagnostic]:
    """Map a diagnostic from generated .py back to .wire source.
    Uses fuzzy mapping if exact coordinates aren't in the source map.
    """
    if not source_map:
        return None
    diag_range = diag.get("range")
    if not diag_range:
        return None
    start = diag_range.get("start")
    end = diag_range.get("end")
    if not start or not end:
        return None

    line, col = start.get("line", 0), start.get("character", 0)
    mapped_start = source_map.to_original(line, col)
    
    # Fuzzy mapping fallback: Ty often points to end of line or tokens slightly outside mappings
    if not mapped_start:
        # Check nearest mapping on same line
        best = None
        best_dist = 1000
        for m in source_map.mappings:
            if m.generated_line == line:
                dist = abs(col - m.generated_col)
                if dist < best_dist:
                    best_dist = dist
                    # Map to the corresponding offset in original
                    # If col is outside range, clamp to range
                    offset = max(0, min(m.length, col - m.generated_col))
                    best = (m.original_line, m.original_col + offset)
        
        if best:
            mapped_start = best
        else:
            # LOG FAILURE
            # Limit logging to avoid spamming 381 lines, maybe just first few?
            # actually server logs are fine.
            if len(diag.get("message", "")) < 50:
                 logger.warning(f"Failed to map diagnostic at gen {line}:{col} - {diag.get('message')}")
            else:
                 logger.warning(f"Failed to map diagnostic at gen {line}:{col}")

    if not mapped_start:
        return None
        
    mapped_end = source_map.to_original(end.get("line", 0), end.get("character", 0))
    if not mapped_end:
        mapped_end = mapped_start

    mapped_range = Range(
        start=Position(line=mapped_start[0], character=mapped_start[1]),
        end=Position(line=mapped_end[0], character=mapped_end[1]),
    )
    return Diagnostic(
        range=mapped_range,
        message=diag.get("message", ""),
        severity=_coerce_diagnostic_severity(diag.get("severity")),
        source=diag.get("source"),
        code=diag.get("code"),
    )

def _fuzzy_to_original(
    source_map: Any, line: int, col: int
) -> Optional[Tuple[int, int]]:
    mapped = source_map.to_original(line, col)
    if mapped:
        return mapped

    best: Optional[Tuple[int, int]] = None
    best_distance = 10**9
    for mapping in source_map.mappings:
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

def _map_location_to_original(loc: Dict[str, Any]) -> Location:
    """Map a virtual location back to an original .wire location if applicable."""
    if "targetUri" in loc:
        # LocationLink
        loc_uri = loc["targetUri"]
        loc_range = loc["targetSelectionRange"]
    else:
        # Location
        loc_uri = loc.get("uri")
        loc_range = loc.get("range")
    
    if not loc_uri or not loc_range:
         return Location(uri=loc.get("uri", ""), range=Range(start=Position(0,0), end=Position(0,0)))

    # Check if it's a shadow file or stub file
    orig_uri = virtual_manager.get_original_uri(loc_uri) if virtual_manager else None
    target_map = None
    if orig_uri:
        target_map = virtual_manager.get_source_map(loc_uri)
    
    if target_map and orig_uri:
        loc_uri = orig_uri
        start = loc_range["start"]
        end = loc_range.get("end", start)
        
        orig_start = _fuzzy_to_original(target_map, start["line"], start["character"])
        orig_end = _fuzzy_to_original(target_map, end["line"], end["character"])
        
        # Create a copy of the range to modify
        new_range = {
            "start": {"line": 0, "character": 0},
            "end": {"line": 0, "character": 0}
        }
        
        if orig_start:
            new_range["start"] = {"line": orig_start[0], "character": orig_start[1]}
            if orig_end:
                new_range["end"] = {"line": orig_end[0], "character": orig_end[1]}
            else:
                new_range["end"] = {"line": orig_start[0], "character": orig_start[1]}
        
        return Location(
            uri=loc_uri,
            range=Range(
                start=Position(line=new_range["start"]["line"], character=new_range["start"]["character"]),
                end=Position(line=new_range["end"]["line"], character=new_range["end"]["character"]),
            )
        )
    else:
        # Keep original (pure python or standard library)
        return Location(
            uri=loc_uri,
            range=Range(
                start=Position(line=loc_range["start"]["line"], character=loc_range["start"]["character"]),
                end=Position(line=loc_range["end"]["line"], character=loc_range["end"]["character"]),
            )
        )

def _map_edit_to_original(edit: Dict[str, Any], source_map: SourceMap) -> Optional[TextEdit]:
    """Map a virtual text edit back to an original .wire edit."""
    start = edit["range"]["start"]
    end = edit["range"]["end"]
    new_text = edit["newText"]
    
    orig_start = source_map.to_original(start["line"], start["character"])
    orig_end = source_map.to_original(end["line"], end["character"])
    
    if orig_start and orig_end:
        return TextEdit(
            range=Range(
                start=Position(orig_start[0], orig_start[1]),
                end=Position(orig_end[0], orig_end[1])
            ),
            new_text=new_text
        )
    return None


@server.feature("textDocument/didOpen")
def did_open(ls: LanguageServer, params: DidOpenTextDocumentParams):
    """Text document did open notification."""
    uri = params.text_document.uri
    # Validate URI scheme
    if not uri.startswith("file://"):
        return

    doc = PyWireDocument(uri, params.text_document.text)
    documents[uri] = doc

    # Sync with Ty
    if virtual_manager:
        shadow_uri = virtual_manager.get_shadow_uri(uri)
        if shadow_uri:
            virtual_manager.set_source_map(shadow_uri, doc.source_map)

        if ty_client and shadow_uri:
            # We must open the SHADOW file in Ty
            # Construct params
            # We need to send textDocument/didOpen for the shadow file
            try:
                shadow_doc_item = {
                    "uri": shadow_uri,
                    "languageId": "python",
                    "version": params.text_document.version,
                    "text": doc.get_python_source(),
                }
                ty_client.send_notification(
                    "textDocument/didOpen", {"textDocument": shadow_doc_item}
                )

                # Update/Open Stub too
                stub_uri = virtual_manager.get_stub_uri(uri)
                if stub_uri:
                    doc_path = virtual_manager._uri_to_path(uri) or ""
                    stub_content, stub_map = doc.transpiler.generate_stub(doc_path)
                    virtual_manager.set_source_map(stub_uri, stub_map)
                    
                    stub_doc_item = {
                        "uri": stub_uri,
                        "languageId": "python",
                        "version": params.text_document.version,
                        "text": stub_content,
                    }
                    ty_client.send_notification(
                        "textDocument/didOpen", {"textDocument": stub_doc_item}
                    )
            except Exception as e:
                logger.error(f"Failed to notify Ty didOpen/stub: {e}")

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

        # Sync with Ty
        if virtual_manager:
            shadow_uri = virtual_manager.get_shadow_uri(uri)
            if shadow_uri:
                virtual_manager.set_source_map(shadow_uri, doc.source_map)


            if ty_client and shadow_uri:
                try:
                    shadow_change_params = {
                        "textDocument": {
                            "uri": shadow_uri,
                            "version": params.text_document.version,
                        },
                        "contentChanges": [{"text": doc.get_python_source()}],
                    }
                    ty_client.send_notification(
                        "textDocument/didChange", shadow_change_params
                    )

                    # Update Stub too
                    stub_uri = virtual_manager.get_stub_uri(uri)
                    if stub_uri:
                        doc_path = virtual_manager._uri_to_path(uri) or ""
                        stub_content, stub_map = doc.transpiler.generate_stub(doc_path)
                        virtual_manager.set_source_map(stub_uri, stub_map)
                        
                        stub_change_params = {
                            "textDocument": {
                                "uri": stub_uri,
                                "version": params.text_document.version,
                            },
                            "contentChanges": [{"text": stub_content}],
                        }
                        ty_client.send_notification(
                            "textDocument/didChange", stub_change_params
                        )
                except Exception as e:
                    logger.error(f"Failed to notify Ty didChange/stub: {e}")

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
            contents=MarkupContent(
                kind="markdown",
                value="""**!path Directive**

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
        )

    # Check if we are inside <script> or <style>
    if _is_inside_script_or_style(doc.lines, position):
        return None

    # Check for word at cursor to detect directives
    line_text = doc.lines[position.line]
    word = _get_word_at_position(line_text, position.character)
    
    # Direct mapping approach
    gen_pos = doc.map_to_generated(position.line, position.character)

    if gen_pos:
        gen_line, gen_col = gen_pos

        # 1. Try Ty Fallback
        if ty_client and virtual_manager:
            shadow_uri = virtual_manager.get_shadow_uri(uri)
            if shadow_uri:
                try:
                    # Construct params for Ty
                    # We need to translate the position to the shadow file
                    shadow_params = {
                        "textDocument": {"uri": shadow_uri},
                        "position": {"line": gen_line, "character": gen_col},
                    }
                    result = await ty_client.send_request(
                        "textDocument/hover", shadow_params
                    )
                    if result and "contents" in result:
                        contents = result["contents"]


                        # Enhance formatting if plaintext
                        kind = "markdown" 
                        value = ""
                        
                        if isinstance(contents, dict):
                            kind = contents.get("kind", "markdown")
                            value = contents.get("value", "")
                        elif isinstance(contents, str):
                            value = contents

                        # If it looks like a type or signature and is plaintext, perform smart wrapping
                        if kind == "plaintext" and value:
                            lines = value.splitlines()
                            if not lines:
                                return Hover(contents=MarkupContent(kind=kind, value=value))

                            first_line = lines[0].strip()
                            # Heuristic: if first line contains [ ] or -> or is a single word starting with uppercase
                            # Also check for 'def ' prefix which Ty often uses for functions
                            is_signature = (
                                "[" in first_line 
                                or "->" in first_line 
                                or first_line.startswith("def ")
                                or (first_line and first_line[0].isupper() and " " not in first_line)
                            )
                            
                            if is_signature:
                                # Clean up generic type noise like <class 'float'> or <module '...'>
                                # Ty/Pyright sometimes returns these in plaintext signatures
                                if first_line.startswith("<class '") and first_line.endswith("'>"):
                                    first_line = first_line[8:-2]  # Extract inside quotes
                                elif first_line.startswith("<module '") and first_line.endswith("'>"):
                                    first_line = f"module {first_line[9:-2]}" # Extract inside quotes
                                
                                # Wrap the signature in python block
                                new_value = f"```python\n{first_line}\n```"
                                
                                # If there are more lines, append them as markdown (after a separator/newline)
                                if len(lines) > 1:
                                    # Ty often separates signature and docstring with a line of dashes if it's from pydoc?
                                    # Or just newlines.
                                    # Let's inspect the second line.
                                    remaining = lines[1:]
                                    
                                    # Convert remaining plain text to markdown friendly format?
                                    # Just appending it is usually fine for Markdown consumers like VS Code.
                                    # But we might want to ensure a blank line before it.
                                    
                                    # Filter out dash separators if Ty adds them
                                    # Ty often adds a line of dashes between signature and doc
                                    if remaining and set(remaining[0].strip()) == {"-"}:
                                        remaining = remaining[1:]
                                    
                                    # Sometimes there is a second line that is just dashes too?
                                    if remaining and set(remaining[0].strip()) == {"-"}:
                                        remaining = remaining[1:]
                                        
                                    if remaining:
                                        doc_content = "\n".join(remaining).strip()
                                        if doc_content:
                                            new_value += f"\n\n---\n\n{doc_content}"

                                value = new_value
                                kind = "markdown"

                        return Hover(
                            contents=MarkupContent(
                                kind=kind,
                                value=value,
                            )
                        )
                except Exception as e:
                    logger.error(f"Ty hover failed: {e}")

        # Fallback checks (if no mapping or Ty failed)

    # Fallback checks (if no mapping or Jedi failed)

    framework_hovers = {
        "path": "**path**\n\nRoute matcher dict. Keys are route names from `!path`, values are `True` when that route matched.",
        "url": "**url**\n\nURL helper dict. Keys are route names from `!path`, values are URL templates.",
        "params": "**params**\n\nURL path parameters extracted from the matched route.",
        "query": "**query**\n\nQuery string parameters from the URL.",
    }

    if word in framework_hovers:
        return Hover(contents=MarkupContent(kind="markdown", value=framework_hovers[word]))

    # Check for scoped attribute on <style> tag
    if word == "scoped":
        # Check if we're in a <style> tag context
        line_text = doc.lines[position.line] if position.line < len(doc.lines) else ""
        if "<style" in line_text.lower():
            return Hover(
                contents=MarkupContent(
                    kind="markdown",
                    value="""**Scoped Styles**

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
            )

    # Framework specific documentation
    block_hover_docs = {
        "if": "**{$if}** Block\n\nConditional block. Content between `{$if}` and `{/if}` is rendered only when condition is truthy.\n\n```html\n{$if condition}\n  ...\n{/if}\n```",
        "elif": "**{$elif}** Block\n\nElse-if branch within a `{$if}` block.\n\n```html\n{$elif other_condition}\n  ...\n```",
        "else": "**{$else}** Block\n\nFallback branch within a `{$if}` block.\n\n```html\n{$else}\n  ...\n{/if}\n```",
        "for": "**{$for}** Block\n\nLoop block. Repeats content for each item.\n\n```html\n{$for item in items}\n  ...\n{/for}\n```",
        "await": "**{$await}** Block\n\nAsync block. Awaits a coroutine and renders content when resolved.\n\n```html\n{$await async_func()}\n  ...\n{/await}\n```",
        "then": "**{$then}** Block\n\nSuccessful resolution branch for a `{$await}` block.\n\n```html\n{$then result}\n  ...\n```",
        "catch": "**{$catch}** Block\n\nError branch for a `{$await}` block.\n\n```html\n{$catch error}\n  ...\n```",
        "try": "**{$try}** Block\n\nError boundary block.\n\n```html\n{$try}\n  ...\n{$except Exception as e}\n  ...\n{/try}\n```",
        "except": "**{$except}** Block\n\nException handler branch for a `{$try}` block.",
        "finally": "**{$finally}** Block\n\nCleanup branch for a `{$try}` block.",
    }

    attr_hover_docs = {
        "$if": "**$if** Attribute\n\nConditional rendering. Element is excluded from DOM when condition is falsy.\n\nExample: `$if={is_admin}`",
        "$show": "**$show** Attribute\n\nConditional visibility. Element stays in DOM but is hidden via CSS when condition is falsy.\n\nExample: `$show={is_visible}`",
        "$for": "**$for** Attribute\n\nLoop directive. Repeats the element for each item in a collection.\n\n**Syntax:**\n- `$for={item in items}`\n- `$for={index, item in enumerate(items)}`\n- `$for={key, value in dict.items()}`",
        "$key": "**$key** Attribute\n\nStable key for loops. Provides a unique identifier for efficient DOM diffing.\n\nExample: `$key={item.id}`",
        "$ref": "**$ref** Attribute\n\nElement reference. Binds the DOM element to a Python variable in your component.\n\nExample: `$ref={my_element}`",
        "$permanent": "**$permanent** Attribute\n\nPersistent element. Prevents the element from being updated or removed during PJAX navigation or component refreshes.\n\nExample: `$permanent={True}`",
        "$reload": "**$reload** Attribute\n\nReload trigger. Forces the component to re-render when the value of this attribute changes.\n\nExample: `$reload={some_state}`",
    }

    event_hover_docs = {
        "@click": "**@click**\n\nClick event handler. Value can be a function name or Python expression.\n\nExample: `@click={change_name}` or `@click={count += 1}`",
        "@submit": "**@submit**\n\nForm submit event handler.",
        "@change": "**@change**\n\nChange event handler.",
        "@input": "**@input**\n\nInput event handler.",
        "@keydown": "**@keydown**\n\nKeydown event handler.",
        "@keyup": "**@keyup**\n\nKeyup event handler.",
        "@focus": "**@focus**\n\nFocus event handler.",
        "@blur": "**@blur**\n\nBlur event handler.",
    }

    # Determine context (block vs attribute)
    # Check if we are inside {$ ... } or {/ ... }
    # Heuristic: check if character before 'word' is '$' and before that is '{'
    # OR if character before 'word' is ' ' and there is '{$' earlier on the line.
    
    # Let's get more precise: find start of word
    word_start = position.character
    while word_start > 0 and (line_text[word_start-1].isalnum() or line_text[word_start-1] in "@$._"):
        word_start -= 1
        
    is_block = False
    clean_word = word
    if word.startswith("$"):
        clean_word = word[1:]
        if word_start > 0 and line_text[word_start-1] == "{":
            is_block = True
    elif word_start > 1 and line_text[word_start-1] == "/" and line_text[word_start-2] == "{":
        is_block = True

    if is_block:
        if clean_word in block_hover_docs:
            return Hover(contents=MarkupContent(kind="markdown", value=block_hover_docs[clean_word]))
        return None  # Will be a diagnostic error if unknown

    if word in attr_hover_docs:
        return Hover(contents=MarkupContent(kind="markdown", value=attr_hover_docs[word]))

    if word in event_hover_docs:
        return Hover(contents=MarkupContent(kind="markdown", value=event_hover_docs[word]))

    if word.startswith("@"):
        parts = word.split(".")
        if parts[0] in event_hover_docs:
            base = event_hover_docs[parts[0]]
            if len(parts) > 1:
                base += f"\n\n**Modifiers:** {', '.join(parts[1:])}"
            return Hover(contents=MarkupContent(kind="markdown", value=base))
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

    source_map = doc.source_map

    # Check if we are inside <script> or <style>
    if _is_inside_script_or_style(doc.lines, position):
        return None

    if ty_client:
        gen_loc = source_map.to_generated(position.line, position.character)
        if not gen_loc:
            gen_loc = source_map.nearest_generated_on_line(
                position.line, position.character
            )
        if gen_loc:
            gen_line, gen_col = gen_loc
            shadow_uri = virtual_manager.get_shadow_uri(uri)
             
            params = {
                "textDocument": {"uri": shadow_uri},
                "position": {"line": gen_line, "character": gen_col},
                "context": {"includeDeclaration": True}
            }
            
            res = await ty_client.send_request("textDocument/references", params)
            if res:
                 locations = []
                 for loc in res:
                     # Use new consolidated mapping logic
                     locations.append(_map_location_to_original(loc))
                 return locations

    return None


@server.feature("textDocument/rename")
async def rename(ls: LanguageServer, params: RenameParams) -> Optional[WorkspaceEdit]:
    """Provide rename refactoring"""
    uri = params.text_document.uri
    position = params.position
    new_name = params.new_name

    doc = documents.get(uri)
    if not doc:
        return None

    source_map = doc.source_map

    # Check if we are inside <script> or <style>
    if _is_inside_script_or_style(doc.lines, position):
        return None

    if ty_client and virtual_manager:
        shadow_uri = virtual_manager.get_shadow_uri(uri)
        if shadow_uri:
            gen_pos = source_map.to_generated(position.line, position.character)
            if gen_pos:
                gen_line, gen_col = gen_pos
                
                # Ty rename request
                shadow_params = {
                    "textDocument": {"uri": shadow_uri},
                    "position": {"line": gen_line, "character": gen_col},
                    "newName": new_name,
                }

                try:
                    result = await ty_client.send_request("textDocument/rename", shadow_params)
                    if result and "changes" in result:
                        # Map changes back to original files
                        original_changes = {}
                        
                        for gen_uri, edits in result["changes"].items():
                            orig_uri = virtual_manager.get_original_uri(gen_uri)
                            target_map = virtual_manager.get_source_map(gen_uri) if orig_uri else None
                            
                            if orig_uri and target_map:
                                wire_edits = []
                                for edit in edits:
                                    mapped = _map_edit_to_original(edit, target_map)
                                    if mapped:
                                        wire_edits.append(mapped)
                                
                                if wire_edits:
                                    original_changes[orig_uri] = wire_edits
                            else:
                                # External file updates (pure python files)
                                original_changes[gen_uri] = [
                                    TextEdit(
                                        range=Range(
                                            start=Position(e["range"]["start"]["line"], e["range"]["start"]["character"]),
                                            end=Position(e["range"]["end"]["line"], e["range"]["end"]["character"])
                                        ),
                                        new_text=e["newText"]
                                    ) for e in edits
                                ]
                        
                        return WorkspaceEdit(changes=original_changes)

                    # Handle documentChanges if returned instead of changes?
                    # Ty/LSP usually prefers 'changes' for simple edits, but check 'documentChanges'
                    if result and "documentChanges" in result:
                         # Not implemented for now, Ty usually sends changes
                         pass

                except Exception as e:
                    logger.error(f"Ty rename failed: {e}")

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

    # Check if we are inside <script> or <style>
    if _is_inside_script_or_style(doc.lines, position):
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
                    target = (base_dir / layout_path).resolve()

                    if target.exists():
                        return [
                            Location(
                                uri=target.as_uri(),
                                range=Range(
                                    start=Position(line=0, character=0),
                                    end=Position(line=0, character=0),
                                ),
                            )
                        ]



    # 1.5 Custom Component Props
    section = _get_section(doc.lines, position.line)
    line_text = doc.lines[position.line]
    in_tag = _is_inside_opening_tag(line_text, position.character)
    
    if (section == "html" or section == "python") and in_tag:
        # Find tag name
        before_cursor = line_text[:position.character]
        last_open = line_text[:position.character + 1].rfind("<")
        if last_open != -1:
            # Look at content starting from <
            content_after = line_text[last_open+1:]
            match = re.match(r"([a-zA-Z0-9_]+)", content_after)
            if match:
                tag_name = match.group(1)
                
                # Identify attribute under cursor
                word = _get_word_at_position(line_text, position.character)
                
                if word:
                     # Check if it is a prop of the component
                     comps = _get_imported_components(doc)
                     
                     if tag_name in comps:
                         module_path = comps[tag_name]
                         comp_uri = _resolve_import_path(uri, module_path)



                         
                         if comp_uri:
                             props = _extract_props_from_file(comp_uri, tag_name)
                             for p in props:
                                 if p.name == word:
                                     return [Location(
                                         uri=comp_uri,
                                         range=Range(
                                             start=Position(line=p.line, character=0),
                                             end=Position(line=p.line, character=len(p.name))
                                         )
                                     )]
                             
                             if word == tag_name:
                                 # Component definition itself!
                                 return [Location(
                                     uri=comp_uri,
                                     range=Range(
                                         start=Position(line=0, character=0),
                                         end=Position(line=0, character=0)
                                     )
                                 )]

    # Map to virtual python
    gen_pos = doc.map_to_generated(position.line, position.character)
    if not gen_pos:
        gen_pos = doc.source_map.nearest_generated_on_line(
            position.line, position.character
        )
    if not gen_pos:
        return None

    gen_line, gen_col = gen_pos

    if ty_client and virtual_manager:
        shadow_uri = virtual_manager.get_shadow_uri(uri)
        if shadow_uri:
            try:
                shadow_params = {
                    "textDocument": {"uri": shadow_uri},
                    "position": {"line": gen_line, "character": gen_col},
                }

                result = await ty_client.send_request(
                    "textDocument/definition", shadow_params
                )

                if result:
                    # Result is Location | Location[] | LocationLink[] | None
                    # Normalize to list
                    if not isinstance(result, list):
                        result = [result]

                    locations = []
                    for loc in result:
                        locations.append(_map_location_to_original(loc))

                    return locations
            except Exception as e:
                logger.error(f"Ty definition error: {e}")

    return None


def _get_current_block_type(lines: List[str], position: Position) -> Optional[str]:
    """Determine the type of the innermost open block at the given position."""
    start_fence, end_fence = _find_fences(lines)
    html_start = end_fence + 1 if end_fence is not None else 0
    if start_fence is not None and end_fence is None:
        html_start = len(lines)
        
    block_stack = [] # list of (keyword)
    
    for idx in range(html_start, position.line + 1):
        line = lines[idx]
        # Only scan up to cursor on the current line
        if idx == position.line:
            line = line[:position.character]
            
        # Patterns: {$keyword ...} or {/keyword}
        block_pattern = re.finditer(r'\{([$/])([a-zA-Z0-9_-]+)', line)
        for match in block_pattern:
            prefix = match.group(1) # '$' or '/'
            keyword = match.group(2)
            
            if prefix == '$':
                # Opening or continuation
                if keyword in BLOCK_OPENERS:
                    block_stack.append(keyword)
            else:
                # Closing {/keyword}
                if block_stack and block_stack[-1] == keyword:
                    block_stack.pop()
    
    return block_stack[-1] if block_stack else None


def _is_component(file_uri: str, component_name: str) -> bool:
    if file_uri.endswith(".wire"):
        return True
    
    path = _uri_to_path(file_uri)
    if not path or not os.path.exists(path):
        return False
        
    try:
        with open(path, "r") as f:
            source = f.read()
            
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == component_name:
                for dec in node.decorator_list:
                    if isinstance(dec, ast.Name) and dec.id == "component":
                        return True
                    if isinstance(dec, ast.Attribute) and dec.attr == "component":
                        return True
        return False
    except Exception:
        return False


@server.feature("textDocument/completion")
async def completions(ls: LanguageServer, params: CompletionParams) -> CompletionList:
    """Provide completions"""
    uri = params.text_document.uri
    position = params.position

    doc = documents.get(uri)
    if not doc:
        return CompletionList(is_incomplete=False, items=[])

    line_text = doc.lines[position.line] if position.line < len(doc.lines) else ""
    in_tag = _is_inside_opening_tag(line_text, position.character)
    section = _get_section(doc.lines, position.line)

    # Map to virtual python
    gen_pos = doc.map_to_generated(position.line, position.character)
    if not gen_pos:
        gen_pos = doc.source_map.nearest_generated_on_line(
            position.line, position.character
        )

    # 0. Directive Completions
    if section == "directive":
        stripped = line_text.strip()
        
        # Check if we are inside a string literal (e.g. !layout '...')
        literal = _extract_first_string_literal(line_text)
        if literal:
            start_col, end_col, layout_path = literal
            if start_col <= position.character <= end_col:
                if stripped.startswith("!layout"):
                    # JS-import style path completion
                    rel_to_cursor = line_text[start_col:position.character]
                    
                    doc_path = _uri_to_path(uri)
                    if not doc_path:
                        return CompletionList(is_incomplete=False, items=[])
                    
                    base_dir = Path(doc_path).parent
                    
                    # Split into directory part and partial filename
                    if "/" in rel_to_cursor:
                        dir_part, partial = rel_to_cursor.rsplit("/", 1)
                        # Use resolve() to handle . and .. correctly
                        try:
                            search_dir = (base_dir / dir_part).resolve()
                        except:
                            search_dir = (base_dir / dir_part)
                    else:
                        dir_part = ""
                        partial = rel_to_cursor
                        search_dir = base_dir
                    
                    items = []
                    if search_dir.exists() and search_dir.is_dir():
                        try:
                            for entry in search_dir.iterdir():
                                if entry.name.startswith(partial):
                                    if entry.is_dir():
                                        items.append(CompletionItem(
                                            label=entry.name + "/",
                                            kind=CompletionItemKind.Folder,
                                            insert_text=entry.name + "/",
                                            command=Command(title="Suggest", command="editor.action.triggerSuggest")
                                        ))
                                    elif entry.suffix == ".wire":
                                        items.append(CompletionItem(
                                            label=entry.name,
                                            kind=CompletionItemKind.File,
                                            insert_text=entry.name
                                        ))
                        except Exception as e:
                            logger.error(f"Error listing directory {search_dir}: {e}")
                    
                    return CompletionList(is_incomplete=False, items=items)

        # General directive suggestions (!layout, !path, etc.)
        if stripped.startswith("!") or not stripped:
             items = [
                 CompletionItem(label="!layout", kind=CompletionItemKind.Keyword, insert_text="!layout '${1:path}.wire'", insert_text_format=InsertTextFormat.Snippet, detail="Layout directive"),
                 CompletionItem(label="!path", kind=CompletionItemKind.Keyword, insert_text="!path '${1:/route}'", insert_text_format=InsertTextFormat.Snippet, detail="Path route directive"),
                 CompletionItem(label="!no_spa", kind=CompletionItemKind.Keyword, insert_text="!no_spa", detail="Disable SPA navigation for this page"),
             ]
             # Filter if user already typed prefix
             if stripped:
                 matched = [item for item in items if item.label.startswith(stripped)]
                 if matched:
                     return CompletionList(is_incomplete=False, items=matched)
             else:
                 return CompletionList(is_incomplete=False, items=items)

        if stripped.startswith("!layout"):
            # Fallback: if not in literal or literal not found, maybe show root files if just "!layout "
            items = []
            if virtual_manager and virtual_manager.root_path:
                root = Path(virtual_manager.root_path)
                doc_path = _uri_to_path(uri)
                if doc_path:
                    base_dir = Path(doc_path).parent
                    # Find all .wire files in root
                    # Limit to 50 for performance
                    count = 0
                    for p in root.rglob("*.wire"):
                        if count > 50: break
                        if str(p) == doc_path: continue
                        
                        try:
                            rel = os.path.relpath(p, base_dir)
                            # Prefix with ./ if not starting with . or /
                            if not rel.startswith("."):
                                rel = "./" + rel
                            
                            items.append(CompletionItem(
                                label=rel,
                                kind=CompletionItemKind.File,
                                insert_text=f"'{rel}'" if "'" not in line_text and "\"" not in line_text else rel
                            ))
                            count += 1
                        except ValueError:
                            continue
            return CompletionList(is_incomplete=False, items=items)

        if stripped.startswith("!path"):
             return CompletionList(is_incomplete=False, items=[
                 CompletionItem(
                     label="Dictionary route",
                     kind=CompletionItemKind.Snippet,
                     insert_text="{\n    '${1:name}': '${2:/route}'\n}",
                     insert_text_format=InsertTextFormat.Snippet
                 ),
                 CompletionItem(
                     label="String route",
                     kind=CompletionItemKind.Snippet,
                     insert_text="'${1:/route}'",
                     insert_text_format=InsertTextFormat.Snippet
                 )
             ])
        
        return CompletionList(is_incomplete=False, items=[])

    # 1. Try Ty Completion first if in Python section, inside {$ ... } or inside attribute ={ ... }
    # Suppress Ty leakage in HTML tag/attribute context
    before_cursor = line_text[: position.character]
    last_open_block = before_cursor.rfind("{$")
    last_open_attr = before_cursor.rfind("={")
    last_close = before_cursor.rfind("}")
    
    inside_expr = (last_open_block > last_close) or (last_open_attr > last_close)
    
    if (section == "python" or inside_expr) and gen_pos and ty_client and virtual_manager:
        shadow_uri = virtual_manager.get_shadow_uri(uri)
        if shadow_uri:
            gen_line, gen_col = gen_pos
            try:
                shadow_params = {
                    "textDocument": {"uri": shadow_uri},
                    "position": {"line": gen_line, "character": gen_col},
                    "context": attrs.asdict(params.context) if params.context else {"triggerKind": 1},
                }
                
                # ... (rest of delegation logic)

                # Ensure triggerKind is present (Ty requires it)
                if not shadow_params["context"].get("triggerKind"):
                    shadow_params["context"]["triggerKind"] = 1

                result = await ty_client.send_request(
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

                    if items:
                         # Find python block range for import insertion
                         py_start, py_end = _find_fences(doc.lines)
                         
                         comp_items = []
                         for item in items:
                             text_edits = []
                             
                             # Handle additionalTextEdits (e.g. auto-imports)
                             raw_edits = item.get("additionalTextEdits")
                             if raw_edits:
                                 for edit in raw_edits:
                                     # Heuristic: if edit is at the top of the file (lines 0-5), it's likely an import
                                     # or if text starts with "import"/"from"
                                     # Note: items from Ty via pygls might be dicts or objects depending on how they are deserialized
                                     # pygls 1.3+ usually deserializes to object if we use type hints
                                     
                                     if isinstance(edit, dict):
                                         start_line = edit["range"]["start"]["line"]
                                         start_char = edit["range"]["start"]["character"]
                                         end_line = edit["range"]["end"]["line"]
                                         end_char = edit["range"]["end"]["character"]
                                         new_text = edit["newText"]
                                     else:
                                         start_line = edit.range.start.line
                                         start_char = edit.range.start.character
                                         end_line = edit.range.end.line
                                         end_char = edit.range.end.character
                                         new_text = edit.new_text
                                     
                                     is_import = start_line < 10 or new_text.strip().startswith(("import ", "from "))
                                     
                                     if is_import:
                                         if py_start is not None:
                                             # Map to top of existing python block
                                             # Insert at py_start + 1
                                             target_line = py_start + 1
                                             final_text = new_text
                                         else:
                                             # No python block exists. Create one after directives.
                                             target_line = _scan_directives_end(doc.lines, len(doc.lines))
                                             # Ensure we have newlines around if needed
                                             # If we are inserting into a blank line, maybe just fences
                                             # Simple approach:
                                             final_text = f"\n---\n{new_text.strip()}\n---\n"
                                             
                                         text_edits.append(TextEdit(
                                             range=Range(
                                                 start=Position(line=target_line, character=0),
                                                 end=Position(line=target_line, character=0)
                                             ),
                                             new_text=final_text
                                         ))
                                     else:
                                         # Try to map normal edits
                                         # e.g. refactorings?
                                         # For now, simplistic mapping or ignore if not mapable
                                         m_start = doc.map_to_original(start_line, start_char)
                                         m_end = doc.map_to_original(end_line, end_char)
                                         
                                         if m_start and m_end:
                                             text_edits.append(TextEdit(
                                                 range=Range(
                                                     start=Position(line=m_start[0], character=m_start[1]),
                                                     end=Position(line=m_end[0], character=m_end[1])
                                                 ),
                                                 new_text=new_text
                                             ))

                             new_item = CompletionItem(
                                 label=item.get("label"),
                                 kind=item.get("kind"),
                                 detail=item.get("detail"),
                                 documentation=item.get("documentation"),
                                 sort_text=item.get("sortText"),
                                 filter_text=item.get("filterText"),
                                 insert_text=item.get("insertText"),
                                 additional_text_edits=text_edits if text_edits else None,
                             )
                             comp_items.append(new_item)

                         return CompletionList(
                             is_incomplete=is_incomplete, items=comp_items
                         )

            except Exception as e:
                logger.error(f"Ty completion failed: {e}")

    section = _get_section(doc.lines, position.line)

    # 1.5 Component & Prop Logic
    if section == "html":
        # A) Component Completion (trigger < or <PartialName)
        # We trigger component completion if we are right after < or typing a TagName without space
        tag_match = re.search(r"<([a-zA-Z0-9_-]*)$", before_cursor)
        if tag_match:
            prefix = tag_match.group(1)
            comps = _get_imported_components(doc)
            items = []
            for name in comps:
                if not prefix or name.lower().startswith(prefix.lower()):
                    items.append(CompletionItem(
                        label=name,
                        kind=CompletionItemKind.Class,
                        detail="Imported Component"
                    ))
            if items:
                return CompletionList(is_incomplete=False, items=items)

        if in_tag:
            # Find which tag we are in: e.g. <TagName ... |
            # Search backwards for <
            last_open = before_cursor.rfind("<")
            if last_open != -1:
                content_after = before_cursor[last_open+1:]

                # Extract first word as tag name
                match = re.match(r"([a-zA-Z0-9_]+)", content_after)
                
                prop_items = []
                if match:
                    tag_name = match.group(1)
                    
                    # Check if we are past the tag name (whitespace check)
                    # length of tag_name vs content_after
                    # partial usage of prop completion while typing name is handled by A) above usually
                    # but if we have `<MyComponent` (no space), match is MyComponent.
                    # We only want props if we have space.
                    if len(content_after) > len(tag_name):
                        # There is something after tag name (likely space)
                        
                        # Check if it's an imported component
                        comps = _get_imported_components(doc)
                        
                        if tag_name in comps:
                            # It is a component!
                            module_path = comps[tag_name]
                            comp_uri = _resolve_import_path(uri, module_path)

                            if comp_uri:
                                props = _extract_props_from_file(comp_uri, tag_name)
                                for p in props:
                                    snippet = f"{p.name}=${{1}}"
                                    prop_items.append(CompletionItem(
                                        label=p.name,
                                        kind=CompletionItemKind.Property,
                                        detail=f"Prop (line {p.line+1})",
                                        documentation=p.doc,
                                        insert_text=snippet,
                                        insert_text_format=InsertTextFormat.Snippet,
                                        sort_text=f"0_{p.name}"
                                    ))
                        
                        # Now add framework attributes
                        
                        # Get prefix for filtering
                        prefix_match = re.search(r"[@$][\w.]*$", before_cursor)
                        prefix = prefix_match.group(0) if prefix_match else ""
                        
                        # Standard framework attributes
                        attr_suggestions = [
                           ("$if", "\\$if={${1:condition}}", "Conditional rendering."),
                           ("$show", "\\$show={${1:condition}}", "Conditional visibility."),
                           ("$for", "\\$for={${1:item} in ${2:items}} \\$key={${1:item}.${3:id}}", "Loop directive."),
                           ("$key", "\\$key={${1:item.id}}", "Stable key for loops."),
                           ("$ref", "\\$ref={${1:my_ref}}", "Element reference."),
                           ("$permanent", "\\$permanent", "Persistent element."),
                           ("$reload", "\\$reload", "Reload trigger."),
                        ]
                        
                        framework_items = []
                        replace_range_local = None
                        if prefix:
                             p_start = position.character - len(prefix)
                             replace_range_local = Range(
                                 start=Position(line=position.line, character=p_start),
                                 end=position
                             )
                             
                        for label, snippet, doc_text in attr_suggestions:
                           if label.startswith(prefix) or not prefix:
                               framework_items.append(CompletionItem(
                                   label=label,
                                   kind=CompletionItemKind.Keyword,
                                   documentation=doc_text,
                                   insert_text=snippet,
                                   insert_text_format=InsertTextFormat.Snippet,
                                   text_edit=TextEdit(range=replace_range_local, new_text=snippet) if replace_range_local else None,
                                   sort_text=f"1_{label}"
                               ))
                               
                        event_labels = ["@click", "@submit", "@change", "@input", "@keydown", "@keyup", "@focus", "@blur"]
                        for ev in event_labels:
                           if ev.startswith(prefix) or not prefix:
                               snippet = f"{ev}={{$1}}"
                               framework_items.append(CompletionItem(
                                   label=ev,
                                   kind=CompletionItemKind.Event,
                                   insert_text=snippet,
                                   insert_text_format=InsertTextFormat.Snippet,
                                   text_edit=TextEdit(range=replace_range_local, new_text=snippet) if replace_range_local else None,
                                   sort_text=f"1_{ev}"
                               ))

                        # Combine: Props first!
                        all_items = prop_items + framework_items
                        return CompletionList(is_incomplete=False, items=all_items)



    # Suggest control flow tags if prefix is {$ or on empty HTML line
    before_cursor = line_text[: position.character]
    stripped_before = before_cursor.strip()
    
    # Get the prefix to filter suggestions
    prefix_match = re.search(r"[@$][\w.]*$", before_cursor)
    prefix_block_match = re.search(r"\{\$([\w]*)$", before_cursor)
    
    prefix = prefix_match.group(0) if prefix_match else ""
    block_prefix = prefix_block_match.group(1) if prefix_block_match else None
    
    # Define prefix range for replacement
    if prefix:
        p_start = position.character - len(prefix)
        replace_range = Range(
            start=Position(line=position.line, character=p_start),
            end=position
        )
    elif block_prefix is not None:
        # Range includes the {$
        p_start = position.character - len(block_prefix) - 2
        replace_range = Range(
            start=Position(line=position.line, character=p_start),
            end=position
        )
    else:
        replace_range = None

    current_block = _get_current_block_type(doc.lines, position)

    # Check if we are on an empty-ish line in HTML section
    if section == "html" and not in_tag and not stripped_before and block_prefix is None:
        # Suggest block snippets
        items = [
            CompletionItem(
                label="{$if}",
                kind=CompletionItemKind.Snippet,
                detail="PyWire if block",
                insert_text="{\\$if ${1:condition}}\n\t$0\n{/if}",
                insert_text_format=InsertTextFormat.Snippet,
                sort_text="00_if"
            ),
            CompletionItem(
                label="{$for}",
                kind=CompletionItemKind.Snippet,
                detail="PyWire for block",
                insert_text="{\\$for ${1:item} in ${2:items}, key=${3:item.id}}\n\t$0\n{/for}",
                insert_text_format=InsertTextFormat.Snippet,
                sort_text="01_for"
            ),
            CompletionItem(
                label="{$await}",
                kind=CompletionItemKind.Snippet,
                detail="PyWire await block",
                insert_text="{\\$await ${1:deferred}}\n\t<p>Loading...</p>\n{\\$then ${2:result}}\n\t$0\n{\\$catch ${3:error}}\n\t<p>Error: {${3:error}}</p>\n{/await}",
                insert_text_format=InsertTextFormat.Snippet,
                sort_text="02_await"
            ),
            CompletionItem(
                label="{$try}",
                kind=CompletionItemKind.Snippet,
                detail="PyWire try block",
                insert_text="{\\$try}\n\t$1\n{\\$except ${2:Exception} as ${3:e}}\n\t$0\n{/try}",
                insert_text_format=InsertTextFormat.Snippet,
                sort_text="03_try"
            ),
        ]
        
        # Add context-specific continuations
        if current_block == "if":
            items.insert(0, CompletionItem(
                label="{$elif}",
                kind=CompletionItemKind.Snippet,
                insert_text="{\\$elif ${1:other_condition}}",
                insert_text_format=InsertTextFormat.Snippet,
                sort_text="00_elif"
            ))
            items.insert(1, CompletionItem(
                label="{$else}",
                kind=CompletionItemKind.Snippet,
                insert_text="{\\$else}",
                insert_text_format=InsertTextFormat.Snippet,
                sort_text="00_else"
            ))
        elif current_block == "await":
            items.insert(0, CompletionItem(label="{$then}", kind=CompletionItemKind.Snippet, insert_text="{\\$then ${1:result}}", insert_text_format=InsertTextFormat.Snippet, sort_text="00_then"))
            items.insert(1, CompletionItem(label="{$catch}", kind=CompletionItemKind.Snippet, insert_text="{\\$catch ${1:error}}", insert_text_format=InsertTextFormat.Snippet, sort_text="00_catch"))
        
        return CompletionList(is_incomplete=False, items=items)

    if block_prefix is not None:
        tags = KNOWN_BLOCKS
        items = []
        for tag in tags:
            if tag.startswith(block_prefix.lower()):
                # Determine precedence
                priority = "zz"
                if current_block == "if" and tag in ["elif", "else"]: priority = "aa"
                elif current_block == "await" and tag in ["then", "catch"]: priority = "aa"
                elif current_block == "try" and tag in ["except", "finally", "else"]: priority = "aa"
                
                # Check if it's a closer
                if current_block == tag: priority = "ab" # Close current block

                items.append(
                    CompletionItem(
                        label=tag,
                        kind=CompletionItemKind.Keyword,
                        detail=f"PyWire control flow tag: {{${tag}}}",
                        insert_text=tag,
                        sort_text=f"{priority}_{tag}",
                        text_edit=TextEdit(range=replace_range, new_text=f"{{${tag}}}") if replace_range else None
                    )
                )
        
        # Add a {/closer} option
        if current_block and current_block.startswith(block_prefix.lower()):
            items.append(
                CompletionItem(
                    label=f"{{/{current_block}}}",
                    kind=CompletionItemKind.Keyword,
                    insert_text=f"{{/{current_block}}}",
                    sort_text=f"00_close",
                    text_edit=TextEdit(range=replace_range, new_text=f"{{/{current_block}}}") if replace_range else None
                )
            )

        if items:
            return CompletionList(is_incomplete=False, items=items)

    # Only suggest directives and event handlers when inside an opening tag
    if not in_tag:
        return CompletionList(is_incomplete=False, items=[])

    # Suppress defaults if inside a {$ block within an attribute
    last_open = before_cursor.rfind("{$")
    last_close = before_cursor.rfind("}")
    if last_open > last_close:
        return CompletionList(is_incomplete=False, items=[])

    # Check if we are inside <script> or <style>
    if _is_inside_script_or_style(doc.lines, position):
        return CompletionList(is_incomplete=False, items=[])

    # Get the prefix to filter suggestions
    before_cursor = line_text[: position.character]
    prefix_match = re.search(r"[@$][\w.]*$", before_cursor)
    prefix = prefix_match.group(0) if prefix_match else ""

    # Suggest attributes
    if prefix.startswith("$") or (not prefix and in_tag):
        # Escape the leading $ as \$ to prevent TextMate from treating it as a variable
        attr_suggestions = [
            ("$if", "\\$if={${1:condition}}", "Conditional rendering."),
            ("$show", "\\$show={${1:condition}}", "Conditional visibility."),
            ("$for", "\\$for={${1:item} in ${2:items}} \\$key={${1:item}.${3:id}}", "Loop directive."),
            ("$key", "\\$key={${1:item.id}}", "Stable key for loops."),
            ("$ref", "\\$ref={${1:my_ref}}", "Element reference."),
            ("$permanent", "\\$permanent", "Persistent element."),
            ("$reload", "\\$reload", "Reload trigger."),
        ]
        
        items = []
        for label, snippet, doc_text in attr_suggestions:
            if label.startswith(prefix) or not prefix:
                items.append(
                    CompletionItem(
                        label=label,
                        kind=CompletionItemKind.Keyword,
                        documentation=doc_text,
                        insert_text=snippet,
                        insert_text_format=InsertTextFormat.Snippet,
                        # If we have a prefix like "$", and we want to replace it with "$if={...}",
                        # The range must cover "$".
                        text_edit=TextEdit(range=replace_range, new_text=snippet) if replace_range else None
                    )
                )
        
        # Add event handlers
        event_labels = ["@click", "@submit", "@change", "@input", "@keydown", "@keyup", "@focus", "@blur"]
        for ev in event_labels:
            if ev.startswith(prefix) or not prefix:
                snippet = f"{ev}={{$1}}"
                items.append(
                    CompletionItem(
                        label=ev,
                        kind=CompletionItemKind.Event,
                        insert_text=snippet,
                        insert_text_format=InsertTextFormat.Snippet,
                        text_edit=TextEdit(range=replace_range, new_text=snippet) if replace_range else None
                    )
                )
        
        return CompletionList(is_incomplete=False, items=items)

    return CompletionList(is_incomplete=False, items=[])


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
