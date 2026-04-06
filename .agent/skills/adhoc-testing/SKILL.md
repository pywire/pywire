---
name: Ad Hoc Testing
description: Instructions for creating and running ad hoc verification tests.
---

# Ad Hoc Testing Skill

This skill guides the creation and execution of ad hoc verification tests. These tests are useful for debugging, implementing new features, or checking for regressions without cluttering the main test suite.

## Location Standards

All ad hoc tests and related files MUST be placed in the `/scratch/adhoc/` directory locally.

-   **Test Scripts**: Place python test scripts directly in `/scratch/adhoc/`.
-   **Input Files**: Place any input files (e.g., `.wire`, `.txt`) in `/scratch/adhoc/in/`.
-   **Output Files**: If the test produces output files, write them to `/scratch/adhoc/out/`.

## Workflow

1.  **Creation**: Create a python script in `/scratch/adhoc/` (e.g., `repro_issue_123.py`).
2.  **Inputs**: If the test requires external input, create the file in `/scratch/adhoc/in/` and reference it in your script.
3.  **Outputs**: Configure your script to write any file outputs to `/scratch/adhoc/out/`.
4.  **Execution**: Run the test script from the project root or the `scratch/adhoc` directory as needed.

## Important Rules

1.  **Gitignore**: The `/scratch/` directory is gitignored. **DO NOT** commit ad hoc tests to source control.
2.  **Actionable Tests**: If an ad hoc test proves to be "TRULY actionable" (i.e., it covers a valuable regression case or a new feature requirement), you **MUST** port it to the main `tests/` directory as a proper unit or integration test.
    -   Do not leave valuable tests rotting in scratch.
    -   Do not add bloat to the source by committing scratch files.
3.  **Cleanup**: Periodically clean up your `/scratch/adhoc/` directory, but it is safe to leave files there for local history if they might be useful later.

## Example Usage

When debugging a parser issue:

1.  Create `scratch/adhoc/in/broken_syntax.wire` with the problematic code.
2.  Create `scratch/adhoc/debug_parser.py` that reads `scratch/adhoc/in/broken_syntax.wire`.
3.  Run `python3 scratch/adhoc/debug_parser.py`.
4.  If fixed and valuable, create a new test case in `tests/test_parser.py` with the content of `broken_syntax.wire`.
