---
name: github-issues
description: Use when the user reports a bug, requests a feature, mentions an issue number, or when finishing work that may resolve or relate to a GitHub issue in pywire/pywire.
---

# GitHub Issues

Use the `gh` CLI (repo: `pywire/pywire`). If `gh auth status` fails, ask the user to run `gh auth login`.

## Before starting work

1. Search open **and closed** issues for the topic: `gh issue list --search "<keywords>" --state all --limit 20`
2. For each match, read the full thread: `gh issue view <n> --comments` — repros, stack traces and workarounds are usually in comments.

## After finishing work

Comment on the related issue with the commit/PR (`gh issue comment <n> --body "Fixed in <sha>"`). Close it only if the user asks; otherwise let `Closes #N` in the PR body close it on merge.

## Filing new issues

When you find a real bug or tech debt outside the current task, offer to file it:

```sh
gh issue create --title "..." --body "..." --label bug --label "scope: runtime"
```

Include repro steps, expected vs actual, and affected package. Labels: `bug`, `enhancement`, `documentation`, `tech debt`, `testing`, and `scope: {core,runtime,client,parser,ssr,dx}` — check `gh label list` for the current set.
