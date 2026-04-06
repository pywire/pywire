import unittest

from pywire.runtime.style_collector import StyleCollector


class TestStyleCollector(unittest.TestCase):
    def test_add_new_style(self) -> None:
        collector = StyleCollector()
        result = collector.add("scope1", ".scope1 { color: red; }")
        self.assertTrue(result)
        self.assertEqual(collector._styles["scope1"], ".scope1 { color: red; }")

    def test_add_duplicate_style(self) -> None:
        collector = StyleCollector()
        collector.add("scope1", ".scope1 { color: red; }")
        result = collector.add("scope1", ".scope1 { color: red; }")
        self.assertFalse(result)

    def test_render_empty(self) -> None:
        collector = StyleCollector()
        self.assertEqual(collector.render(), "")

    def test_render_styles(self) -> None:
        collector = StyleCollector()
        collector.add("scope1", ".a { color: red; }")
        collector.add("scope2", ".b { color: blue; }")

        rendered = collector.render()
        self.assertTrue(rendered.startswith("<style>"))
        self.assertTrue(rendered.endswith("</style>"))
        self.assertIn(".a { color: red; }", rendered)
        self.assertIn(".b { color: blue; }", rendered)


if __name__ == "__main__":
    unittest.main()
