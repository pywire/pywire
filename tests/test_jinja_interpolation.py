import unittest

from pywire.compiler.ast_nodes import InterpolationNode
from pywire.compiler.interpolation.jinja import JinjaInterpolationParser


class TestJinjaInterpolation(unittest.TestCase):
    def setUp(self) -> None:
        self.parser = JinjaInterpolationParser()

    def test_parse_simple_variable(self) -> None:
        text = "Hello {name}!"
        result = self.parser.parse(text, 1, 0)
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0], "Hello ")
        assert isinstance(result[1], InterpolationNode)
        self.assertEqual(result[1].expression, "name")
        self.assertEqual(result[2], "!")

    def test_parse_expression(self) -> None:
        text = "Result: {1 + 2}"
        result = self.parser.parse(text, 1, 0)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0], "Result: ")
        assert isinstance(result[1], InterpolationNode)
        self.assertEqual(result[1].expression, "1 + 2")

    def test_parse_format_specifier(self) -> None:
        text = "Price: {price:.2f}"
        result = self.parser.parse(text, 1, 0)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0], "Price: ")
        assert isinstance(result[1], InterpolationNode)
        self.assertEqual(result[1].expression, "price:.2f")

    def test_parse_css_literal(self) -> None:
        # CSS with braces should be treated as literal if it contains semicolon
        text = ".btn { color: red; }"
        result = self.parser.parse(text, 1, 0)
        self.assertEqual(result, [text])

    def test_parse_unmatched_brace(self) -> None:
        text = "Hello {name"
        result = self.parser.parse(text, 1, 0)
        self.assertEqual(result, [text])

    def test_compile_simple(self) -> None:
        text = "Hello {name}!"
        compiled = self.parser.compile(text)
        self.assertEqual(compiled, "f'Hello {self.name}!'")

    def test_compile_complex_expression(self) -> None:
        text = "Status: {'Active' if is_active else 'Inactive'}"
        compiled = self.parser.compile(text)
        # The current implementation replaces tokens with self.token
        # 'Active' and 'Inactive' are strings, should not be prefixed
        # is_active and else part?
        # Let's see what it actually does.
        self.assertIn("self.is_active", compiled)
        self.assertNotIn("self.if", compiled)
        self.assertNotIn("self.else", compiled)

    def test_compile_format_spec(self) -> None:
        text = "{price:.2f}"
        compiled = self.parser.compile(text)
        self.assertEqual(compiled, "f'{self.price:.2f}'")

    def test_compile_empty(self) -> None:
        self.assertEqual(self.parser.compile(""), "''")
        self.assertEqual(self.parser.compile(None), "''")  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
