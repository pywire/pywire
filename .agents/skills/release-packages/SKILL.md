---
name: release-packages
description: Use when asked to release pywire packages ("release pywire", "release all packages", "release pywire-cli and the LSP") — merges the open release-please PRs upstream-first, waiting on CI, release runs and publish jobs between merges.
---

# Release packages

Merge open release-please PRs in dependency order, one at a time, waiting between merges until the previous release is tagged **and published**, then report what shipped. One merge usually takes about five minutes end to end; don't rush it.

Read AGENTS.md "Cross-package version floors" and "Commits, PRs, releases" first. Everything below builds on `scripts/monorepo_graph.py` and `.github/workflows/release.yml`.

## Authority

- The user asking to release (all packages, or named ones) is the go-ahead to **merge the release-please PRs you list in the plan**, and nothing else.
- Floor-bump PRs, fixes, re-runs of workflow jobs, and anything outside the plan need their own explicit yes.
- Never approve the `release` environment, set commit statuses, bypass a required check, or touch publish tokens. Publishing is gated on a maintainer approving the `release` environment in GitHub Actions; that is the user's step.
- A request for a *dry run* ("what would you release?") merges nothing: stop after step 2.

## Tools

Repo: `pywire/pywire`, base `main`. Locally, use `gh` (`gh auth status` must pass). In a cloud session without `gh`, use the GitHub MCP tools; equivalents are noted as *MCP:*. Registry checks (`monorepo_graph.py check-publishable`/`check-floors`) hit PyPI and npm directly and need no auth.

Waiting: prefer blocking watchers (`gh run watch <id> --exit-status`, `gh pr checks <n> --watch`). Where those aren't available, poll every 30–60 s with the harness's wait mechanism (Monitor with an until-loop, or a scheduled wake-up), not one long sleep. When waiting on a person (publish approval), tell them what to approve and check back every few minutes; it can take hours.

## 1. Inventory

```sh
git fetch origin main && git checkout --detach origin/main   # graph + floors must come from current main
gh pr list --state open --json number,title,headRefName,headRefOid,mergeStateStatus \
  --jq '[.[] | select(.headRefName | startswith("release-please--"))]'
gh run list --workflow release.yml --branch main --limit 5 \
  --json databaseId,status,conclusion,headSha,displayTitle,url
```

*MCP:* `list_pull_requests` (state open; keep heads starting `release-please--branches--main--components--`), `actions_list` `list_workflow_runs` on `release.yml` with branch `main`.

The component is the branch suffix after `--components--`. `pywire-docs` is the `docs` unit; every other component is `packages/<component>`.

Stop and report if:
- A Release run on `main` is `queued`/`in_progress` with its `release-please` job not finished (wait for it first; it is about to rebuild the PRs you're reading).
- A Release run has a publish job still `waiting` for approval or `in_progress` from an earlier merge. Finish that release before starting another.
- A recent Release run has a **failed** publish or build job. That package is tagged but not published; downstream floors can't be satisfied. Report the job link; the fix is re-running *that job only* (never "Re-run all jobs": see the comment at the top of `release.yml`), which is the user's call.

## 2. Plan

Choose the set:
- **"release all"**: every open release PR.
- **"release X, Y"**: those components, plus any upstream component whose release PR is open *and* is needed. An upstream is needed when `python3 scripts/monorepo_graph.py check-publishable <component>` fails naming it (the requested package's floor on main isn't published yet). Release PRs never change floors, so an upstream with no failing floor is **not** pulled in. Name every pulled-in package and why.
- A requested package with no open release PR has nothing to release (no releasable commits since its last tag). Say so; don't invent a release.

Order: `python3 scripts/monorepo_graph.py release-order <components...>` (topological, upstream first). Then apply these adjustments:
- **docs before pywire.** When pywire releases, `sync-docs-release` closes the open `pywire-docs` release PR and cuts a *patch* docs release instead, losing a minor bump. Merging the docs PR first keeps its version.
- `(order-free)` units can go anywhere; keep them first so they finish while nothing depends on them.

**First publishes are held.** If a package has never been released by CI (its `.release-please-manifest.json` entry is `0.0.0`, or no `<component>-v*` tag exists), its registry setup must be confirmed first: the name claimed (a manual first publish by the maintainer) and trusted publishing configured for this repo, `release.yml` and the `release` environment. Trusted-publisher config isn't publicly visible, so only the user can confirm it. Until they do, list that PR as held with this reason and leave it unmerged. A request to "release all" is not that confirmation.

Show the plan before merging: one line per PR (`#N component old → new`), pulled-in packages with the reason, and the expected floor-bump follow-ups (section 4). For a dry run, this is the whole answer.

## 3. Merge loop

For each PR in order:

1. **Main is quiet.** No Release run on `main` has `release-please` queued or running (step 1 check). Merging while it runs means it rebuilds the PR under you.
2. **PR is fresh and green.** Re-read the PR: still open, head SHA is the one the latest finished Release run stamped (its statuses exist on the current head), every status and check run on the head is `success`/`skipped`/`neutral`, and `mergeStateStatus` is `CLEAN`.
   - `gh pr checks <n> --watch` waits out anything pending. *MCP:* `pull_request_read` `get_status` + `get_check_runs` + `get` (`mergeable_state == clean`).
   - Run `python3 scripts/monorepo_graph.py check-publishable <component>` on fresh main yourself; it must pass. Don't rely on a green **Release Floors Gate** alone: since release PRs run `ci.yml`, its `floors-gate` job also posts a pass-through success to that context, and whichever posts last wins.
   - **Release Floors Gate** red: an upstream isn't published. If it's in the plan and not yet published, you're out of order: fix the order. If `check-publishable <component>` now passes locally (upstream published after the gate was stamped), the gate is stale; it refreshes on the next push to main. Merge another ready PR in the plan first if there is one; otherwise report it and stop.
   - **Check Monorepo Graph** red with a `check-floors` "below published" message: a floor bump is needed first (section 4).
   - Any other red check: stop and report it with the link. Don't retry, re-run, or merge around it.
3. **Merge.** Squash, with the title release-please gave it:
   ```sh
   gh pr merge <n> --squash
   ```
   *MCP:* `merge_pull_request` with `merge_method: squash`. Don't pass `--admin` or any bypass. If the merge is refused, stop and report why.
4. **Wait for the release.** Find the Release run for the merge commit (`gh run list --workflow release.yml --branch main --commit <merge-sha>`), then wait for its `release-please` job. Confirm the tag exists (`gh release view <component>-v<version>`) and that other open release PRs have been re-stamped.
5. **Wait for publish.** The run's build/publish jobs for this package sit in `waiting` on the `release` environment. Tell the user once, with the run link: "Approve the `release` deployment for <package> <version>." Then wait for those jobs to finish:
   - All publish jobs `success`, and the registry shows the new version (`check-publishable` on the next downstream passes, or query PyPI/npm directly). VS Code Marketplace has no public version check; the job's success is enough.
   - A publish job fails or is rejected: stop the loop. Report it; downstream releases depend on it.
   - Packages with no publish job (`docs` deploys via `deploy-docs`, and `pywire` also triggers `sync-docs-release`): wait for those jobs instead.
6. Go to the next PR, starting from sub-step 1. Re-read the PR list first: release-please may have closed, retitled or re-versioned PRs (for example, `sync-docs-release` closes the docs PR when pywire releases).

## 4. Floors after a publish

`check-floors` requires every floor to be **≥ the latest published** upstream. So publishing an upstream with dependents (pywire, pywire-parser, pywire-templates, tree-sitter-pywire) turns "Check Monorepo Graph" red on main and on every downstream release PR until the floors are raised. After each such publish:

```sh
git fetch origin main && git checkout --detach origin/main
python3 scripts/monorepo_graph.py check-floors
```

If it reports violations, prepare the floor-bump PR (this is how #312 did it):
- Branch from main, raise each reported floor in the downstream `pyproject.toml` **and** `_FLOORS` in its `src/<pkg>/_compat.py`, run `uv lock`, then `check-floors` must pass.
- One PR, conventional commit `fix(<downstream-scopes>): bump <dep> floor to <version>`, no parentheses in the title beyond the scope. It must touch real files in each downstream package so release-please cuts their releases.
- Open it as a **draft** and ask the user to merge it; the release request doesn't cover it. After it merges, release-please opens/updates the downstream release PRs; add them to the plan and continue the loop.

If you're releasing only upstream packages, still do this: leaving it means main's CI goes red.

## 5. Report

Finish with one short message:
- Shipped: `package old → new` for each, with the GitHub release link, and where it published (PyPI, npm, Marketplace, docs deploy).
- Pulled in: any package added for a floor, and why.
- Not shipped: anything skipped, closed by automation, blocked (failed check, rejected publish, stale gate), or waiting on the user (publish approval, floor-bump PR), each with the link and the one action that unblocks it.
- Main's state: Release run and Check Monorepo Graph green, or what's red.
