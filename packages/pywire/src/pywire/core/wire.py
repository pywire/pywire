from contextvars import ContextVar
from typing import TypeVar, Generic, Any, Optional, Tuple, cast
from weakref import WeakSet

T = TypeVar("T")

_render_context: ContextVar[Optional[Tuple[Any, Optional[str]]]] = ContextVar(
    "pywire_render_context", default=None
)


def set_render_context(page: Any, region_id: Optional[str]) -> Any:
    return _render_context.set((page, region_id))


def reset_render_context(token: Any) -> None:
    _render_context.reset(token)


class WireList(list):
    """A list that notifies a wire of mutations."""

    def __init__(self, items, wire_obj, field):
        super().__init__(items)
        self._wire_obj = wire_obj
        self._field = field

    def _notify(self):
        self._wire_obj._notify_write(self._field)

    def append(self, item):
        super().append(item)
        self._notify()

    def extend(self, items):
        super().extend(items)
        self._notify()

    def insert(self, index, item):
        super().insert(index, item)
        self._notify()

    def remove(self, item):
        super().remove(item)
        self._notify()

    def pop(self, index=-1):
        res = super().pop(index)
        self._notify()
        return res

    def clear(self):
        super().clear()
        self._notify()

    def sort(self, *args, **kwargs):
        super().sort(*args, **kwargs)
        self._notify()

    def reverse(self):
        super().reverse()
        self._notify()

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        self._notify()

    def __delitem__(self, key):
        super().__delitem__(key)
        self._notify()


class WireDict(dict):
    """A dict that notifies a wire of mutations."""

    def __init__(self, items, wire_obj, field):
        super().__init__(items)
        self._wire_obj = wire_obj
        self._field = field

    def _notify(self):
        self._wire_obj._notify_write(self._field)

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        self._notify()

    def __delitem__(self, key):
        super().__delitem__(key)
        self._notify()

    def update(self, *args, **kwargs):
        super().update(*args, **kwargs)
        self._notify()

    def clear(self):
        super().clear()
        self._notify()

    def pop(self, key, default=None):
        res = super().pop(key, default)
        self._notify()
        return res

    def popitem(self):
        res = super().popitem()
        self._notify()
        return res


class wire(Generic[T]):
    """
    A reactive container for state.

    Usage:
        # Single value
        count = wire(0)
        count.value += 1

        # Namespace
        user = wire(name="Alice", age=30)
        user.name = "Bob"
    """

    def __init__(self, value: Optional[T] = None, **kwargs):
        # We use strict dict manipulation to avoid triggering __setattr__
        self.__dict__["_value"] = self._wrap_value(value, "value")
        self.__dict__["_namespace"] = {
            k: self._wrap_value(v, k) for k, v in kwargs.items()
        }
        self.__dict__["_pages"] = WeakSet()

    def _wrap_value(self, val: Any, field: str) -> Any:
        if isinstance(val, list) and not isinstance(val, WireList):
            return WireList(val, self, field)
        if isinstance(val, dict) and not isinstance(val, WireDict):
            return WireDict(val, self, field)
        return val

    def _track_read(self, field: str) -> None:
        ctx = _render_context.get()
        if not ctx:
            return
        page, region_id = ctx

        pages = cast(WeakSet[Any], self.__dict__.get("_pages"))
        if pages is not None:
            pages.add(page)
        register = getattr(page, "_register_wire_read", None)
        if register:
            register(self, field, region_id)

    def _notify_write(self, field: str) -> None:
        pages = cast(WeakSet[Any], self.__dict__.get("_pages"))
        if not pages:
            return
        for page in list(pages):
            invalidate = getattr(page, "_invalidate_wire", None)
            if invalidate:
                invalidate(self, field)

    @property
    def value(self) -> T:
        """Access the underlying value."""
        # strict priority: if 'value' is in namespace, return that.
        # otherwise return the positional value.
        if "value" in self.__dict__["_namespace"]:
            self._track_read("value")
            return self.__dict__["_namespace"]["value"]
        self._track_read("value")
        return self.__dict__["_value"]

    @value.setter
    def value(self, new_val: T):
        new_val = self._wrap_value(new_val, "value")
        if "value" in self.__dict__["_namespace"]:
            self.__dict__["_namespace"]["value"] = new_val
        else:
            self.__dict__["_value"] = new_val
        self._notify_write("value")

    # Alias for shorter typing, if desired.
    @property
    def val(self) -> T:
        return self.value

    @val.setter
    def val(self, new_val: T):
        self.value = new_val

    def __getattr__(self, name: str) -> Any:
        if name in self.__dict__["_namespace"]:
            self._track_read(name)
            return self.__dict__["_namespace"][name]
        raise AttributeError(f"'wire' object has no attribute '{name}'")

    def __setattr__(self, name: str, val: Any):
        # If the attribute is 'value' or 'val', go through the property
        if name in ("value", "val"):
            super().__setattr__(name, val)
            return

        # If it's an internal attribute (shouldn't really happen from outside)
        if name in self.__dict__:
            super().__setattr__(name, val)
            return

        # Otherwise, treat it as setting a namespace key
        # We allow adding new keys dynamically
        val = self._wrap_value(val, name)
        self.__dict__["_namespace"][name] = val
        self._notify_write(name)

    # --- Proxy Methods for Transparent Reactivity ---

    def __bool__(self) -> bool:
        return bool(self.value)

    def __iter__(self):
        from typing import Iterable

        return iter(cast(Iterable[Any], self.value))

    def __len__(self) -> int:
        from typing import Sized

        return len(cast(Sized, self.value))

    # Comparisons
    def __eq__(self, other: Any) -> bool:
        if isinstance(other, wire):
            return self is other
        return self.value == other

    def __hash__(self) -> int:
        return id(self)

    def __ne__(self, other: Any) -> bool:
        return self.value != other

    def __lt__(self, other: Any) -> bool:
        return self.value < other

    def __le__(self, other: Any) -> bool:
        return self.value <= other

    def __gt__(self, other: Any) -> bool:
        return self.value > other

    def __ge__(self, other: Any) -> bool:
        return self.value >= other

    # Arithmetic
    def __add__(self, other: Any) -> Any:
        return self.value + other

    def __radd__(self, other: Any) -> Any:
        return other + self.value

    def __sub__(self, other: Any) -> Any:
        return self.value - other

    def __rsub__(self, other: Any) -> Any:
        return other - self.value

    def __mul__(self, other: Any) -> Any:
        return self.value * other

    def __rmul__(self, other: Any) -> Any:
        return other * self.value

    def __truediv__(self, other: Any) -> Any:
        return self.value / other

    def __rtruediv__(self, other: Any) -> Any:
        return other / self.value

    def __floordiv__(self, other: Any) -> Any:
        return self.value // other

    def __rfloordiv__(self, other: Any) -> Any:
        return other // self.value

    # In-place assignments (Mutation + Notification)
    def __iadd__(self, other: Any) -> "wire[T]":
        # We use the property setter to ensure notification
        self.value = self.value + other
        return self

    def __isub__(self, other: Any) -> "wire[T]":
        self.value = self.value - other
        return self

    def __repr__(self):
        _namespace = self.__dict__["_namespace"]
        if _namespace:
            items = [f"{k}={v!r}" for k, v in _namespace.items()]
            # If we also have a positional value that isn't None (and not shadowed), show it?
            # Typically one uses EITHER positional OR kwargs.
            if self.__dict__["_value"] is not None and "value" not in _namespace:
                return f"wire({self.__dict__['_value']!r}, {', '.join(items)})"
            return f"wire({', '.join(items)})"
        return f"wire({self.__dict__['_value']!r})"
