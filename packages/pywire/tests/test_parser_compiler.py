import unittest

from pywire.compiler.ast_nodes import (
    InterpolationNode,
    LayoutDirective,
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
        content = """---
name = 'World'
def hello(): pass
---
<h1>Title</h1>"""
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
        content = "!layout 'main.wire'\n<div>Content</div>"
        parsed = self.parser.parse(content)
        self.assertEqual(len(parsed.directives), 1)
        assert isinstance(parsed.directives[0], LayoutDirective)
        self.assertEqual(parsed.directives[0].layout_path, "main.wire")


if __name__ == "__main__":
    unittest.main()
