from pydantic import BaseModel, Field
from pywire.components import Form
from pywire.core import wire
from pywire.core.signals import Derived


class SampleModel(BaseModel):
    name: str = Field(title="Full Name", min_length=3)
    age: int = Field(gt=0)
    is_active: bool = True
    bio: str = Field(default="", max_length=500)


def test_schema_fields_basic():
    """Test basic metadata extraction from Pydantic model."""
    form = Form(None, {}, {}, model=SampleModel)
    fields = form.schema_fields()

    # Assert fields count
    assert len(fields) == 4

    # Check "name" field
    name_field = next(f for f in fields if f["name"] == "name")
    assert name_field["title"] == "Full Name"
    assert name_field["input_type"] == "text"
    assert name_field["required"] is True
    assert name_field["minlength"] == 3

    # Check "age" field
    age_field = next(f for f in fields if f["name"] == "age")
    assert age_field["input_type"] == "number"  # Auto-detected from int
    assert age_field["required"] is True

    # Check "is_active" field
    active_field = next(f for f in fields if f["name"] == "is_active")
    assert active_field["input_type"] == "checkbox"  # Auto-detected from bool
    assert active_field["required"] is False  # Has default


def test_schema_fields_exclude():
    """Test the exclude parameter (list, string, set)."""
    form = Form(None, {}, {}, model=SampleModel)

    # Exclude as list
    fields = form.schema_fields(exclude=["name", "age"])
    assert len(fields) == 2
    assert not any(f["name"] in ["name", "age"] for f in fields)

    # Exclude as comma-separated string
    fields = form.schema_fields(exclude="name, age")
    assert len(fields) == 2
    assert not any(f["name"] in ["name", "age"] for f in fields)


def test_schema_fields_reactivity():
    """Test that schema_fields tracks dependencies when using a wire for exclude."""
    form = Form(None, {}, {}, model=SampleModel)
    exclude_wire = wire(["bio"])

    # Define a derived that uses schema_fields
    # This simulates how a template would react
    d = Derived(lambda: form.schema_fields(exclude=exclude_wire))

    # Initial run
    initial_fields = d.value
    assert len(initial_fields) == 3
    assert not any(f["name"] == "bio" for f in initial_fields)

    # Update wire
    exclude_wire.append("name")

    # The derived should have re-executed (automatically since it's a Derived)
    updated_fields = d.value
    assert len(updated_fields) == 2
    assert not any(f["name"] == "name" for f in updated_fields)
    assert not any(f["name"] == "bio" for f in updated_fields)


def test_schema_fields_no_model():
    """Should return empty list if no model is bound."""
    form = Form(None, {}, {}, model=None)
    assert form.schema_fields() == []
