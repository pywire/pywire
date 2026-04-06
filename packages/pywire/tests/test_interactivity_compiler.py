import unittest

from pywire.compiler.ast_nodes import EventAttribute
from pywire.compiler.attributes.events import EventAttributeParser
from pywire.compiler.codegen.attributes.events import EventAttributeCodegen


class TestInteractivityCompiler(unittest.TestCase):
    def setUp(self) -> None:
        self.parser = EventAttributeParser()
        self.codegen = EventAttributeCodegen()

    def test_parser_basic(self) -> None:
        attr = self.parser.parse("@click", "{handler}", 1, 1)
        assert attr is not None
        self.assertEqual(attr.event_type, "click")
        self.assertEqual(attr.handler_name, "handler")
        self.assertEqual(attr.modifiers, [])

    def test_parser_single_modifier(self) -> None:
        attr = self.parser.parse("@click.prevent", "{handler}", 1, 1)
        assert attr is not None
        self.assertEqual(attr.event_type, "click")
        self.assertEqual(attr.modifiers, ["prevent"])

    def test_parser_multiple_modifiers(self) -> None:
        attr = self.parser.parse("@keyup.enter.stop", "{handler}", 1, 1)
        assert attr is not None
        self.assertEqual(attr.event_type, "keyup")
        self.assertEqual(attr.modifiers, ["enter", "stop"])

    def test_parser_performance_modifiers(self) -> None:
        attr = self.parser.parse("@input.debounce", "{handler}", 1, 1)
        assert attr is not None
        self.assertEqual(attr.modifiers, ["debounce"])

        attr = self.parser.parse("@scroll.throttle", "{handler}", 1, 1)
        assert attr is not None
        self.assertEqual(attr.modifiers, ["throttle"])

    def test_codegen_no_modifiers(self) -> None:
        attr = EventAttribute(
            name="@click",
            value="{handler}",
            event_type="click",
            handler_name="handler",
            modifiers=[],
            line=1,
            column=1,
        )
        html = self.codegen.generate_html(attr)
        self.assertEqual(html, 'data-on-click="handler"')

    def test_codegen_with_modifiers(self) -> None:
        attr = EventAttribute(
            name="@click.prevent.stop",
            value="{handler}",
            event_type="click",
            handler_name="handler",
            modifiers=["prevent", "stop"],
            line=1,
            column=1,
        )
        html = self.codegen.generate_html(attr)
        # Order matters based on implementation
        self.assertIn('data-on-click="handler"', html)
        self.assertIn('data-modifiers-click="prevent stop"', html)

    def test_parser_strip_quotes(self) -> None:
        attr = self.parser.parse("@click", "{handler}", 1, 1)
        assert attr is not None
        self.assertEqual(attr.handler_name, "handler")

    def test_can_parse_validation(self) -> None:
        self.assertTrue(self.parser.can_parse("@click"))
        self.assertTrue(self.parser.can_parse("@anything"))
        self.assertFalse(self.parser.can_parse(":id"))
        self.assertFalse(self.parser.can_parse("class"))

    def test_parser_edge_cases(self) -> None:
        # Multiple dots
        attr = self.parser.parse("@click..stop", "{h}", 1, 1)
        assert attr is not None
        self.assertIn("stop", attr.modifiers)

        # Only @
        attr = self.parser.parse("@", "{h}", 1, 1)
        assert attr is not None
        self.assertEqual(attr.event_type, "")
        self.assertEqual(attr.modifiers, [])


if __name__ == "__main__":
    unittest.main()
