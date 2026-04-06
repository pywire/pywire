
import asyncio
from pywire.compiler.parser import PyWireParser
from pywire.compiler.codegen.generator import CodeGenerator
from pywire.runtime.page import BasePage
from pywire.core.wire import wire

# Mock print to verify it was called
printed_data = []
def mock_print(*args):
    printed_data.append(args)

def test_click_print_success():
    source = """
    <div>
        <button @click={print}>Click Me</button>
    </div>
    """
    parser = PyWireParser()
    parsed = parser.parse(source)
    generator = CodeGenerator()
    ast_mod = generator.generate(parsed)
    import ast
    code = ast.unparse(ast_mod)
    print("DEBUG CODE:\n", code)
    
    # Execute generated code to get the Page class
    namespace = {"print": mock_print}
    exec(code, namespace)
    PageClass = namespace["Page"]
    
    # Instantiate
    page = PageClass(None, {}, {}, {})
    
    # Simulate event
    # Construct raw event data like the client sends
    raw_event = {
        "type": "click",
        "clientX": 100,
        "clientY": 200,
        "target_tag": "BUTTON"
    }
    
    asyncio.run(page.handle_event("_handler_0", raw_event))
    
    assert len(printed_data) > 0
    event_obj = printed_data[0][0]
    from pywire.runtime.events import MouseEventData
    assert isinstance(event_obj, MouseEventData)
    assert event_obj.type == "click"
    assert event_obj.client_x == 100
    assert event_obj.client_y == 200
    
    print("Test SUCCEEDED!")

if __name__ == "__main__":
    try:
        test_click_print_success()
    except Exception as e:
        import traceback
        traceback.print_exc()
        exit(1)

if __name__ == "__main__":
    test_click_print_failure()
    print("Test finished")
