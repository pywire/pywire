import os
from pathlib import Path
from textwrap import dedent
import sys

# Add src to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

def test_native_component_import():
    from pywire.runtime.importer import install_import_hook
    install_import_hook()
    
    # Create temp directory for components
    temp_dir = Path(__file__).parent / "temp_phase3"
    temp_dir.mkdir(exist_ok=True)
    sys.path.append(str(temp_dir))
    
    # 1. Create a Child component
    child_file = temp_dir / "Child.wire"
    child_file.write_text(dedent("""
        ---
        from pywire import props
        @props
        class Props:
            message: str = "Hello"
        ---
        <div class="child">{message}</div>
    """))
    
    # 2. Create a Parent component that imports Child
    parent_file = temp_dir / "Parent.wire"
    parent_file.write_text(dedent("""
        ---
        from Child import Child
        ---
        <div class="parent">
            <h1>Parent</h1>
            <Child message="Greetings from Parent" />
        </div>
    """))
    
    try:
        # Import Parent
        import Parent
        Component = Parent.Parent
        print(f"Parent component class: {Component}")
        
        # Instantiate and render (mocking request etc)
        from pywire.runtime.app import PyWire
        app = PyWire(pages_dir=str(temp_dir))
        
        # We'll use the loader to get an instance (easier than mocking request)
        from pywire.runtime.loader import get_loader
        loader = get_loader()
        
        # Test rendering
        import asyncio
        async def run_render():
            instance = Component(request=None, params={}, query={})
            html = await instance._render_template()
            print("Rendered HTML:")
            print(html)
            assert "Parent" in html
            assert "Greetings from Parent" in html
            assert 'class="child"' in html
            
        asyncio.run(run_render())
        print("Rendering successful!")
        
    finally:
        # Cleanup
        for f in temp_dir.glob("*.wire"):
            f.unlink()
        if temp_dir.exists():
            import shutil
            shutil.rmtree(temp_dir)

if __name__ == "__main__":
    test_native_component_import()
    print("Phase 3 native import test passed!")
