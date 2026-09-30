from pywire import PyWire

# Pages come from src/pages; static/ next to this project is served at /static.
app = PyWire(pages_dir="src/pages")
