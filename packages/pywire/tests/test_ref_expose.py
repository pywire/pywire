import pytest
from pywire.core.refs import ref, InputElement, ComponentRef
from pywire.core.expose import expose
from pywire.runtime.page import BasePage
from unittest.mock import Mock


class MyComponent:
    def __init__(self):
        self.internal_value = 42
        self.public_value = 100
        self._element_id = "comp-1"

    @expose
    def public_method(self):
        return "called"

    def internal_method(self):
        return "secret"

    @expose
    @property
    def exposed_prop(self):
        return self.public_value


class TestRefFactory:
    def test_ref_factory_types(self):
        # runtime checks for the factory
        r1 = ref[InputElement]()
        assert isinstance(r1, InputElement)

        r2 = ref[MyComponent]()
        assert isinstance(r2, ComponentRef)

        r3 = ref()
        assert hasattr(r3, "value")  # AnyRef


class TestComponentRefExpose:
    def test_expose_decorator(self):
        comp = MyComponent()
        page = Mock(spec=BasePage)
        page._refs_by_id = {}

        # Bind ref
        comp_ref = ref[MyComponent]()
        comp_ref._bind_component(comp, page)

        # Test exposed method
        assert comp_ref.public_method() == "called"

        # Test exposed property
        assert comp_ref.exposed_prop == 100

        # Test unexposed method/prop raises AttributeError
        with pytest.raises(AttributeError):
            comp_ref.internal_method()

        with pytest.raises(AttributeError):
            _ = comp_ref.internal_value

    def test_expose_manual_attribute(self):
        # Test validation for manually setting _exposed_methods set
        # (Though @expose is preferred)
        class ManualComp:
            def __init__(self):
                self._exposed_methods = {"manual_method"}

            def manual_method(self):
                return "manual"

            def hidden(self):
                pass

        comp = ManualComp()
        page = Mock(spec=BasePage)
        page._refs_by_id = {}

        r = ref[ManualComp]()
        r._bind_component(comp, page)

        assert r.manual_method() == "manual"
        with pytest.raises(AttributeError):
            r.hidden()
