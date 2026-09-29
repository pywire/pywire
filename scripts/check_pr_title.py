#!/usr/bin/env python3
"""Check a PR title against the rules release-please needs (stdlib-only).

PRs are squash-merged, so the title becomes the commit subject that
release-please parses. A title it cannot parse is dropped from every
changelog and version bump without failing anything (#274 was), so CI
rejects it before merge instead.

Usage: check_pr_title.py "<title>"   (exit 1 with the reasons on failure)
"""

from __future__ import annotations

import re
import sys

TYPES = ("build", "chore", "ci", "deps", "docs", "feat", "fix", "perf", "refactor", "revert", "style", "test")

_TITLE_RE = re.compile(r"^(?P<type>[A-Za-z]+)(?:\((?P<scope>[^()]*)\))?(?P<bang>!)?: (?P<subject>.*)$")


def title_problems(title: str) -> list[str]:
    m = _TITLE_RE.match(title)
    if not m:
        return [
            "not a conventional commit: expected `type(scope): subject` or `type: subject`, e.g. "
            "`fix(pywire-cli): handle missing config` (release-please would drop this commit)"
        ]
    problems: list[str] = []
    if m["type"] not in TYPES:
        problems.append(f"unknown type `{m['type']}`: use one of {', '.join(TYPES)}")
    if m["scope"] is not None and not re.fullmatch(r"[a-z0-9-]+(,\s?[a-z0-9-]+)*", m["scope"]):
        problems.append(f"bad scope `({m['scope']})`: lowercase package names, comma-separated")
    subject = m["subject"]
    if not subject.strip():
        problems.append("empty subject after `: `")
    elif subject != subject.strip():
        problems.append("subject has leading or trailing whitespace")
    if "(" in subject or ")" in subject:
        problems.append(
            "parentheses in the subject: squash-merge appends ` (#NN)` and an extra `(` makes "
            "release-please drop the commit; reword without them"
        )
    return problems


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    problems = title_problems(argv[1])
    for p in problems:
        print(f"PR title: {p}")
    print(f"check-pr-title: {'FAIL' if problems else 'ok'} ({argv[1]!r})")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
