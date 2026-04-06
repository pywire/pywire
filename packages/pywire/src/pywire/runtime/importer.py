import importlib.abc
import importlib.machinery
import sys
import types
from pathlib import Path
from typing import Optional, Sequence


class PyWireLoader(importlib.abc.Loader):
    def __init__(self, path: str):
        self.path = path

    def create_module(self, spec: importlib.machinery.ModuleSpec):
        return None  # Use default module creation

    def exec_module(self, module):
        from pywire.runtime.loader import get_loader, _loading_file

        loader = get_loader()
        # Compile the .wire file into a page class
        page_class = loader.load(Path(self.path))

        # Record reverse dependency if we're being loaded from another .wire file
        dependent = _loading_file.get()
        if dependent:
            resolved = str(Path(self.path).resolve())
            if resolved not in loader._reverse_deps:
                loader._reverse_deps[resolved] = set()
            loader._reverse_deps[resolved].add(dependent)

        # Inject the page class into the module
        # Convention: The class name is PascalCase of the filename
        # Convention: The class name is PascalCase of the filename
        stem = Path(self.path).stem
        # Always convert to PascalCase
        parts = stem.replace("-", "_").split("_")
        class_name = "".join(p.capitalize() for p in parts)

        setattr(module, class_name, page_class)
        # Also store it as __page_class__ for loader consistency
        module.__page_class__ = page_class
        module.__file__ = str(Path(self.path).resolve())


class PyWireFinder(importlib.abc.MetaPathFinder):
    def find_spec(
        self,
        fullname: str,
        path: Optional[Sequence[str]],
        target: Optional[types.ModuleType] = None,
    ) -> Optional[importlib.machinery.ModuleSpec]:
        # We only care about imports that might resolve to .wire files
        # For now, let's look in the current sys.path or specific component roots if we have them

        # fullname is e.g. "components.button"
        # path is the __path__ of the parent package

        parts = fullname.split(".")
        basename = parts[-1]

        search_paths = path or sys.path

        for p in search_paths:
            # Try as a .wire file
            wire_path = Path(p) / f"{basename}.wire"
            if wire_path.is_file():
                return importlib.machinery.ModuleSpec(
                    fullname, PyWireLoader(str(wire_path)), origin=str(wire_path)
                )

            # If path represents a directory and we are looking for a sub-item,
            # we should also check if it's a directory with the basename.
            # But the parent finder should handle identifying packages.

        return None


def install_import_hook():
    """Register the PyWire import hook."""
    for finder in sys.meta_path:
        if isinstance(finder, PyWireFinder):
            return
    sys.meta_path.insert(0, PyWireFinder())
