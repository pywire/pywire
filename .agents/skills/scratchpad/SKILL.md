---
name: scratchpad
description: Use when you could verify a hypothesis, reproduce a bug, probe parser/compiler/runtime output, or check an assumption by running throwaway code instead of reasoning about it or editing the real test suite.
---

# Scratchpad

**Claude Code:** don't use this skill. Use the native session scratchpad directory from your system prompt instead.

Running code beats guessing. You may write throwaway code to `scratch/adhoc/` and execute it without asking the user, **after an independent review approves it**.

## Layout

`scratch/` is gitignored. Never commit anything from it.

- `scratch/adhoc/<name>.py` — scripts (name them by purpose: `repro_issue_71.py`, `debug_codegen_slots.py`)
- `scratch/adhoc/in/` — input fixtures (`.wire` files, etc.)
- `scratch/adhoc/out/` — anything the script writes

Run through the workspace env so packages import: `uv run --package pywire python scratch/adhoc/<name>.py`.

## Review before every execution

Before running a new or changed script, get a review from a **different model with none of your context**:

```sh
bash .agents/skills/scratchpad/review.sh -m <model> -c "<exact command>" scratch/adhoc/<name>.py [inputs...]
```

- Exit 0 + `APPROVE` → run it. Anything else → read the reason, fix the script, review again.
- Pick a reviewer from a different model family than you. Defaults: `openrouter/google/gemini-3.8-flash`; if you are Gemini, `openrouter/z-ai/glm-5.3-flash`.
- Re-running an already-approved script unchanged needs no new review.

Scratch code stays within the limits the reviewer enforces: writes only under `scratch/`, no state-changing git, no network beyond localhost, no secrets, no leftover processes.

## Afterwards

If a script proves a real regression or a new requirement, port it into the owning package's `tests/` as a proper test. Leave the rest in scratch.
