import os
from pathlib import Path
from textwrap import dedent
import sys

# Add src to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

def test_import_hook():
    from pywire.runtime.importer import install_import_hook
    install_import_hook()
    
    # Create a temporary .wire component
    temp_dir = Path(__file__).parent / "temp_components"
    temp_dir.mkdir(exist_ok=True)
    sys.path.append(str(temp_dir))
    
    wire_file = temp_dir / "MyButton.wire"
    wire_file.write_text(dedent("""
        ---
        from pywire import props
        @props
        class Props:
            label: str = "Click Me"
        ---
        <button>{label}</button>
    """))
    
    try:
        # Import the component
        import MyButton
        print("Import successful!")
        
        # Check if the class is there
        assert hasattr(MyButton, "MyButton")
        Component = MyButton.MyButton
        print(f"Component class: {Component}")
        
        # Verify it's a PyWire component
        from pywire.runtime.page import BasePage
        assert issubclass(Component, BasePage)
        print("BasePage check passed!")
        
    finally:
        # Cleanup
        if wire_file.exists():
            wire_file.unlink()
        if temp_dir.exists():
            temp_dir.rmdir()

if __name__ == "__main__":
    test_import_hook()
    print("Import hook test passed!")
