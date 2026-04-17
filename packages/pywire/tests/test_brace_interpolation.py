import unittest

from pywire.compiler.ast_nodes import InterpolationNode
from pywire.compiler.interpolation.brace import BraceInterpolationParser


class TestBraceInterpolation(unittest.TestCase):
    def setUp(self) -> None:
        self.parser = BraceInterpolationParser()

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
        self.assertEqual(self.parser.compile(None), "''")

    # ------------------------------------------------------------------
    # Brace escape: \{ → literal {, \} → literal }
    # ------------------------------------------------------------------

    def test_parse_escaped_open_brace(self) -> None:
        result = self.parser.parse(r"a \{ b", 1, 0)
        self.assertEqual(result, ["a { b"])

    def test_parse_escaped_close_brace(self) -> None:
        result = self.parser.parse(r"a \} b", 1, 0)
        self.assertEqual(result, ["a } b"])

    def test_parse_escape_then_interp(self) -> None:
        result = self.parser.parse(r"\{ {name} \}", 1, 0)
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0], "{ ")
        assert isinstance(result[1], InterpolationNode)
        self.assertEqual(result[1].expression, "name")
        self.assertEqual(result[2], " }")

    def test_parse_bare_backslash_unchanged(self) -> None:
        # Backslash not followed by `{` or `}` passes through verbatim.
        result = self.parser.parse(r"path\to\file", 1, 0)
        self.assertEqual(result, [r"path\to\file"])

    def test_parse_alpine_data_style(self) -> None:
        # Regression for Alpine `x-data` literal attribute usage.
        text = r"\{ step: 1, total: 3 \}"
        result = self.parser.parse(text, 1, 0)
        self.assertEqual(result, ["{ step: 1, total: 3 }"])

    def test_compile_escaped_braces(self) -> None:
        # Doubled braces in f-string source → single literal brace at runtime.
        compiled = self.parser.compile(r"a \{ b \}")
        self.assertEqual(compiled, "f'a {{ b }}'")
        # Confirm the f-string evaluates to the expected literal.
        self.assertEqual(eval(compiled), "a { b }")

    def test_compile_escape_with_interp(self) -> None:
        compiled = self.parser.compile(r"\{ {name} \}")
        self.assertIn("{{", compiled)
        self.assertIn("}}", compiled)
        self.assertIn("self.name", compiled)


if __name__ == "__main__":
    unittest.main()
