from typing import TypeVar, Generic, Any, Optional, Dict

T = TypeVar("T")

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
    def __init__(self, value: T = None, **kwargs):
        # We use strict dict manipulation to avoid triggering __setattr__
        self.__dict__["_value"] = value
        self.__dict__["_namespace"] = kwargs
        
    @property
    def value(self) -> T:
        """Access the underlying value."""
        # strict priority: if 'value' is in namespace, return that.
        # otherwise return the positional value.
        if "value" in self.__dict__["_namespace"]:
            return self.__dict__["_namespace"]["value"]
        return self.__dict__["_value"]
    
    @value.setter
    def value(self, new_val: T):
        if "value" in self.__dict__["_namespace"]:
            self.__dict__["_namespace"]["value"] = new_val
        else:
            self.__dict__["_value"] = new_val
            
    # Alias for shorter typing, if desired.
    @property
    def val(self) -> T:
        return self.value
        
    @val.setter
    def val(self, new_val: T):
        self.value = new_val

    def __getattr__(self, name: str) -> Any:
        if name in self.__dict__["_namespace"]:
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
        self.__dict__["_namespace"][name] = val

    def __repr__(self):
        if self._namespace:
            items = [f"{k}={v!r}" for k,v in self._namespace.items()]
            # If we also have a positional value that isn't None (and not shadowed), show it?
            # Typically one uses EITHER positional OR kwargs.
            if self._value is not None and "value" not in self._namespace:
                return f"wire({self._value!r}, {', '.join(items)})"
            return f"wire({', '.join(items)})"
        return f"wire({self._value!r})"
