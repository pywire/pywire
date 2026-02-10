
import os
import subprocess
import sys
from pathlib import Path

# We run this script from tests/repro_path_resolution/
# We want to run project/src/app.py
# We expect app.py to resolve "pages" relative to itself, NOT CWD.

base_dir = Path(__file__).parent.resolve()
project_src = base_dir / "project" / "src"
app_path = project_src / "app.py"

# Expected path: project_src / "pages"
expected_pages = project_src / "pages"
expected_static = project_src / "static" # Even if it doesn't exist, if it resolves relative to app.py

print(f"Running app.py from {base_dir}...")
print(f"App Path: {app_path}")
print(f"Expected Pages Dir: {expected_pages}")


# Create dummy static dir to ensure it's found if logic is correct?
(project_src / "static").mkdir(exist_ok=True)

env = os.environ.copy()
# base_dir is tests/repro_path_resolution
# we want pywire/src which is ../../src from base_dir
pywire_root = base_dir.parent.parent
pywire_src = pywire_root / "src"
env["PYTHONPATH"] = str(pywire_src) + os.pathsep + env.get("PYTHONPATH", "")

result = subprocess.run(
    [sys.executable, str(app_path)],
    cwd=str(base_dir),
    env=env,
    capture_output=True,
    text=True
)


print("--- STDOUT ---")
print(result.stdout)
print("--- STDERR ---")
print(result.stderr)

output = result.stdout
resolved_pages_line = next((line for line in output.splitlines() if line.startswith("Pages Dir:")), None)

if resolved_pages_line:
    resolved_path = Path(resolved_pages_line.split(": ")[1].strip())
    print(f"Resolved: {resolved_path}")
    if resolved_path.resolve() == expected_pages.resolve():
        print("SUCCESS: Pages directory correctly resolved relative to app.py")
    else:
        print(f"FAILURE: Pages directory resolved to {resolved_path}, expected {expected_pages}")
        
        # Check if it resolved relative to CWD
        cwd_pages = base_dir / "pages"
        if resolved_path.resolve() == cwd_pages.resolve():
             print("DIAGNOSIS: It resolved relative to CWD.")
else:
    print("FAILURE: Could not find Pages Dir in output")
