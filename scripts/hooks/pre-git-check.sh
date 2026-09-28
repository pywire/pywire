#!/usr/bin/env bash
# Quality gate for agent-run `git commit` / `git push`: runs ./scripts/check for
# the packages the commit (or unpushed commits) touch, and blocks on failure.
#
# Wired up in:
#   Claude Code  .claude/settings.json     (PreToolUse hook, JSON on stdin)
#   Codex        .codex/hooks.json         (PreToolUse hook, JSON on stdin)
#   Pi           .pi/extensions/pre-git-check.ts  (command passed as $1)
#
# Input: hook JSON on stdin ({"tool_input":{"command":...},"cwd":...}) or the
# shell command as $1. Exit 0 = allow, 2 = block (reason on stderr).
set -uo pipefail

if [[ $# -gt 0 ]]; then
  cmd=$1
  cwd=$PWD
else
  input=$(cat)
  cmd=$(jq -r '.tool_input.command // empty' <<<"$input")
  cwd=$(jq -r '.cwd // empty' <<<"$input")
fi
[[ -n $cwd ]] && cd "$cwd" 2>/dev/null

# Match `git [-C dir] [-c k=v] commit|push` anywhere in a compound command.
git_re='(^|[;&|(]|\$\()[[:space:]]*git([[:space:]]+-[Cc][[:space:]]+[^[:space:]]+)*[[:space:]]+(commit|push)([[:space:]]|$)'
[[ $cmd =~ $git_re ]] || exit 0
action=${BASH_REMATCH[3]}
[[ $cmd =~ --dry-run ]] && exit 0

# Follow `git -C <dir>` so worktree commits check the right checkout.
dir_re='git[[:space:]]+-C[[:space:]]+([^[:space:];&|]+)'
if [[ $cmd =~ $dir_re ]]; then
  dir=${BASH_REMATCH[1]/#\~/$HOME}
  cd "$dir" 2>/dev/null || true
fi
root=$(git rev-parse --show-toplevel 2>/dev/null) || exit 0
cd "$root"

if [[ $action == commit ]]; then
  files=$(git diff --cached --name-only)
  # `git commit -a` / `-am` / `--all` also commits tracked, unstaged changes.
  all_re='commit[^;&|]*[[:space:]](-[a-zA-Z]*a[a-zA-Z]*|--all)([[:space:]]|$)'
  if [[ $cmd =~ $all_re ]]; then
    files+=$'\n'$(git diff --name-only)
  fi
else
  upstream=$(git rev-parse --abbrev-ref '@{u}' 2>/dev/null || echo origin/main)
  # A single new commit was already gated at commit time.
  [[ $(git rev-list --count "$upstream..HEAD" 2>/dev/null || echo 0) -gt 1 ]] || exit 0
  files=$(git diff --name-only "$upstream...HEAD")
fi

# Map files to checkable units: packages/*, examples, docs. Workspace-wide
# config changes trigger the full workspace check; other root files need none.
# Spec/planning docs (docs/superpowers/**) never trigger the docs unit.
units=""
full=false
while IFS= read -r f; do
  case $f in
    packages/*/*) p=${f#packages/}; units+="packages/${p%%/*}"$'\n' ;;
    examples/*) units+=$'examples\n' ;;
    docs/superpowers/*) ;;
    docs/*) units+=$'docs\n' ;;
    scripts/hooks/* | scripts/tests/*) ;;
    pyproject.toml | uv.lock | package.json | pnpm-lock.yaml | pnpm-workspace.yaml | scripts/*) full=true ;;
  esac
done <<<"$files"

# Canonical unit list from the graph script — hook, orchestrators and
# ci.yml all derive from the same source, so they can't drift apart.
graph_units=$(python3 scripts/monorepo_graph.py units 2>/dev/null || true)

tmp=${TMPDIR:-/tmp}
log=$(mktemp "${tmp%/}/pre-git-check.XXXXXX")
fail() {
  {
    echo "BLOCKED: $1 — fix the errors, then retry the git $action."
    echo "--- last 60 lines of output (full log: $log) ---"
    tail -n 60 "$log"
  } >&2
  exit 2
}

if $full; then
  echo "pre-git-check: workspace config changed, running ./scripts/check" >&2
  ./scripts/check >"$log" 2>&1 || fail "workspace check failed"
  exit 0
fi

for unit in $(sort -u <<<"$units"); do
  if [[ -n $graph_units ]] && ! grep -qx "$unit" <<<"$graph_units"; then
    echo "pre-git-check: $unit is not a graph unit — skipping" >&2
    continue
  fi
  if [[ -x $unit/scripts/check ]]; then
    echo "pre-git-check: $unit" >&2
    (cd "$unit" && ./scripts/check) >>"$log" 2>&1 || fail "$unit check failed"
  fi
done
rm -f "$log"
exit 0
