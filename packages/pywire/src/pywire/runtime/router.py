"""Routing system."""

import re
from typing import Any, Dict, Optional, Tuple, Type

from pywire.runtime.page import BasePage


class Route:
    """Represents a single route pattern."""

    def __init__(self, pattern: str, page_class: Type[BasePage], name: Optional[str]) -> None:
        self.pattern = pattern
        self.page_class = page_class
        self.name = name

        # Compile pattern to regex
        self.regex = self._compile_pattern(pattern)

    def _compile_pattern(self, pattern: str) -> re.Pattern:
        """Convert '/projects/:id:int' to regex."""
        if pattern == "/":
            return re.compile(r"^/$")

        # 1. Normalize :param syntax to {param} for internal processing if needed,
        #    or just process directly. Let's process :param directly.
        #    Supported format: :name or :name:type or {name} or {name:type}

        # We need to handle both :param and {param} syntax
        # Let's standardize on one before regex gen or handle both in regex replacement

        # Replace placeholders with regex groups
        # We look for two patterns:
        # 1. :name(:type)?
        # 2. \{name(:type)?\}

        # Helper to generate regex for a type
        def get_type_regex(type_name: str) -> str:
            if type_name == "int":
                return r"\d+"
            elif type_name == "str":
                return r"[^/]+"
            # Default to string
            return r"[^/]+"

        # This logic is a bit complex for a single regex replace.
        # Let's manually parse/split the string or use a strict regex.

        # Let's use a tokenizing approach for robustness,
        # or a series of regex replacements that don't conflict.

        # Tokenizing approach for robustness
        # 1. Split by '/'
        # 2. Process segments
        # 3. Join

        parts = pattern.split("/")
        regex_parts = []

        for part in parts:
            if not part:
                # Empty part (e.g. start of string)
                continue

            # Check for :param
            if part.startswith(":"):
                # :id or :id:int
                content = part[1:]
                if ":" in content:
                    name, type_name = content.split(":", 1)
                else:
                    name, type_name = content, "str"

                regex = get_type_regex(type_name)
                regex_parts.append(f"(?P<{name}>{regex})")

            # Check for {param}
            elif part.startswith("{") and part.endswith("}"):
                content = part[1:-1]
                if ":" in content:
                    name, type_name = content.split(":", 1)
                else:
                    name, type_name = content, "str"

                regex = get_type_regex(type_name)
                regex_parts.append(f"(?P<{name}>{regex})")

            else:
                # Literal
                regex_parts.append(re.escape(part))

        regex_str = "^/" + "/".join(regex_parts) + "$"
        return re.compile(regex_str)

    def match(self, path: str) -> Optional[dict[str, str]]:
        """Try to match path, return params if successful."""
        match = self.regex.match(path)
        if match:
            # We need to convert types!
            params = match.groupdict()
            # Since we baked types into regex (e.g. \d+), we know they match format.
            # But we should cast them to Python types.

            # For this MVP, we might just return strings,
            # BUT the user asked for ":id:int matches /test/2", which implies type checking
            # Match only digits. The generated params dict currently contains strings.
            # We should probably convert them if we have the type info available.

            # Re-parsing pattern to get types is inefficient.
            # Let's assume for now they want the matching behavior.
            # BasePage expects params: Dict[str, str].
            # If we change that, we break compatibility or need to update BasePage.
            # User requirement: "params['id'] is guaranteed to be populated".
            # Doesn't explicitly demand it be an int object, but ":int" suggests validation.
            # Given dynamic nature, let's keep as strings in params for now to
            # satisfy Dict[str, str] hint, or update hint in BasePage.

            return params
        return None


class URLHelper:
    """Helper to generate URLs."""

    def __init__(self, routes: Dict[str, str]) -> None:
        self.routes = routes

    def __getitem__(self, key: str) -> "URLTemplate":
        if key not in self.routes:
            raise KeyError(f"Route variant '{key}' not found")
        return URLTemplate(self.routes[key])

    def __str__(self) -> str:
        # Return dict with normalized patterns
        import re

        def normalize_pattern(pattern: str) -> str:
            def replace_param(match: re.Match) -> str:
                return f"{{{match.group(1)}}}"

            cleaned = re.sub(r":(\w+)(:\w+)?", replace_param, pattern)
            cleaned = re.sub(r"\{(\w+)(:\w+)?\}", replace_param, cleaned)
            return cleaned

        normalized = {k: normalize_pattern(v) for k, v in self.routes.items()}
        return str(normalized)


class URLTemplate:
    """Wraps a route pattern to allow .format()."""

    def __init__(self, pattern: str) -> None:
        self.pattern = pattern

    def format(self, **kwargs: Any) -> str:
        url = self.pattern
        # Simple replacement for now.
        # Needs to handle :param syntax conversion to {param} for format,
        # or custom formatter.

        # Regex to find params in pattern:
        # 1. {name:type} or {name}
        # 2. :name:type or :name
        # Note: We must be careful not to match the :type part of {name:type} as a :name.
        # We can do this by matching the more specific {name:type} first in an OR,
        # or by using a single regex for both.

        pattern = r"\{(\w+)(?::\w+)?\}|:(\w+)(?::\w+)?"

        def replace_match(match: re.Match) -> str:
            # Group 1 is from {}, Group 2 is from :
            name = match.group(1) or match.group(2)
            return f"{{{name}}}"

        return re.sub(pattern, replace_match, url).format(**kwargs)

    def __str__(self) -> str:
        # Return normalized pattern with {param} instead of :param
        pattern = r"\{(\w+)(?::\w+)?\}|:(\w+)(?::\w+)?"

        def replace_match(match: re.Match) -> str:
            name = match.group(1) or match.group(2)
            return f"{{{name}}}"

        return re.sub(pattern, replace_match, self.pattern)


class Router:
    """Routes requests to page classes based on !path directives."""

    def __init__(self) -> None:
        self.routes: list[Route] = []

    def add_route(
        self, pattern: str, page_class: Type[BasePage], name: Optional[str] = None
    ) -> None:
        """Add route from compiled page."""
        self.routes.append(Route(pattern, page_class, name))

    def add_page(self, page_class: Type[BasePage]) -> None:
        """Register all routes for a page class."""
        if hasattr(page_class, "__routes__"):
            for name, pattern in page_class.__routes__.items():
                self.add_route(pattern, page_class, name)
        elif hasattr(page_class, "__route__"):
            self.add_route(page_class.__route__, page_class)

    def match(self, path: str) -> Optional[Tuple[Type[BasePage], dict[str, str], Optional[str]]]:
        """Match URL path to page class. Returns: (PageClass, params, variant_name)."""
        for route in self.routes:
            params = route.match(path)
            if params is not None:
                return (route.page_class, params, route.name)
        return None

    def remove_routes_for_file(self, file_path: str) -> None:
        """Remove all routes associated with a file path."""
        # Normalize file path for comparison
        file_path = str(file_path)

        self.routes = [
            r for r in self.routes if getattr(r.page_class, "__file_path__", "") != file_path
        ]
