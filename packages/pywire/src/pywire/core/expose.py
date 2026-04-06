from typing import Any, Callable, TypeVar

F = TypeVar("F", bound=Callable[..., Any])


class ExposedProperty(property):
    """Wrapper for property objects to allow setting attributes."""

    pass


def expose(fn: F) -> F:
    """Mark a component method or property as accessible via $ref.

    Usage:
        @expose
        def open(): ...

        @expose
        @property
        def value(): ...

    In parent: <Modal $ref={modal_ref} />
    Then:      modal_ref.value.open() or modal_ref.value.value
    """
    if isinstance(fn, property):
        # Create a subclass instance so we can set attributes
        new_prop = ExposedProperty(fn.fget, fn.fset, fn.fdel, fn.__doc__)
        setattr(new_prop, "_pywire_exposed", True)
        return new_prop  # type: ignore

    setattr(fn, "_pywire_exposed", True)
    return fn
