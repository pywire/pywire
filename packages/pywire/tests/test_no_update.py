import unittest
from unittest.mock import Mock, AsyncMock
from pywire.runtime.page import BasePage

class TestNoUpdate(unittest.IsolatedAsyncioTestCase):
    async def test_no_update_when_clean(self):
        # Setup page with region support
        request = Mock()
        page = BasePage(request, {}, {})
        
        # Mock region renderers to simulate a compiled page
        page.__region_renderers__ = {"r1": "_render_r1"}
        page._render_r1 = AsyncMock(return_value="<div>Content</div>")
        
        # Initial state: clean
        page._dirty_regions = set()
        
        # Call render_update(init=False)
        result = await page.render_update(init=False)
        
        # Expect empty regions update, NOT full update
        self.assertEqual(result["type"], "regions")
        self.assertEqual(result["regions"], [])
        
    async def test_update_when_dirty(self):
        request = Mock()
        page = BasePage(request, {}, {})
        page.__region_renderers__ = {"r1": "_render_r1"}
        page._render_r1 = AsyncMock(return_value="<div>New Content</div>")
        
        # Mark dirty
        page._dirty_regions.add("r1")
        
        result = await page.render_update(init=False)
        
        self.assertEqual(result["type"], "regions")
        self.assertEqual(len(result["regions"]), 1)
        self.assertEqual(result["regions"][0]["region"], "r1")
        self.assertEqual(result["regions"][0]["html"], "<div>New Content</div>")

if __name__ == "__main__":
    unittest.main()
