"""Tests for the event field static analyzer."""

from pywire.compiler.event_analysis import analyze_event_fields


def test_single_field_access():
    """Handler accessing event.key returns {'key'}."""
    source = """
def handle(event):
    print(event.key)
"""
    result = analyze_event_fields(source)
    assert result == {"key"}


def test_multiple_field_access():
    """Handler accessing event.client_x and event.client_y returns camelCase names."""
    source = """
def handle(event):
    x = event.client_x
    y = event.client_y
"""
    result = analyze_event_fields(source)
    assert result == {"clientX", "clientY"}


def test_event_data_param_name():
    """Handler using event_data parameter name is also recognized."""
    source = """
def handle(event_data):
    return event_data.value
"""
    result = analyze_event_fields(source)
    assert result == {"value"}


def test_kwargs_returns_none():
    """Handler with **kwargs needs all fields."""
    source = """
def handle(**kwargs):
    pass
"""
    result = analyze_event_fields(source)
    assert result is None


def test_event_passed_to_function_returns_none():
    """Handler passing event to another function needs all fields."""
    source = """
def handle(event):
    process(event)
"""
    result = analyze_event_fields(source)
    assert result is None


def test_getattr_returns_none():
    """Handler using getattr(event, ...) needs all fields."""
    source = """
def handle(event):
    val = getattr(event, 'key')
"""
    result = analyze_event_fields(source)
    assert result is None


def test_no_event_param():
    """Handler with no event usage returns empty set."""
    source = """
def handle():
    print("hello")
"""
    result = analyze_event_fields(source)
    assert result == set()


def test_syntax_error_returns_none():
    """Unparseable handler source returns None."""
    source = "def handle(event): !!!syntax error"
    result = analyze_event_fields(source)
    assert result is None


def test_snake_to_camel_mapping():
    """Snake_case fields are mapped to their camelCase JS equivalents."""
    source = """
def handle(event):
    a = event.alt_key
    b = event.key_code
    c = event.form_data
"""
    result = analyze_event_fields(source)
    assert result == {"altKey", "keyCode", "formData"}


def test_target_fields_mapping():
    """target_id, target_name, target_tag map to id, name, tagName."""
    source = """
def handle(event):
    event.target_id
    event.target_name
    event.target_tag
"""
    result = analyze_event_fields(source)
    assert result == {"id", "name", "tagName"}


def test_unmapped_field_passes_through():
    """Fields not in SNAKE_TO_CAMEL are passed through as-is."""
    source = """
def handle(event):
    event.key
    event.code
    event.button
"""
    result = analyze_event_fields(source)
    assert result == {"key", "code", "button"}


def test_event_passed_as_keyword_arg():
    """Handler passing event as keyword argument needs all fields."""
    source = """
def handle(event):
    process(data=event)
"""
    result = analyze_event_fields(source)
    assert result is None


def test_async_handler_with_kwargs():
    """Async handler with **kwargs needs all fields."""
    source = """
async def handle(**kwargs):
    pass
"""
    result = analyze_event_fields(source)
    assert result is None


def test_inline_expression():
    """Inline expression (not a function def) is also analyzed."""
    source = "event.key"
    result = analyze_event_fields(source)
    assert result == {"key"}


def test_mixed_event_and_event_data():
    """Both event and event_data variable names are tracked."""
    source = """
event.key
event_data.value
"""
    result = analyze_event_fields(source)
    assert result == {"key", "value"}
