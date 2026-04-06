from dataclasses import dataclass
from typing import List, Optional, Tuple


@dataclass
class Mapping:
    """Represents a mapping from a range in the compiled file to a range in the original file."""

    generated_line: int
    generated_col: int
    original_line: int
    original_col: int
    length: int  # Length of the mapped segment


class SourceMap:
    def __init__(self, original_source: str, generated_source: str):
        self.original_source = original_source
        self.generated_source = generated_source
        self.mappings: List[Mapping] = []

        # Pre-compute line offsets for fast lookups if needed,
        # simplifies generic absolute-offset mapping logic.
        self._gen_line_offsets = self._compute_line_offsets(generated_source)
        self._orig_line_offsets = self._compute_line_offsets(original_source)

    def _compute_line_offsets(self, source: str) -> List[int]:
        offsets = [0]
        for i, char in enumerate(source):
            if char == "\n":
                offsets.append(i + 1)
        return offsets

    def add_mapping(
        self, gen_line: int, gen_col: int, orig_line: int, orig_col: int, length: int
    ):
        """Add a 1:1 mapping for a segment of code."""
        self.mappings.append(Mapping(gen_line, gen_col, orig_line, orig_col, length))

    def to_original(self, line: int, col: int) -> Optional[Tuple[int, int]]:
        """Map generated position (line, col) -> original position (line, col).
        Returns None if no mapping exists for this position.
        """
        # Linear search for now, can optimize with binary search or interval tree later
        # We search specifically for a mapping that contains this position.
        for m in self.mappings:
            if m.generated_line == line:
                if m.generated_col <= col <= m.generated_col + m.length:
                    offset = col - m.generated_col
                    return (m.original_line, m.original_col + offset)

        return None

    def to_generated(self, line: int, col: int) -> Optional[Tuple[int, int]]:
        """Map original position -> generated position."""
        for m in self.mappings:
            if m.original_line == line:
                if m.original_col <= col <= m.original_col + m.length:
                    offset = col - m.original_col
                    return (m.generated_line, m.generated_col + offset)
        return None

    def nearest_generated_on_line(
        self, line: int, col: int, max_distance: int = 64
    ) -> Optional[Tuple[int, int]]:
        """Best-effort mapping to generated position on the same line."""
        best: Optional[Tuple[int, int]] = None
        best_distance = max_distance + 1

        for m in self.mappings:
            if m.original_line != line:
                continue

            if col < m.original_col:
                distance = m.original_col - col
                if distance > max_distance:
                    continue
                candidate_col = m.generated_col
            elif col <= m.original_col + m.length:
                distance = 0
                candidate_col = m.generated_col + (col - m.original_col)
            else:
                distance = col - (m.original_col + m.length)
                if distance > max_distance:
                    continue
                candidate_col = m.generated_col + m.length

            if distance < best_distance:
                best_distance = distance
                best = (m.generated_line, candidate_col)
                if distance == 0:
                    break

        return best
