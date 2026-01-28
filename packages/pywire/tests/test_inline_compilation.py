import ast

from pywire.compiler.ast_nodes import EventAttribute, ParsedPyWire, TemplateNode
from pywire.compiler.codegen.generator import CodeGenerator


def test_inline_handler_extraction() -> None:
    generator = CodeGenerator()

    # Create template with inline handler
    # <button @click={count += 1}>
    click_attr = EventAttribute(
        line=1,
        column=1,
        name="@click",
        value="count += 1",
        event_type="click",
        handler_name="count += 1",
    )

    button_node = TemplateNode(line=1, column=1, tag="button", special_attributes=[click_attr])

    parsed = ParsedPyWire(template=[button_node], file_path="test_inline.pywire")

    module_ast = generator.generate(parsed)
    ast.fix_missing_locations(module_ast)

    # Check if a handler method was created
    found_handler = False
    for node in module_ast.body:
        if isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, ast.AsyncFunctionDef) and item.name.startswith("_handler_"):
                    found_handler = True

    assert found_handler, "No synthetic handler created!"

    # Check if attribute was updated
    assert click_attr.handler_name.startswith("_handler_"), (
        f"Attribute handler_name was not updated correctly! Got: {click_attr.handler_name}"
    )
