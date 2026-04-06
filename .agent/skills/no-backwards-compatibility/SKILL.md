---
name: No Backwards Compatibility
description: Instructions to actively avoid preserving backwards compatibility or dead code by default.
---

# No Backwards Compatibility / Dead Code Policy

This skill instructs the agent on the project's philosophy regarding backwards compatibility and dead code preservation. 

## Core Philosophy

This project currently has very few users. Therefore, there is **no need** to keep old code around "just in case" or for the sake of backwards compatibility during feature requests, bug fixes, modernizations, and refactors.

It is actively preferred to break backwards compatibility and clean up unused code if it results in a cleaner, more modern, and more maintainable codebase. Do not fall back to the typical default behavior of "playing it safe" by leaving old code untouched.

## Guidelines

1. **Delete Dead Code**: If a function, class, module, or test is no longer used after a refactor or feature addition, **delete it immediately**. Do not leave it commented out, and do not mark it as `@deprecated` unless explicitly instructed to do so.
2. **Do Not Preserve Backwards Compatibility**: When modifying APIs, interfaces, or core logic, do not wrap the changes in backwards-compatible shims (e.g., keeping the old function signature and forwarding to the new one). Update all internal callers to use the new API instead.
3. **Assume Breakage is Okay**: If a modernization or bug fix requires breaking an existing API, do it. The priority is a clean, minimal codebase, not preserving existing (potentially unused) integrations.
4. **Be Ruthless, but Correct**: While you should delete dead code and break compatibility freely, ensure that the active codebase (i.e., tests and current features) still works with your changes. Fix any internal callers that break due to your API changes.
