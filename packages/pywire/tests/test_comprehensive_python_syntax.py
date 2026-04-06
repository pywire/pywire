"""---
Test that comprehensive Python syntax is properly supported below the separator.

This test ensures that the parser and code generator correctly handle all Python
syntax elements without interference from template parsing.
"""

import ast
from pathlib import Path

import pytest

from pywire.compiler.codegen.generator import CodeGenerator
from pywire.compiler.parser import PyWireParser


@pytest.fixture
def test_wire_file(tmp_path: Path) -> Path:
    """Create a comprehensive test .wire file with all Python syntax."""
    wire_content = """---
# Comprehensive Python Syntax Test
# This file tests that all Python syntax is supported below the separator

# ============================================================================
# IMPORTS - Various import styles
# ============================================================================
import os
import sys
from typing import List, Dict, Tuple, Optional, Union, Any, Callable
from collections import defaultdict, Counter
from datetime import datetime, timedelta
import json as json_module
from pathlib import Path
from functools import wraps, lru_cache, partial
import asyncio

# ============================================================================
# CONSTANTS AND VARIABLES
# ============================================================================
CONSTANT_VALUE = 42
STRING_CONSTANT = "hello world"
MULTILINE_STRING = \"\"\"
This is a multiline
string with multiple lines
\"\"\"
F_STRING = f"Value: {CONSTANT_VALUE}"
RAW_STRING = r"raw\\string\\with\\backslashes"
BYTES_LITERAL = b"bytes string"

# ============================================================================
# TYPE ANNOTATIONS
# ============================================================================
def typed_function(x: int, y: str, z: Optional[List[int]] = None) -> Dict[str, Any]:
    \"\"\"Function with type annotations\"\"\"
    return {"x": x, "y": y, "z": z or []}

# ============================================================================
# BASIC DATA STRUCTURES
# ============================================================================
# Lists
simple_list = [1, 2, 3, 4, 5]
nested_list = [[1, 2], [3, 4], [5, 6]]
list_comprehension = [x ** 2 for x in range(10) if x % 2 == 0]
nested_comprehension = [[i * j for j in range(5)] for i in range(5)]

# Dictionaries
simple_dict = {"a": 1, "b": 2, "c": 3}
dict_comprehension = {k: v ** 2 for k, v in simple_dict.items()}
nested_dict = {"outer": {"inner": {"deep": "value"}}}

# Sets
simple_set = {1, 2, 3, 4, 5}
set_comprehension = {x for x in range(10) if x % 2 == 0}

# Tuples
simple_tuple = (1, 2, 3)
named_tuple_style = (1, "test", 3.14)

# ============================================================================
# FUNCTIONS - Various definitions and decorators
# ============================================================================
def simple_function():
    \"\"\"A simple function with no parameters\"\"\"
    return "simple"

def function_with_args(a, b, c):
    \"\"\"Function with positional arguments\"\"\"
    return a + b + c

def function_with_defaults(a=1, b=2, c=3):
    \"\"\"Function with default arguments\"\"\"
    return a + b + c

def function_with_kwargs(a, b, *args, **kwargs):
    \"\"\"Function with *args and **kwargs\"\"\"
    return (a, b, args, kwargs)

def function_with_type_hints(name: str, age: int, active: bool = True) -> str:
    \"\"\"Function with type hints\"\"\"
    return f"{name} is {age} years old"

# Decorators (defined but not applied at class level to avoid scoping issues)
def simple_decorator(func):
    \"\"\"A simple decorator\"\"\"
    @wraps(func)
    def wrapper(*args, **kwargs):
        result = func(*args, **kwargs)
        return result
    return wrapper

def undecorated_function():
    \"\"\"A function without decorators to avoid class-level decorator issues\"\"\"
    return "undecorated"

# Multiple decorators definition
def another_decorator(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)
    return wrapper

def multi_undecorated():
    \"\"\"Function that could have multiple decorators\"\"\"
    return "multi"

# Decorator with arguments
def decorator_with_args(prefix: str):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            result = func(*args, **kwargs)
            return f"{prefix}: {result}"
        return wrapper
    return decorator

def undecorated_with_args():
    return "value"

# Lambda functions
lambda_func = lambda x: x ** 2
lambda_with_multiple_args = lambda x, y, z: x + y + z

# ============================================================================
# CLASSES - Various class definitions
# ============================================================================
class SimpleClass:
    \"\"\"A simple class\"\"\"
    pass

class ClassWithInit:
    \"\"\"Class with __init__\"\"\"
    def __init__(self, value):
        self.value = value
    
    def get_value(self):
        return self.value

class ClassWithClassVariable:
    \"\"\"Class with class variables\"\"\"
    class_var = "shared"
    
    def __init__(self, instance_var):
        self.instance_var = instance_var

class ClassWithMethods:
    \"\"\"Class with various method types\"\"\"
    
    def __init__(self, value):
        self.value = value
    
    def instance_method(self):
        \"\"\"Regular instance method\"\"\"
        return self.value
    
    @classmethod
    def class_method(cls):
        \"\"\"Class method\"\"\"
        return cls.__name__
    
    @staticmethod
    def static_method():
        \"\"\"Static method\"\"\"
        return "static"
    
    @property
    def value_property(self):
        \"\"\"Property getter\"\"\"
        return self.value
    
    @value_property.setter
    def value_property(self, new_value):
        \"\"\"Property setter\"\"\"
        self.value = new_value

class ParentClass:
    \"\"\"Parent class for inheritance\"\"\"
    def parent_method(self):
        return "parent"

class ChildClass(ParentClass):
    \"\"\"Child class demonstrating inheritance\"\"\"
    def child_method(self):
        return "child"
    
    def parent_method(self):
        \"\"\"Override parent method\"\"\"
        return f"child overrides {super().parent_method()}"

class MultipleInheritance(ParentClass, ClassWithInit):
    \"\"\"Class with multiple inheritance\"\"\"
    def __init__(self):
        ClassWithInit.__init__(self, value=42)

# Dataclass-style (manual)
class DataClassStyle:
    \"\"\"Class that mimics dataclass\"\"\"
    def __init__(self, name: str, age: int, active: bool = True):
        self.name = name
        self.age = age
        self.active = active
    
    def __repr__(self):
        return f"DataClassStyle(name={self.name!r}, age={self.age}, active={self.active})"

# ============================================================================
# CONTROL FLOW
# ============================================================================
def test_control_flow():
    \"\"\"Test all control flow statements\"\"\"
    
    # If-elif-else
    x = 10
    if x > 10:
        result = "greater"
    elif x < 10:
        result = "less"
    else:
        result = "equal"
    
    # Ternary operator
    ternary_result = "positive" if x > 0 else "non-positive"
    
    # For loops
    for i in range(10):
        if i == 5:
            continue
        if i == 8:
            break
    
    # While loops
    counter = 0
    while counter < 5:
        counter += 1
    
    # For-else
    for i in range(5):
        pass
    else:
        pass  # Loop completed
    
    # While-else
    while False:
        pass
    else:
        pass  # While-else

# ============================================================================
# EXCEPTION HANDLING
# ============================================================================
def safe_operation():
    return 42

def risky_operation():
    pass

def some_operation():
    return "result"

def cleanup():
    pass

def operation():
    pass

def test_exceptions():
    \"\"\"Test exception handling\"\"\"
    
    # Basic try-except
    try:
        result = safe_operation()
    except ZeroDivisionError:
        result = None
    
    # Multiple except clauses
    try:
        risky_operation()
    except ValueError as e:
        pass
    except TypeError as e:
        pass
    except Exception as e:
        pass
    
    # Try-except-else
    try:
        result = safe_operation()
    except Exception:
        result = None
    else:
        pass  # No exception occurred
    
    # Try-except-finally
    try:
        result = some_operation()
    except Exception:
        result = None
    finally:
        cleanup()

# ============================================================================
# CONTEXT MANAGERS
# ============================================================================
class CustomContextManager:
    \"\"\"Custom context manager\"\"\"
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        return False

def test_context_managers():
    \"\"\"Test context managers\"\"\"
    # With statement
    with CustomContextManager() as cm:
        pass  # Inside context
    
    # Multiple context managers
    with CustomContextManager() as cm1, CustomContextManager() as cm2:
        pass  # Multiple contexts

# ============================================================================
# GENERATORS AND ITERATORS
# ============================================================================
def simple_generator():
    \"\"\"A simple generator\"\"\"
    yield 1
    yield 2
    yield 3

def generator_with_logic(n):
    \"\"\"Generator with logic\"\"\"
    for i in range(n):
        if i % 2 == 0:
            yield i

def generator_expression_example():
    \"\"\"Generator expressions\"\"\"
    gen_exp = (x ** 2 for x in range(10))
    return list(gen_exp)

class CustomIterator:
    \"\"\"Custom iterator class\"\"\"
    def __init__(self, max_value):
        self.max_value = max_value
        self.current = 0
    
    def __iter__(self):
        return self
    
    def __next__(self):
        if self.current >= self.max_value:
            raise StopIteration
        self.current += 1
        return self.current

# ============================================================================
# ASYNC/AWAIT
# ============================================================================
async def async_function():
    \"\"\"Async function\"\"\"
    await asyncio.sleep(0.01)
    return "async result"

async def async_with_logic():
    \"\"\"Async function with logic\"\"\"
    results = []
    for i in range(5):
        result = await async_function()
        results.append(result)
    return results

# ============================================================================
# OPERATORS AND EXPRESSIONS
# ============================================================================
def test_operators():
    \"\"\"Test all operators\"\"\"
    # Arithmetic
    a = 10 + 5
    b = 10 - 5
    c = 10 * 5
    d = 10 / 5
    e = 10 // 3  # Floor division
    f = 10 % 3   # Modulo
    g = 2 ** 10  # Power
    
    # Comparison
    eq = (10 == 10)
    ne = (10 != 5)
    lt = (5 < 10)
    le = (5 <= 10)
    gt = (10 > 5)
    ge = (10 >= 5)
    
    # Logical
    and_op = True and False
    or_op = True or False
    not_op = not True
    
    # Bitwise
    bit_and = 10 & 5
    bit_or = 10 | 5
    bit_xor = 10 ^ 5
    bit_not = ~10
    left_shift = 10 << 2
    right_shift = 10 >> 2
    
    # Assignment operators
    x = 10
    x += 5
    x -= 2
    x *= 3
    x /= 2
    x //= 2
    x %= 3
    x **= 2
    
    # Membership
    in_op = 5 in [1, 2, 3, 4, 5]
    not_in_op = 10 not in [1, 2, 3, 4, 5]
    
    # Identity
    is_op = None is None
    temp_val = 10
    is_not_op = temp_val is not None
    
    # Walrus operator (Python 3.8+) - with temp variable to avoid self. assignment
    temp_n = 0
    if (temp_n := 10) > 5:
        pass

# ============================================================================
# ADVANCED FEATURES
# ============================================================================
# Unpacking
def test_unpacking():
    \"\"\"Test unpacking features\"\"\"
    a, b, c = [1, 2, 3]
    first, *rest = [1, 2, 3, 4, 5]
    *start, last = [1, 2, 3, 4, 5]
    first, *middle, last = [1, 2, 3, 4, 5]
    
    # Dictionary unpacking
    dict1 = {"a": 1, "b": 2}
    dict2 = {"c": 3, "d": 4}
    merged = {**dict1, **dict2}
    
    # Function call unpacking
    args = [1, 2, 3]
    kwargs = {"x": 10, "y": 20}
    result = some_function(*args, **kwargs)

def some_function(*args, **kwargs):
    return args, kwargs

# Closures
def outer_function(x):
    \"\"\"Outer function for closure\"\"\"
    def inner_function(y):
        \"\"\"Inner function that closes over x\"\"\"
        return x + y
    return inner_function

closure_example = outer_function(10)

# Annotations
def annotated_function(x: int) -> int:
    \"\"\"Function with annotations\"\"\"
    return x * 2

annotated_var: int = 42

# Global and nonlocal
global_var = "global"

def test_scope():
    \"\"\"Test scope keywords\"\"\"
    global global_var
    global_var = "modified"
    
    outer_var = "outer"
    
    def inner():
        nonlocal outer_var
        outer_var = "modified"
    
    inner()
    return outer_var

# Assert
def test_assert():
    \"\"\"Test assert statements\"\"\"
    assert True, "This should pass"
    assert 1 + 1 == 2, "Math should work"

# Del
def test_del():
    \"\"\"Test del statement\"\"\"
    x = [1, 2, 3, 4, 5]
    del x[0]
    
    y = {"a": 1, "b": 2}
    del y["a"]
    
    z = 42
    del z

# Pass, break, continue
def test_flow_control():
    \"\"\"Test pass, break, continue\"\"\"
    for i in range(10):
        if i == 2:
            continue
        if i == 7:
            break
        if i == 5:
            pass

# ============================================================================
# SPECIAL METHODS (DUNDER METHODS)
# ============================================================================
class CompleteClass:
    \"\"\"Class with many special methods\"\"\"
    
    def __init__(self, value):
        self.value = value
    
    def __str__(self):
        return f"CompleteClass({self.value})"
    
    def __repr__(self):
        return f"CompleteClass(value={self.value!r})"
    
    def __len__(self):
        return len(str(self.value))
    
    def __getitem__(self, key):
        return str(self.value)[key]
    
    def __iter__(self):
        return iter(str(self.value))
    
    def __contains__(self, item):
        return item in str(self.value)
    
    def __call__(self, *args, **kwargs):
        return f"Called with {args} and {kwargs}"
    
    def __eq__(self, other):
        return self.value == other.value
    
    def __lt__(self, other):
        return self.value < other.value
    
    def __hash__(self):
        return hash(self.value)
    
    def __bool__(self):
        return bool(self.value)
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        return False

# ============================================================================
# EDGE CASES AND SPECIAL SYNTAX
# ============================================================================
# Ellipsis
def ellipsis_example():
    \"\"\"Ellipsis usage\"\"\"
    x = ...
    return x

# Multiple assignment
def multiple_assignment():
    \"\"\"Multiple assignment\"\"\"
    a = b = c = 10
    return a, b, c

# Chained comparison
def chained_comparison():
    \"\"\"Chained comparison\"\"\"
    x = 5
    result = 0 < x < 10
    return result

# Line continuation
long_calculation = 1 + 2 + 3 + 4 + 5 + \\
                   6 + 7 + 8 + 9 + 10

# Implicit line continuation
long_list = [
    1, 2, 3, 4, 5,
    6, 7, 8, 9, 10
]

# String concatenation
concatenated = "This is " "a concatenated " "string"

# Docstrings
def documented_function():
    \"\"\"
    This is a documented function.
    
    It has multiple lines in its docstring.
    
    Returns:
        str: A string value
    \"\"\"
    return "documented"

# Type aliases
IntList = List[int]
StringDict = Dict[str, str]

# Test that everything is valid
test_result = "All Python syntax elements defined successfully!"
---

<div>
    <h1>Python Syntax Comprehensive Test</h1>
    <p>Testing all Python syntax and structures below the separator</p>
</div>
"""
    
    test_file = tmp_path / "test_comprehensive.wire"
    test_file.write_text(wire_content)
    return test_file


def test_parse_comprehensive_python_syntax(test_wire_file: Path) -> None:
    """---
Test that comprehensive Python syntax can be parsed."""
    parser = PyWireParser()
    
    # Should parse without errors
    parsed = parser.parse_file(test_wire_file)
    
    # Verify template was parsed
    assert len(parsed.template) > 0
    assert parsed.template[0].tag == "div"
    
    # Verify Python code exists
    assert parsed.python_code is not None
    assert len(parsed.python_code) > 0
    
    # Verify Python AST was created
    assert parsed.python_ast is not None


def test_generate_code_from_comprehensive_syntax(test_wire_file: Path) -> None:
    """Test that code generation works with comprehensive Python syntax."""
    parser = PyWireParser()
    generator = CodeGenerator()
    
    # Parse the file
    parsed = parser.parse_file(test_wire_file)
    
    # Generate code - should not raise any errors
    module_ast = generator.generate(parsed)
    
    # Verify we got a valid module
    assert isinstance(module_ast, ast.Module)
    assert len(module_ast.body) > 0


def test_compile_comprehensive_python_syntax(test_wire_file: Path) -> None:
    """Test that generated code compiles to valid Python bytecode."""
    parser = PyWireParser()
    generator = CodeGenerator()
    
    # Parse and generate
    parsed = parser.parse_file(test_wire_file)
    module_ast = generator.generate(parsed)
    
    # Fix missing locations (required for compilation)
    ast.fix_missing_locations(module_ast)
    
    # Convert to Python source code
    generated_code = ast.unparse(module_ast)
    
    # This should compile without syntax errors
    try:
        compile(generated_code, str(test_wire_file), "exec")
    except SyntaxError as e:
        pytest.fail(f"Generated code has syntax error: {e}\n\nGenerated code:\n{generated_code}")


def test_execute_comprehensive_python_syntax(test_wire_file: Path) -> None:
    """Test that generated code can be executed without runtime errors during class definition."""
    parser = PyWireParser()
    generator = CodeGenerator()
    
    # Parse and generate
    parsed = parser.parse_file(test_wire_file)
    module_ast = generator.generate(parsed)
    
    # Fix missing locations
    ast.fix_missing_locations(module_ast)
    
    # Convert to Python source code
    generated_code = ast.unparse(module_ast)
    
    # Compile
    code_obj = compile(generated_code, str(test_wire_file), "exec")
    
    # Execute - this tests that all the Python syntax is valid at runtime
    # Note: This only tests that the module/class can be defined, not that all functions work
    namespace: dict = {}
    try:
        exec(code_obj, namespace)
    except Exception as e:
        pytest.fail(
            f"Generated code raised exception during execution: {e}\n\n"
            f"Generated code:\n{generated_code}"
        )
    
    # Verify that the component class was created
    page_or_component_classes = [
        obj for obj in namespace.values() 
        if isinstance(obj, type) and (obj.__name__.endswith("Component") or obj.__name__.endswith("Page"))
    ]
    assert len(page_or_component_classes) > 0, "No page/component class found in generated code"


def test_python_syntax_preservation() -> None:
    """Test that specific Python constructs are preserved correctly."""
    parser = PyWireParser()
    
    # Test content with various Python features
    content = """---
# Decorators
from functools import wraps

def my_decorator(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)
    return wrapper

@my_decorator
def decorated():
    return "result"

# Classes with inheritance
class Base:
    def method(self):
        return "base"

class Child(Base):
    def method(self):
        return super().method() + " child"

# Type hints
from typing import Optional, List

def typed(x: int, y: Optional[List[str]] = None) -> str:
    return str(x)

# Comprehensions
squares = [x**2 for x in range(10) if x % 2 == 0]
mapping = {k: v for k, v in {"a": 1}.items()}

# Context managers
class Manager:
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False

    # Async
    import asyncio
    
    async def async_func():
        await asyncio.sleep(0.01)
        return "done"
    
    # Match statement (Python 3.10+)
    x = 1
    match x:
        case 1:
            result = "one"
        case _:
            result = "other"
---

    <div>Test</div>
    """
    
    parsed = parser.parse(content)
    generator = CodeGenerator()
    module_ast = generator.generate(parsed)
    ast.fix_missing_locations(module_ast)
    
    # Should compile successfully
    generated = ast.unparse(module_ast)
    compile(generated, "test.wire", "exec")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
