from typing import Any, Callable, TypeVar

F = TypeVar("F", bound=Callable[..., Any])


def expose(fn: F) -> F:
    """Mark a component method as accessible via ref.

    Usage:
        @expose
        def open():
            ...

    In parent: <Modal ref={modal_ref} />
    Then:      modal_ref.value.open()
    """
    setattr(fn, "_pywire_exposed", True)
    return fn
