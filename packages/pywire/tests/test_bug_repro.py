import ast
import pytest
from pywire.compiler.parser import PyWireParser
from pywire.compiler.codegen.generator import CodeGenerator
import asyncio
from unittest.mock import MagicMock, AsyncMock
import sys
from pathlib import Path

# Add src to path for real components
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


class TestBugFix:
    @pytest.mark.asyncio
    async def test_shadowing_and_directive_fix_real(self):
        source = """
---
from pywire.components import Form
show = True
---
<div id="wrapper">
    <Form $if={show}>
        <input name="username" />
    </Form>
    <form id="standard-form">
        <input name="password" />
    </form>
</div>
"""
        parser = PyWireParser()
        parsed = parser.parse(source, "repro.wire")

        generator = CodeGenerator()
        module_ast = generator.generate(parsed)
        code = ast.unparse(module_ast)

        # Mock the environment for exec
        mock_base_page = AsyncMock()
        # Ensure _resolve_component returns an AsyncMock for the component
        mock_base_page.return_value._resolve_component.return_value = AsyncMock()

        namespace = {
            "BasePage": mock_base_page,
            "wire": lambda x: x,
            "unwrap_wire": lambda x: x,
            "set_render_context": MagicMock(),
            "reset_render_context": MagicMock(),
            "derived": MagicMock(),
            "effect": MagicMock(),
            "props": lambda x: x,
            "expose": lambda x: x,
            "Response": MagicMock(),
            "load_component": MagicMock(),
            "render_attrs": lambda attrs, spread: "".join(
                f' {k}="{v}"' for k, v in attrs.items()
            ),
            "asyncio": asyncio,
            "ensure_async_iterator": lambda x: x,
            "escape_html": lambda x: x,
            "json": MagicMock(),
        }

        # Execute the generated code
        exec(code, namespace)
        page_class = namespace["ReproPage"]

        # Mock request
        mock_request = MagicMock()
        mock_request.app.state.pywire._get_client_script_url.return_value = "/pywire.js"

        # Instantiate page
        page = page_class(mock_request, {}, {})

        # Render
        content = await page._render_template()

        # 1. Check directive fix: <Form $if={show}> should render its <form> tag
        # The real Form component adds data-pw-ref
        assert '<form data-pw-ref="' in content
        assert 'data-pw-ref="' in content
        assert "pw-ref-" in content
        assert '<input name="username"' in content

        # 2. Check shadowing fix: <form id="standard-form"> should render as a standard tag
        # Standard tags do NOT get data-pw-ref unless explicitly added
        assert '<form id="standard-form">' in content

        # Double check: the standard form shouldn't have been "componentized"
        # If it were, it would likely have the structure of the Form component
        # (which includes a data-pw-ref)
        standard_form_html_part = content.split('id="standard-form"')[0].rsplit("<", 1)[
            -1
        ]
        assert "data-pw-ref" not in standard_form_html_part
