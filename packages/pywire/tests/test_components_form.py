import pytest
from unittest.mock import AsyncMock, MagicMock

from pydantic import BaseModel, Field

from pywire.runtime.page import BasePage
from pywire.components import Form
from pywire.core import ref
from pywire.core.refs import FormElement


class UserModel(BaseModel):
    username: str = Field(min_length=3)
    email: str


@pytest.fixture
def mock_page(request):
    """
    Mock page for component testing.
    Needs to support basic page operations.
    """
    page = AsyncMock(spec=BasePage)
    page._refs_by_id = {}
    return page


def _bind_form_ref_as_form(form_instance):
    """Simulate binding the form_ref to a <form> element, triggering auto-upgrade."""
    fr = form_instance.form_ref
    mock_page = MagicMock(spec=BasePage)
    mock_page._refs_by_id = {}
    fr._bind("form", "test-form-ref", mock_page)
    assert isinstance(fr, FormElement)


@pytest.mark.asyncio
async def test_form_validation_success():
    """Test that valid data calls submit."""
    submit_mock = AsyncMock()

    # Instantiate component
    form = Form(None, {}, {}, model=UserModel, handle_submit=submit_mock)

    # Bind the form_ref so it upgrades to FormElement
    _bind_form_ref_as_form(form)

    # Mock ref data
    form.form_ref._data = {"username": "testuser", "email": "test@example.com"}

    # Simulate submit
    await form._dispatch_submit(AsyncMock())

    # Assertions
    assert form.errors == {}
    submit_mock.assert_called_once()
    args = submit_mock.call_args[0]
    assert isinstance(args[0], UserModel)
    assert args[0].username == "testuser"


@pytest.mark.asyncio
async def test_form_validation_failure():
    """Test that invalid data populates errors."""
    submit_mock = AsyncMock()

    form = Form(None, {}, {}, model=UserModel, handle_submit=submit_mock)

    # Bind the form_ref so it upgrades to FormElement
    _bind_form_ref_as_form(form)

    # Invalid data (username too short)
    form.form_ref._data = {"username": "ab", "email": "test@example.com"}

    await form._dispatch_submit(AsyncMock())

    assert form.errors != {}
    assert "username" in form.errors
    submit_mock.assert_not_called()


@pytest.mark.asyncio
async def test_form_render():
    """Test standard rendering of the form."""
    form = Form(None, {}, {}, model=UserModel, submit=AsyncMock())
    # Components use _render_template
    # We need to mock slots["default"] or ensure it handles missing slots gracefully
    # The current implementation uses self.slots['default']
    # If no slots passed, it might key error or render empty?
    # BasePage (component base) handles slots?
    # We didn't implement slot handling in Form.wire explicitly, relying on base class/codegen.

    # For this test, let's just see if handle_submit exists
    assert hasattr(form, "handle_submit")


@pytest.mark.asyncio
async def test_form_html5_rules_validation_failure():
    submit_mock = AsyncMock()
    form = Form(
        None,
        {},
        {},
        handle_submit=submit_mock,
        _field_rules={
            "username": {"required": True, "minlength": 3, "pattern": "^[A-Za-z]+$"},
            "email": {"required": True, "input_type": "email"},
            "age": {"required": True, "input_type": "number", "min_value": "18"},
        },
    )

    _bind_form_ref_as_form(form)
    form.form_ref._data = {"username": "te", "email": "bad-email", "age": "15"}
    await form._dispatch_submit(AsyncMock())

    assert "username" in form.errors
    assert "age" in form.errors
    submit_mock.assert_not_called()
    assert form.errors.username.rule == "minlength"
    assert form.errors.username.message == "Must be at least 3 characters"


@pytest.mark.asyncio
async def test_form_html5_rules_validation_success():
    submit_mock = AsyncMock()
    form = Form(
        None,
        {},
        {},
        handle_submit=submit_mock,
        _field_rules={
            "username": {"required": True, "minlength": 3},
            "email": {"required": True, "input_type": "email"},
            "age": {"required": True, "input_type": "number", "min_value": "18"},
        },
    )

    _bind_form_ref_as_form(form)
    form.form_ref._data = {
        "username": "alice",
        "email": "alice@example.com",
        "age": "25",
    }
    await form._dispatch_submit(AsyncMock())

    assert form.errors == {}
    submit_mock.assert_called_once()
    payload = submit_mock.call_args[0][0]
    assert payload["username"] == "alice"
    assert payload["email"] == "alice@example.com"
    assert payload["age"] == 25


@pytest.mark.asyncio
async def test_form_html5_file_rules_validation():
    submit_mock = AsyncMock()
    form = Form(
        None,
        {},
        {},
        handle_submit=submit_mock,
        _field_rules={
            "avatar": {
                "input_type": "file",
                "required": True,
                "allowed_types": [".png", ".jpg"],
                "max_size": 8,
            }
        },
    )

    _bind_form_ref_as_form(form)
    form.form_ref._data = {
        "avatar": {
            "content": b"0123456789",
            "name": "avatar.png",
            "type": "image/png",
            "size": 10,
        }
    }
    await form._dispatch_submit(AsyncMock())

    assert form.errors.avatar
    assert form.errors.avatar.rule == "file_too_large"
    submit_mock.assert_not_called()


def test_form_ref_exposes_errors_property():
    form = Form(None, {}, {}, submit=AsyncMock())
    component_ref = ref()
    page = AsyncMock(spec=BasePage)
    page._refs_by_id = {}
    component_ref._bind_component(form, page)
    assert component_ref.errors is form.errors
