import pytest
from pywire.core.wire import wire, set_render_context, reset_render_context
from pywire.runtime.page import BasePage
from pywire.core.wire import wire
from pywire.runtime.page import BasePage
# from starlette.requests import Request # Avoid importing if mocking

class MockApp:
    def __init__(self):
        self.state = type("State", (), {"enable_pjax": False, "debug": False, "pywire": None})()

class MockRequest:
    def __init__(self):
        self.app = MockApp()

class PartialUpdatePage(BasePage):
    def __init__(self, **kwargs):
        super().__init__(MockRequest(), {}, {}, **kwargs)
        self.count = wire(0)
        self.static_val = 100
        
    async def _render_template(self):
        # Emulate: <div>{self.count} - {self.static_val}</div>
        # With static caching for self.static_val
        
        parts = []
        
        # {self.count} - Reactive, uses wire, wrapped in _render_expr
        count_val = self._render_expr("expr_count", lambda: self.count.value)
        parts.append(str(count_val))
        
        parts.append(" - ")
        
        # {self.static_val} - Static, no wire, wrapped in _render_expr
        static_val = self._render_expr("expr_static", lambda: self.static_val)
        parts.append(str(static_val))
        
        return "".join(parts)

@pytest.mark.asyncio
async def test_partial_update_static_cache():
    page = PartialUpdatePage()
    
    # 1. Initial Render
    html = await page.render(init=True)
    assert html.body.decode() == "0 - 100"
    
    # Check cache
    assert "expr_static:0" in page._static_cache
    assert page._static_cache["expr_static:0"] == 100
    
    # 2. Update Wire
    page.count.value = 1
    
    # 3. Simulate Side Effect on Static Var
    page.static_val = 999 
    
    # 4. Render Update (simulate region update logic)
    # Since we don't have full regions here, we assume _render_template is called 
    # but we want to know if _render_expr returns cached value.
    
    # Manually invoke expression evaluation logic as if inside a re-render
    # We must start a "region update" context (reset counts)
    page._expr_counts.clear()
    
    # Establish context explicitly so wire tracking works!
    token = set_render_context(page, "test_region")
    try:
        # Re-evaluate count (should be new value, not cached because it had deps)
        count_res = page._render_expr("expr_count", lambda: page.count.value)
        assert count_res == 1
        
        # Re-evaluate static (should be OLD value 100, not 999)
        static_res = page._render_expr("expr_static", lambda: page.static_val)
        assert static_res == 100
    finally:
        reset_render_context(token)
    
    # Verify strictness: if we force clear cache, it updates
    page._static_cache.clear()
    page._expr_counts["expr_static"] = 0 # reset count for id
    
    # We need context again for correct tracking (even if static, we need to check deps)
    token = set_render_context(page, "test_region")
    try:
        static_res_fresh = page._render_expr("expr_static", lambda: page.static_val)
        assert static_res_fresh == 999
    finally:
        reset_render_context(token)

@pytest.mark.asyncio
async def test_loop_static_cache():
    # Test collision handling in loops
    page = PartialUpdatePage()
    page._expr_counts.clear()
    
    # Mock loop: 2 iterations of same static expression
    # Iter 1
    val1 = page._render_expr("loop_expr", lambda: "A")
    assert val1 == "A"
    
    # Iter 2
    val2 = page._render_expr("loop_expr", lambda: "A") 
    assert val2 == "A"
    
    # Verify unique entries
    assert "loop_expr:0" in page._static_cache
    assert "loop_expr:1" in page._static_cache

