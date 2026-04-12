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

        For AnyRef instances, auto-upgrades to a specialized class when the
        bound_type has an entry in _BOUND_TYPE_TO_CLASS (e.g. media, dialog, canvas).
        """
        # Auto-upgrade AnyRef to specialized class when appropriate
        if type(self) is AnyRef and bound_type in _BOUND_TYPE_TO_CLASS:
            target_cls = _BOUND_TYPE_TO_CLASS[bound_type]
            self.__class__ = target_cls
            target_cls.__init__(self)  # type: ignore[misc]

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
        """Bind the ref to a custom component instance."""
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
            # print(f"DEBUG: ComponentRef.__setattr__ proxying {name} to {self._instance}") # Removed print
            setattr(self._instance, name, value)
            self._notify_write()
        else:
            # print(f"DEBUG: ComponentRef.__setattr__ setting {name} on self (unbound)") # Removed print
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


class MediaElement(HTMLElement):
    """Ref for <audio> and <video> elements."""

    def __init__(self):
        super().__init__()
        self._current_time: float = 0.0
        self._paused: bool = True
        self._duration: float = 0.0

    def play(self) -> None:
        """Queue a play command for the client."""
        self._queue_command("play")

    def pause(self) -> None:
        """Queue a pause command for the client."""
        self._queue_command("pause")

    def load(self) -> None:
        """Queue a load command for the client."""
        self._queue_command("load")

    @property
    def current_time(self) -> float:
        return self._current_time

    @property
    def paused(self) -> bool:
        return self._paused

    @property
    def duration(self) -> float:
        return self._duration

    def _update_media_state(self, state: Dict[str, Any]) -> None:
        """Called when client syncs media state."""
        if "currentTime" in state:
            self._current_time = float(state["currentTime"])
        if "paused" in state:
            self._paused = bool(state["paused"])
        if "duration" in state:
            self._duration = float(state["duration"])


class DialogElement(HTMLElement):
    """Ref for <dialog> elements."""

    def __init__(self):
        super().__init__()
        self._open: bool = False

    def show_modal(self) -> None:
        """Queue a showModal command for the client."""
        self._queue_command("showModal")

    def close(self, return_value: str = "") -> None:
        """Queue a close command for the client."""
        self._queue_command("close", returnValue=return_value)

    @property
    def open(self) -> bool:
        return self._open

    def _update_dialog_state(self, state: Dict[str, Any]) -> None:
        """Called when client syncs dialog state."""
        if "open" in state:
            self._open = bool(state["open"])


class CanvasElement(HTMLElement):
    """Ref for <canvas> elements."""

    def __init__(self):
        super().__init__()
        self._data_url: Optional[str] = None

    def request_data_url(self, type: str = "image/png") -> None:
        """Queue a requestDataUrl command for the client."""
        self._queue_command("requestDataUrl", type=type)

    @property
    def data_url(self) -> Optional[str]:
        return self._data_url

    def _update_canvas_state(self, state: Dict[str, Any]) -> None:
        """Called when client syncs canvas state."""
        if "dataUrl" in state:
            self._data_url = state["dataUrl"]


# Mapping from bound_type string to specialized ref class for auto-upgrade
_BOUND_TYPE_TO_CLASS: Dict[str, type] = {
    "media": MediaElement,
    "dialog": DialogElement,
    "canvas": CanvasElement,
}


class AnyRef(FormElement, InputElement, ComponentRef):
    """
    Backward compatibility Ref that supports all operations.
    Used when `ref()` is called without type arguments.
    """

    def __init__(self, initial_value: Any = None):
        # Initialize bases
        HTMLElement.__init__(self)
        InputElement.__init__(self, initial_value)
        FormElement.__init__(self)
        ComponentRef.__init__(self, None)

    # Re-implement guards to avoid confusion even in "Any" mode
    def _update_data(self, data: Dict[str, Any]):
        if self._bound_type == "form":
            self._data = data
        else:
            # Maintain old behavior: mostly silent or specific error?
            # Old code raised RefTypeError, but AnyRef combines them.
            pass

    def _update_value(self, value: Any):
        if self._bound_type in ("input", "element", "component"):
            self._value = value

    @property
    def value(self) -> Any:
        self._track_read()
        if (
            self._bound_type == "component"
            and self._instance
            and hasattr(self._instance, "value")
        ):
            return self._instance.value
        return self._value

    @value.setter
    def value(self, val: Any):
        if (
            self._bound_type == "component"
            and self._instance
            and hasattr(self._instance, "value")
        ):
            self._instance.value = val
        else:
            self._value = val
        self._notify_write()

    def submit(self):
        """
        Handle submit command.
        Prioritizes component proxy if available,
        otherwise falls back to native form submit.
        """
        print(f"DEBUG: AnyRef.submit() entered. self={self} instance={self._instance}")
        if self._instance:
            handler = getattr(self._instance, "submit", None)
            exposed_methods = getattr(self._instance, "_exposed_methods", set())
            is_exposed = ("submit" in exposed_methods) or (
                handler is not None and getattr(handler, "_pywire_exposed", False)
            )

            print(
                f"DEBUG: AnyRef.submit() found handler={handler} is_exposed={is_exposed}"
            )
            if handler is not None and is_exposed:
                # Call proxied component method
                print("DEBUG: AnyRef.submit() calling proxy handler")
                res = handler()
                import inspect

                if inspect.iscoroutine(res):
                    return res

                async def _nop():
                    pass

                return _nop()

        # If we have a DOM ID, use the native command to ensure data sync
        if self._ref_id:
            print(
                f"DEBUG: AnyRef.submit() using native command for ref_id={self._ref_id}"
            )
            super().submit()

            async def _nop():
                pass

            return _nop()

        # Default to native command (will raise if unbound)
        print("DEBUG: AnyRef.submit() falling back to native command (super)")
        super().submit()

        async def _nop():
            pass

        return _nop()


# Type alias for static analysis ease
Ref = Union[RefBase, HTMLElement, InputElement, FormElement, ComponentRef, AnyRef]


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
    def __getitem__(self, item: Type[MediaElement]) -> Type[MediaElement]: ...

    @overload
    def __getitem__(self, item: Type[DialogElement]) -> Type[DialogElement]: ...

    @overload
    def __getitem__(self, item: Type[CanvasElement]) -> Type[CanvasElement]: ...

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

    def __call__(self, initial_value: Any = None) -> "AnyRef":
        return AnyRef(initial_value)


ref: RefFactory = RefFactory()
