from typing import Type, TypeVar

T = TypeVar("T", bound=Type)


def props(cls: T) -> T:
    """Decorator to mark a class as the component's props definition.

    Usage:
        @props
        class Props:
            name: str
            count: int = 0
    """
    setattr(cls, "_pywire_props", True)
    return cls
