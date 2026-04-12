import pytest
import ast
from pathlib import Path
from datetime import date
from enum import Enum
from typing import Optional, List
from unittest.mock import AsyncMock, MagicMock

from pydantic import BaseModel, Field, field_validator

from pywire.compiler.parser import PyWireParser
from pywire.compiler.codegen.generator import CodeGenerator
from pywire.components import Form
from pywire.core.refs import FormElement
from pywire.runtime.files import FileUpload
from pywire.runtime.page import BasePage


# --- Test Models ---


class Role(str, Enum):
    ADMIN = "admin"
    USER = "user"


class Address(BaseModel):
    street: str
    city: str


class AdvancedUser(BaseModel):
    username: str = Field(min_length=3)
    role: Role
    birth_date: date
    address: Address
    tags: List[str] = []
    profile_pic: Optional[FileUpload] = None


def _bind_form_ref_as_form(form_instance):
    """Simulate binding the form_ref to a <form> element, triggering auto-upgrade."""
    fr = form_instance.form_ref
    mock_page = MagicMock(spec=BasePage)
    mock_page._refs_by_id = {}
    fr._bind("form", "test-form-ref", mock_page)
    assert isinstance(fr, FormElement)


class CustomValidatorUser(BaseModel):
    """Model with custom @field_validator for testing."""

    username: str
    email: str

    @field_validator("username")
    @classmethod
    def username_must_not_contain_spaces(cls, v: str) -> str:
        if " " in v:
            raise ValueError("Username must not contain spaces")
        return v

    @field_validator("email")
    @classmethod
    def email_must_be_corporate(cls, v: str) -> str:
        if not v.endswith("@corp.com"):
            raise ValueError("Only @corp.com emails are allowed")
        return v


class InnerAddress(BaseModel):
    street: str
    city: str

    @field_validator("city")
    @classmethod
    def city_must_be_uppercase(cls, v: str) -> str:
        if v != v.upper():
            raise ValueError("City must be uppercase")
        return v


class NestedUser(BaseModel):
    name: str
    address: InnerAddress


@pytest.fixture
def form_setup():
    # Mock dependencies
    submit_mock = AsyncMock()

    # Instantiate component manually (simulating runtime)
    form = Form(
        None,
        {},
        {},
        model=AdvancedUser,
        on_submit=submit_mock,
    )
    # Bind form_ref so it auto-upgrades to FormElement
    _bind_form_ref_as_form(form)
    return form, submit_mock


def test_codegen_structure():
    """Verify that form.wire compiles correctly and properties are accessible."""
    form_file = Path(__file__).resolve().parents[1] / "src/pywire/components/form.wire"
    with open(form_file, "r", encoding="utf-8") as f:
        source = f.read()

    parser = PyWireParser()
    parsed = parser.parse(source, "form.wire")

    generator = CodeGenerator()
    module_ast = generator.generate(parsed)
    code = ast.unparse(module_ast)

    # Verify props are handled
    assert "self.model = model" in code
    assert "self.on_submit = on_submit" in code
    assert "self._errors_wire" in code

    # Verify handle_submit uses model validation
    assert "validate_with_model" in code
    assert "self.model" in code


@pytest.mark.asyncio
async def test_nested_model_validation(form_setup):
    """Test validation with nested Pydantic models (dots in keys)."""
    form, submit_mock = form_setup

    # Simulate form data from client (flat dict with dot notation)
    form.form_ref._data = {
        "username": "admin_user",
        "role": "admin",
        "birth_date": "1990-01-01",
        "address.street": "123 Admin St",
        "address.city": "Adminville",
    }

    await form.handle_submit(AsyncMock())

    # Should be successful
    assert form.errors == {}
    submit_mock.assert_called_once()

    user = submit_mock.call_args[0][0]
    assert isinstance(user, AdvancedUser)
    assert user.address.street == "123 Admin St"
    assert user.role == Role.ADMIN
    assert user.birth_date == date(1990, 1, 1)


@pytest.mark.asyncio
async def test_enum_validation_error(form_setup):
    """Test validation failure for Enums."""
    form, submit_mock = form_setup

    form.form_ref._data = {
        "username": "valid_user",
        "role": "invalid_role",  # Invalid
        "birth_date": "1990-01-01",
        "address.street": "St",
        "address.city": "City",
    }

    await form.handle_submit(AsyncMock())

    # Should fail
    assert form.errors != {}
    assert "role" in form.errors
    submit_mock.assert_not_called()


@pytest.mark.asyncio
async def test_date_validation_error(form_setup):
    """Test validation failure for Dates."""
    form, submit_mock = form_setup

    form.form_ref._data = {
        "username": "valid_user",
        "role": "user",
        "birth_date": "not-a-date",  # Invalid
        "address.street": "St",
        "address.city": "City",
    }

    await form.handle_submit(AsyncMock())

    assert "birth_date" in form.errors


@pytest.mark.asyncio
async def test_error_clearing_lifecycle(form_setup):
    """Test that errors are populated on failure and cleared on success."""
    form, submit_mock = form_setup

    # 1. Submit invalid data
    form.form_ref._data = {"username": "ab"}  # Too short

    await form.handle_submit(AsyncMock())

    assert "username" in form.errors
    assert "role" in form.errors  # Missing

    # 2. Submit valid data
    form.form_ref._data = {
        "username": "valid_user",
        "role": "user",
        "birth_date": "1990-01-01",
        "address.street": "St",
        "address.city": "City",
    }

    await form.handle_submit(AsyncMock())

    # Errors should be cleared
    assert form.errors == {}
    submit_mock.assert_called()


@pytest.mark.asyncio
async def test_file_upload_handling(form_setup):
    """Test handling of FileUpload objects in form data."""
    form, submit_mock = form_setup

    # Mock file upload
    mock_file = FileUpload(
        filename="test.png",
        content_type="image/png",
        size=1024,
        content=b"fake_image_content",
    )

    form.form_ref._data = {
        "username": "user_with_file",
        "role": "user",
        "birth_date": "1990-01-01",
        "address.street": "St",
        "address.city": "City",
        "profile_pic": mock_file,
    }

    await form.handle_submit(AsyncMock())

    assert form.errors == {}
    user = submit_mock.call_args[0][0]
    assert isinstance(user.profile_pic, FileUpload)
    assert user.profile_pic.filename == "test.png"


# --- Custom Pydantic Validator Tests ---


@pytest.fixture
def custom_validator_form():
    submit_mock = AsyncMock()
    form = Form(
        None,
        {},
        {},
        model=CustomValidatorUser,
        on_submit=submit_mock,
    )
    return form, submit_mock


@pytest.mark.asyncio
async def test_custom_field_validator_error(custom_validator_form):
    """Test that @field_validator errors flow into ErrorNamespace with source='pydantic'."""
    form, submit_mock = custom_validator_form

    form.form_ref._data = {
        "username": "has space",
        "email": "user@corp.com",
    }
    form.form_ref._bound_type = "form"

    await form.handle_submit(AsyncMock())

    # Custom validator should produce an error on username
    assert form.errors.username
    assert form.errors.username.source == "pydantic"
    assert "spaces" in form.errors.username.message.lower()
    submit_mock.assert_not_called()


@pytest.mark.asyncio
async def test_custom_field_validator_success(custom_validator_form):
    """Test that valid data passes custom @field_validator."""
    form, submit_mock = custom_validator_form

    form.form_ref._data = {
        "username": "validuser",
        "email": "user@corp.com",
    }
    form.form_ref._bound_type = "form"

    await form.handle_submit(AsyncMock())

    assert form.errors == {}
    submit_mock.assert_called_once()
    user = submit_mock.call_args[0][0]
    assert isinstance(user, CustomValidatorUser)
    assert user.username == "validuser"


@pytest.mark.asyncio
async def test_custom_validator_email_error(custom_validator_form):
    """Test that custom email validator produces a pydantic error."""
    form, submit_mock = custom_validator_form

    form.form_ref._data = {
        "username": "validuser",
        "email": "user@gmail.com",
    }
    form.form_ref._bound_type = "form"

    await form.handle_submit(AsyncMock())

    assert form.errors.email
    assert form.errors.email.source == "pydantic"
    assert "@corp.com" in form.errors.email.message
    submit_mock.assert_not_called()


# --- Nested Model Error Dot-Notation Tests ---


@pytest.fixture
def nested_model_form():
    submit_mock = AsyncMock()
    form = Form(
        None,
        {},
        {},
        model=NestedUser,
        on_submit=submit_mock,
    )
    return form, submit_mock


@pytest.mark.asyncio
async def test_nested_model_error_dot_notation(nested_model_form):
    """Test that nested model validation errors use dot-notation field names."""
    form, submit_mock = nested_model_form

    form.form_ref._data = {
        "name": "Alice",
        "address.street": "123 Main St",
        "address.city": "lowercase",  # Custom validator requires uppercase
    }
    form.form_ref._bound_type = "form"

    await form.handle_submit(AsyncMock())

    # Nested error should be accessible via dot notation
    assert form.errors.address
    assert form.errors.address.city
    assert form.errors.address.city.source == "pydantic"
    assert "uppercase" in form.errors.address.city.message.lower()
    submit_mock.assert_not_called()


@pytest.mark.asyncio
async def test_nested_model_missing_required_field(nested_model_form):
    """Test that missing nested required fields produce dot-notation errors."""
    form, submit_mock = nested_model_form

    form.form_ref._data = {
        "name": "Alice",
        "address.street": "123 Main St",
        # address.city is missing
    }
    form.form_ref._bound_type = "form"

    await form.handle_submit(AsyncMock())

    assert form.errors.address
    assert form.errors.address.city
    assert form.errors.address.city.source == "pydantic"
    submit_mock.assert_not_called()


@pytest.mark.asyncio
async def test_nested_model_success(nested_model_form):
    """Test that valid nested model data passes validation."""
    form, submit_mock = nested_model_form

    form.form_ref._data = {
        "name": "Alice",
        "address.street": "123 Main St",
        "address.city": "NYC",
    }
    form.form_ref._bound_type = "form"

    await form.handle_submit(AsyncMock())

    assert form.errors == {}
    submit_mock.assert_called_once()
    user = submit_mock.call_args[0][0]
    assert isinstance(user, NestedUser)
    assert user.address.street == "123 Main St"
    assert user.address.city == "NYC"
