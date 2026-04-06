import pywire
import os
import sys

print(f"Python Version: {sys.version}")
print(f"Python Executable: {sys.executable}")
print(f"PyWire File: {pywire.__file__}")
print(f"PyWire Path: {os.path.dirname(pywire.__file__)}")

try:
    from pywire.runtime.page import BasePage
    import inspect
    print(f"BasePage File: {inspect.getfile(BasePage)}")
except Exception as e:
    print(f"Error loading BasePage: {e}")
