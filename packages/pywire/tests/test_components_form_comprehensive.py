import pytest
import ast
from pathlib import Path
from datetime import date
from enum import Enum
from typing import Optional, List
from unittest.mock import AsyncMock, MagicMock

from pydantic import BaseModel, Field

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
