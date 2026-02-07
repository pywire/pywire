import asyncio
import unittest
from unittest.mock import MagicMock
from pywire.runtime.page import BasePage

class TestSlotRuntime(unittest.TestCase):
    def setUp(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        
    def tearDown(self):
        self.loop.close()

    def test_named_slots_rendering(self):
        # 1. Component with named slots
        class Card(BasePage):
            LAYOUT_ID = "CARD"
            
            async def _render_template(self) -> str:
                # <div class="card">
                #   <div class="header"><slot name="header" /></div>
                #   <div class="body"><slot /></div>
                # </div>
                
                header_renderer = self.slots.get("CARD", {}).get("header")
                header_content = await header_renderer() if header_renderer else ""
                
                default_renderer = self.slots.get("CARD", {}).get("default")
                body_content = await default_renderer() if default_renderer else "Default Body"
                
                return f"<card><header>{header_content}</header><body>{body_content}</body></card>"

        # 2. Usage Page
        class Page(Card):
            # NO LAYOUT_ID (it inherits Card behavior but acts as usage)
            # Conceptually: <Card><template slot="header">My Header</template>My Body</Card>
            
            # Implementation: Register slots for parent layout CARD
            
            async def _fill_header(self):
                return "My Header"
            
            async def _fill_default(self):
                return "My Body"
                
            def _init_slots(self):
                # Manually simulate what codegen does
                super()._init_slots() if hasattr(super(), "_init_slots") else None
                self.register_slot("CARD", "header", self._fill_header)
                self.register_slot("CARD", "default", self._fill_default)

        
        request = MagicMock()
        page = Page(request, {}, {})
        page._init_slots()
        
        content = self.loop.run_until_complete(page._render_template())
        self.assertEqual(content, "<card><header>My Header</header><body>My Body</body></card>")

    def test_slot_fallback(self):
        # Test fallback content when slot is missing
        class Card(BasePage):
            LAYOUT_ID = "CARD_FB"
            async def _render_template(self) -> str:
                renderer = self.slots.get("CARD_FB", {}).get("default")
                # Fallback "Default Content"
                content = await renderer() if renderer else "Fallback"
                return f"<div>{content}</div>"

        class Page(Card):
            def _init_slots(self):
                super()._init_slots() if hasattr(super(), "_init_slots") else None
                # Don't register default slot

        request = MagicMock()
        page = Page(request, {}, {})
        page._init_slots()
        content = self.loop.run_until_complete(page._render_template())
        self.assertEqual(content, "<div>Fallback</div>")

    def test_head_slot_runtime(self):
         # Validates <pywire-head> -> register_head_slot -> rendering
         # CodeGen generates: self.register_head_slot(layout_id, renderer)
         # Layout renders: self.render_slot("$head", ..., append=True)
         
         class Layout(BasePage):
             LAYOUT_ID = "MAIN"
             async def _render_template(self):
                 # <head><slot name="$head" /></head>
                 # Note: $head is special, it aggregates.
                 head_content = await self.render_slot("$head", layout_id="MAIN", append=True)
                 return f"<head>{head_content}</head>"
                 
         class Page(Layout):
             async def _fill_head(self):
                 return "<meta foo>"
                 
             def _init_slots(self):
                 super()._init_slots() if hasattr(super(), "_init_slots") else None
                 self.register_head_slot("MAIN", self._fill_head)
                 
         request = MagicMock()
         page = Page(request, {}, {})
         page._init_slots()
         content = self.loop.run_until_complete(page._render_template())
         self.assertEqual(content, "<head><meta foo></head>")

if __name__ == "__main__":
    unittest.main()
