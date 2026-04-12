from typing import (
    Any,
    Dict,
    List,
    Optional,
    Type,
    TypeVar,
    Generic,
    Union,
    TYPE_CHECKING,
    overload,
    Callable,
)
import logging
from pywire.runtime.form_errors import MISSING_FIELD_ERROR
from pywire.core.wire import WireBase

if TYPE_CHECKING:
    from pywire.runtime.page import BasePage

logger = logging.getLogger(__name__)

T = TypeVar("T")


class RefNotBoundError(Exception):
    """Raised when attempting to access an unbound ref."""

    pass


class RefTypeError(Exception):
    """Raised when attempting an operation not supported by the current ref binding."""

    pass


class RefBase(WireBase):
    """Base class for all refs, handling internal state and command queueing."""

    def __init__(self):
        WireBase.__init__(self)
        self._bound_type: Optional[str] = (
            None  # "input", "form", "component", "element"
        )
        self._ref_id: Optional[str] = None
        self._page: Optional["BasePage"] = None
        self._instance: Optional[Any] = (
            None  # The child component instance if bound to one
        )
        self._commands: List[Dict[str, Any]] = []

    def _bind(self, bound_type: str, ref_id: str, page: "BasePage"):
        """Bind the ref to a specific HTML element or form.

        If this ref was created as a generic HTMLElement (via bare ``ref()``),
        it will be automatically upgraded to the appropriate subclass
        (InputElement / FormElement) based on *bound_type*.
        """
        # Auto-upgrade: if this is a plain HTMLElement (not a subclass), swap
        # the class to match the element it was actually bound to.
        if type(self) is HTMLElement:
            target_cls = _BOUND_TYPE_TO_CLASS.get(bound_type, HTMLElement)
            if target_cls is not HTMLElement:
                self.__class__ = target_cls  # type: ignore[assignment]
                # Re-run the target's __init__ to set up any extra state
                if target_cls is InputElement:
                    self._value = None  # type: ignore[attr-defined]
                elif target_cls is FormElement:
                    self._data = {}  # type: ignore[attr-defined]

        self._bound_type = bound_type
        self._ref_id = ref_id
        self._page = page
        page._refs_by_id[ref_id] = self
        # Also register on the parent page so commands are collected during parent render_update
        parent = getattr(page, "_parent_page", None)
        if parent is not None:
            parent._refs_by_id[ref_id] = self
        self._notify_write()

    def _bind_component(self, instance: Any, page: "BasePage"):
        """Bind the ref to a custom component instance.

        If this ref was created as a plain ``HTMLElement`` (via bare ``ref()``),
        it will be automatically upgraded to ``ComponentRef`` so that attribute
        proxying works correctly.
        """
        # Auto-upgrade bare HTMLElement -> ComponentRef
        if type(self) is HTMLElement:
            self.__class__ = ComponentRef  # type: ignore[assignment]
            self._component_type = None  # type: ignore[attr-defined]

        self._bound_type = "component"
        self._instance = instance
        self._page = page

        # Components use their component_key as the DOM ID for their root element
        component_key = getattr(instance, "_component_key", None)
        if component_key:
            self._ref_id = component_key
            page._refs_by_id[component_key] = self

        self._notify_write()

    def _queue_command(self, cmd: str, **kwargs):
        """Queue a command for the client."""
        # Always use the bound ref_id if available
        ref_id = self._ref_id

        # Fallback for components that might not have set _ref_id yet
        if not ref_id and self._bound_type == "component" and self._instance:
            ref_id = getattr(self._instance, "_component_key", None)

        self._commands.append({"cmd": cmd, "refId": ref_id, "args": kwargs})

    def _collect_commands(self) -> List[Dict[str, Any]]:
        cmds = list(self._commands)
        self._commands.clear()
        return cmds

    # Hooks for value/data updates (to be overridden or extended)
    def _update_data(self, data: Dict[str, Any]):
        pass

    def _update_value(self, value: Any):
        pass

    def _update_rect(self, rect: Dict[str, float]):
        pass


class HTMLElement(RefBase):
    """Ref for standard HTML elements."""

    def __init__(self):
        super().__init__()
        self._rect: Optional[Dict[str, float]] = None

    @property
    def rect(self) -> Optional[Dict[str, float]]:
        """Get the last known bounding client rect from the client."""
        return self._rect

    def _update_rect(self, rect: Dict[str, float]):
        self._rect = rect

    def focus(self):
        """Queue a focus command for the client."""
        self._queue_command("focus")

    def blur(self):
        """Queue a blur command for the client."""
        self._queue_command("blur")

    def scroll_to(self, **kwargs):
        """Queue a scroll_to command for the client."""
        self._queue_command("scrollTo", **kwargs)

    def add_class(self, name: str):
        """Queue an addClass command for the client."""
        self._queue_command("addClass", name=name)

    def remove_class(self, name: str):
        """Queue a removeClass command for the client."""
        self._queue_command("removeClass", name=name)

    def toggle_class(self, name: str):
        """Queue a toggleClass command for the client."""
        self._queue_command("toggleClass", name=name)

    def set_attribute(self, name: str, value: Any):
        """Queue a setAttribute command for the client."""
        self._queue_command("setAttribute", name=name, value=value)

    def remove_attribute(self, name: str):
        """Queue a removeAttribute command for the client."""
        self._queue_command("removeAttribute", name=name)

    def request_rect(self):
        """Request the bounding client rect from the client."""
        self._queue_command("requestRect")

    def clear_file(self):
        """Clear a bound file input element on the client."""
        self._queue_command("clearFileInput")


class InputElement(HTMLElement):
    """Ref for input elements (has value)."""

    def __init__(self, initial_value: Any = None):
        super().__init__()
        self._value: Any = initial_value

    @property
    def value(self) -> Any:
        """Get the current value."""
        # For Typed Ref, we might assume it's correct context, but let's be safe
        if self._bound_type and self._bound_type not in (
            "input",
            "element",
            "component",
        ):
            # If strictly bound to something else (e.g. form), raise error
            raise RefTypeError(
                f"InputElement bound to '{self._bound_type}' does not support value"
            )
        return self._value

    @value.setter
    def value(self, value: Any):
        self._update_value(value)

    def _update_value(self, value: Any):
        if self._bound_type and self._bound_type not in (
            "input",
            "element",
            "component",
        ):
            raise RefTypeError(
                f"InputElement bound to '{self._bound_type}' cannot accept value updates"
            )
        self._value = value


class FormElement(HTMLElement):
    """Ref for form elements (has data, reset)."""

    def __init__(self):
        super().__init__()
        self._data: Dict[str, Any] = {}

    @property
    def data(self) -> Dict[str, Any]:
        """Get form data."""
        if self._bound_type and self._bound_type != "form":
            raise RefTypeError(
                f"FormElement bound to '{self._bound_type}' does not have data"
            )
        return self._data

    def _update_data(self, data: Dict[str, Any]):
        if self._bound_type and self._bound_type != "form":
            raise RefTypeError(
                f"FormElement bound to '{self._bound_type}' cannot accept data updates"
            )
        self._data = data

    def reset(self):
        """Queue a reset command for the client."""
        self._queue_command("reset")

    def submit(self):
        """Queue a submit command for the client."""
        self._queue_command("submit")


class ComponentRef(RefBase, Generic[T]):
    """Ref bound to a custom component."""

    def __init__(self, component_type: Optional[Type[T]] = None):
        super().__init__()
        self._component_type = component_type
        # Components often proxy HTMLElement methods to their root manually,
        # but pure ComponentRef primarily exposes python methods.
        # We can mixin HTMLElement methods if we want to support `comp.ref.focus()` directly
        # assuming the component forwards it or we find the root element id.

    def __getattr__(self, name: str) -> Any:
        self._track_read()
        """Proxy calls to exposed methods."""
        if not self._instance:
            return MISSING_FIELD_ERROR

        # 1. Check for manual exposure allowlist
        if name in getattr(self._instance, "_exposed_methods", set()):
            return getattr(self._instance, name)

        # 2. Check for @expose decorator OR listed in _exposed_methods
        # (The compiler collects @expose into _exposed_methods but might strip the decorator)
        exposed_methods = getattr(self._instance, "_exposed_methods", set())

        cls_attr = getattr(type(self._instance), name, None)
        if (name in exposed_methods) or (
            cls_attr is not None and getattr(cls_attr, "_pywire_exposed", False)
        ):
            return getattr(self._instance, name)

        # For instance-level methods or functions assigned to instances
        inst_attr = getattr(self._instance, name, None)
        if inst_attr is not None and getattr(inst_attr, "_pywire_exposed", False):
            return inst_attr

        raise AttributeError(
            f"Component '{type(self._instance).__name__}' does not expose '{name}'"
        )

    def __setattr__(self, name: str, value: Any) -> None:
        if name.startswith("_"):
            super().__setattr__(name, value)
            return

        if hasattr(self, "_instance") and self._instance:
            setattr(self._instance, name, value)
            self._notify_write()
        else:
            super().__setattr__(name, value)

    @property
    def instance(self) -> T:
        """Get the bound component instance with proper typing."""
        if self._instance is None:
            raise RefNotBoundError("Component ref not bound")
        return self._instance

    @property
    def value(self) -> Any:
        self._track_read()
        # Some components expose value directly
        if self._instance and hasattr(self._instance, "value"):
            return self._instance.value
        raise AttributeError("Component does not have a value property")

    # Support basic element methods if bound
    def focus(self):
        self._queue_command("focus")

    def scroll_to(self, **kwargs):
        self._queue_command("scrollTo", **kwargs)

    def add_class(self, name: str):
        self._queue_command("addClass", name=name)


# Type alias for static analysis ease
Ref = Union[RefBase, HTMLElement, InputElement, FormElement, ComponentRef]


# Mapping from bound_type string to the ref class that should handle it
_BOUND_TYPE_TO_CLASS: Dict[str, Type[RefBase]] = {
    "input": InputElement,
    "form": FormElement,
    "element": HTMLElement,
    "component": ComponentRef,
}


class RefFactory:
    """
    Factory for creating Ref instances with proper typing support.
    Usage:
        input_ref = ref[InputElement]()
        comp_ref = ref[MyComponent]()
        any_ref = ref()
    """

    @overload
    def __getitem__(self, item: Type[InputElement]) -> Type[InputElement]: ...

    @overload
    def __getitem__(self, item: Type[FormElement]) -> Type[FormElement]: ...

    @overload
    def __getitem__(self, item: Type[HTMLElement]) -> Type[HTMLElement]: ...

    @overload
    def __getitem__(self, item: Type[T]) -> Callable[[], T]: ...

    def __getitem__(self, item: Any) -> Any:
        if isinstance(item, type) and issubclass(item, RefBase):
            return item

        # For components, return a callable that creates a ComponentRef
        def _factory():
            return ComponentRef(item)

        return _factory

    def __call__(self, initial_value: Any = None) -> "HTMLElement":
        """Create an untyped ref.  Returns an ``HTMLElement`` that will be
        auto-upgraded to ``InputElement`` or ``FormElement`` when bound via
        ``_bind()``."""
        return HTMLElement()


ref: RefFactory = RefFactory()
