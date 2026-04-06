import logging
from contextvars import ContextVar
from typing import (
    TypeVar,
    Generic,
    Any,
    Optional,
    Tuple,
    Dict as PyDict,
    Iterable,
    overload,
    TYPE_CHECKING,
)
from weakref import WeakSet

logger = logging.getLogger(__name__)

T = TypeVar("T")
K = TypeVar("K")
V = TypeVar("V")

# Render context for tracking which page/region is reading a wire
_render_context: ContextVar[Optional[Tuple[Any, Optional[str]]]] = ContextVar(
    "pywire_render_context", default=None
)


def set_render_context(page: Any, region_id: Optional[str]) -> Any:
    return _render_context.set((page, region_id))


def reset_render_context(token: Any) -> None:
    _render_context.reset(token)


def _is_mutable(val: Any) -> bool:
    """Check if a value is a mutable container we should proxy."""
    return isinstance(val, (list, dict, set)) and not isinstance(val, WireBase)


def _create_proxy(
    val: Any, parent: Optional["WireBase"] = None, field: Optional[str] = None
) -> "WireBase":
    """Factory to create a proxy for a value."""
    if isinstance(val, list):
        return WireList(val, parent=parent, field=field)
    if isinstance(val, dict):
        return WireDict(val, parent=parent, field=field)
    if isinstance(val, set):
        return WireSet(val, parent=parent, field=field)
    return WirePrimitive(val, parent=parent, field=field)


class WireBase:
    """Base class for all reactive wires and proxies."""

    def __init__(
        self, parent: Optional["WireBase"] = None, field: Optional[str] = None
    ):
        self._pages = WeakSet()
        self._subscribers = WeakSet()  # Derived/Effect subscribers
        self._parent = parent
        self._field = field
        self._frozen = False

    def _track_read(self, field: str = "value") -> None:
        if self._frozen:
            return

        # 1. Track render context
        ctx = _render_context.get()
        if ctx:
            page, region_id = ctx
            self._pages.add(page)
            print(
                f"WIRE-TRACK: wire={id(self)} registered page={id(page)} region={region_id} field={field}",
                flush=True,
            )
            register = getattr(page, "_register_wire_read", None)
            if register:
                register(self, field, region_id)

        # 2. Track signal context (Derived/Effect)
        from pywire.core.signals import _TRACKING_STACK

        if _TRACKING_STACK:
            subscriber = _TRACKING_STACK[-1]
            self._subscribers.add(subscriber)
            subscriber.dependencies.add(self)

    def _notify_write(self, field: str = "value") -> None:
        from pywire.core.signals import (
            _TRACKING_STACK,
            Derived,
            ReactivityError,
            start_batch,
            end_batch,
        )

        # Guard: No mutation allowed inside Derived
        if _TRACKING_STACK and isinstance(_TRACKING_STACK[-1], Derived):
            raise ReactivityError(
                f"Cannot modify wire state inside a derived (derived fn={_TRACKING_STACK[-1].fn.__name__})"
            )

        # Notify parent if this is a proxy
        if self._parent:
            self._parent._notify_write(self._field or "value")

        start_batch()
        try:
            # Notify signal subscribers
            subscribers = list(self._subscribers)
            for sub in subscribers:
                sub.execute()
        finally:
            end_batch()

        # Notify connected pages for re-render
        for page in list(self._pages):
            print(
                f"WIRE-NOTIFY: wire={id(self)} notifying page={id(page)} field={field}",
                flush=True,
            )
            invalidate = getattr(page, "_invalidate_wire", None)
            if invalidate:
                invalidate(self, field)

    def peek(self) -> Any:
        """Read value without tracking dependencies."""
        raise NotImplementedError()

    def freeze(self) -> None:
        """Make the wire read-only."""
        self._frozen = True

    def _check_frozen(self):
        if self._frozen:
            raise TypeError("Cannot mutate a frozen wire")

    def __hash__(self) -> int:
        return id(self)

    def __str__(self):
        if hasattr(self, "value"):
            return str(self.value)
        return super().__str__()


class WirePrimitive(WireBase, Generic[T]):
    """Wire for immutable types (int, str, bool, tuple)."""

    def __init__(
        self, value: T, parent: Optional[WireBase] = None, field: Optional[str] = None
    ):
        super().__init__(parent, field)
        self._value = value

    if TYPE_CHECKING:
        value: T
    else:

        @property
        def value(self) -> T:
            self._track_read()
            return self._value

        @value.setter
        def value(self, new_val: T):
            self._check_frozen()
            if self._value == new_val:
                return
            self._value = new_val
            self._notify_write()

    def peek(self) -> T:
        return self._value

    def __repr__(self) -> str:
        return f"WirePrimitive({self._value!r})"

    def __str__(self) -> str:
        return str(self.value)

    def __format__(self, spec) -> str:
        return format(self.value, spec)

    def __bool__(self) -> bool:
        return bool(self.value)

    # Delegate arithmetic/comparisons
    def __add__(self, other) -> Any:
        return self.value + other

    def __radd__(self, other) -> Any:
        return other + self.value

    def __sub__(self, other) -> Any:
        return self.value - other

    def __rsub__(self, other) -> Any:
        return other - self.value

    def __mul__(self, other) -> Any:
        return self.value * other

    def __rmul__(self, other) -> Any:
        return other * self.value

    def __hash__(self) -> int:
        return id(self)

    def __eq__(self, other: Any) -> bool:
        # Avoid recursion if comparing two wires
        if isinstance(other, WireBase):
            return self is other
        return self.value == other

    def __ne__(self, other: Any) -> bool:
        if isinstance(other, WireBase):
            return self is not other
        return self.value != other

    def __lt__(self, other: Any) -> bool:
        return self.value < other

    def __le__(self, other: Any) -> bool:
        return self.value <= other

    def __gt__(self, other: Any) -> bool:
        return self.value > other

    def __ge__(self, other: Any) -> bool:
        return self.value >= other

    def __iadd__(self, other):
        self.value += other
        return self

    def __isub__(self, other):
        self.value -= other
        return self

    def __imul__(self, other):
        self.value *= other
        return self

    def __itruediv__(self, other):
        self.value /= other
        return self


class WireList(WireBase, list, Generic[T]):
    """Reactive proxy for a list."""

    def __init__(
        self,
        items: Iterable,
        parent: Optional[WireBase] = None,
        field: Optional[str] = None,
    ):
        WireBase.__init__(self, parent, field)
        list.__init__(self, items)

    def __getitem__(self, index):
        self._track_read()
        val = super().__getitem__(index)
        if _is_mutable(val):
            proxy = _create_proxy(val, parent=self)
            self[index] = proxy  # Eagerly replace with proxy for consistency
            return proxy
        return val

    def __setitem__(self, index, value):
        self._check_frozen()
        old_val = super().__getitem__(index) if isinstance(index, int) else None
        if old_val == value:
            return
        super().__setitem__(index, value)
        self._notify_write()

    def append(self, item):
        self._check_frozen()
        super().append(item)
        self._notify_write()

    def extend(self, items):
        self._check_frozen()
        super().extend(items)
        self._notify_write()

    def insert(self, index, item):
        self._check_frozen()
        super().insert(index, item)
        self._notify_write()

    def remove(self, item):
        self._check_frozen()
        super().remove(item)
        self._notify_write()

    def pop(self, index=-1):
        self._check_frozen()
        res = super().pop(index)
        self._notify_write()
        return res

    def clear(self):
        self._check_frozen()
        super().clear()
        self._notify_write()

    def sort(self, *args, **kwargs):
        self._check_frozen()
        super().sort(*args, **kwargs)
        self._notify_write()

    def reverse(self):
        self._check_frozen()
        super().reverse()
        self._notify_write()

    def __iter__(self):
        self._track_read()
        return super().__iter__()

    def __contains__(self, item):
        self._track_read()
        return super().__contains__(item)

    def __len__(self):
        self._track_read()
        return super().__len__()

    def __bool__(self):
        self._track_read()
        return super().__len__() > 0

    def __lt__(self, other):
        self._track_read()
        return super().__lt__(other)

    def __le__(self, other):
        self._track_read()
        return super().__le__(other)

    def __gt__(self, other):
        self._track_read()
        return super().__gt__(other)

    def __ge__(self, other):
        self._track_read()
        return super().__ge__(other)

    def __ne__(self, other):
        self._track_read()
        return super().__ne__(other)

    def __iadd__(self, other):
        self._check_frozen()
        super().__iadd__(other)
        self._notify_write()
        return self

    def peek(self):
        return list(self)

    @property
    def value(self):
        self._track_read()
        return self

    @value.setter
    def value(self, new_list):
        self._check_frozen()
        if not isinstance(new_list, (list, tuple)):
            raise TypeError("value must be a list or tuple")
        self.clear()
        self.extend(new_list)

    def __repr__(self):
        return f"WireList({list(self)!r})"


class WireDict(WireBase, dict, Generic[K, V]):
    """Reactive proxy for a dict."""

    def __init__(
        self,
        items: PyDict,
        parent: Optional[WireBase] = None,
        field: Optional[str] = None,
    ):
        WireBase.__init__(self, parent, field)
        dict.__init__(self, items)

    def __getitem__(self, key):
        self._track_read()
        val = super().__getitem__(key)
        if _is_mutable(val):
            proxy = _create_proxy(
                val, parent=self, field=key if isinstance(key, str) else None
            )
            self[key] = proxy
            return proxy
        return val

    def __setitem__(self, key, value):
        self._check_frozen()
        if super().get(key) == value:
            return
        super().__setitem__(key, value)
        self._notify_write()

    def __iter__(self):
        self._track_read()
        return super().__iter__()

    def __contains__(self, key):
        self._track_read()
        return super().__contains__(key)

    def keys(self):
        self._track_read()
        return super().keys()

    def values(self):
        self._track_read()
        return super().values()

    def items(self):
        self._track_read()
        return super().items()

    def __delitem__(self, key):
        self._check_frozen()
        super().__delitem__(key)
        self._notify_write()

    def update(self, *args, **kwargs):
        self._check_frozen()
        super().update(*args, **kwargs)
        self._notify_write()

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            return super().__getattribute__(name)
        try:
            return self[name]
        except KeyError:
            raise AttributeError(
                f"'{self.__class__.__name__}' object has no attribute '{name}'"
            )

    def __setattr__(self, name: str, value: Any) -> None:
        if name.startswith("_") or name == "value":
            super().__setattr__(name, value)
        else:
            self[name] = value

    def clear(self):
        self._check_frozen()
        super().clear()
        self._notify_write()

    def pop(self, key, default=None):
        self._check_frozen()
        res = super().pop(key, default)
        self._notify_write()
        return res

    def popitem(self):
        self._check_frozen()
        res = super().popitem()
        self._notify_write()
        return res

    def setdefault(self, key, default=None):
        self._check_frozen()
        if key not in self:
            res = super().setdefault(key, default)
            self._notify_write()
            return res
        return self[key]

    def __len__(self) -> int:
        self._track_read()
        return super().__len__()

    def __bool__(self) -> bool:
        self._track_read()
        return super().__len__() > 0

    def __ne__(self, other) -> bool:
        self._track_read()
        return super().__ne__(other)

    def peek(self):
        return dict(self)

    @property
    def value(self):
        self._track_read()
        return self

    @value.setter
    def value(self, new_dict):
        self._check_frozen()
        if not isinstance(new_dict, dict):
            raise TypeError("value must be a dict")
        self.clear()
        self.update(new_dict)

    def __repr__(self):
        return f"WireDict({dict(self)!r})"


class WireSet(WireBase, set, Generic[T]):
    """Reactive proxy for a set."""

    def __init__(
        self,
        items: Iterable,
        parent: Optional[WireBase] = None,
        field: Optional[str] = None,
    ):
        WireBase.__init__(self, parent, field)
        set.__init__(self, items)

    def __iter__(self):
        self._track_read()
        return super().__iter__()

    def __contains__(self, item):
        self._track_read()
        return super().__contains__(item)

    def add(self, item):
        self._check_frozen()
        if item in self:
            return
        super().add(item)
        self._notify_write()

    def remove(self, item):
        self._check_frozen()
        super().remove(item)
        self._notify_write()

    def discard(self, item):
        self._check_frozen()
        if item not in self:
            return
        super().discard(item)
        self._notify_write()

    def pop(self):
        self._check_frozen()
        res = super().pop()
        self._notify_write()
        return res

    def clear(self):
        self._check_frozen()
        super().clear()
        self._notify_write()

    def update(self, *args):
        self._check_frozen()
        super().update(*args)
        self._notify_write()

    def intersection_update(self, *args):
        self._check_frozen()
        super().intersection_update(*args)
        self._notify_write()

    def difference_update(self, *args):
        self._check_frozen()
        super().difference_update(*args)
        self._notify_write()

    def symmetric_difference_update(self, *args):
        self._check_frozen()
        super().symmetric_difference_update(*args)
        self._notify_write()

    def __len__(self) -> int:
        self._track_read()
        return super().__len__()

    def __bool__(self) -> bool:
        self._track_read()
        return super().__len__() > 0

    def __lt__(self, other) -> bool:
        self._track_read()
        return super().__lt__(other)

    def __le__(self, other) -> bool:
        self._track_read()
        return super().__le__(other)

    def __gt__(self, other) -> bool:
        self._track_read()
        return super().__gt__(other)

    def __ge__(self, other) -> bool:
        self._track_read()
        return super().__ge__(other)

    def __ne__(self, other) -> bool:
        self._track_read()
        return super().__ne__(other)

    def peek(self):
        return set(self)

    @property
    def value(self):
        self._track_read()
        return self

    @value.setter
    def value(self, new_set):
        self._check_frozen()
        if not isinstance(new_set, (set, list, tuple)):
            raise TypeError("value must be a set, list or tuple")
        self.clear()
        self.update(new_set)

    def __repr__(self):
        return f"WireSet({set(self)!r})"


class WireNamespace(WireBase):
    """Wire created via wire(x=1, y=2) style."""

    def __init__(self, **kwargs):
        super().__init__()
        self._data = {
            k: _create_proxy(v, parent=self, field=k) for k, v in kwargs.items()
        }

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            return super().__getattribute__(name)
        if name in self._data:
            val = self._data[name]
            return self._wrap_value(val, name)
        raise AttributeError(
            f"'{self.__class__.__name__}' object has no attribute '{name}'"
        )

    def _wrap_value(self, val: Any, field: str) -> Any:
        self._track_read(field)
        return val

    def __setattr__(self, name: str, value: Any) -> None:
        if name.startswith("_") or name == "value":
            super().__setattr__(name, value)
        else:
            self._data[name] = value
            self._notify_write(name)

    def __getitem__(self, key: str) -> Any:
        if key in self._data:
            return self._wrap_value(self._data[key], key)
        raise KeyError(key)

    def __setitem__(self, key: str, value: Any) -> None:
        self._data[key] = value
        self._notify_write(key)

    @property
    def value(self):
        self._track_read()
        return self._data

    def __str__(self):
        return str(self.value)

    def peek(self):
        return {
            k: (v.peek() if hasattr(v, "peek") else v) for k, v in self._data.items()
        }

    def __repr__(self):
        items = [f"{k}={v!r}" for k, v in self._data.items()]
        return f"wire({', '.join(items)})"


@overload
def wire(initial_value: list[T]) -> WireList[T]: ...
@overload
def wire(initial_value: PyDict[K, V]) -> WireDict[K, V]: ...
@overload
def wire(initial_value: set[T]) -> WireSet[T]: ...
@overload
def wire(initial_value: T) -> WirePrimitive[T]: ...
@overload
def wire(**kwargs: Any) -> WireNamespace: ...


def wire(initial_value: Any = None, **kwargs) -> Any:
    """Factory for reactive wires."""
    if kwargs:
        return WireNamespace(**kwargs)

    if isinstance(initial_value, list):
        return WireList(initial_value)
    if isinstance(initial_value, dict):
        return WireDict(initial_value)
    if isinstance(initial_value, set):
        return WireSet(initial_value)

    # Primitives
    return WirePrimitive(initial_value)


# Helpers for backward compatibility if needed, though 'wire' is now the entry point.
def unwrap_wire(val: Any) -> Any:
    """Recursively unwrap wires and proxies into raw Python objects."""
    from pywire.core.signals import Derived
    from pywire.core.wire import WireBase

    if isinstance(val, Derived):
        return unwrap_wire(val.value)

    if isinstance(val, WireBase):
        val = val.value

    if type(val) is dict:
        return {k: unwrap_wire(v) for k, v in val.items()}
    if type(val) is list:
        return [unwrap_wire(i) for i in val]
    if type(val) is set:
        return {unwrap_wire(i) for i in val}
    if type(val) is tuple:
        return tuple(unwrap_wire(i) for i in val)

    return val
