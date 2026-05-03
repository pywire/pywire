from typing import Any, Type, TypeVar

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


class PropsNamespace:
    """Read-only namespace exposing declared props inside a template.

    Codegen unpacks props as bare locals (so ``{name}`` works) and also
    binds ``props`` to one of these so ``{props.name}`` works too. The
    docs and tutorials teach the ``props.x`` form; the bare form is an
    implementation detail of the unpacking.
    """

    __slots__ = ("_values",)

    def __init__(self, **values: Any) -> None:
        object.__setattr__(self, "_values", values)

    def __getattr__(self, name: str) -> Any:
        values = object.__getattribute__(self, "_values")
        if name in values:
            return values[name]
        raise AttributeError(name)

    def __repr__(self) -> str:  # pragma: no cover - debug only
        values = object.__getattribute__(self, "_values")
        body = ", ".join(f"{k}={v!r}" for k, v in values.items())
        return f"PropsNamespace({body})"
