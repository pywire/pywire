import pytest
from pywire.core import (
    ref,
    InputElement,
    FormElement,
    ComponentRef,
    AnyRef,
    RefTypeError,
)
from pywire.runtime.page import BasePage
from unittest.mock import MagicMock


def test_untyped_ref():
    """Test that ref() returns AnyRef."""
    r = ref()
    assert isinstance(r, AnyRef)
    # Should have all methods/properties available (though maybe Raise if unbound)
    assert hasattr(r, "value")
    assert hasattr(r, "data")
    assert hasattr(r, "reset")
    assert hasattr(r, "focus")


def test_input_ref():
    """Test ref[InputElement]."""
    r = ref[InputElement]()
    assert isinstance(r, InputElement)
    assert not isinstance(r, AnyRef)

    # Has value and focus
    assert hasattr(r, "value")
    assert hasattr(r, "focus")

    # Does NOT have data or reset
    assert not hasattr(r, "data")
    assert not hasattr(r, "reset")


def test_form_ref():
    """Test ref[FormElement]."""
    r = ref[FormElement]()
    assert isinstance(r, FormElement)

    # Has data, reset, focus
    assert hasattr(r, "data")
    assert hasattr(r, "reset")
    assert hasattr(r, "focus")

    # Does NOT have value
    assert not hasattr(r, "value")


class MyComponent:
    def method(self):
        pass


def test_component_ref():
    """Test ref[MyComponent]."""
    r = ref[MyComponent]()
    assert isinstance(r, ComponentRef)

    # Has focus (from RefBase/ComponentRef mixin if implemented)
    assert hasattr(r, "focus")

    # Should handle __getattr__
    # Mock binding
    mock_page = MagicMock(spec=BasePage)
    mock_page._refs_by_id = {}
    comp = MyComponent()
    r._bind_component(comp, mock_page)

    # Attributes on component rely on proxying which we need to test separately
    # if ComponentRef proxies.


def test_typed_ref_binding(mock_page):
    """Test that typed refs bind and check types correctly."""
    r = ref[InputElement]()
    # Binding to input should be fine
    r._bind("input", "inp-1", mock_page)
    r._update_value("test")
    assert r.value == "test"

    # Binding to form should technically be allowed by _bind but usage might fail?
    # The _bind method in RefBase just sets _bound_type.
    # But InputElement specific methods might check it.

    r2 = ref[InputElement]()
    r2._bind("form", "form-1", mock_page)
    # _update_value checks if bound type is input/element
    # user logic: if I use InputRef on a form, and call .value, it should fail
    # because form doesn't have value.

    with pytest.raises(RefTypeError):
        r2._update_value("fail")


@pytest.fixture
def mock_page():
    mock_request = MagicMock()
    return BasePage(mock_request, {}, {})
