import unittest
from pywire.compiler.parser import PyWireParser, PyWireSyntaxError
from pywire.compiler.codegen.template import TemplateCodegen
from pywire.compiler.ast_nodes import IfAttribute, ForAttribute


class TestControlFlow(unittest.TestCase):
    def test_if_block(self):
        source = """{$if True}
    <div>Found</div>
{/if}
"""
        parser = PyWireParser()
        ast = parser.parse(source)
        node = ast.template[0]

        # Check node type (tag=None -> template wrapper)
        self.assertIsNone(node.tag)
        # Check IfAttribute
        if_attrs = [a for a in node.special_attributes if isinstance(a, IfAttribute)]
        self.assertEqual(len(if_attrs), 1)
        self.assertEqual(if_attrs[0].condition, "True")

        # Check child exists (ignoring whitespace)
        real_children = [c for c in node.children if c.tag]
        self.assertEqual(len(real_children), 1)  # div

    def test_html_block(self):
        source = """{$html "<b>Raw</b>"}
"""
        parser = PyWireParser()
        ast = parser.parse(source)
        node = ast.template[0]
        self.assertIsNone(node.tag)
        from pywire.compiler.ast_nodes import InterpolationNode

        interp_attrs = [
            a for a in node.special_attributes if isinstance(a, InterpolationNode)
        ]
        self.assertEqual(len(interp_attrs), 1)
        self.assertTrue(interp_attrs[0].is_raw)
        self.assertEqual(interp_attrs[0].expression, '"<b>Raw</b>"')

    def test_for_block_valid(self):
        source = """{$for item in items}
    <div>{item}</div>
{/for}
"""
        parser = PyWireParser()
        ast = parser.parse(source)
        node = ast.template[0]
        self.assertIsNone(node.tag)
        for_attrs = [a for a in node.special_attributes if isinstance(a, ForAttribute)]
        self.assertEqual(len(for_attrs), 1)
        self.assertEqual(for_attrs[0].iterable, "items")

    def test_for_block_single_root_valid(self):
        source = """{$for i in x}
   <!-- comment -->
   <div>Single Root</div>
{/for}
"""
        parser = PyWireParser()
        parser.parse(source)  # Should pass

    def test_for_block_invalid_multi_root(self):
        source = """{$for i in x}
   <div>Root 1</div>
   <div>Root 2</div>
{/for}
"""
        parser = PyWireParser()
        with self.assertRaises(PyWireSyntaxError) as cm:
            parser.parse(source)
        self.assertIn("must have exactly one root element", str(cm.exception))

    def test_for_else(self):
        source = """<ul>
    {$for item in items}
        <li>{item}</li>
    {$else}
        <li class="empty-state">Empty</li>
    {/for}
</ul>
"""
        parser = PyWireParser()
        parsed = parser.parse(source)

        import ast

        codegen = TemplateCodegen()
        body = []
        # Simulate items is empty
        codegen._add_node(parsed.template[0], body, local_vars={"items"})

        # Verify AST contains the loop_any flag and If block
        dump = "\n".join(ast.dump(s) for s in body)
        self.assertIn("_loop_any", dump)
        self.assertIn("AsyncFor", dump)
        self.assertIn("If(test=UnaryOp(op=Not()", dump)

    def test_keyed_for_multi_root(self):
        source = """<ul>
    {$for key, val in items.items(), key=key}
        <dt>{key}</dt>
        <dd>{val}</dd>
    {/for}
</ul>
"""
        parser = PyWireParser()
        parser.parse(source)  # Should pass


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------------------
# Runtime tests for $if attribute-form behaviour
# ---------------------------------------------------------------------------

import pytest
from textwrap import dedent
from types import SimpleNamespace
from pywire.runtime.loader import PageLoader


def _make_page(tmp_path, source):
    file_path = tmp_path / "page.wire"
    file_path.write_text(dedent(source))
    loader = PageLoader()
    page_class = loader.load(file_path)
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(sibling_paths=[], enable_pjax=False, debug=False)
        )
    )
    return page_class(request, {}, {}, {}, None)


@pytest.mark.asyncio
async def test_if_attribute_form_renders_tag_when_true(tmp_path):
    """<p $if={True}>text</p> — both the tag and its text must appear."""
    page = _make_page(
        tmp_path,
        """
        <p $if={True}>hello</p>
        """,
    )
    html = await page._render_template()
    assert "<p" in html
    assert "hello" in html


@pytest.mark.asyncio
async def test_if_attribute_form_omits_tag_when_false(tmp_path):
    """<p $if={False}>text</p> — neither tag nor text should appear."""
    page = _make_page(
        tmp_path,
        """
        <p $if={False}>hidden</p>
        """,
    )
    html = await page._render_template()
    assert "<p" not in html
    assert "hidden" not in html


@pytest.mark.asyncio
async def test_if_attribute_form_sibling_not_affected(tmp_path):
    """$if on one element must not remove sibling elements without their own $if."""
    page = _make_page(
        tmp_path,
        """
        <p $if={False}>gone</p>
        <button>stays</button>
        """,
    )
    html = await page._render_template()
    assert "gone" not in html
    assert "stays" in html
    assert "<button" in html


@pytest.mark.asyncio
async def test_if_attribute_form_wrapper_groups_siblings(tmp_path):
    """Wrapper div with $if controls all its children as a unit."""
    page = _make_page(
        tmp_path,
        """
        <div $if={False}>
            <p>text 1</p>
            <p>text 2</p>
            <button>click</button>
        </div>
        """,
    )
    html = await page._render_template()
    assert "text 1" not in html
    assert "text 2" not in html
    assert "click" not in html
