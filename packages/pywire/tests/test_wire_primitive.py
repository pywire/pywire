import ast
import asyncio
import pytest
from textwrap import dedent
from types import SimpleNamespace
from pywire.compiler.parser import PyWireParser
from pywire.compiler.codegen.generator import CodeGenerator
from pywire.runtime.loader import PageLoader

def test_wire_primitive_compilation():
    source = dedent("""
        ---
        count = wire(0)
        ---

        <div>
            Count: {count}
            <button @click={count += 1}>Inc</button>
        </div>
    """)
    
    parser = PyWireParser()
    parsed = parser.parse(source, "test.pywire")
    
    generator = CodeGenerator()
    module_ast = generator.generate(parsed)
    code = ast.unparse(module_ast)
    
    print("\nGenerated Code:\n", code)
    
    # 1. Verify initialization
    assert "self.count = wire(0)" in code
    
    # 2. Verify Render Usage
    # {count} -> unwrap_wire(self.count)
    assert "unwrap_wire(self.count)" in code
    
    # 3. Verify Handler Usage
    # @click={count += 1} -> self.count += 1
    # NOTE: Since preprocessor is now no-op, it stays self.count += 1
    # And and wire objects support += via __iadd__ if implemented, 
    # but here it's likely transformed by the assignment lifter to self.count
    assert "self.count += 1" in code

    # 4. Verify __top_level_init__ calls
    # Should be called in __init__, not just INIT_HOOKS
    assert "self.__top_level_init__()" in code

def test_wire_string_handling():
    """Ensure $ inside strings is NOT replaced."""
    source = dedent("""
        ---
        text = wire("$100")
        dummy = "$not_a_var"
        ---

        <div>
            Text: {text}
        </div>
    """)
    
    parser = PyWireParser()
    parsed = parser.parse(source, "test.pywire")
    
    generator = CodeGenerator()
    module_ast = generator.generate(parsed)
    code = ast.unparse(module_ast)
    
    print("\nGenerated Code String:\n", code)
    
    # Initialization should keep "$100" literal
    assert 'self.text = wire("$100")' in code or "self.text = wire('$100')" in code
    
    # Dummy assignment should keep "$not_a_var" - literals stay class attributes
    assert "dummy = '$not_a_var'" in code or 'dummy = "$not_a_var"' in code
    
    # Interpolation should work
    assert "unwrap_wire(self.text)" in code


@pytest.mark.asyncio
async def test_wire_auto_unwrap_in_template(tmp_path) -> None:
    source = dedent(
        """
        ---
        count = wire(0)
        user = wire(name="Alice")
        ---

        <div>
            <p>Count: {count}</p>
            <p>User: {user}</p>
        </div>
        """
    )
    file_path = tmp_path / "page.wire"
    file_path.write_text(source)

    loader = PageLoader()
    page_class = loader.load(file_path)
    from types import SimpleNamespace

    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        sibling_paths=[], enable_pjax=False, debug=False
    )))
    page = page_class(request, {}, {}, {}, None)
    html = await page._render_template()

    assert "Count: 0" in html
    assert "User: {'name': 'Alice'}" in html


@pytest.mark.asyncio
async def test_wire_region_updates(tmp_path) -> None:
    source = dedent(
        """
        ---
        count = wire(0)

        def increment():
            self.count += 1
        ---

        <div>
            <p>Count: {count}</p>
            <button @click={increment}>Inc</button>
        </div>
        """
    )
    file_path = tmp_path / "page.wire"
    file_path.write_text(source)

    loader = PageLoader()
    page_class = loader.load(file_path)
    from types import SimpleNamespace

    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        sibling_paths=[], enable_pjax=False, debug=False
    )))
    page = page_class(request, {}, {}, {}, None)
    await page.render()
    update = await page.handle_event("increment", {})

    assert update["type"] == "regions"
    assert update["regions"]
    assert "data-pw-region" in update["regions"][0]["html"]
    assert "Count: 1" in update["regions"][0]["html"]


@pytest.mark.asyncio
async def test_wire_dot_value_compilation_and_updates(tmp_path) -> None:
    source = dedent(
        """
        ---
        count = wire(0)
        ---

        <div>
            <p>Raw: {count}</p>
            <p>Value: {count.value}</p>
        </div>
        """
    )
    parser = PyWireParser()
    parsed = parser.parse(source, "test.pywire")

    generator = CodeGenerator()
    module_ast = generator.generate(parsed)
    code = ast.unparse(module_ast)

    assert "unwrap_wire(self.count).value" not in code

    file_path = tmp_path / "page.wire"
    file_path.write_text(source)
    loader = PageLoader()
    page_class = loader.load(file_path)

    from types import SimpleNamespace

    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(sibling_paths=[], enable_pjax=False, debug=False))
    )
    page = page_class(request, {}, {}, {}, None)

    initial = await page.render(init=True)
    html = initial.body.decode()
    assert "Raw: 0" in html
    assert "Value: 0" in html

    page.count.value = 1
    update = await page.render_update()
    if update["type"] == "full":
        assert "Raw: 1" in update["html"]
        assert "Value: 1" in update["html"]
        return
    assert any("Raw: 1" in region["html"] for region in update["regions"])
    assert any("Value: 1" in region["html"] for region in update["regions"])


@pytest.mark.asyncio
async def test_loop_click_handler_id_based_runtime(tmp_path) -> None:
    """Regression: @click={delete_by_id(item.get('id',''))} inside $for receives id, not full object."""
    source = dedent(
        """
        ---
        items = wire([{"id": "a", "name": "A"}, {"id": "b", "name": "B"}])
        deleted_ids = wire([])

        def delete_by_id(rid):
            self.deleted_ids.append(rid)
            kept = [x for x in self.items.value if x.get("id") != rid]
            self.items.clear()
            self.items.extend(kept)
        ---

        <div>
            <div $for={item in items.value} $key={item.get('id','')}>
                <span>{item.get('name','')}</span>
                <button @click={delete_by_id(item.get('id', ''))}>Del</button>
            </div>
        </div>
        """
    )
    file_path = tmp_path / "page.wire"
    file_path.write_text(source)

    loader = PageLoader()
    page_class = loader.load(file_path)
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(sibling_paths=[], enable_pjax=False, debug=False))
    )
    page = page_class(request, {}, {}, {}, None)

    html = await page._render_template()
    assert "A" in html
    assert "B" in html

    # Simulate click on first row's delete - handler receives id "a"
    update = await page.handle_event("_handler_0", {"type": "click", "args": {"arg0": "a"}})
    assert update["type"] in ("regions", "full")
    assert page.deleted_ids.value == ["a"]
    assert len(page.items.value) == 1
    assert page.items.value[0].get("id") == "b"

