# CI/Monorepo Tooling + Terraform Remote State — Design

Date: 2026-09-23
Status: Awaiting user review

## Intent

Four workstreams, one spec:

1. **Version-graph & CI fan-out tooling** — the monorepo's cross-package dependency
   graph is currently maintained by hand in two places (release-please floors +
   `_compat.py` `_FLOORS`, and `ci.yml` `if:` conditions). Make the graph derived,
   not declared. (User pain ranking: this is #1 and #2.)
2. **CI/CD speed & best practices** — cheaper scoped jobs, caching, Node 24,
   current action majors, pnpm 10 everywhere.
3. **Terraform remote state + GitHub Actions** — infra lives in
   `~/projects/pywire.dev` (`infra/`, Cloudflare-only) with local-only state.
   Move state to Cloudflare R2 (S3-compatible backend), add plan-on-PR,
   manual-apply, and drift-on-main workflows **in the pywire.dev repo**.
4. **Decision records** — bun (rejected), nx/turborepo (rejected for now),
   OpenTofu (rejected).

Out of scope: implementing anything in this spec from this session (planning
only); moving infra into the monorepo (stays in pywire.dev); adopting bun or nx.

## Current state (verified by recon)

- Monorepo: 11 release-please packages, 8 Python (uv workspace) + 5 JS
  (pnpm workspace). `ci.yml` path-filters per package via `dorny/paths-filter`
  with hand-maintained downstream fan-out in `if:` conditions.
- Cross-package version floors exist in two forms that must agree and don't
  verify each other: `pyproject.toml` dep floors (e.g. `pywire-parser>=0.6.0`)
  and `_FLOORS` in each downstream package's `src/<pkg>/_compat.py`.
- Terraform: only in pywire.dev (`infra/main.tf`, `variables.tf`); state is
  local-only and gitignored (`terraform.tfstate` + backups). Resources: 2
  Cloudflare Pages projects, 1 R2 bucket (CDN), 1 router Worker. Pages git
  builds are disabled — the monorepo's `deploy-docs.yml` and pywire.dev's
  `deploy.yml` build and push via `cloudflare/pages-action`.
- Node/tooling skew: monorepo workflows use `node-version: '22'` ×6,
  `pnpm/action-setup` version 9; pywire.dev uses Node **20** and
  `pnpm/action-setup@v2`. First-party actions are on node20-runtime majors
  (`actions/checkout@v4`, `actions/setup-node@v4`) — source of the recurring
  GHA Node deprecation warnings.
- The user's Cloudflare API token already exists locally in
  `~/projects/pywire.dev/infra/terraform.tfvars` (gitignored) and as the
  `CLOUDFLARE_API_TOKEN` GH secret (pywire/pywire, and pywire.dev for its
  deploy workflow).

## Part A — Dependency graph as derived truth (monorepo)

New stdlib-only script: `scripts/monorepo_graph.py` (Python ≥3.11 `tomllib`,
no third-party deps, runnable as `python3 scripts/monorepo_graph.py <cmd>`).

- **Graph derivation**: parse each `packages/*/pyproject.toml`; an edge
  exists when a dependency name matches another monorepo package. Static
  side-table for units without pyproject edges: `examples → pywire`,
  `docs → (none)`, JS packages → (none). Must reproduce today's `ci.yml`
  fan-out exactly (that's the correctness test).
- Subcommands:
  - `print` — human-readable graph (edges + floors).
  - `check-floors` — for every edge A→B: A's `pyproject.toml` floor for B
    must be ≥ B's current version, and A's `_compat.py` `_FLOORS` entry (if
    present) must equal the pyproject floor. Prints every violation with the
    expected value; exit 1 on any.
  - `check-ci` — parse `ci.yml`, extract each check job's
    `needs.changes.outputs.*` set, compare against the graph-derived fan-out
    (a job's trigger set = its own package + all transitive upstream
    packages). Exit 1 with a diff on mismatch, so the YAML can't silently rot.
  - `check-publishable <pkg>` — for every monorepo dep of `<pkg>`, verify the
    floor in `<pkg>`'s pyproject is satisfiable by a version already published
    on PyPI (npm registry for the JS packages). This is the release-ordering
    invariant: a release PR is safe to merge only when all its floors are
    publicly installable. It subsumes "merge upstream first" *and* catches
    "upstream release PR merged but its publish job failed."
  - `release-order [pkgs...]` — print the topological merge order for the
    given packages (or, with no args, auto-detect open `release-please--*`
    PRs via `gh pr list` and order those). Registry-independent packages
    (e.g. `vscode-pywire`, npm-side) are marked order-free.
- New always-on CI job `check-monorepo-graph` in `ci.yml` (no `uv sync`, no
  paths filter — runs in seconds on the runner's system python3) running
  `check-floors` + `check-ci`.
- New **release-PR gate** job in `ci.yml`: triggers on PRs from
  `release-please--*` branches, runs `check-publishable` for that PR's
  package, and fails the status check while any floor is unsatisfiable.
  Merging release PRs out of order becomes impossible (a red check), not a
  remembered ritual.

  - `units` — print all checkable units in topological order (upstream
    first), for the root orchestrators below.
  - `check-scripts` — verify the local-tooling contract (Part D): every unit
    exposes `scripts/check`, and each root orchestrator covers exactly the
    intended unit set. Exit 1 listing any drift.

`AGENTS.md` "Cross-package version floors" section gets updated to point at
the tool (the rule "bump both in the same commit" becomes "`check-floors`
tells you what to bump"), and the "Commits, PRs, releases" section gains a
short release-ordering protocol:

1. Feature PR bumps floors for any new upstream feature it uses (same commit).
2. Merge release PRs upstream-first (`release-order` prints the order);
   the release-PR gate enforces it.
3. If the gate is red, the blocker is upstream: an unmerged release PR or a
   failed publish job — fix that, not the gate.

## Part D — Consistent local tooling & orchestration (monorepo)

Current state is inconsistent: `pywire-templates` and `tree-sitter-pywire`
have only `scripts/check`; `lint`/`test`/`coverage` exist in some units and
not others; and the root orchestrators (`scripts/check`, `scripts/test`,
`scripts/lint`) are hardcoded per-package lists in dependency order — the
same hand-maintained graph as `ci.yml`, and already drifting (`scripts/lint`
omits cli/auth/parser/templates/prettier/tree-sitter with nothing verifying
whether that's intentional).

**Interface contract** (documented in `AGENTS.md`):
- Every checkable unit MUST expose `scripts/check` = the full local gate
  (format, lint, types, generated-code staleness, tests) — already true
  today, now enforced by `check-scripts`.
- `scripts/lint` (format+lint only) and `scripts/test` (tests only) are
  OPTIONAL granular entry points. No forced shims — orchestrators skip units
  that lack them.

**Orchestration**:
- Root `scripts/check`, `scripts/test`, `scripts/lint` iterate
  `monorepo_graph.py units` (topological order: grammar/parser before
  consumers, client build before pywire checks) instead of hardcoded lists —
  a new package is orchestrated automatically and ordering is correct by
  construction.
- Root `scripts/check` gains `--changed [base-ref]`: run only units affected
  by the working tree / branch diff, computed from the same graph (cheap
  local scoped checks — addresses local-speed pain without nx).
- `scripts/hooks/pre-git-check.sh` keeps its file→unit mapping but sources
  the unit list from the graph script, so hook, orchestrators, and `ci.yml`
  can't drift apart (all three verified by `check-scripts`/`check-ci`).

## Part B — CI/CD speed & hygiene (monorepo + pywire.dev)

Monorepo (`ci.yml`, `release.yml`, `test-publish.yml`, `deploy-docs.yml`,
`codeql.yml`):

1. **Node 24 everywhere**: all `node-version: '22'` → `'24'`.
2. **Action majors**: bump first-party actions to the latest major that runs
   on the node24 runtime (kills the deprecation warnings):
   `actions/checkout@v5`, `actions/setup-node@v5` (implementer verifies each
   action's current latest major and runtime at implementation time —
   `dorny/paths-filter`, `Swatinem/rust-cache`, `dtolnay/rust-toolchain`,
   `cloudflare/pages-action`, `astral-sh/setup-uv` included in the sweep).
   Explicitly: `googleapis/release-please-action@v4` → `@v5` (v5.0.0's only
   breaking change is the node24 runtime; config/manifest interface
   unchanged, and it bumps the bundled release-please lib 17.3.0 → 17.6.0).
3. **pnpm 10 in CI**: all `pnpm/action-setup` `version: 9` → `10` (matches
   local; `pnpm-workspace.yaml` `allowBuilds` starts applying — sanity-check
   the install step afterward).
4. **Scoped uv syncs**: Python check jobs use `uv sync --package <pkg>` (with
   the extras each package's `scripts/check` already assumes) instead of
   full-workspace sync.
5. **Playwright browser cache** in `check-pywire`: `actions/cache` on
   `~/.cache/ms-playwright` keyed by the resolved Playwright version.
6. **pnpm store caching**: `actions/setup-node` with `cache: pnpm` (ordered
   after `pnpm/action-setup`) in the JS-heavy jobs (`check-pywire`,
   `check-vscode`, `check-prettier`, `check-pywire-docs`, `deploy-docs`).
7. **PR concurrency**: `concurrency: ci-${{ github.ref }}` with
   `cancel-in-progress: true` for pull_request runs in `ci.yml`.
8. **Spec/planning docs don't trigger docs CI**: add `!docs/superpowers/**`
   to the `pywire-docs` paths-filter, and skip the docs unit in
   `scripts/hooks/pre-git-check.sh` when the commit only touches
   `docs/superpowers/**`.

pywire.dev (`ci.yml`, `deploy.yml`): Node 20 → 24, `pnpm/action-setup@v2` →
`@v4` with version 10, action-major sweep same as above.

## Part C — Terraform remote state + workflows (pywire.dev)

### Backend

`infra/main.tf` gains (and is applied via migration, see bootstrap):

```hcl
terraform {
  backend "s3" {
    bucket                      = "pywire-tfstate"
    key                         = "pywire.dev.tfstate"
    region                      = "auto"
    endpoints                   = { s3 = "https://<account_id>.r2.cloudflarestorage.com" }
    skip_credentials_validation = true
    skip_region_validation      = true
    skip_requesting_account_id  = true
    skip_metadata_api_check     = true
    use_lockfile                = true   # TF >= 1.10; single-maintainer contention is minimal regardless
  }
}
```

(Implementer verifies against current R2/S3-backend docs — e.g. whether
`skip_s3_checksum` is needed with the pinned Terraform version. Terraform
pinned to a current 1.x in the workflows via `hashicorp/setup-terraform`.)

### Workflows (new, in pywire.dev `.github/workflows/`)

- **`infra-plan.yml`**
  - `pull_request` on paths `infra/**`, `worker/**` (the Worker's
    `content_sha256` makes worker edits produce a plan diff):
    `terraform plan -detailed-exitcode`; posts the plan as a PR comment
    (`actions/github-script`); a non-empty plan on a PR is *expected* →
    comment only, never fails the PR.
  - `push` to `main` on the same paths: same plan, but a non-empty result
    **fails the job** — this is the "applied infra does not match what the
    PR expects" error. Failure message tells you to run the apply workflow.
  - `schedule` (weekly): same check; on drift, opens a GitHub issue via
    `gh issue create` (deduped by title). Included because it reuses the same
    job for ~10 extra lines.
- **`infra-apply.yml`**
  - `workflow_dispatch` only, hard-coded to the `main` branch.
  - `concurrency: terraform` (no cancel-in-progress) so plans/applies
    serialize against the state lock.
  - `terraform init` + `apply -auto-approve`, then a final
    `plan -detailed-exitcode` that must be empty → apply job is
    self-verifying.
  - Both workflows run `init` with the R2 S3 credentials from secrets
    (`AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` env from
    `R2_ACCESS_KEY_ID`/`R2_SECRET_ACCESS_KEY` secrets) and
    `TF_VAR_cloudflare_api_token` from `CLOUDFLARE_API_TOKEN`.

### Secrets to add in pywire.dev repo settings

- `CLOUDFLARE_API_TOKEN` — expand the existing token (or mint `pywire-terraform`)
  with: Account → Cloudflare Pages:Edit, Workers Scripts:Edit, R2 Storage:Edit.
  Current value is recoverable from local `infra/terraform.tfvars`.
- `CLOUDFLARE_ACCOUNT_ID` — dashboard → any domain → right sidebar.
- `R2_ACCESS_KEY_ID` / `R2_SECRET_ACCESS_KEY` — dashboard → R2 → Manage R2 API
  Tokens → token with Object Read & Write scoped to `pywire-tfstate`.

### One-time bootstrap runbook (executed during implementation, documented in the plan)

1. Create R2 bucket `pywire-tfstate` (dashboard, once — not in Terraform to
   avoid the state-backend chicken-and-egg).
2. Add the four secrets above to pywire.dev.
3. Locally in `infra/`: commit the backend block, `terraform init -migrate-state`
   (migrates local state into R2), `terraform plan` must be empty.
4. Archive the local `terraform.tfstate*` files out of the repo dir.
5. Merge → open a no-op PR touching `infra/` to see plan comment; merge;
   confirm drift job passes; run `infra-apply` once to confirm green.

## Decision records

- **Bun → rejected.** Cloudflare impact is nil in our favor (Pages never
  builds; GHA builds and pushes), so there's no deployment story to gain.
  Win would be install seconds at 330 KB-lockfile scale; risks are real
  (`vsce`/keytar native builds, `tree-sitter-cli` build scripts, lockfile
  migration). The free fix — pnpm 10 in CI — is in Part B. User agreed.
- **nx/turborepo → rejected for now.** nx *can* orchestrate Python
  (`nx:run-commands`, community `@nxlv/python`), and `nx affected` +
  caching are real — but against the actual pain ranking (floors > CI YAML >
  local speed > CI speed): it does nothing for release-please floors, and it
  replaces one hand-maintained graph with another plus an orchestration
  layer. CI is already path-scoped, so remote caching saves only work that
  scoped jobs already skip. Part A derives the graph from `pyproject.toml`
  and verifies both floors and `ci.yml` — the two top pains — with a stdlib
  script. **Revisit triggers**: JS package count grows substantially, a
  second maintainer appears (shared remote cache starts paying), or
  full-repo local check time becomes the measured bottleneck.
- **OpenTofu → rejected.** Benefits over Terraform here are licensing
  (MPL vs BUSL) and client-side state encryption; no functional need, and
  Terraform is what's installed. Same provider, zero migration cost if ever
  revisited.
- **State on R2/S3 backend → chosen** over GitHub artifacts/cache (no
  locking, eviction semantics) and over Terraform Cloud (paid tier for the
  useful features). R2 is free at this size and stays in the Cloudflare
  account that owns the infra.

## Success criteria

- `python3 scripts/monorepo_graph.py check-floors`, `check-ci`, and
  `check-scripts` pass on main, and each demonstrably fails when a floor, an
  `if:` condition, or a unit's script interface is perturbed.
- `./scripts/check` iterates units in topological order from the graph (no
  hardcoded package list); `./scripts/check --changed` on a parser-only
  branch runs parser + its downstream units and nothing else.
- CI on a docs-only PR runs zero Python jobs; a parser-only PR runs exactly
  the parser's downstream jobs (unchanged behavior, now machine-verified).
- No workflow in either repo references Node 20/22 or node20-runtime action
  majors (including release-please-action, on v5); GHA deprecation warnings
  gone from run summaries.
- `terraform plan` in CI (pywire.dev) is green on main; a PR editing
  `infra/` shows a plan comment; merging without applying turns the main
  drift job red; `infra-apply` dispatch turns it green again.
- Local `terraform.tfstate` no longer exists in pywire.dev; state is in R2
  with locking.

## Open questions

None blocking. Minor implementation-time verifications are inline above
(action majors, R2 backend flags, pnpm 10 install behavior).
