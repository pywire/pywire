"""Style collector for scoped CSS."""

from typing import Dict


class StyleCollector:
    """Collects and deduplicates scoped styles per request."""

    def __init__(self) -> None:
        self._styles: Dict[str, str] = {}  # scope_id -> css

    def add(self, scope_id: str, css: str) -> bool:
        """Add CSS for scope_id. Returns True if new (first occurrence)."""
        if scope_id in self._styles:
            return False
        self._styles[scope_id] = css
        return True

    def render(self) -> str:
        """Render all collected styles as a single <style> block."""
        if not self._styles:
            return ""

        # Sort by scope_id to ensure deterministic output (important for tests)
        # But maybe preserving insertion order is better?
        # Actually insertion order implicitly handles dependency order if children render first?
        # No, children render inside parent body.
        # But we collect during render.
        # Let's just join values. Dicts preserve insertion order in modern Python.
        combined = "\n".join(self._styles.values())
        return f"<style>{combined}</style>"
