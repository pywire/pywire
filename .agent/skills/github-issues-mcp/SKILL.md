---
name: GitHub Issues Management (MCP)
description: Instructions for checking, reading, and updating GitHub issues using the MCP GitHub server.
---

# GitHub Issues Management (MCP)

This skill instructs the agent to actively incorporate GitHub Issues into the development workflow using an installed Model Context Protocol (MCP) server.

When working within the PyWire workspace, you should actively query the issue tracker to ground your understanding, verify bug reports, and track your progress.

## Rules & Directives

1. **Check for Context Before Starting Work**:
   Whenever a user brings up a bug or requests a new feature, use the MCP server tools to search for related issues in the relevant repository. This ensures you're not duplicating work, and gives you historical context or replication steps that other developers might have provided.
   
2. **Check Across Releases**:
   If a bug is mentioned that might be present in a Live Release (e.g. `v0.1.10`) rather than just the current development branch (`v0.1.11`), query the issues to see if it was reported there. 

3. **Read Issues Thoroughly**:
   If you find a related issue, read all of its comments via MCP. Users often supply stack traces, minimal reproducible examples, or temporary workarounds in the comments.

4. **Update Issues When Completing Work**:
   When you write a fix for a bug or implement a feature, use the MCP server to:
   - Comment on the issue acknowledging that the fix is implemented in the current branch.
   - Mention the commit hash or PR (if applicable).
   - Close the issue if the user's workflow allows it.

5. **Create New Issues Thoughtfully**:
   If you encounter technical debt or discover a new bug during your work, create an issue for it. When creating issues, follow the [GitHub Issue Organization Plan](github-issue-organization-plan.md) guidelines: use proper scope tags, assign an appropriate milestone, and format the body with clear reproduction steps.

## Expected Workflow Sequence
1. Identify target repository (e.g., `pywire`, `pywire-language-server`).
2. MCP Search/List issues for keywords related to the current task.
3. MCP Read Issue (if a match is found) for context.
4. Perform code changes.
5. MCP Comment / Close Issue upon validation of the fix.
