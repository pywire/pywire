import ast
import sys
import os

# Add src to path
sys.path.append(os.path.join(os.getcwd(), "src"))

# Mock starlette and other dependencies that might be missing
from unittest.mock import MagicMock
sys.modules["starlette"] = MagicMock()
sys.modules["starlette.applications"] = MagicMock()
sys.modules["starlette.responses"] = MagicMock()
sys.modules["watchfiles"] = MagicMock()
sys.modules["uvicorn"] = MagicMock()

from pywire.compiler.parser import PyWireParser
from pywire.compiler.codegen.generator import CodeGenerator

source = """
---
from pywire.components import Form
---
<Form>
    <input type="text" name="username" />
</Form>
"""

parser = PyWireParser()
parsed = parser.parse(source, "repro.wire")

generator = CodeGenerator()
module_ast = generator.generate(parsed)
code = ast.unparse(module_ast)
print(code)
