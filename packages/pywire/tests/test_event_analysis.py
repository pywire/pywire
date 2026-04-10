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


# ---------------------------------------------------------------------------
# Additional edge cases
# ---------------------------------------------------------------------------


def test_empty_handler_body():
    """Handler with pass-only body returns empty set."""
    source = """
def handle(event):
    pass
"""
    result = analyze_event_fields(source)
    assert result == set()


def test_event_in_conditional():
    """Fields accessed in if/else branches are all collected."""
    source = """
def handle(event):
    if True:
        x = event.client_x
    else:
        k = event.key
"""
    result = analyze_event_fields(source)
    assert result == {"clientX", "key"}


def test_event_in_list_comprehension():
    """Event access inside comprehension is detected."""
    source = """
def handle(event):
    vals = [event.key for _ in range(1)]
"""
    result = analyze_event_fields(source)
    assert result == {"key"}


def test_event_subscript_string_literal():
    """event['key'] with string literal is tracked."""
    source = """
def handle(event):
    val = event['key']
"""
    result = analyze_event_fields(source)
    assert result == {"key"}


def test_event_subscript_dynamic_returns_none():
    """event[some_var] with dynamic key needs all fields."""
    source = """
def handle(event):
    field = 'key'
    val = event[field]
"""
    result = analyze_event_fields(source)
    assert result is None


def test_event_subscript_snake_to_camel():
    """event['client_x'] maps to camelCase."""
    source = """
def handle(event):
    x = event['client_x']
"""
    result = analyze_event_fields(source)
    assert result == {"clientX"}


def test_reassigned_event_tracked():
    """If event is reassigned (e = event), the alias IS tracked."""
    source = """
def handle(event):
    e = event
    print(e.key)
"""
    result = analyze_event_fields(source)
    assert result == {"key"}


def test_chained_reassignment():
    """Transitive aliases: e = event; f = e; f.key."""
    source = """
def handle(event):
    e = event
    f = e
    print(f.key)
"""
    result = analyze_event_fields(source)
    assert result == {"key"}


def test_reassignment_plus_direct():
    """Alias access combined with direct access collects both."""
    source = """
def handle(event):
    e = event
    print(e.key)
    print(event.code)
"""
    result = analyze_event_fields(source)
    assert result == {"key", "code"}


def test_annotated_reassignment():
    """Annotated alias: e: Any = event."""
    source = """
def handle(event):
    e: object = event
    print(e.key)
"""
    result = analyze_event_fields(source)
    assert result == {"key"}


# ---------------------------------------------------------------------------
# Codegen integration
# ---------------------------------------------------------------------------


def test_codegen_emits_field_mask():
    """EventAttributeCodegen generates data-pw-fields-* attribute when field_mask is set."""
    from pywire.compiler.ast_nodes import EventAttribute
    from pywire.compiler.codegen.attributes.events import EventAttributeCodegen

    attr = EventAttribute(
        name="@click",
        value="{handler}",
        event_type="click",
        handler_name="handler",
        line=1,
        column=0,
    )
    attr.field_mask = {"clientX", "clientY"}

    codegen = EventAttributeCodegen()
    html = codegen.generate_html(attr)
    assert 'data-on-click="handler"' in html
    assert 'data-pw-fields-click="clientX,clientY"' in html


def test_codegen_no_field_mask_attribute_when_none():
    """No data-pw-fields-* attribute when field_mask is None (send all fields)."""
    from pywire.compiler.ast_nodes import EventAttribute
    from pywire.compiler.codegen.attributes.events import EventAttributeCodegen

    attr = EventAttribute(
        name="@click",
        value="{handler}",
        event_type="click",
        handler_name="handler",
        line=1,
        column=0,
    )
    attr.field_mask = None

    codegen = EventAttributeCodegen()
    html = codegen.generate_html(attr)
    assert 'data-on-click="handler"' in html
    assert "data-pw-fields" not in html


def test_codegen_empty_field_mask():
    """Empty field mask emits empty data-pw-fields attribute."""
    from pywire.compiler.ast_nodes import EventAttribute
    from pywire.compiler.codegen.attributes.events import EventAttributeCodegen

    attr = EventAttribute(
        name="@click",
        value="{handler}",
        event_type="click",
        handler_name="handler",
        line=1,
        column=0,
    )
    attr.field_mask = set()

    codegen = EventAttributeCodegen()
    html = codegen.generate_html(attr)
    assert 'data-pw-fields-click=""' in html
