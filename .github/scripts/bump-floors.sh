#!/usr/bin/env bash
# After a publish, raise downstream floors to the new versions and land the
# change through an auto-merging PR, so check-floors never sees main stale
# for longer than one CI run. Runs from a checkout of the latest main.
#
# Args: NAME=VERSION for each package this run released (bump-floors waits
# until the registry serves them; names nothing depends on are ignored).
# Env: GH_TOKEN (RELEASE_PAT, so the PR's CI runs), GITHUB_REPOSITORY.
set -euo pipefail

: "${GITHUB_REPOSITORY:?}"
branch=release-floors/bump

expect=()
for e in "$@"; do expect+=(--expect "$e"); done

edits=$(python3 scripts/monorepo_graph.py bump-floors "${expect[@]}")
echo "$edits"
if git diff --quiet; then
  exit 0
fi

uv lock
python3 scripts/monorepo_graph.py check-floors

# fix(<downstream packages>): release-please cuts a patch for each of them,
# so the released packages carry the new floors too.
scopes=$(git diff --name-only -- packages | cut -d/ -f2 | sort -u | paste -sd, -)
bumped=$(echo "$edits" | sed -n 's/^[^:]*: \([^>]*\)>=.* -> >=\(.*\)$/\1 \2/p' | sort -u | paste -sd, - | sed 's/,/, /g')
title="fix(${scopes}): bump floors to ${bumped}"
python3 scripts/check_pr_title.py "$title"

git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
git checkout -B "$branch"
git commit -qam "$title"
git push --force origin "$branch"

body=$(printf 'Automated by release.yml after a publish: raises downstream floors to the newly published versions.\n\n```\n%s\n```\n\nAuto-merges once the required checks pass.' "$edits")
num=$(gh pr list --repo "$GITHUB_REPOSITORY" --head "$branch" --state open --json number --jq '.[0].number // empty')
if [ -n "$num" ]; then
  gh pr edit "$num" --repo "$GITHUB_REPOSITORY" --title "$title" --body "$body"
else
  url=$(gh pr create --repo "$GITHUB_REPOSITORY" --base main --head "$branch" --title "$title" --body "$body")
  num=${url##*/}
fi
gh pr merge "$num" --repo "$GITHUB_REPOSITORY" --auto --squash
echo "Floor bump PR #$num set to auto-merge"
