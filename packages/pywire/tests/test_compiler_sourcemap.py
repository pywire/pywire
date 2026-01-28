import traceback
from pathlib import Path
from typing import Any, cast

import pytest
from pywire.runtime.loader import PageLoader


class TestCompilerSourceMap:
    def test_traceback_line_numbers_script_runtime(self, tmp_path: Path) -> None:
        """Verify runtime errors in python blocks point to correct lines."""
        loader = PageLoader()

        # Line 1: ---
        # Line 2: raise ValueError("Boom")
        # Line 3: ---
        # Line 4: <h1>Test</h1>
        source = """---
raise ValueError("Boom")
---
<h1>Test</h1>"""

        pywire_file = tmp_path / "script_error.pywire"
        pywire_file.write_text(source)

        try:
            page_cls = loader.load(pywire_file)
            page = page_cls(cast(Any, None), {}, {}, {}, None)
            import asyncio

            asyncio.run(page.render())
            pytest.fail("Should have raised ValueError")
        except ValueError as e:
            tb = traceback.extract_tb(e.__traceback__)
            frames = [f for f in tb if f.filename == str(pywire_file)]

            assert len(frames) >= 1, f"Traceback frames: {frames}"

            error_frame = frames[-1]

            # raise on line 2
            assert error_frame.lineno == 2, f"Raise should be on line 2, got {error_frame.lineno}"

    def test_traceback_line_numbers_embedded_expr(self, tmp_path: Path) -> None:
        """Verify errors in { expression } point to correct lines."""
        loader = PageLoader()

        # Line 1: <h1>Test</h1>
        # Line 2: <p>
        # Line 3:     Value: { 1 / 0 }
        # Line 4: </p>
        source = """<h1>Test</h1>
<p>
    Value: { 1 / 0 }
</p>"""

        pywire_file = tmp_path / "expr_error.pywire"
        pywire_file.write_text(source)

        try:
            page_cls = loader.load(pywire_file)
            # Expressions in template are evaluated during render(), not load()
            # unless they are constant folded or top-level (which these aren't)

            # Setup minimal page instance
            page = page_cls(cast(Any, None), {}, {}, {}, None)

            # Render needs to be awaited? BasePage.render is async
            import asyncio

            asyncio.run(page.render())

            pytest.fail("Should have raised ZeroDivisionError")
        except ZeroDivisionError as e:
            tb = traceback.extract_tb(e.__traceback__)
            frames = [f for f in tb if f.filename == str(pywire_file)]

            assert len(frames) >= 1, f"Traceback frames: {frames}"

            # Expression is on line 3
            # Depending on how the generator structures 'yield', it should map back to 3
            error_frame = frames[-1]
            assert error_frame.lineno == 3, (
                f"Expression error should be on line 3, got {error_frame.lineno}"
            )
