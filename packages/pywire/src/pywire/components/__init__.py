from pathlib import Path
from typing import TYPE_CHECKING
from pywire.runtime.loader import get_loader

_here = Path(__file__).parent

if TYPE_CHECKING:
    from pywire.runtime.page import BasePage

    Form: type[BasePage]
    FileInput: type[BasePage]


def __getattr__(name: str):
    if name == "Form":
        return get_loader().load(_here / "form.wire")
    if name == "FileInput":
        return get_loader().load(_here / "file_input.wire")
    raise AttributeError(name)


__all__ = ["Form", "FileInput"]
