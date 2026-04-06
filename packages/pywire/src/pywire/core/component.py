from typing import Any, Dict, Optional


class WireComponent:
    """
    Base class for PyWire components to support proper typing on refs.
    Inheriting from this ensures that `ref[MyComponent]` understands
    both your component methods and standard ref methods like `focus()`.
    """

    # Stub methods that are available on the Ref proxy
    # These are not actually called on the component instance itself,
    # but the Ref object proxies them.
    # By defining them here, we satisfy static analysis when strict typing is used.

    def focus(self) -> None:
        """Type stub for ref.focus()"""
        pass

    def blur(self) -> None:
        """Type stub for ref.blur()"""
        pass

    def scroll_to(self, **kwargs: Any) -> None:
        """Type stub for ref.scroll_to()"""
        pass

    def add_class(self, name: str) -> None:
        """Type stub for ref.add_class()"""
        pass

    def remove_class(self, name: str) -> None:
        """Type stub for ref.remove_class()"""
        pass

    def toggle_class(self, name: str) -> None:
        """Type stub for ref.toggle_class()"""
        pass

    def set_attribute(self, name: str, value: Any) -> None:
        """Type stub for ref.set_attribute()"""
        pass

    def remove_attribute(self, name: str) -> None:
        """Type stub for ref.remove_attribute()"""
        pass

    def request_rect(self) -> None:
        """Type stub for ref.request_rect()"""
        pass

    @property
    def rect(self) -> Optional[Dict[str, float]]:
        """Type stub for ref.rect"""
        return None
