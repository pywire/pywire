import unittest

from pywire.compiler.ast_nodes import (
    ComponentDirective,
    InjectDirective,
    InterpolationNode,
    LayoutDirective,
    PropsDirective,
    ProvideDirective,
)
from pywire.compiler.parser import PyWireParser


class TestParserCompiler(unittest.TestCase):
    def setUp(self) -> None:
        self.parser = PyWireParser()

    def test_parse_simple_html(self) -> None:
        content = "<div><span>Hello</span></div>"
        parsed = self.parser.parse(content)
        self.assertEqual(len(parsed.template), 1)
        root = parsed.template[0]
        self.assertEqual(root.tag, "div")
        self.assertEqual(len(root.children), 1)
        self.assertEqual(root.children[0].tag, "span")

    def test_parse_with_python(self) -> None:
        content = """<h1>Title</h1>\n---\nname = 'World'\ndef hello(): pass"""
        parsed = self.parser.parse(content)
        self.assertEqual(parsed.template[0].tag, "h1")
        self.assertIn("name = 'World'", parsed.python_code)
        self.assertIsNotNone(parsed.python_ast)

    def test_parse_interpolation(self) -> None:
        content = "<div>Hello {name}!</div>"
        parsed = self.parser.parse(content)
        div = parsed.template[0]
        self.assertEqual(len(div.children), 3)
        # Interpolation is wrapped in a TemplateNode with tag=None
        interp_wrapper = div.children[1]
        self.assertIsNone(interp_wrapper.tag)
        assert isinstance(interp_wrapper.special_attributes[0], InterpolationNode)
        self.assertEqual(interp_wrapper.special_attributes[0].expression, "name")

    def test_parse_directives(self) -> None:
        content = "!layout 'main.pywire'\n<div>Content</div>"
        parsed = self.parser.parse(content)
        self.assertEqual(len(parsed.directives), 1)
        assert isinstance(parsed.directives[0], LayoutDirective)
        self.assertEqual(parsed.directives[0].layout_path, "main.pywire")

    def test_extract_form_validation(self) -> None:
        content = """
<form @submit={save}>
    <input name="email" type="email" required minlength="5">
    <input name="age" type="number" min="18">
</form>
"""
        parsed = self.parser.parse(content)
        form = parsed.template[0]
        # The parser extracts validation schema for forms with @submit
        from pywire.compiler.ast_nodes import EventAttribute

        submit_attr = next(
            a
            for a in form.special_attributes
            if isinstance(a, EventAttribute) and a.event_type == "submit"
        )
        assert isinstance(submit_attr, EventAttribute)
        self.assertIsNotNone(submit_attr.validation_schema)
        schema = submit_attr.validation_schema
        assert schema is not None
        fields = schema.fields
        self.assertIn("email", fields)
        self.assertTrue(fields["email"].required)
        self.assertEqual(fields["email"].minlength, 5)
        self.assertEqual(fields["age"].min_value, "18")

    def test_parse_component_directive(self) -> None:
        content = "!component 'components/button' as Button"
        parsed = self.parser.parse(content)
        self.assertEqual(len(parsed.directives), 1)
        d = parsed.directives[0]
        assert isinstance(d, ComponentDirective)
        self.assertEqual(d.path, "components/button")
        self.assertEqual(d.component_name, "Button")

    def test_parse_props_directive(self) -> None:
        content = "!props(title: str, count: int = 0)"
        parsed = self.parser.parse(content)
        self.assertEqual(len(parsed.directives), 1)
        d = parsed.directives[0]
        assert isinstance(d, PropsDirective)
        self.assertEqual(len(d.args), 2)
        self.assertEqual(d.args[0], ("title", "str", None))
        self.assertEqual(d.args[1], ("count", "int", "0"))

    def test_parse_provide_inject(self) -> None:
        # Provide
        content = "!provide { 'theme': 'dark' }\n!inject { theme: 'theme' }\n<div></div>"
        parsed = self.parser.parse(content)
        self.assertEqual(len(parsed.directives), 2)
        assert isinstance(parsed.directives[0], ProvideDirective)
        assert isinstance(parsed.directives[1], InjectDirective)
        self.assertEqual(parsed.directives[0].mapping, {"theme": "'dark'"})
        self.assertEqual(parsed.directives[1].mapping, {"theme": "theme"})


if __name__ == "__main__":
    unittest.main()
