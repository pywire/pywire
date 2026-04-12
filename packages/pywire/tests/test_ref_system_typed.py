import pytest
from pywire.core import (
    ref,
    HTMLElement,
    InputElement,
    FormElement,
    ComponentRef,
    RefTypeError,
)
from pywire.runtime.page import BasePage
from unittest.mock import MagicMock


def test_untyped_ref():
    """Test that ref() returns HTMLElement (auto-upgradable)."""
    r = ref()
    assert isinstance(r, HTMLElement)
    assert type(r) is HTMLElement
    # Has element methods
    assert hasattr(r, "focus")
    assert hasattr(r, "blur")


def test_untyped_ref_auto_upgrade_to_input(mock_page):
    """Test that a bare ref() auto-upgrades to InputElement when bound to an input."""
    r = ref()
    assert type(r) is HTMLElement
    r._bind("input", "inp-1", mock_page)
    assert isinstance(r, InputElement)
    assert hasattr(r, "value")
    r._update_value("hello")
    assert r.value == "hello"


def test_untyped_ref_auto_upgrade_to_form(mock_page):
    """Test that a bare ref() auto-upgrades to FormElement when bound to a form."""
    r = ref()
    assert type(r) is HTMLElement
    r._bind("form", "form-1", mock_page)
    assert isinstance(r, FormElement)
    assert hasattr(r, "data")
    assert hasattr(r, "reset")
    r._update_data({"name": "test"})
    assert r.data == {"name": "test"}


def test_untyped_ref_stays_element(mock_page):
    """Test that a bare ref() stays HTMLElement when bound to a generic element."""
    r = ref()
    r._bind("element", "el-1", mock_page)
    assert type(r) is HTMLElement


def test_input_ref():
    """Test ref[InputElement]."""
    r = ref[InputElement]()
    assert isinstance(r, InputElement)

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

    # Has focus (from ComponentRef)
    assert hasattr(r, "focus")

    # Mock binding
    mock_page = MagicMock(spec=BasePage)
    mock_page._refs_by_id = {}
    comp = MyComponent()
    r._bind_component(comp, mock_page)


def test_typed_ref_binding(mock_page):
    """Test that typed refs bind and check types correctly."""
    r = ref[InputElement]()
    # Binding to input should be fine
    r._bind("input", "inp-1", mock_page)
    r._update_value("test")
    assert r.value == "test"

    # InputElement bound to form should raise on value update
    r2 = ref[InputElement]()
    r2._bind("form", "form-1", mock_page)

    with pytest.raises(RefTypeError):
        r2._update_value("fail")


def test_typed_ref_no_auto_upgrade(mock_page):
    """Explicitly typed refs should NOT be auto-upgraded."""
    r = ref[InputElement]()
    assert type(r) is InputElement
    r._bind("input", "inp-1", mock_page)
    # Still InputElement, not changed
    assert type(r) is InputElement


@pytest.fixture
def mock_page():
    mock_request = MagicMock()
    return BasePage(mock_request, {}, {})
