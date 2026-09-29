#!/usr/bin/env bash
# Stamp release-please PRs: success on the per-package CI checks (release
# PRs only bump versions and changelogs) and a real Release Floors Gate.
#
# Only PRs that release-please itself opened count: head branch in this
# repo (not a fork) and authored by the RELEASE_PAT account. Matching on the
# branch name alone let a fork PR named release-please--… get every
# required check stamped green.
#
# Env: GH_TOKEN (statuses: write), GITHUB_REPOSITORY, RELEASE_AUTHOR (login).
set -euo pipefail

: "${GITHUB_REPOSITORY:?}" "${RELEASE_AUTHOR:?}"

prs=$(gh pr list --repo "$GITHUB_REPOSITORY" --state open --limit 100 \
  --json number,headRefOid,headRefName,isCrossRepository,author \
  | jq -c --arg author "$RELEASE_AUTHOR" '[.[]
      | select(.headRefName | startswith("release-please--"))
      | select(.isCrossRepository | not)
      | select(.author.login == $author)]')

if [ "$prs" = "[]" ]; then
  echo "No open release-please PRs"
  exit 0
fi

checks=(
  "Check PyWire Core"
  "Check PyWire Parser"
  "Check PyWire CLI"
  "Check PyWire Templates"
  "Check PyWire Auth"
  "Check Language Server"
  "Check VS Code Extension"
  "Check Prettier Plugin"
  "Check Tree-sitter Grammar"
  "Check Create PyWire App"
  "Check Create PyWire App (npm)"
  "Check Examples"
  "Check PyWire Docs"
)

status() { # sha state context description
  gh api "repos/$GITHUB_REPOSITORY/statuses/$1" \
    -f state="$2" -f context="$3" -f description="$4" --silent
}

echo "$prs" | jq -c '.[]' | while read -r pr; do
  sha=$(echo "$pr" | jq -r '.headRefOid')
  num=$(echo "$pr" | jq -r '.number')
  branch=$(echo "$pr" | jq -r '.headRefName')
  echo "Setting CI statuses on PR #$num ($sha)"
  for context in "${checks[@]}"; do
    status "$sha" success "$context" "Skipped for release-please PR"
  done

  # Release floors gate: separate-pull-requests means one component per PR,
  # named release-please--branches--main--components--<pkg>. It stays
  # pending (waiting, not failed) while an upstream it needs is unpublished
  # or its floors still wait on release.yml's bump-floors PR. It is
  # re-evaluated on every push to main and after every publish.
  gate_state=success
  gate_desc="All floors published and current"
  case "$branch" in
    release-please--branches--main--components--*)
      component=${branch#release-please--branches--main--components--}
      [ "$component" = "pywire-docs" ] && component="docs"
      if out=$(python3 scripts/monorepo_graph.py check-publishable --fresh "$component" 2>&1); then
        echo "PR #$num: floors ok ($component)"
      else
        gate_state=pending
        gate_desc="Waiting: $(echo "$out" | grep 'floor' | head -1 | cut -c1-120)"
        echo "PR #$num: floors gate pending — $gate_desc"
      fi
      ;;
    *)
      echo "PR #$num: not a component release PR, skipping floors gate"
      ;;
  esac
  status "$sha" "$gate_state" "Release Floors Gate" "$gate_desc"
done
