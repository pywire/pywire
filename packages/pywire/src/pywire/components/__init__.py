from pathlib import Path
from typing import TYPE_CHECKING
from pywire.runtime.loader import get_loader

_here = Path(__file__).parent

if TYPE_CHECKING:
    from pywire.runtime.page import BasePage

    FileInput: type[BasePage]


def __getattr__(name: str):
    if name == "Form":
        raise ImportError(
            "pywire.components.Form was replaced by model-bound forms: "
            "`signup = form(Signup)` with `<form $bind={signup}>`. "
            "See https://pywire.dev/docs/guides/forms/"
        )
    if name == "FileInput":
        return get_loader().load(_here / "file_input.wire")
    raise AttributeError(name)


__all__ = ["FileInput"]
