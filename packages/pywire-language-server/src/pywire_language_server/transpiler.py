import re
from typing import List, Tuple, Dict, Any, Optional
from .sourcemap import SourceMap

class Transpiler:
    def __init__(self, source: str):
        self.source = source
        self.lines = source.splitlines(keepends=True)
        self.generated_code: List[str] = []
        self.source_map = SourceMap(source, "")
        self.directive_ranges: Dict[str, Tuple[int, int]] = {}
        
        self.current_line_idx = 0
        self.generated_line_idx = 0 # 0-indexed

    def transpile(self) -> Tuple[str, SourceMap]:
        """Convert .wire source to virtual .py source with source map."""
        
        separator_idx = self._find_separator()
        limit = separator_idx if separator_idx is not None else len(self.lines)

        # Implicit Import
        self.generated_code.append("from pywire import wire\n")
        self.generated_line_idx += 1

        # --- Phase 1: Python Section (Definitions) ---
        if separator_idx is not None:
             python_source_lines = self.lines[separator_idx + 1:]
             
             # Process each line for syntax rewriting ($var -> var.value)
             for i, line in enumerate(python_source_lines):
                 orig_line_idx = separator_idx + 1 + i
                 self._emit_python_line_with_rewrites(line, orig_line_idx)
            
             # Spacer to separate definitions from expressions
             self.generated_code.append("\n# --- HTML Expressions ---\n")
             self.generated_line_idx += 2

        # --- Phase 2: HTML Section (Expressions) ---
        i = 0
        while i < limit:
            line = self.lines[i]
            stripped = line.strip()
            
            if not stripped:
                 i += 1
                 continue
                
            if stripped.startswith("!path"):
                start = i
                i = self._handle_path_directive(i)
                self.directive_ranges["path"] = (start, i - 1)
            elif stripped.startswith("!layout"):
                i += 1
            elif stripped.startswith("!"):
                i += 1
            else:
                # HTML line
                i = self._process_html_section(i, limit)
        
        full_code = "".join(self.generated_code)
        self.source_map.generated_source = full_code
        return full_code, self.source_map

    def _emit_python_line_with_rewrites(self, line: str, orig_line_idx: int):
        """Emit a python line, replacing $var with var.value and correcting the source map."""
        # Use helper starting at col 0
        stripline = line.rstrip('\r\n')
        text = self._emit_rewritten_segment(stripline, orig_line_idx, 0, self.generated_line_idx, 0)
        self.generated_code.append(text + "\n")
        self.generated_line_idx += 1

    def _emit_rewritten_segment(self, text: str, orig_line: int, orig_col: int, gen_line: int, start_gen_col: int) -> str:
        """
        Rewrites $var -> var.value in text, adding mappings.
        Returns the rewritten text string.
        """
        # Split but keep delimiters ($var)
        parts = re.split(r'(\$[a-zA-Z_]\w*)', text)
        current_gen_col = start_gen_col
        current_orig_col = orig_col
        
        rewritten_parts = []
        
        for part in parts:
            if not part:
                continue
            
            if part.startswith("$"):
                # Rewrite: $count -> count.value
                var_name = part[1:]
                
                # 1. Map 'count' -> 'count'
                # Orig: $count (starts at current_orig_col). 'count' starts at +1.
                # Gen: count (starts at current_gen_col).
                rewritten_parts.append(var_name)
                self.source_map.add_mapping(
                    gen_line=gen_line, gen_col=current_gen_col,
                    orig_line=orig_line, orig_col=current_orig_col + 1, # Skip $
                    length=len(var_name)
                )
                current_gen_col += len(var_name)
                
                # 2. Append '.value' (Unmapped)
                # This ensures the length in generated code > original code doesn't confuse the map
                suffix = ".value"
                rewritten_parts.append(suffix)
                current_gen_col += len(suffix)
                
                # Original consumed length is len("$count")
                current_orig_col += len(part)
            else:
                # Text -> Text
                rewritten_parts.append(part)
                self.source_map.add_mapping(
                    gen_line=gen_line, gen_col=current_gen_col,
                    orig_line=orig_line, orig_col=current_orig_col,
                    length=len(part)
                )
                current_gen_col += len(part)
                current_orig_col += len(part)
                
        return "".join(rewritten_parts)

    def _find_separator(self) -> Optional[int]:
        for i, line in enumerate(self.lines):
             if line.strip() == '---':
                 return i
        return None

    def _emit_empty_line(self):
        self.generated_code.append("\n")
        self.generated_line_idx += 1

    def _emit_comment(self, text: str):
        self.generated_code.append(f"# {text.strip()[:50]}...\n")
        self.generated_line_idx += 1

    def _handle_path_directive(self, start_idx: int) -> int:
        line = self.lines[start_idx]
        
        # Check if it opens a brace
        if "{" in line and "}" not in line:
            # Multi-line directive
            # Consume until we find closing brace
            current_idx = start_idx
            content_accum = []
            
            while current_idx < len(self.lines):
                l = self.lines[current_idx]
                content_accum.append(l)
                if "}" in l:
                    break
                current_idx += 1
            
            # Now we have the full block.
            # We want to emit: __path = { ... }
            # Mapping is tricky for multi-line. We map line-by-line.
            
            full_text = "".join(content_accum)
            match = re.search(r"!path\s*({.*})", full_text, re.DOTALL)
            if match:
                 # It's a dict.
                 # We emit "__path = <content>"
                 # To preserve mapping we should emit each line of the content.
                 self.generated_code.append("__path = ")
                 # We'll map the FIRST line's `{` part.
                 
                 # Simpler strategy: Just dump the lines as is, but prefix the first one?
                 # "!path {" -> "__path = {"
                 # " 'foo': 'bar'" -> " 'foo': 'bar'"
                 # "}" -> "}"
                 
                 # First line replacement:
                 l0 = content_accum[0]
                 l0_fixed = l0.replace("!path", "", 1).lstrip()
                 # If l0 was "!path {", l0_fixed is "{".
                 # We append "__path = " + l0_fixed
                 self.generated_code.append("__path = " + l0_fixed)
                 
                 # Map it roughly? For now let's just dump it.
                 # Ideally we map "path" to the "!path" keyword location?
                 self.generated_line_idx += 1
                 
                 for i in range(1, len(content_accum)):
                     self.generated_code.append(content_accum[i])
                     self.generated_line_idx += 1
                 
                 return current_idx + 1
            
            return current_idx + 1
        else:
            # Single line
            self.generated_code.append("__path = " + line.replace("!path", "", 1).strip() + "\n")
            self.generated_line_idx += 1
            return start_idx + 1

    def _process_html_section(self, start_idx: int, safe_limit: int) -> int:
        """Process one or more lines of HTML, extracting interpolations."""
        
        # We need to scan potentially across lines if a brace is open.
        current_idx = start_idx
        
        # State
        balance = 0
        in_quote = None
        interpolation_start: Optional[Tuple[int, int]] = None # (line_idx, char_idx)
        
        # To handle context wrappers ($if=...), we need to look backwards from the opening brace.
        # But spanning lines makes "looking back" hard if the directive attribute name is on previous line.
        # Example: <div \n $if={...}> is fine.
        # Example: <div $if \n ={...}> -- HTML allows spaces around =.
        
        # Parsing full HTML carefully is hard.
        # Simplified approach: Tokenize the stream of characters starting from start_idx.
        
        while current_idx < safe_limit:
            line = self.lines[current_idx]
            i = 0
            while i < len(line):
                char = line[i]
                
                if in_quote:
                    if char == in_quote:
                        if i > 0 and line[i-1] != '\\':
                            in_quote = None
                else:
                    if char in ('"', "'"):
                        if balance > 0:
                            # We are inside Python. Quotes matter.
                            in_quote = char
                        else:
                            # We are in HTML. " doesn't stop us from finding {
                            pass
                            
                    elif char == '{':
                        if balance == 0:
                            interpolation_start = (current_idx, i)
                        balance += 1
                    elif char == '}':
                        if balance > 0:
                            balance -= 1
                            if balance == 0:
                                # Found end of interpolation!
                                start_line, start_col = interpolation_start
                                end_line, end_col = current_idx, i
                                
                                self._emit_interpolation(start_line, start_col, end_line, end_col)
                                interpolation_start = None
                
                i += 1
            
            # End of line
            if balance > 0:
                # Continue to next line
                current_idx += 1
            else:
                return current_idx + 1
        
        return current_idx

    def _emit_interpolation(self, start_line: int, start_col: int, end_line: int, end_col: int):
        # Detect Context
        # We look at the text immediately preceding the start brace
        preceding_text = self.lines[start_line][:start_col]
        # We want to find `word=`
        match = re.search(r'([@$][\w\.]+|[\w\-]+)\s*=$', preceding_text.rstrip())
        
        prefix = ""
        suffix = ""
        
        if match:
            attr_name = match.group(1)
            if attr_name.startswith("$if") or attr_name.startswith("$show"):
                prefix = "if ("
                suffix = "): pass"
            elif attr_name.startswith("$for"):
                prefix = "for "
                suffix = ": pass"
            elif attr_name.startswith("@"):
                 # Event handler
                 # @click={foo} -> def __handler(): (foo)
                 prefix = "def __handler(): ("
                 suffix = ")"
        
        # Emit prefix
        # We don't append yet, we combine with content
        current_gen_col = len(prefix)
        
        # Emit Content with Rewrites
        if start_line == end_line:
            # Single line content
            content = self.lines[start_line][start_col+1:end_col]
            rewritten_content = self._emit_rewritten_segment(
                content, 
                start_line, 
                start_col + 1, 
                self.generated_line_idx, 
                current_gen_col
            )
            self.generated_code.append(prefix + rewritten_content + suffix + "\n")
            self.generated_line_idx += 1
        else:
            # Multi-line
            # Do best effort: Join lines and rewrite?
            # Or iterate?
            # Iterating is hard because _emit_rewritten_segment assumes one gen_line.
            # If we align lines, we can emit newlines.
            
            # Line 1
            l1_cont = self.lines[start_line][start_col+1:] # includes \n
            # We strip the \n for rewrite, then add it back?
            # Or just rewrite. rewrite splits by $var. \n is text.
            
            current_gen_col = self._emit_rewritten_segment(
                l1_cont, 
                start_line, 
                start_col + 1, 
                self.generated_line_idx, 
                current_gen_col
            )
            # l1_cont included \n, so rewritten segment included \n.
            # But wait, generated_line_idx only increments explicitly.
            # generated_code is list of fragments.
            # If l1_cont has \n, it is inside the fragment.
            # SourceMap needs explicit line increment?
            # SourceMap `gen_line` remains same.
            
            # Currently SourceMap implementation assumes line numbers are handled by caller.
            # `generated_line_idx` tracks "current line in generated file".
            # If I emit \n in text, I must increment `generated_line_idx`.
            
            # _emit_rewritten_segment does NOT increment generated_line_idx.
            # It just appends fragments.
            
            # If l1_cont has \n, the generated code has \n.
            # So next chars are effectively on next line.
            # But I passed `gen_line=self.generated_line_idx` to all mappings in that segment!
            # So if I map line 2's content using line 1's index... mapping is broken.
            
            # FIX: Iterate manually.
            
            # But for now, to support basic single-line fix, I will rely on single line path.
            # Multi-line interpolation support in PyWire is rare/discouraged anyway?
            # Or I can fix it now.
            
            # Correct logic:
            # For multi-line, we must process per-line to keep line mapping sane.
            # Line 1
            l1 = self.lines[start_line][start_col+1:].rstrip('\r\n')
            rewritten_l1 = self._emit_rewritten_segment(l1, start_line, start_col+1, self.generated_line_idx, current_gen_col)
            
            # Append prefix + l1 + \n
            # Note: prefix is only added to the first line
            self.generated_code.append(prefix + rewritten_l1 + "\n")
            self.generated_line_idx += 1
            current_gen_col = 0
            
            # Middle lines
            for l_idx in range(start_line + 1, end_line):
                l_text = self.lines[l_idx].rstrip('\r\n')
                rewritten_text = self._emit_rewritten_segment(l_text, l_idx, 0, self.generated_line_idx, 0)
                self.generated_code.append(rewritten_text + "\n")
                self.generated_line_idx += 1
                
            # Last line
            l_last = self.lines[end_line][:end_col]
            rewritten_last = self._emit_rewritten_segment(l_last, end_line, 0, self.generated_line_idx, 0)
            
            # Append last line + suffix + \n
            self.generated_code.append(rewritten_last + suffix + "\n")
            self.generated_line_idx += 1
