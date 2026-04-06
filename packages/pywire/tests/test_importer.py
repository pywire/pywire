"""Tests for the .wire import hook and native component loading."""

import sys
from pathlib import Path
from textwrap import dedent

import pytest

from pywire.runtime.page import BasePage


def test_import_hook(tmp_path: Path) -> None:
    from pywire.runtime.importer import install_import_hook

    install_import_hook()
    sys.path.insert(0, str(tmp_path))

    # Use my_button.wire so PascalCase yields MyButton
    (tmp_path / "my_button.wire").write_text(
        dedent("""
            ---
            from pywire import props
            @props
            class Props:
                label: str = "Click Me"
            ---
            <button>{label}</button>
        """)
    )

    try:
        import my_button  # noqa: F401

        assert hasattr(my_button, "MyButton")
        assert issubclass(my_button.MyButton, BasePage)
    finally:
        sys.path.remove(str(tmp_path))
        sys.modules.pop("my_button", None)


@pytest.mark.asyncio
async def test_native_component_import_and_render(tmp_path: Path) -> None:
    from pywire.runtime.importer import install_import_hook

    install_import_hook()
    sys.path.insert(0, str(tmp_path))

    (tmp_path / "child.wire").write_text(
        dedent("""
            ---
            from pywire import props
            @props
            class Props:
                message: str = "Hello"
            ---
            <div class="child">{message}</div>
        """)
    )
    (tmp_path / "parent.wire").write_text(
        dedent("""
            ---
            from child import Child
            ---
            <div class="parent">
                <h1>Parent</h1>
                <Child message="Greetings from Parent" />
            </div>
        """)
    )

    try:
        import parent  # noqa: F401

        Component = parent.Parent
        instance = Component(request=None, params={}, query={})
        html = await instance._render_template()
        assert "Parent" in html
        assert "Greetings from Parent" in html
        assert 'class="child"' in html
    finally:
        sys.path.remove(str(tmp_path))
        for name in ("child", "parent"):
            sys.modules.pop(name, None)
