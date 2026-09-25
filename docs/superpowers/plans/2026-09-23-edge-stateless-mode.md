# Edge Stateless Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (chosen execution method) to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Per-task model assignments are in **Execution & Model Budget** below.

**Goal:** Make PyWire the fastest-practical server-driven framework at the edge: stateless snapshot round-tripping on any FaaS platform (Cloudflare Workers, AWS Lambda, Azure Functions, GCP), O(1) list updates via per-iteration region diffing, and declarative optimistic UI — so typical interactions feel instant and cost near-zero server resources.

**Architecture:** A new "stateless mode" (`PyWire(stateless=True)`) where the serialized page snapshot (already produced by `session_serializer.snapshot_page_state`) is HMAC-signed, embedded in the initial HTML, and round-tripped on every event via `POST /_pywire/stateless`. The server restores → dispatches → renders dirty regions → re-snapshots (Livewire v3's model, but with msgpack + fine-grained regions). Two engine optimizations make the payloads small enough for that model to win: **keyed per-iteration `{$for}` regions** (LiveView's comprehension-diff idea — one toggled row ships ~200 B, not the whole loop) and **declarative optimistic UI** (client applies presentation-level predictions instantly; the server morphdom patch _is_ the reconciler — wrong predictions self-revert). `{$await}` degrades to hold-open-until-budget inside the request. All FaaS targets ride one `OneShotASGIAdapter` (extracted from the existing Pyodide adapter). Durable-Object/WebSocket mode is untouched and remains the tier for server-push features.

**Tech Stack:** Python 3.11+ / Starlette / msgpack / stdlib `hmac`+`hashlib`+`base64` (no new deps); TypeScript client (existing transport + morphdom); Jinja2 deploy templates in `pywire-templates`; CLI wiring in `pywire-cli`.

**Spec (inline — this plan is the spec):**

1. Stateless event round-trip: `POST /_pywire/stateless` with msgpack `{snapshot, handler, data, path}` → response msgpack `{type:"update", regions, commands, meta, snapshot}`.
2. Snapshot is HMAC-SHA256 signed; tampered/corrupt snapshots → HTTP 400, never a crash or state injection.
3. Snapshot excludes `page.user` (re-resolved server-side per request) and any wire marked `.lock()`.
4. Handler dispatch is restricted to a compile-time allowlist (`__event_handlers__`).
5. `{$await}` blocks hold the request open up to `PyWire(await_budget=5.0)` seconds; still-pending tasks are cancelled at response time and reported via `meta.pending_awaits`. Unbounded background work and server push remain stateful-tier features (documented, build-time hint).
6. **Keyed list regions:** a `{$for ... key=K}` loop whose item fields are mutated re-renders and ships ONLY the affected iteration's region (`{site_id}#{key}`). Structural changes (append/remove/reorder/full reassign) fall back to whole-loop region render (v1 ceiling — documented). Acceptance: toggling one row of a 5000-row list ships ≤ 1 KB total payload (from 913 KB baseline measured in `scratch/adhoc/bench_engine.py`).
7. **Optimistic UI:** `@click.optimistic` (+ `.optimistic-class-<name>` variants) applies `data-pw-pending` + declared classes to the event target synchronously on dispatch (< 1 frame), guarded against double-submit, and reconciled solely by the arriving morphdom patch (correct prediction = no-op; wrong prediction = auto-revert). No JS-side reimplementation of handler logic, ever.
8. New deploy platforms: `cloudflare-edge` (plain Worker), `aws-lambda`, `azure-functions`, `gcp-functions`, `gcp-cloudrun` (reuses docker output). All produce `.pywire/deploy/<platform>/` with per-platform README deploy commands.
9. Measured gate before shipping multi-provider targets: counter-app event round-trip ≤ 15 ms server-side in local `wrangler dev` (workerd+Pyodide), snapshot ≤ 250 B, 1000-row single-item toggle ≤ 1 KB payload, no per-event storage I/O.

## Global Constraints

- Monorepo rules from `AGENTS.md`: uv workspace, pnpm (never npm), `ty` not mypy, ruff format/check, conventional commits with scopes (`pywire`, `pywire-cli`, `pywire-templates`, `pywire-docs`).
- Cross-package version floors: `pywire-cli`/`pywire-templates` start using new `pywire` runtime APIs (snapshot codec, one-shot adapter, keyed regions) → bump the dep floor in their `pyproject.toml` **and** `_FLOORS` in their `src/<package>/_compat.py` in the same commit (Task 24 owns the final bump; earlier tasks must not import new APIs from CLI/templates).
- Transport parity: middleware/auth behave identically for the stateless POST and normal HTTP loads — the endpoint is mounted _inside_ the Starlette app so the full middleware stack applies. Keyed-region rendering is transport-agnostic (same `render_update` output shape on WS, HTTP-session, and stateless).
- No new runtime Python dependencies in `pywire` core (stdlib `hmac`/`hashlib`/`base64` only). No new npm deps in the client (morphdom already present).
- Client TS changes require rebuild: `cd packages/pywire/src/pywire/client && pnpm install && pnpm build` (outputs into `pywire/static/`); commit built assets in the same commit.
- Per-package checks: run `./scripts/check` (and `./scripts/test` for Python packages) from each touched package dir before committing. The pre-commit hook runs them anyway — never bypass.
- Secrets: `PyWire(secret_key=...)` or env `PYWIRE_SECRET_KEY`; stateless mode MUST refuse to start without one — never auto-generate.
- Throwaway verification scripts go in `scratch/adhoc/` and follow the scratchpad skill (independent review before execution).

## Review Focus

1. **Tampered snapshot** — flipping any byte, or replaying a snapshot signed with another secret, must yield HTTP 400 with no state mutation (Task 4 test).
2. **Secret leakage** — `.lock()`ed wires and `page.user` never appear in an emitted snapshot; locked attrs are re-initialized by frontmatter on restore (Tasks 3, 6 tests).
3. **Handler allowlist bypass** — `handler="__init__"`, `"attrs"`, or any public non-handler attribute is refused, not dispatched (Task 5 test).
4. **Await overrun** — a 10 s `{$await}` with `await_budget=0.5` responds in ≈0.5 s with `meta.pending_awaits == 1`, no task writes to a closed response (Task 7 test).
5. **Missing secret** — `PyWire(stateless=True)` with no secret raises at construction naming `PYWIRE_SECRET_KEY` (Task 6 test).
6. **Keyed-region staleness** — an item mutation must NOT leave a sibling row showing stale data, and a structural change (append) must NOT ship only a partial loop (full-loop fallback fires). Both pinned (Task 12 tests).
7. **Key identity churn** — duplicate or unstable `key=` values within one loop must not cross-wire regions (two rows updating each other's DOM). Pinned (Task 11 test).
8. **Optimistic prediction never survives contradiction** — a class predicted ON but rejected server-side must be gone from the DOM after the patch; pending guard must not permanently disable a control if the response errors (Tasks 15–17 tests).
9. **Oversized snapshots** — a 1 MB wire state still round-trips (no hard cap v1) but logs via `session_warn_size` (Task 4 test).

## Execution & Model Budget

Execution method: **subagent-driven** (fresh implementer per task, cross-family reviewer gate before the next task, whole-branch review at each phase end). Model selection for every subagent seat is governed by the **`model-routing` skill** (`.agents/skills/model-routing/SKILL.md` + `references/fleet.md`) and AGENTS.md's "Model routing" section — those are the source of truth; this block is a plan-local summary. The orchestrator seat maps to **MiMo V2.6 Pro** per protocol (the active pi session should match it; escalation → Kimi K3 [validated-only] — the Opus path is BANNED, see below).

**Fleet (OpenRouter IDs, in/out per Mtok, queried 2026-09-24):**

| Seat | Model(s) | ID(s) | $/M | Flags |
|---|---|---|---|---|
| Orchestrator (default) | MiMo V2.6 Pro | `xiaomi/mimo-v2.6-pro` | 0.43/0.87 | top open-weight, no reliability flag |
| Primary coding (large/complex) | rotate MiMo V2.6 Pro · Qwen3.8 Max · GLM 5.3 | `xiaomi/mimo-v2.6-pro` · `qwen/qwen3.8-max-0902` · `z-ai/glm-5.3` | 0.43/0.87 · 2.00/6.00 · 1.40/4.40 | GLM coding output gets MORE review scrutiny (reliability flag) |
| Long-horizon multi-file | Kimi K2.6 | `moonshotai/kimi-k2.6` | 0.95/4.00 | steadier than K3 |
| Small/cheap coding + long-context | DeepSeek V4.1 Flash · MiMo V2.6 Flash · GLM-5.3-Flash | `deepseek/deepseek-v4.1-flash` · `xiaomi/mimo-v2.6-flash` · `z-ai/glm-5.3-flash` | 0.30/1.20 · 0.14/0.28 · 0.04/0.60 | route by language/task fit |
| Review (general) | cross-family from author — MANDATORY | — | — | never same family as author |
| Security review | GLM 5.3 | `z-ai/glm-5.3` | 1.40/4.40 | mandatory on auth/secrets/input-validation/external-surface diffs |

**Excluded / banned:** `deepseek/deepseek-v4-pro*` (EXCLUDED by fleet policy — scores below its own V4.1 Flash; used by T3/T4/T28 before this policy → historical, not re-run). All frontier-lab models (Anthropic/OpenAI/Google) — includes `gemini` (cut 2026-09-24) and `claude-opus-5.5`. **Opus conflict:** the fleet skill keeps Opus 5.5 as a complexity-gated escalation for the orchestrator/security seats, but the owner's standing directive ("no more opus ever", 2026-09) supersedes it per the superpowers precedence rule (user instructions > skills). The gate's Opus option is therefore DISABLED; escalation routes to the next-best fleet model, and any security item that outgrows GLM 5.3 becomes a human decision point, not an auto-Opus call. → **owner to confirm.**

**Hard constraints (from the skill, enforced at every dispatch):**
1. Reviewer family ≠ author family (cross-family review, mandatory).
2. Any diff touching auth/secrets/input-validation/an external surface gets a **mandatory GLM 5.3 security pass** (+ a second independent reviewer if GLM authored it).
3. Complexity gate (orchestrator/security seats): Opus escalation disabled (above); in-fleet, a high-effort × security-critical item gets GLM 5.3 + human escalation.
4. Escalation rule: flash/small-tier output that fails review or exceeds a 2-attempt budget escalates one tier up — not a third identical retry.
5. Shadow validation: GLM 5.3 and Kimi K3 carry "falls apart on real work" flags — their committed CODE gets extra scrutiny; neither gets unattended orchestrator authority until validated against MiMo Pro.
6. Provenance: each work item logs `work_item_id, tier, author_model, reviewer_model, context_tokens, gate_count, escalated, escalation_reason, outcome, rework_count` to the SDD ledger.

The per-phase tables below are a **historical as-run record** (phases 0–5B): the models shown are what actually ran, including now-banned `opus` (phases 1/3/5), now-excluded `deepseek-v4-pro` (T3/4/28), and now-cut `gemini` (reviews). Kept for provenance, NOT forward routing — remaining work routes per the block after the table.

| Phase                              | Complexity                                                             | Implementer                                                                        | Reviewer                                                                                     | Est. cost |
| ---------------------------------- | ---------------------------------------------------------------------- | ---------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------- | --------- |
| 0 — quick wins (T1–2)              | **Low** — mechanical transforms, pinned by tests                       | `z-ai/glm-5.3-flash`                                                               | `xiaomi/mimo-v2.6-flash`                                                                     | < $1      |
| 1 — stateless core (T3–7)          | **High** — security boundary, app.py refactor                          | `deepseek/deepseek-v4-pro-0813`; T5+T6 → `anthropic/claude-opus-5.5`               | T3,4,7: `google/gemini-3.8-flash`; **T5,6: `claude-opus-5.5`** (short diffs, highest stakes) | $8–20     |
| 2 — client transport (T8–9)        | **Medium** — TS, fully spec'd interfaces                               | `z-ai/glm-5.3`                                                                     | `google/gemini-3.8-flash`                                                                    | $2–5      |
| 3 — keyed {$for} regions (T10–13)  | **Very high** — 5k-line codegen + runtime invalidation; riskiest phase | T10 spike: `qwen3.8-max-0902`; T11–13: `anthropic/claude-opus-5.5` (high thinking) | `qwen3.8-max-0902` (cross-family)                                                            | $20–50    |
| 4 — optimistic UI (T14–17)         | **Medium-high** — client + attrs codegen, e2e timing                   | `qwen3.8-max-0902`; T14 → `z-ai/glm-5.3`                                           | `google/gemini-3.8-flash`; T17 → `qwen3.8-max-0902`                                          | $5–12     |
| 5 — validation gate (T18–20)       | **Low-medium** to build, **judgment-heavy** to evaluate                | `xiaomi/mimo-v2.6-pro`                                                             | Numbers reviewed by parent session; `claude-opus-5.5` only if gate marginally fails          | $2–5      |
| 6 — deploy targets + docs (T21–25) | **Low-medium** — pattern repeats after T20/T21                         | `xiaomi/mimo-v2.6-pro`; T21 (AWS, first of pattern) → `z-ai/glm-5.3`               | `xiaomi/mimo-v2.6-pro` (task); `qwen/qwen3.8-max-0902` (phase-end)                           | $3–8      |

> **FORWARD ROUTING (remaining work, per the model-routing skill).** Reviewer is always cross-family from author. Historical rows above are as-run and do not change.
>
> | Item | Author | General reviewer | Security pass | Notes |
> |---|---|---|---|---|
> | T29 review (pending) | `xiaomi/mimo-v2.6-pro` | `qwen/qwen3.8-max-0902` | not triggered (wire-arg semantics, not auth/secrets) | reviewer must scrutinize the framework-wide `generator.py` `unwrap_wire` arg change |
> | Phase 5B phase-end | T28 deepseek-v4-pro (hist) + T29 mimo | `z-ai/glm-5.3` | folded into retro pass | cross-family from both authors |
> | **Retroactive security review** (NEW, mandatory) | — | — | `z-ai/glm-5.3` | T27 snapshot inspector (external debug endpoint + HMAC), T28 poll allowlist dispatch-auth, Phase 1 stateless codec HMAC — all shipped without the now-mandatory GLM pass; schedule before merge |
> | T30 (5C spike) | `xiaomi/mimo-v2.6-pro` | human gate (findings, not committed code) | n/a | investigation + scratch prototype |
> | T21–23 (deploy targets) | `deepseek/deepseek-v4.1-flash` or `xiaomi/mimo-v2.6-flash` (scaffold/config) | cross-family (`qwen3.8-max` / `glm-5.3`) | GLM pass if templates touch secrets/env | pattern repeats after T20 |
> | T24 (gating + floors) | `qwen/qwen3.8-max-0902` (correctness) | cross-family (`z-ai/glm-5.3`) | **yes** — missing-secret build check = secrets surface | |
> | T25 (docs) | `qwen/qwen3.8-flash` or `deepseek-v4.1-flash` (docs glue) | cross-family light | no | |
> | Final whole-branch review | — | `qwen/qwen3.8-max-0902` + `z-ai/glm-5.3` | **yes** — full-branch GLM security (stateless core is the trust boundary) | strongest cross-family + security |
>
> **Compliance flags (completed work):**
> - **T28 used `deepseek/deepseek-v4-pro-0813`** — now fleet-EXCLUDED. Historical deviation (predates policy); work is orchestrator-verified, will NOT re-run. Logged in the provenance ledger.
> - **T27's debug snapshot inspector shipped without the mandatory GLM 5.3 security pass** — it handles HMAC-signed blobs on an external-facing debug endpoint. Real gap; the retroactive security review above closes it before merge.
> - Phases 1/3/5 used `claude-opus-5.5` before the owner's permanent ban; T3/T4 + phase 5A/5B task reviews used `gemini` (now cut). Historical; not re-run.
| 5A — tier rectification (T26–27)   | **Medium-high** — removes shipped machinery, gates tiers at build      | `qwen/qwen3.8-max-0902` (T26); `xiaomi/mimo-v2.6-pro` (T27)                        | `google/gemini-3.8-flash`                                                                    | $3–6      |
| 5B — poll primitive (T28–29)       | **Medium** — grammar + client directive, e2e + demo                    | `deepseek/deepseek-v4-pro-0813` (T28); `xiaomi/mimo-v2.6-pro` (T29)                | `xiaomi/mimo-v2.6-pro` (task); `qwen/qwen3.8-max-0902` (phase-end)                           | $3–6      |
| 5C — per-page tier spike (T30)     | **Spike only — findings gate, no committed design**                    | `qwen/qwen3.8-max-0902`                                                            | findings reviewed by parent session + human gate                                             | $1–3      |

**Forward cost (remaining work): ~$8–20** — T29 review + 5B phase-end + retroactive security pass + T30 spike + Phase 6 + final whole-branch review, driven mainly by the GLM 5.3 security passes and the final review. Cost levers: (a) reviewer prompts get the diff only, not the codebase; (b) `:batch` variants (`z-ai/glm-5.3:batch` $0.45/$2.00, deepseek batch) halve non-interactive Phase 6 work; (c) small/cheap tier (DeepSeek V4.1 Flash, MiMo Flash, GLM-Flash) for scaffold/docs, escalating per the 2-attempt rule. Historical phases 0–5B spend is sunk.

---

## Phase 0 — Hot-path quick wins (ship independently)

### Task 1: Lazy log formatting on the wire read/write hot path

**Files:**

- Modify: `packages/pywire/src/pywire/core/wire.py` (`_track_read`, `_notify_write`)
- Modify: `packages/pywire/src/pywire/runtime/page.py` (`_register_wire_read`, `_invalidate_wire`)
- Test: `packages/pywire/tests/test_wire_logging_lazy.py`

**Interfaces:**

- Consumes: nothing.
- Produces: identical log record _content_ (verified by test) with `%s`-style lazy args; no API change.

- [ ] **Step 1: Write the failing test** — asserts hot-path debug logs still render correctly AND use lazy args:

```python
import logging
from pywire import wire

def test_wire_debug_logs_lazy(caplog):
    w = wire(1)
    with caplog.at_level(logging.DEBUG, logger="pywire.core.wire"):
        _ = w.value
        w.value = 2
    msgs = [r.getMessage() for r in caplog.records]
    assert any("WIRE-NOTIFY" in m for m in msgs)
    notify = [r for r in caplog.records if "WIRE-NOTIFY" in r.getMessage()][0]
    assert notify.args, "expected lazy %-args on hot-path debug log"

def test_no_formatting_when_disabled(caplog):
    w = wire(1)
    with caplog.at_level(logging.INFO, logger="pywire.core.wire"):
        for i in range(100):
            w.value = i
    assert not [r for r in caplog.records if "WIRE-NOTIFY" in r.getMessage()]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --package pywire --extra dev pytest tests/test_wire_logging_lazy.py -v`
Expected: FAIL — `notify.args` is empty because current code uses f-strings.

- [ ] **Step 3: Convert f-string `logger.debug` calls to lazy args** in the four named functions, e.g.:

```python
# wire.py _track_read — before:
logger.debug(f"WIRE-TRACK: wire={id(self)} registered page={id(page)} region={region_id} field={field}")
# after:
logger.debug("WIRE-TRACK: wire=%s registered page=%s region=%s field=%s",
             id(self), id(page), region_id, field)
```

Same transformation for `_notify_write` (`WIRE-NOTIFY`), `page._register_wire_read` (`register_read:`), `page._invalidate_wire` (`INVALIDATE:`). Do not touch non-hot-path logging.

- [ ] **Step 4: Run tests**

Run: `uv run --package pywire --extra dev pytest tests/test_wire_logging_lazy.py tests/ -x -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/pywire/src/pywire/core/wire.py packages/pywire/src/pywire/runtime/page.py packages/pywire/tests/test_wire_logging_lazy.py
git commit -m "perf(pywire): lazy %-args for hot-path wire/page debug logs"
```

### Task 2: Throttled DO session persistence

**Files:**

- Modify: `packages/pywire/src/pywire/runtime/cf_durable_object.py` (add `ThrottledPersister`)
- Modify: `packages/pywire-templates/src/pywire_templates/deploy/pywire_do.py.j2` (use it)
- Test: `packages/pywire/tests/test_cf_durable_object.py` (extend if exists, else create)

**Interfaces:**

- Consumes: nothing.
- Produces: `ThrottledPersister(interval: float = 2.0)` with `should_persist(now: float) -> bool` — True on first call, then at most once per `interval`; `force() -> bool` always True and resets the clock (used on close/hibernate).

- [ ] **Step 1: Write the failing test**

```python
from pywire.runtime.cf_durable_object import ThrottledPersister

def test_throttled_persister():
    p = ThrottledPersister(interval=2.0)
    assert p.should_persist(100.0) is True     # first write always persists
    assert p.should_persist(100.5) is False
    assert p.should_persist(101.9) is False
    assert p.should_persist(102.1) is True     # interval elapsed
    assert p.should_persist(102.2) is False
    assert p.force() is True                   # close/hibernate path
    assert p.should_persist(102.3) is False    # force reset the clock
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --package pywire --extra dev pytest tests/test_cf_durable_object.py -v`
Expected: FAIL — `ImportError: cannot import name 'ThrottledPersister'`.

- [ ] **Step 3: Implement** in `cf_durable_object.py`:

```python
class ThrottledPersister:
    """Rate-limit DO storage writes; always persist on close/hibernate."""

    def __init__(self, interval: float = 2.0) -> None:
        self._interval = interval
        self._last: float | None = None

    def should_persist(self, now: float) -> bool:
        if self._last is None or now - self._last >= self._interval:
            self._last = now
            return True
        return False

    def force(self) -> bool:
        import time
        self._last = time.monotonic()
        return True
```

- [ ] **Step 4: Update the DO template** `pywire_do.py.j2`: import `ThrottledPersister` and `time`; in `__init__` add `self._persister = ThrottledPersister(2.0)`; in `_handle_event` / `_handle_init` / `_handle_relocate` replace `await self._persist_state()` with:

```python
if self._persister.should_persist(time.monotonic()):
    await self._persist_state()
```

Keep the unconditional `await self._persist_state()` in `on_webSocketClose`.

- [ ] **Step 5: Run tests + template check**

Run: `uv run --package pywire --extra dev pytest tests/test_cf_durable_object.py -v && cd packages/pywire-templates && ./scripts/check`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add packages/pywire/src/pywire/runtime/cf_durable_object.py packages/pywire/tests/test_cf_durable_object.py packages/pywire-templates/src/pywire_templates/deploy/pywire_do.py.j2
git commit -m "perf(pywire): throttle DO session persistence to 1 write / 2s + on close"
```

---

## Phase 1 — Stateless server core (`pywire` package)

### Task 3: Lockable wires (client-invisible state)

**Files:**

- Modify: `packages/pywire/src/pywire/core/wire.py` (`WireBase.lock()`, `_locked` flag)
- Modify: `packages/pywire/src/pywire/runtime/session_serializer.py` (skip locked in page and component snapshots)
- Test: `packages/pywire/tests/test_wire_locked.py`

**Interfaces:**

- Consumes: `WireBase` internals.
- Produces: `WireBase.lock() -> WireBase` (sets `_locked=True`, returns self, chainable off `wire(...)`); `WireBase._locked: bool` default False. `snapshot_page_state` omits locked wires from `attrs`/`wire_tags` and from `component_snapshots`.

- [ ] **Step 1: Write the failing test**

```python
from pywire import wire
from pywire.runtime.session_serializer import snapshot_page_state

class _FakePage:
    pass

def make_page():
    p = _FakePage()
    p.public = wire(1)
    p.token = wire("sk-secret").lock()
    p.errors = {}; p.loading = {}; p._components = {}; p._await_states = {}
    return p

def test_locked_wire_excluded_from_snapshot():
    snap = snapshot_page_state(make_page())
    assert snap["attrs"]["public"] == 1
    assert "token" not in snap["attrs"]
    assert "token" not in snap["wire_tags"]

def test_locked_wire_keeps_value_in_process():
    p = make_page()
    assert p.token.value == "sk-secret"   # lock() hides from snapshots only
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --package pywire --extra dev pytest tests/test_wire_locked.py -v`
Expected: FAIL — `AttributeError: 'WirePrimitive' object has no attribute 'lock'`.

- [ ] **Step 3: Implement** — in `WireBase.__init__` add `self._locked = False`; add:

```python
def lock(self) -> "WireBase":
    """Exclude this wire from client-visible session snapshots.
    The attr must be re-derivable by frontmatter on every instantiation."""
    self._locked = True
    return self
```

In `session_serializer.snapshot_page_state`, inside the wire branch (`isinstance(value, WireBase)`), `continue` before tagging when `value._locked`. Same in the component-snapshot loop.

- [ ] **Step 4: Run tests**

Run: `uv run --package pywire --extra dev pytest tests/test_wire_locked.py -v && uv run --package pywire --extra dev pytest tests -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/pywire/src/pywire/core/wire.py packages/pywire/src/pywire/runtime/session_serializer.py packages/pywire/tests/test_wire_locked.py
git commit -m "feat(pywire): wire.lock() excludes state from client snapshots"
```

### Task 4: Signed snapshot codec

**Files:**

- Create: `packages/pywire/src/pywire/runtime/snapshot_codec.py`
- Test: `packages/pywire/tests/test_snapshot_codec.py`

**Interfaces:**

- Consumes: `snapshot_page_state(page, warn_size=...)`, `restore_page_state(page, snapshot)` from `session_serializer`.
- Produces:
  - `class SnapshotError(Exception)`
  - `encode_snapshot(page, *, secret: bytes, warn_size: int = 0) -> str` — msgpack snapshot **without `user` key**, HMAC-SHA256 prefixed, urlsafe-b64 encoded.
  - `decode_snapshot(blob: str, *, secret: bytes) -> dict` — raises `SnapshotError` on bad base64, bad signature (`hmac.compare_digest`), corrupt msgpack, or non-dict payload.

- [ ] **Step 1: Write the failing tests** (Review Focus #1, #9)

```python
import base64
import pytest
from pywire import wire
from pywire.runtime.snapshot_codec import encode_snapshot, decode_snapshot, SnapshotError

SECRET = b"test-secret-key"

class _FakePage:
    pass

def make_page():
    p = _FakePage()
    p.count = wire(7)
    p.user = {"id": "u1", "token": "bearer-xyz"}
    p.errors = {}; p.loading = {}; p._components = {}; p._await_states = {}
    p.request = None
    return p

def test_round_trip():
    blob = encode_snapshot(make_page(), secret=SECRET)
    assert decode_snapshot(blob, secret=SECRET)["attrs"]["count"] == 7

def test_user_never_in_snapshot():
    snap = decode_snapshot(encode_snapshot(make_page(), secret=SECRET), secret=SECRET)
    assert "user" not in snap

def test_tampered_snapshot_rejected():
    blob = encode_snapshot(make_page(), secret=SECRET)
    raw = bytearray(base64.urlsafe_b64decode(blob))
    raw[-1] ^= 0xFF
    with pytest.raises(SnapshotError):
        decode_snapshot(base64.urlsafe_b64encode(bytes(raw)).decode(), secret=SECRET)

def test_wrong_secret_rejected():
    blob = encode_snapshot(make_page(), secret=SECRET)
    with pytest.raises(SnapshotError):
        decode_snapshot(blob, secret=b"other-secret")

def test_garbage_rejected():
    for bad in ("", "!!!", base64.urlsafe_b64encode(b"short").decode()):
        with pytest.raises(SnapshotError):
            decode_snapshot(bad, secret=SECRET)

def test_large_state_round_trips():
    p = make_page()
    p.big = wire([{"row": i, "name": f"item-{i}"} for i in range(5000)])
    blob = encode_snapshot(p, secret=SECRET, warn_size=1024)
    assert len(decode_snapshot(blob, secret=SECRET)["attrs"]["big"]) == 5000
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --package pywire --extra dev pytest tests/test_snapshot_codec.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement** `snapshot_codec.py`:

```python
"""HMAC-signed session snapshots for stateless (client-held state) mode."""

import base64
import hashlib
import hmac
import logging

import msgpack

from pywire.runtime.session_serializer import snapshot_page_state

logger = logging.getLogger(__name__)

_SIG_LEN = 32  # SHA-256


class SnapshotError(Exception):
    """Raised when a client snapshot is corrupt, tampered, or foreign."""


def encode_snapshot(page, *, secret: bytes, warn_size: int = 0) -> str:
    snap = snapshot_page_state(page, warn_size=warn_size)
    # Never trust the client with identity — re-resolved per request.
    snap.pop("user", None)
    raw = msgpack.packb(snap)
    sig = hmac.new(secret, raw, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(sig + raw).decode("ascii")


def decode_snapshot(blob: str, *, secret: bytes) -> dict:
    try:
        data = base64.urlsafe_b64decode(blob.encode("ascii"))
    except Exception as exc:
        raise SnapshotError("malformed snapshot encoding") from exc
    if len(data) <= _SIG_LEN:
        raise SnapshotError("snapshot too short")
    sig, raw = data[:_SIG_LEN], data[_SIG_LEN:]
    expected = hmac.new(secret, raw, hashlib.sha256).digest()
    if not hmac.compare_digest(sig, expected):
        raise SnapshotError("snapshot signature mismatch")
    try:
        snap = msgpack.unpackb(raw, raw=False)
    except Exception as exc:
        raise SnapshotError("snapshot payload corrupt") from exc
    if not isinstance(snap, dict):
        raise SnapshotError("snapshot payload not a mapping")
    return snap
```

- [ ] **Step 4: Run tests**

Run: `uv run --package pywire --extra dev pytest tests/test_snapshot_codec.py -v`
Expected: PASS (all six).

- [ ] **Step 5: Commit**

```bash
git add packages/pywire/src/pywire/runtime/snapshot_codec.py packages/pywire/tests/test_snapshot_codec.py
git commit -m "feat(pywire): HMAC-signed stateless session snapshot codec"
```

### Task 5: Compile-time handler allowlist

**Files:**

- Modify: `packages/pywire/src/pywire/compiler/codegen/generator.py` (emit `__event_handlers__`)
- Modify: `packages/pywire/src/pywire/runtime/page.py` (`_dispatch_handler` enforcement)
- Test: `packages/pywire/tests/test_handler_allowlist.py`

**Interfaces:**

- Consumes: codegen's existing knowledge of frontmatter `FunctionDef`s and generated `_handle_bind_*` / `_handler_*` framework handlers.
- Produces: compiled page/component classes carry `__event_handlers__: frozenset[str]` — every user `def` name from frontmatter plus every framework-generated bind/handler name templates can emit. `_dispatch_handler` raises `ValueError` for names outside the set (when the set exists). `BasePage.__event_handlers__ = None` (hand-rolled test pages keep current permissive behavior).

- [ ] **Step 1: Write the failing test** (Review Focus #3) — compile a real `.wire` source via `PageLoader`:

```python
import asyncio
import pytest
from starlette.requests import Request
from pywire.runtime.loader import PageLoader

WIRE = """---
count = wire(0)

def increment():
    count.value += 1
---
<p>{count}</p>
<button @click={increment()}>go</button>
"""

def _page(tmp_path):
    f = tmp_path / "allowlist.wire"
    f.write_text(WIRE)
    cls = PageLoader().load(f, use_cache=False)
    scope = {"type": "http", "http_version": "1.1", "method": "GET", "path": "/",
             "raw_path": b"/", "root_path": "", "query_string": b"",
             "headers": [(b"host", b"localhost")], "scheme": "http",
             "server": ("localhost", 80), "client": ("127.0.0.1", 1)}
    return cls(request=Request(scope), params={}, query={}, path={"main": True})

def test_allowlist_contains_user_handlers(tmp_path):
    allowed = type(_page(tmp_path)).__event_handlers__
    assert allowed is not None and "increment" in allowed

@pytest.mark.parametrize("name", ["attrs", "render", "__init__", "navigate", "push_state"])
def test_dispatch_rejects_non_handlers(tmp_path, name):
    with pytest.raises(ValueError):
        asyncio.run(_page(tmp_path)._dispatch_handler(name, {}))

def test_dispatch_allows_listed_handler(tmp_path):
    page = _page(tmp_path)
    asyncio.run(page._dispatch_handler("increment", {}))
    assert page.count.value == 1
```

Security property being pinned: **arbitrary instance attributes, base methods, and dunder names are not dispatchable.** User frontmatter defs ARE in the set (they're addressable by `@click` today; excluding them changes behavior beyond security).

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --package pywire --extra dev pytest tests/test_handler_allowlist.py -v`
Expected: FAIL — `__event_handlers__` is None / dispatch of `render` succeeds.

- [ ] **Step 3: Implement.**
  - `page.py`: add `__event_handlers__: ClassVar[Optional[frozenset]] = None` to `BasePage`; in `_dispatch_handler`, after the existing framework-prefix branch:

```python
allowed = self.__class__.__event_handlers__
if allowed is not None and event_name not in allowed:
    raise ValueError(f"Handler '{event_name}' is not a registered event handler")
```

Keep the existing `startswith("_")` rejection after this check (framework `_handle_bind_`/`_handler_` names must be in the allowlist — verify codegen adds them; audit via full suite).

- `generator.py`: when building each page/component class body, collect a `frozenset` of (a) all frontmatter `FunctionDef`/`AsyncFunctionDef` names, (b) all `_handle_bind_*` names emitted by reactive-attribute codegen, (c) all `_handler_*` names emitted by event codegen; emit as `__event_handlers__`.

- [ ] **Step 4: Run test + full core suite** (expect fallout where tests dispatch non-handler names; fix by using real handlers in fixtures, not by weakening the check):

Run: `uv run --package pywire --extra dev pytest tests/test_handler_allowlist.py -v && uv run --package pywire --extra dev pytest tests -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/pywire/src/pywire/compiler/codegen/generator.py packages/pywire/src/pywire/runtime/page.py packages/pywire/tests/test_handler_allowlist.py
git commit -m "feat(pywire)!: enforce compile-time event handler allowlist in dispatch"
```

(Include `BREAKING CHANGE:` footer noting dispatch of unregistered names now raises — release-please per AGENTS.md.)

### Task 6: Stateless config + POST endpoint + snapshot embedding

**Files:**

- Create: `packages/pywire/src/pywire/runtime/stateless_handler.py`
- Modify: `packages/pywire/src/pywire/runtime/app.py` (config kwargs, route mount, snapshot embedding in `_handle_request`)
- Create: `packages/pywire/tests/fixtures/stateless_app/` (fixture app: `pages/index.wire` below)
- Test: `packages/pywire/tests/test_stateless_endpoint.py`

**Interfaces:**

- Consumes: `encode_snapshot`/`decode_snapshot`/`SnapshotError` (Task 4), `restore_page_state`, `resolve_page` (`pywire.runtime.page_resolver`), `build_update_payload` (`pywire.runtime.protocol`), app's HTTP user-resolution path.
- Produces:
  - `PyWire(stateless: bool = False, secret_key: str | None = None, await_budget: float = 5.0)`; `stateless=True` without secret (param or `PYWIRE_SECRET_KEY` env) raises `RuntimeError` at construction. Attributes: `app.stateless`, `app._stateless_secret: bytes`, `app.await_budget`, `app.state.stateless`.
  - Route `POST /_pywire/stateless` mounted only when `stateless=True`; body msgpack `{path, handler, data, snapshot}`; response `msgpack(build_update_payload(update) | {"snapshot": str})` with `meta.pending_awaits`; `SnapshotError` → 400 `{"error": "invalid snapshot"}`; unknown path → 404. In stateless mode, WS and HTTP-session routes are NOT mounted.
  - Initial GET renders embed `<script id="_pywire_snapshot" type="text/plain">{blob}</script>` before `</body>` and add `"stateless": true` to the `_pywire_spa_meta` JSON.
  - `StatelessHandler.build_page(request, path, snapshot) -> BasePage | None` — resolve, instantiate, restore, re-resolve `user` from the request (never from snapshot).
  - `app._instantiate_page(page_class, request, params, variant_name)` and `app._resolve_user_for_request(request)` — extracted from the existing `_handle_request` inline logic (behavior-preserving; existing app tests pin it).

- [ ] **Step 1: Write the failing tests** (Review Focus #2, #5) — model the `client` fixture on existing HTTP tests (see `packages/pywire/tests/test_app_runtime.py` for the TestClient pattern):

Fixture `tests/fixtures/stateless_app/pages/index.wire`:

```
---
count = wire(0)
api_key = wire("sk-hidden").lock()

def increment():
    count.value += 1
---
<p id="c">{count}</p><button @click={increment()}>+</button>
```

```python
import base64
import msgpack
import pytest

def _blob(html: str) -> str:
    return html.split('_pywire_snapshot" type="text/plain">')[1].split("</script>")[0]

def test_missing_secret_raises(monkeypatch):
    from pywire import PyWire
    monkeypatch.delenv("PYWIRE_SECRET_KEY", raising=False)
    with pytest.raises(RuntimeError, match="PYWIRE_SECRET_KEY"):
        PyWire(pages_dir="tests/fixtures/stateless_app", stateless=True)

def test_get_embeds_snapshot_without_secrets(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "_pywire_snapshot" in r.text
    assert "sk-hidden" not in r.text

def test_event_round_trip(client):
    blob = _blob(client.get("/").text)
    r = client.post("/_pywire/stateless",
                    content=msgpack.packb({"path": "/", "handler": "increment",
                                           "data": {}, "snapshot": blob}),
                    headers={"Content-Type": "application/x-msgpack"})
    assert r.status_code == 200
    msg = msgpack.unpackb(r.content, raw=False)
    assert msg["snapshot"] != blob
    assert any("1" in reg["html"] for reg in msg.get("regions", []))

def test_tampered_snapshot_400(client):
    raw = bytearray(base64.urlsafe_b64decode(_blob(client.get("/").text)))
    raw[-1] ^= 0xFF
    r = client.post("/_pywire/stateless",
                    content=msgpack.packb({"path": "/", "handler": "increment", "data": {},
                                           "snapshot": base64.urlsafe_b64encode(bytes(raw)).decode()}),
                    headers={"Content-Type": "application/x-msgpack"})
    assert r.status_code == 400

def test_user_never_restored_from_client(client):
    snap = msgpack.unpackb(base64.urlsafe_b64decode(_blob(client.get("/").text))[32:], raw=False)
    assert "user" not in snap
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --package pywire --extra dev pytest tests/test_stateless_endpoint.py -v`
Expected: FAIL — `PyWire.__init__() got an unexpected keyword argument 'stateless'`.

- [ ] **Step 3: Implement.**
  - `app.py`: add the three kwargs; resolve secret (`secret_key or os.environ.get("PYWIRE_SECRET_KEY")`, utf-8 encode); raise `RuntimeError("PyWire(stateless=True) requires secret_key= or the PYWIRE_SECRET_KEY env var — it signs client-held session snapshots")` when missing; export `app.state.stateless` next to `interactive_server_mode` (`app.py:482`); in the route builder (near `app.py:361-382`) mount `Route("/_pywire/stateless", self.stateless_handler.handle_event, methods=["POST"])` when stateless, and skip `WebSocketRoute`/`/_pywire/session`/`/_pywire/poll`/`/_pywire/event` mounts in that mode.
  - `stateless_handler.py`:

```python
import asyncio
import logging

import msgpack
from starlette.requests import Request
from starlette.responses import Response

from pywire.runtime.page_resolver import resolve_page
from pywire.runtime.protocol import build_update_payload
from pywire.runtime.session_serializer import restore_page_state
from pywire.runtime.snapshot_codec import SnapshotError, decode_snapshot, encode_snapshot

logger = logging.getLogger(__name__)


class StatelessHandler:
    def __init__(self, app) -> None:
        self.app = app

    async def build_page(self, request: Request, path: str, snapshot: dict):
        result = resolve_page(self.app.router, path, base_scope=dict(request.scope))
        if result is None:
            return None
        page_class, params, variant_name = result
        page = self.app._instantiate_page(page_class, request, params, variant_name)
        restore_page_state(page, snapshot)
        # identity ALWAYS from the request (middleware/session), never the client
        resolved_user = await self.app._resolve_user_for_request(request)
        if resolved_user is not None:
            page.user = resolved_user
        return page

    async def handle_event(self, request: Request) -> Response:
        try:
            data = msgpack.unpackb(await request.body(), raw=False)
        except Exception:
            return self._err(400, "malformed request body")
        try:
            snapshot = decode_snapshot(data.get("snapshot", ""),
                                       secret=self.app._stateless_secret)
        except SnapshotError as exc:
            logger.warning("stateless: rejected snapshot: %s", exc)
            return self._err(400, "invalid snapshot")
        page = await self.build_page(request, data.get("path", "/"), snapshot)
        if page is None:
            return self._err(404, "no route")

        captured: list = []

        async def capture_update() -> None:
            captured.append(await page.render_update(init=False))

        page._on_update = capture_update
        pending = 0
        try:
            handler_name = data.get("handler")
            if handler_name:
                update = await page.handle_event(handler_name, data.get("data", {}))
            else:
                update = await page.render_update(init=False)
            # {$await} hold-open: drain background tasks up to the budget
            tasks = {t for t in page._background_tasks if not t.done()}
            if tasks:
                await asyncio.wait(tasks, timeout=self.app.await_budget)
                pending = sum(1 for t in tasks if not t.done())
                if captured:
                    update = self._merge_updates(update, captured)
        except Exception:
            logger.exception("stateless: event failed")
            return self._err(500, "event failed")
        finally:
            for t in page._background_tasks:
                if not t.done():
                    t.cancel()

        payload = build_update_payload(update)
        payload["snapshot"] = encode_snapshot(
            page, secret=self.app._stateless_secret,
            warn_size=self.app.session_warn_size)
        payload.setdefault("meta", {})["pending_awaits"] = pending
        return Response(msgpack.packb(payload), media_type="application/x-msgpack")

    @staticmethod
    def _merge_updates(base: dict, extras: list) -> dict:
        regions = {r["region"]: r["html"] for r in base.get("regions", [])}
        commands = list(base.get("commands", []))
        for upd in extras:
            for r in upd.get("regions", []):
                regions[r["region"]] = r["html"]
            commands.extend(upd.get("commands", []))
        merged = dict(base)
        merged["regions"] = [{"region": k, "html": v} for k, v in regions.items()]
        if commands:
            merged["commands"] = commands
        return merged

    @staticmethod
    def _err(status: int, msg: str) -> Response:
        return Response(msgpack.packb({"error": msg}), status=status,
                        media_type="application/x-msgpack")
```

- Snapshot embedding: in `_handle_request`, after a successful `init=True` render and when `self.stateless`, inject the script tag before the last `</body>` (reuse `_find_tag_outside_raw_text` from `page.py`); `page.render` adds `"stateless": True` to the SPA meta dict when `request.app.state.stateless`.

- [ ] **Step 4: Run tests**

Run: `uv run --package pywire --extra dev pytest tests/test_stateless_endpoint.py -v && uv run --package pywire --extra dev pytest tests -q`
Expected: PASS (new + no regressions).

- [ ] **Step 5: Commit**

```bash
git add packages/pywire/src/pywire/runtime/stateless_handler.py packages/pywire/src/pywire/runtime/app.py packages/pywire/tests/test_stateless_endpoint.py packages/pywire/tests/fixtures/stateless_app
git commit -m "feat(pywire): stateless client-held-state mode with signed snapshot endpoint"
```

### Task 7: `{$await}` hold-open semantics test (Review Focus #4)

**Files:**

- Create: `packages/pywire/tests/fixtures/stateless_app/pages/slow.wire` + `fast_await.wire`
- Test: `packages/pywire/tests/test_stateless_await.py`
- Modify (only if the test exposes a bug): `packages/pywire/src/pywire/runtime/stateless_handler.py`

**Interfaces:**

- Consumes: Task 6 endpoint; `PyWire(await_budget=...)`.
- Produces: pinned semantics — response arrives ≈ budget after handler return; `meta.pending_awaits` counts unfinished tasks; cancelled tasks never write to the response.

- [ ] **Step 1: Write the tests.** `slow.wire` frontmatter: `async def slow_thing(): import asyncio; await asyncio.sleep(10)` with `{$await slow_thing()}loading...{:result}{/await}` (match actual `{$await}` syntax from existing tests — see `packages/pywire/tests/test_await*.py` for the exact directive form and mirror it). App fixture built with `await_budget=0.3`:

```python
import time
import msgpack

def _blob(html): return html.split('_pywire_snapshot" type="text/plain">')[1].split("</script>")[0]

def _post(client, path, blob, handler=None):
    return client.post("/_pywire/stateless",
        content=msgpack.packb({"path": path, "handler": handler, "data": {}, "snapshot": blob}),
        headers={"Content-Type": "application/x-msgpack"})

def test_overlong_await_returns_at_budget(client_await_budget):
    blob = _blob(client_await_budget.get("/slow").text)
    t0 = time.perf_counter()
    r = _post(client_await_budget, "/slow", blob)
    dt = time.perf_counter() - t0
    assert r.status_code == 200 and dt < 2.0
    assert msgpack.unpackb(r.content, raw=False)["meta"]["pending_awaits"] == 1

def test_fast_await_resolves_in_band(client_await_budget):
    blob = _blob(client_await_budget.get("/fast").text)   # asyncio.sleep(0) awaitable
    r = _post(client_await_budget, "/fast", blob)
    msg = msgpack.unpackb(r.content, raw=False)
    assert msg["meta"]["pending_awaits"] == 0
```

- [ ] **Step 2: Run — if it hangs > 5 s,** the drain/cancel logic in Task 6 has a bug (likely `asyncio.wait` on a growing set, or a task awaiting a send). Fix in `stateless_handler.py`, re-run.
- [ ] **Step 3: Full suite, then commit**

```bash
git add packages/pywire/tests packages/pywire/src/pywire/runtime/stateless_handler.py
git commit -m "test(pywire): pin stateless await hold-open and cancellation semantics"
```

---

## Phase 2 — Client transport

### Task 8: `StatelessTransport` (TS)

**Files:**

- Create: `packages/pywire/src/pywire/client/src/core/transports/stateless.ts`
- Modify: `packages/pywire/src/pywire/client/src/core/transports/index.ts` (export)
- Modify: `packages/pywire/src/pywire/client/src/core/app.ts` (selection when `meta.stateless`)
- Test: `packages/pywire/src/pywire/client/src/core/transports/stateless.test.ts` (vitest)

**Interfaces:**

- Consumes: `BaseTransport` (`transports/base.ts`), `encode`/`decode` from `@msgpack/msgpack`, existing update-application path in `app.ts` (the transport only emits `ServerMessage`s shaped exactly like the WS `update` payload — `build_update_payload` output plus `snapshot`).
- Produces: `class StatelessTransport extends BaseTransport`:
  - `constructor(baseUrl?: string)` — reads initial snapshot from the `#_pywire_snapshot` script tag.
  - `connect(): Promise<void>` — no network; `notifyStatus(true)`; emits `{type:'init', version}` from meta.
  - `send(msg)` — `type:'event'` → POST msgpack `{path, handler, data, snapshot}` to `/_pywire/stateless`, decode response, store `response.snapshot`, `notifyHandlers(response)`; `type:'relocate'` → `fetch(path)` GET, emit as full-document update through the existing full-update path, re-extract `#_pywire_snapshot` from the returned HTML.
  - Server error responses (400/404/500 msgpack `{error}`) → `notifyHandlers({type:'error', error})`.

- [ ] **Step 1: Write the failing vitest** — mock `fetch`; assert: event POST body decodes to `{path, handler, data, snapshot}`; response snapshot replaces the held one; a second event POSTs the NEW snapshot; HTTP 400 → `{type:'error'}` notified; relocate GETs the path and re-extracts the snapshot.
- [ ] **Step 2: Run to verify fail:** `cd packages/pywire/src/pywire/client && pnpm vitest run src/core/transports/stateless.test.ts` — FAIL (module missing).
- [ ] **Step 3: Implement** (~120 lines; model message plumbing on `websocket.ts`, request/response on `http.ts`).
- [ ] **Step 4: Wire selection** in `app.ts`: prefer `StatelessTransport` when `meta.stateless === true` (before the WS/WebTransport/HTTP fallback order).
- [ ] **Step 5: Tests + lint + types + build:**

Run: `cd packages/pywire/src/pywire/client && pnpm vitest run && pnpm exec tsc --noEmit && pnpm build`
Expected: PASS; built assets updated in `pywire/static/`.

- [ ] **Step 6: Commit**

```bash
git add packages/pywire/src/pywire/client packages/pywire/src/pywire/static
git commit -m "feat(pywire): stateless client transport (snapshot round-trip over fetch)"
```

### Task 9: End-to-end playwright test (stateless app)

**Files:**

- Modify: `packages/pywire/tests/e2e/fixtures/stateless_app/` (add a second page for SPA nav)
- Create: `packages/pywire/tests/e2e/test_stateless.py`

**Interfaces:**

- Consumes: everything from Phases 1–2; server started like existing e2e fixtures (`tests/e2e/conftest.py` — `pywire_cli.main` subprocess).

- [ ] **Step 1: Write the e2e test:** load `/`, click the counter button, assert DOM updates; assert `performance.getEntriesByType('resource')` shows the event POSTed to `/_pywire/stateless`; assert `page.on('websocket')` NEVER fires; SPA-navigate to page 2 and back, assert counter state persisted via snapshots.
- [ ] **Step 2: Run:** `uv run --package pywire --extra dev pytest tests/e2e/test_stateless.py -v` — FAIL first (fixture app not stateless-configured), then PASS.
- [ ] **Step 3: Commit**

```bash
git add packages/pywire/tests/e2e
git commit -m "test(pywire): e2e coverage for stateless transport"
```

---

## Phase 3 — Keyed per-iteration `{$for}` regions (LiveView-class payload diffing)

**Design context (verified against current code):** regions already anchor via generated `<div data-pw-region="{id}" style="display: contents;">` wrappers (`codegen/template.py:2658, 2843`) and the client already patches any region by `document.querySelector('[data-pw-region=...]')` (`dom-updater.ts:611 updateRegion`) — **so per-iteration regions need ZERO client changes for patching.** `render_update` currently falls back to a full re-render when a dirty region id isn't in the static `__region_renderers__` map (`page.py` render_update, "Silently skipping would leave the UI stuck" branch) — keyed ids (`site#key`) will route through a new `__keyed_region_renderers__` map instead. Invalidation registers reads per render-context region id (`_register_wire_read`), so setting the render context to `site#key` during each iteration is what buys item-granular dirtying.

### Task 10: Spike — verify item-level invalidation granularity (decision gate for T11–12)

**Files:**

- Create: `scratch/adhoc/spike_keyed_regions.py` (+ `scratch/adhoc/out/keyed_regions_findings.md`) — throwaway, scratchpad-skill review before run

**Interfaces:**

- Consumes: existing runtime only.
- Produces: a written findings file answering, with evidence: (a) when `items.value[i]['done']` is written, which `(wire_obj, field)` keys does `_invalidate_wire` see — nested item proxy or top-level list? (b) are nested proxies identity-stable across renders or recreated (churns subscription keys)? (c) if iteration render-context were set to `site#key` per item, would an item-field write dirty ONLY that item's region? (d) what does a structural write (`append`) dirty?

- [ ] **Step 1: Write the spike:** 100-row list fixture page (reuse `scratch/adhoc/bench_engine.py` fixtures); instrument `_register_wire_read`/`_invalidate_wire` via a logging handler or monkeypatch counters; render once; write `items.value[50]['done']`; dump the dirty-region set and subscription keys; repeat for `items.value.append(...)`.
- [ ] **Step 2: Run via scratchpad review flow; record findings** in `scratch/adhoc/out/keyed_regions_findings.md`.
- [ ] **Step 3: Decision:** if (c) holds with today's proxy semantics → T11/T12 proceed as written. If nested writes only ever dirty the top-level list (proxy identity churn), the fix lands in T11 as an extra step: stabilize per-item proxy identity (cache child proxies on `WireList`/`WireDict` keyed by index/key, invalidated on structural change) — add that to T11's scope before executing it. **If findings contradict the design more fundamentally, STOP and report to the orchestrator before T11.**
- [ ] **Step 4: No commit** (scratch is gitignored); findings are pasted into the T11 task briefing at dispatch time.

### Task 11: Codegen — keyed item regions for `{$for}`

**Files:**

- Modify: `packages/pywire/src/pywire/compiler/codegen/template.py` (`{$for}` handling)
- Modify: `packages/pywire/src/pywire/core/wire.py` (ONLY if T10 findings require proxy-identity stabilization)
- Test: `packages/pywire/tests/test_keyed_for_codegen.py`

**Interfaces:**

- Consumes: T10 findings; existing region wrapper emission pattern (`display: contents` div) and `key=` expression support in `{$for}`.
- Produces: for `{$for <vars> in <iter>, key=<expr>}`, compiled classes gain:
  - `__keyed_region_renderers__: dict[str, str]` mapping `site_id -> renderer method name`; the renderer is `def _pw_item_<site>(self, key) -> str` re-deriving the item from the loop source by key (index → `source[key]`; dict key → `source[key]`; arbitrary key expr → linear scan fallback) and rendering ONE iteration under render-context region id `f"{site_id}#{key}"`.
  - Per-iteration HTML wrapped in `<div data-pw-region="{site_id}#{key}" style="display: contents;">` — emitted only when the loop has `key=` (loops without keys keep today's whole-loop region behavior).
  - The whole-loop renderer keeps its existing `site_id` region and registers iteration-level reads (the loop expression itself, `len`) so structural writes dirty the loop region.
  - Key hygiene: keys are stringified (`str(key)`) into region ids; duplicate keys within one render raise a compile-visible `ValueError` at render time (first duplicate wins the region; duplicates = authoring bug, Review Focus #7).

- [ ] **Step 1: Write the failing tests:** (a) compiled class has `__keyed_region_renderers__` with the loop's site id; (b) rendered HTML contains one `data-pw-region="{site}#{k}"` wrapper per item with `display: contents`; (c) loops WITHOUT `key=` render exactly as today (no item wrappers) — snapshot-compare against pre-change output; (d) duplicate keys raise `ValueError`.
- [ ] **Step 2: Run to verify fail:** `uv run --package pywire --extra dev pytest tests/test_keyed_for_codegen.py -v` — FAIL.
- [ ] **Step 3: Implement** in `template.py` (this is the phase's deep work — the `{$for}` codegen path; keep the wrapper style byte-identical to the existing region wrapper emission at `template.py:2843`). If T10 required proxy stabilization, implement child-proxy caching in `wire.py` with its own unit tests (proxy identity stable across reads; invalidated by `append/pop/clear/__setitem__` at the list level).
- [ ] **Step 4: Full core suite** — existing `{$for}`/rendering tests pin no-regression for keyless loops: `uv run --package pywire --extra dev pytest tests -q`.
- [ ] **Step 5: Commit**

```bash
git add packages/pywire/src/pywire/compiler/codegen/template.py packages/pywire/src/pywire/core/wire.py packages/pywire/tests/test_keyed_for_codegen.py
git commit -m "feat(pywire): keyed per-iteration region wrappers for {\$for} loops"
```

### Task 12: Runtime — keyed region dispatch + invalidation

**Files:**

- Modify: `packages/pywire/src/pywire/runtime/page.py` (`render_update`, `_invalidate_wire`, `BasePage.__init__` for `__keyed_region_renderers__` default)
- Test: `packages/pywire/tests/test_keyed_regions_runtime.py`

**Interfaces:**

- Consumes: `__keyed_region_renderers__` + `_pw_item_<site>(key)` renderers (T11); existing `set_render_context(page, region_id)`.
- Produces: `render_update` handles dirty region ids containing `#`: split `site_id, key = region_id.split("#", 1)`; dispatch via `__keyed_region_renderers__[site_id]` renderer bound with `key`, under render context `(page, region_id)`. Missing site, missing key (item deleted since dirtying), or renderer exception → existing full-render fallback (safe path, already implemented). Output-equality cache (`_region_output_cache`) keyed by the full `site#key` id. Whole-loop fallback: when the loop's base `site_id` is dirty, the whole-loop renderer runs as today and the response's single region patch covers all item wrappers (morphdom keys keep DOM churn minimal client-side).

- [ ] **Step 1: Write the failing tests** (Review Focus #6): 100-row page; (a) `items.value[50]['done'] = True` → `render_update` returns exactly ONE region whose id ends `#50` and whose HTML contains only row 50's markup (assert `"item-49" not in html` and `"item-51" not in html`); (b) `items.value.append(new)` → response contains the whole-loop region (base site id, no `#`), all 101 rows present; (c) deleting the row whose region is dirty (race) → full-render fallback, no exception; (d) two sequential item writes to different rows → two regions, each single-row.
- [ ] **Step 2: Run to verify fail:** `uv run --package pywire --extra dev pytest tests/test_keyed_regions_runtime.py -v` — FAIL (falls back to full render).
- [ ] **Step 3: Implement** the `#` dispatch branch in `render_update` (before the existing "not in `__region_renderers__` → full fallback" branch) and verify `_invalidate_wire` needs no change beyond what T10/T11 established (item proxy reads already register under the active render-context region id).
- [ ] **Step 4: Full suite + suite-wide e2e smoke:** `uv run --package pywire --extra dev pytest tests -q`.
- [ ] **Step 5: Commit**

```bash
git add packages/pywire/src/pywire/runtime/page.py packages/pywire/tests/test_keyed_regions_runtime.py
git commit -m "feat(pywire): dispatch keyed item regions in render_update with safe fallbacks"
```

### Task 13: Keyed-region e2e + payload acceptance test (Spec #6)

**Files:**

- Create: `packages/pywire/tests/e2e/fixtures/keyed_list_app/` (1000-row generated list page, toggle handler)
- Create: `packages/pywire/tests/e2e/test_keyed_regions.py`
- Create: `packages/pywire/tests/test_keyed_region_payload.py` (CI-safe in-process acceptance: no playwright)

**Interfaces:**

- Consumes: T11–12; either transport (assert on the stateless POST payload AND the WS payload — transport parity constraint).
- Produces: pinned acceptance — single-item toggle on 1000 rows ships ≤ 1 KB total update payload; DOM mutations outside the toggled row == 0 (MutationObserver count); structural append still correct.

- [ ] **Step 1: Write the in-process payload test:** build the 1000-row page, `handle_event("toggle", {"args": {"i": 500}})`, assert `sum(len(r["html"]) for r in update["regions"]) <= 1024` and exactly one region with `#500`.
- [ ] **Step 2: Write the playwright e2e:** MutationObserver on the `<ul>`; click row 500's toggle; assert observer saw changes confined to that row's wrapper; assert row 499/501 DOM nodes are identical objects (`el.isSameNode` before/after via evaluate).
- [ ] **Step 3: Run both to verify fail → implement any gaps → PASS.**
- [ ] **Step 4: Re-run `scratch/adhoc/bench_engine.py`** (5000-row scenario) and record the before/after payload numbers in the commit message (expected: 913 KB → ≤ 1 KB).
- [ ] **Step 5: Commit**

```bash
git add packages/pywire/tests
git commit -m "test(pywire): keyed region payload acceptance (5000-row toggle ≤1KB)"
```

---

## Phase 4 — Declarative optimistic UI

**Design (Spec #7):** predictions are presentation-only, declared in `.wire`, compiled to data attributes, applied by the client on dispatch, and reconciled exclusively by the arriving morphdom patch. Correct prediction = invisible no-op (server HTML carries the same class). Wrong prediction = auto-revert (server HTML lacks it). `data-pw-pending` never exists in server HTML, so the patch strips it — that strip IS the "request finished" signal, and while it's present the control is guarded against double-submit. No rollback engine, no client-side state model, no Python-in-JS.

### Task 14: Codegen — `.optimistic` modifiers → data attributes

**Files:**

- Modify: `packages/pywire/src/pywire/compiler/codegen/attributes/events.py` (+ `packages/pywire/src/pywire/compiler/attributes/events.py` parse side)
- Test: `packages/pywire/tests/test_optimistic_modifiers.py`

**Interfaces:**

- Consumes: existing modifier pipeline (`@click.prevent`, `.debounce-500ms` parsing — hyphen-arg pattern at client `handler.ts:746`).
- Produces: `@click.optimistic={h()}` compiles to the existing `data-on-click="h"` + `data-modifiers-click="optimistic"`; `@click.optimistic-class-done={h()}` adds token `optimistic-class-done` to `data-modifiers-click` (multiple allowed: `optimistic-class-done optimistic-class-dim`). No new attributes — modifiers ride the existing channel.

- [ ] **Step 1: Failing test:** compile a fixture wire with both forms; assert emitted HTML has `data-modifiers-click="optimistic"` / contains `optimistic-class-done`; assert `.prevent.optimistic` combines.
- [ ] **Step 2: Run → FAIL.** Run: `uv run --package pywire --extra dev pytest tests/test_optimistic_modifiers.py -v`
- [ ] **Step 3: Implement** — modifier parsing is likely already generic (any `.name` passes through to `data-modifiers-*`); if so this task is tests + documenting the reserved `optimistic` / `optimistic-class-*` token grammar, plus validation that `optimistic-class-` tokens are non-empty. If pass-through already works, keep the diff to validation + tests only.
- [ ] **Step 4: Full suite, commit**

```bash
git add packages/pywire/src/pywire/compiler packages/pywire/tests/test_optimistic_modifiers.py
git commit -m "feat(pywire): .optimistic / .optimistic-class-* event modifier grammar"
```

### Task 15: Client — apply prediction, guard, morph-reconcile

**Files:**

- Modify: `packages/pywire/src/pywire/client/src/events/handler.ts` (modifier parse + prediction apply)
- Modify: `packages/pywire/src/pywire/client/src/core/app.ts` or `dom-updater.ts` (clear pending on error responses)
- Modify: `packages/pywire/src/pywire/client/src/core/dom-updater.ts` (ONLY if morphdom strips/guards need adjustment for `data-pw-pending`)
- Test: `packages/pywire/src/pywire/client/src/events/handler.optimistic.test.ts` (vitest, jsdom)

**Interfaces:**

- Consumes: `data-modifiers-click` tokens (T14); existing dispatch path in `handler.ts` (where debounce/throttle are honored — prediction applies AFTER debounce resolves, immediately BEFORE `transport.send`).
- Produces: on dispatch of an event whose modifiers include `optimistic`: set `data-pw-pending=""` on `event.currentTarget` (the element carrying `data-on-*`); for each `optimistic-class-X` token, `classList.add('X')` on the same element; if the element is a `button`/`input[type=submit]`, set `disabled` and remember it was us (`data-pw-pending-disabled`). Clearing: any received update message (regions or full) → remove all `data-pw-pending*` markers and restore `disabled` for guarded controls; error responses (`{type:'error'}`) → same clearing (never leave a control stuck disabled — Review Focus #8). Optimistic classes are NOT explicitly cleared — the morph is the reconciler; on error responses, explicitly remove classes added by the failed event's tokens (tracked in a per-dispatch list until the next update).

- [ ] **Step 1: Failing vitest (jsdom):** dispatch click with `optimistic optimistic-class-done` → element has `data-pw-pending` + `done` class synchronously (same tick, before fetch resolves); button disabled; simulate update message → markers gone, disabled restored; simulate error message → markers gone AND `done` class removed; second click while pending → not sent (double-submit guard).
- [ ] **Step 2: Run → FAIL:** `cd packages/pywire/src/pywire/client && pnpm vitest run src/events/handler.optimistic.test.ts`
- [ ] **Step 3: Implement** (~60–80 lines across handler.ts + a small `pending.ts` helper module if cleaner).
- [ ] **Step 4: Verify morph interaction:** add a dom-updater vitest — element with `data-pw-pending` + server HTML without it → after `updateRegion`, marker is gone (morphdom attribute sync). If morphdom's `onBeforeElUpdated` guards interfere, adjust and re-test.
- [ ] **Step 5: `pnpm vitest run && pnpm exec tsc --noEmit && pnpm build`; commit with built assets**

```bash
git add packages/pywire/src/pywire/client packages/pywire/src/pywire/static
git commit -m "feat(pywire): optimistic prediction apply/guard with morph-reconciled rollback"
```

### Task 16: Bind echo — inputs stay user-owned during round-trip

**Files:**

- Modify (only if tests expose gaps): `packages/pywire/src/pywire/client/src/core/dom-updater.ts` (focus/value guards — existing value-sync caveat near `dom-updater.ts:453`)
- Test: `packages/pywire/src/pywire/client/src/core/dom-updater.bind.test.ts` (vitest)

**Interfaces:**

- Consumes: existing focus capture/restore in `applyUpdate`.
- Produces: pinned behavior — a patch arriving while an input is focused and being typed into must not clobber the user's in-flight text or caret (browser-native optimism confirmed; server echo reconciles on blur/next patch). This is mostly a _characterization_ task: write the tests first; only touch `dom-updater.ts` where a test fails.

- [ ] **Step 1: Write the vitest:** focused input with user-typed value; `updateRegion` with server HTML containing the older value → assert focused input keeps user text + caret (if current code already guards this, test passes immediately — fine, it's now pinned).
- [ ] **Step 2: Run; fix only failures.**
- [ ] **Step 3: Client checks + build + commit**

```bash
git add packages/pywire/src/pywire/client packages/pywire/src/pywire/static
git commit -m "test(pywire): pin bind-echo optimism — patches never clobber focused inputs"
```

### Task 17: Optimistic e2e under artificial latency (Review Focus #8)

**Files:**

- Modify: `packages/pywire/tests/e2e/fixtures/stateless_app/` (add `optimistic.wire` page: toggle button with `.optimistic-class-done` where the handler REJECTS every 2nd toggle via a counter — exercises wrong-prediction revert)
- Create: `packages/pywire/tests/e2e/test_optimistic.py`

**Interfaces:**

- Consumes: Phases 2–4 (stateless transport makes latency injection trivial: `page.route("**/_pywire/stateless", ...)` delay 500 ms).
- Produces: pinned timing/behavior — predicted class present < 50 ms after click while the request is in flight; button disabled in flight; on accepted toggle the class survives the patch (no flicker: assert the element node identity is stable through the morph, `isSameNode`); on rejected toggle the class is GONE after the patch; no double-submit (handler invocation count == 1 for a rapid double-click).

- [ ] **Step 1: Write the e2e test** with `page.route` latency injection + MutationObserver flicker check.
- [ ] **Step 2: Run → FAIL/PASS cycle; fix in client/codegen as needed.**
- [ ] **Step 3: Full e2e suite:** `uv run --package pywire --extra dev pytest tests/e2e -q`.
- [ ] **Step 4: Commit**

```bash
git add packages/pywire/tests/e2e
git commit -m "test(pywire): optimistic UI e2e under 500ms latency incl. wrong-prediction revert"
```

---

## Phase 5 — Validation gate (the "final verification of the model")

### Task 18: Native round-trip benchmark + CI perf smoke

**Files:**

- Create: `scratch/adhoc/bench_stateless.py` (throwaway; scratchpad review before run)
- Create: `packages/pywire/tests/test_stateless_perf.py` (CI-safe loose bounds)

**Interfaces:**

- Consumes: full stateless path + keyed regions (Phases 1–3).
- Produces: measured table — full stateless round-trip (decode+verify+resolve+instantiate+restore+event+render+re-snapshot+encode) for counter / 100-row / 1000-row / 5000-row-toggle fixtures, alongside WS-mode numbers from `scratch/adhoc/bench_engine.py` for the writeup. CI smoke bounds (catch 10× regressions, not noise): counter event round-trip < 50 ms server-side; snapshot < 500 B; 1000-row single toggle payload < 2 KB.

- [ ] **Step 1: Write the bench** (pattern: `bench_engine.py`), run it, record the table in `scratch/adhoc/out/stateless_numbers.md`.
- [ ] **Step 2: Write the CI smoke test** with the loose bounds; run → PASS.
- [ ] **Step 3: Commit the test only** (scratch is gitignored):

```bash
git add packages/pywire/tests/test_stateless_perf.py
git commit -m "test(pywire): stateless round-trip perf smoke bounds"
```

### Task 19: One-shot ASGI adapter extraction

**Files:**

- Rename: `packages/pywire/src/pywire/adapters/pyodide.py` → `packages/pywire/src/pywire/adapters/oneshot.py`; class `PyodideASGIAdapter` → `OneShotASGIAdapter`; `fetch()` returns `(status, headers, body: bytes)` (binary-safe for msgpack)
- Modify callers: `docs/public/shim.py` (regenerate `docs/dist/shim.py` via docs build); grep-audit for any other references (`grep -rn PyodideASGIAdapter --include='*.py' --include='*.md' --include='*.j2' packages docs examples`)
- Test: `packages/pywire/tests/test_oneshot_adapter.py`

**Interfaces:**

- Produces: `OneShotASGIAdapter(app)` with `async fetch(method='GET', path='/', headers=None, body=b'', query_string='') -> tuple[int, list[tuple[str, str]], bytes]`. THE integration surface for every FaaS template.

- [ ] **Step 1: Failing test:** stateless fixture app through `adapter.fetch("GET", "/")` → 200 + bytes body containing `_pywire_snapshot`; extract snapshot, POST `/_pywire/stateless` event through the adapter → 200 msgpack with `regions` and `snapshot`.
- [ ] **Step 2: Run → FAIL** (`ImportError`).
- [ ] **Step 3: Rename + bytes return + update docs shims** (they `.decode()` where text is needed).
- [ ] **Step 4: Full suite + docs build** (`cd docs && pnpm build` must pass — AGENTS.md).
- [ ] **Step 5: Commit**

```bash
git add -A packages/pywire docs
git commit -m "feat(pywire)!: generalize PyodideASGIAdapter to OneShotASGIAdapter with binary-safe fetch"
```

(`BREAKING CHANGE:` footer — adapter renamed, fetch returns bytes.)

### Task 20: Cloudflare plain-Worker target + workerd measurement — GATE (Spec #9)

**Files:**

- Create: `packages/pywire-templates/src/pywire_templates/deploy/cloudflare_edge/entry.py.j2`, `wrangler.toml.j2`
- Modify: `packages/pywire-cli/src/pywire_cli/main.py` (`cloudflare-edge` in build/deploy platform choices; generation branch mirroring the existing `cloudflare` branch at `main.py:391`/`main.py:748`)
- Modify: `packages/pywire/src/pywire/compiler/build_artifacts.py` (`generate_cf_bundle(..., durable_objects: bool = True)`; edge bundle omits DO class + migrations)
- Create: `scratch/adhoc/bench_workerd.py` + `bench_workerd.sh` (throwaway; scratchpad review)
- Test: `packages/pywire-cli/tests/test_deploy_cloudflare_edge.py`

**Interfaces:**

- Consumes: `OneShotASGIAdapter` (T19), precompiled artifacts from `pywire build`.
- Produces: `pywire build --platform cloudflare-edge` → `.pywire/deploy/` with `entry.py`, `wrangler.toml` (assets binding, NO `durable_objects`, `compatibility_flags = ["python_workers"]`); deployable via `npx wrangler dev` / `wrangler deploy`.

- [ ] **Step 1: Template** `entry.py.j2`:

```python
"""PyWire edge worker — stateless, no Durable Objects."""
from urllib.parse import urlparse

from workers import Response

from pywire.adapters.oneshot import OneShotASGIAdapter
from {{ app_module }} import {{ app_attr }}
import _routes  # noqa: F401

_adapter = OneShotASGIAdapter({{ app_attr }})


async def on_fetch(request, env):
    parsed = urlparse(request.url)
    body = b""
    if request.method in ("POST", "PUT", "PATCH"):
        body = bytes(await request.array_buffer())
    headers = {k: v for k, v in request.headers.items()}
    status, resp_headers, resp_body = await _adapter.fetch(
        request.method, parsed.path, headers, body, parsed.query or "")
    return Response(resp_body, status=status, headers=dict(resp_headers))
```

`wrangler.toml.j2`: copy of the DO template minus `[[durable_objects.bindings]]` / `[[migrations]]`.

- [ ] **Step 2: Generation test:** pywire-cli test asserting `pywire build --platform cloudflare-edge` on a fixture app emits `entry.py` containing `OneShotASGIAdapter` and a `wrangler.toml` WITHOUT `durable_objects`. Run → FAIL → implement CLI branch → PASS.
- [ ] **Step 3: Local workerd validation** (manual, scratch): build the stateless counter fixture + a 1000-row keyed-list fixture for `cloudflare-edge`; `npx wrangler dev`; script 200 sequential stateless event POSTs; record p50/p99 server time and cold start (first request).
- [ ] **Step 4: GATE criteria** (record actuals in `scratch/adhoc/out/workerd_gate.md`): counter event ≤ 15 ms p50; snapshot ≤ 250 B; 1000-row single-item toggle payload ≤ 1 KB; cold start recorded vs the DO target (informational). **If the gate fails: STOP — report numbers to the orchestrator; do NOT start Phase 6.** Likely culprits: Starlette eager-import weight, Pyodide msgpack, snapshot verify cost.
- [ ] **Step 5: Commit**

```bash
git add packages/pywire-templates packages/pywire-cli packages/pywire/src/pywire/compiler/build_artifacts.py
git commit -m "feat(pywire-cli): cloudflare-edge stateless worker deploy target"
```

---

## Phase 5A — Tier rectification (inserted 2026-09-24 after adversarial model review)

**Rationale (owner decision):** the framework currently has three overlapping paradigms — interactive (WS), non-interactive (`!no_interactive` form-post), and stateless (snapshot POST). Rectify into a clean model: a **feature kernel** that works identically in both deployment tiers, plus tier-specific features. The kernel's teaching boundary is *who owns the timeline*: stateless pages only change when the user acts (request-driven); stateful pages can change on their own (server-driven). Everything excluded from stateless follows from that one sentence.

**Feature model (binding for T26+ and docs):**

- **Kernel (identical both tiers):** events/handlers/forms, wires + reactive regions, keyed `{$for}` regions, optimistic UI, SPA nav/pjax, auth/middleware parity, `@poll` (Phase 5B), error pages, deploy tooling, file uploads (verified in T27).
- **Stateless-only:** snapshot round-trip; pure-FaaS portability. Idiomatic pattern for long-running work: `@poll` + external store/queue.
- **Stateful-only:** `{$await}` template blocks (server holds the timeline), WebSocket push, server-side background tasks, DO hibernation, future WS rooms (multi-user concurrent — the ONE accepted fundamental loss in stateless).
- **No-JS floor (`!no_interactive`):** not a third tier — the framework JS always loads; the directive skips event/wire wiring on the page (page.py: client script injected unconditionally, `page_interactive` meta). Whether forms work with JS fully disabled (native POST, no `X-PyWire-Handler` from JS) is UNVERIFIED — T27 checks and fixes, then docs may claim the floor.

**Accepted costs (documented, from adversarial review):** O(n) snapshot tax means bulk collections live in `.lock()`ed wires + store reads, not page state (teach this as THE stateless design pattern); snapshot state is opaque in devtools (T27 adds a debug-mode inspector); `@poll` bills per invocation on FaaS (docs guidance on intervals; SSE is the future upgrade for per-token streaming — roadmap, not this plan).

### Task 26: Tier gating + `{$await}` removal from stateless

**Files:**

- Modify: `packages/pywire/src/pywire/compiler/` (codegen/validation: page containing `{$await}` blocks compiled into a `stateless=True` app → **build/compile-time error** naming the page and pointing to `@poll` or the stateful tier)
- Modify: `packages/pywire/src/pywire/runtime/stateless_handler.py` (delete the hold-open machinery: `await_budget` drain, `meta.pending_awaits`), `packages/pywire/src/pywire/runtime/app.py` (delete `await_budget` param — BREAKING, pre-1.0)
- Delete: `packages/pywire/tests/test_stateless_await.py`, `packages/pywire/tests/fixtures/stateless_app/pages/{slow,fast_await}.wire` (superseded by gating tests)
- Modify: `examples/demo-edge-stateless/` (remove `/await` page + README section — replaced by poll page in T29; keep the "no-JS floor" and ceilings honest)
- Test: `packages/pywire/tests/test_tier_gating.py` (stateless app with `{$await}` page fails at build with actionable message; stateful app with same page compiles fine; async *handlers* still allowed in stateless — only template await blocks are excluded)

- [ ] **Step 1: TDD** — gating test RED (no error today) → implement compile-time check → GREEN.
- [ ] **Step 2: Delete hold-open machinery** — `await_budget` param, drain loop, `meta.pending_awaits`, T7 tests + fixtures. Suite stays green (delete dead code, no forwarding shims).
- [ ] **Step 3: Demo rework** — remove `/await` page; README drops the await section (T29 adds the poll replacement).
- [ ] **Step 4: Commit**

```bash
git add packages/pywire examples/demo-edge-stateless
git commit -m "feat(pywire)!: exclude {$await} from stateless tier — build-time gate, drop hold-open machinery"
```

(BREAKING CHANGE footer: `PyWire(await_budget=...)` removed; `{$await}` blocks no longer render in stateless apps.)

### Task 27: Kernel verification gaps + debug snapshot inspector

**Files:**

- Test: `packages/pywire/tests/test_stateless_uploads.py` (file upload through a stateless app — upload endpoints must work without WS; if not mounted in stateless mode, mount them)
- Modify: `packages/pywire/src/pywire/runtime/app.py` (debug-mode only: `GET /_pywire/debug/snapshot?blob=...` decodes + pretty-prints a snapshot for development; registered only when `debug=True`)
- Test: `packages/pywire/tests/test_debug_snapshot.py`
- Test: `packages/pywire/tests/test_no_js_floor.py` — render a `!no_interactive` page with a form; POST it WITHOUT any JS-set headers (exactly what a browser with JS disabled sends); assert the server handles it (fix `_handle_form_post`'s header expectation if it blocks the native path) and returns a full document.

- [ ] **Step 1: TDD** — upload test first (verify current behavior; mount endpoints if missing) → inspector test (debug on: 200 + decoded JSON; debug off: 404) → no-JS form test → implement → GREEN.
- [ ] **Step 2: Commit**

```bash
git add packages/pywire
git commit -m "feat(pywire): stateless file uploads + debug-mode snapshot inspector"
```

---

## Phase 5B — Poll primitive (the stateless long-running-action idiom)

### Task 28: `@poll` directive (grammar + client)

**Files:**

- Modify: `packages/pywire-parser/src/pywire_parser/attributes/` — **verified: `@poll.every-400={tick()}` already parses** through the existing `EventAttributeParser` into `EventAttribute(event_type='poll', handler_name='tick()', modifiers=['every-400'])`. So do NOT add a parallel parser/AST node unless validation demands it — reuse `EventAttribute` and special-case `event_type == 'poll'` downstream. Add validation the generic event path lacks: reject unknown poll modifiers, and parse/validate `every-<int>`. CRITICAL: ensure `@poll` is NOT also wired as a real DOM listener (`addEventListener('poll', …)`) — codegen and client must route `poll` separately from DOM events.
- Modify: `packages/pywire/src/pywire/compiler/codegen/` (compile to `data-pw-poll="{handler}"` + `data-pw-poll-every="{ms}"` and add the handler to the same allowlist event handlers use, so stateless POST and WS dispatch both accept it)
- Modify: `packages/pywire/src/pywire/client/src/events/` (new `poll.ts` + wire into the existing mount/morph lifecycle in `handler.ts` — do NOT build a parallel tracker; interval dispatch through the SAME event dispatch path so WS + stateless both work; overlap guard: one in-flight poll per element; stop on element unmount / region replacement / page nav)
- Test: parser tests + `packages/pywire/tests/test_poll_directive.py` (codegen) + client vitest (`src/events/poll.test.ts`)

> **Design decisions (orchestrator, 2026-09-24 — REVISED after grammar check):** The grammar's `special_attribute_name` is `@` + `/[a-zA-Z_][\w.\-]*/`: dots/dashes allowed, but `=` ends the name (it is the name/value delimiter) and there is exactly one value slot. Consequences: (1) **`.every-<ms>` is a DASH modifier** (`@poll.every-400={handler}`), matching the existing `.optimistic-class-<name>` precedent — NOT `.every=400` (unbuildable). Clamp `< 100 ms` → compile error (FaaS billing foot-gun). (2) **No `.while` in v1.** An inline `{expr}` cannot be a name-modifier, and the value slot holds the handler. The stop condition is **conditional rendering** — the framework's existing primitive: wrap the polled element in `{cond}...{/cond}`; when `cond` goes false the element unmounts and the client's unmount cleanup (already required for page-nav) stops the timer. This is strictly less code and reuses reactive conditionals. `ponytail:` ceiling — if "stop polling but keep the element visible" is ever needed, add a paired `@poll-while={expr}` attribute (server-evaluated → `data-pw-poll-while`), not an inline modifier. (3) Overlap guard: skip a tick while a prior dispatch for that element is in flight.

- [ ] **Step 1: TDD** — parser + codegen tests RED → grammar-free parser module + codegen → GREEN. (No tree-sitter `grammar.js` change needed: `@poll.every-400` already tokenizes as a `special_attribute_name`; verify this with a parse test before touching anything.)
- [ ] **Step 2: Client** — vitest RED (fake timers: interval dispatch, stop-on-unmount, while-condition, no overlap) → implement → GREEN.
- [ ] **Step 3: Commit**

```bash
git add packages/pywire-parser packages/pywire
git commit -m "feat(pywire): @poll directive — interval handler dispatch, kernel across tiers"
```

### Task 29: Poll e2e + demo page

**Files:**

- Test: `packages/pywire/tests/e2e/test_poll.py` (stateless fixture: `@poll` ticks visible in Network as stateless POSTs; stops when condition false; works identically on a stateful fixture over WS)
- Modify: `examples/demo-edge-stateless/` (new `/poll` page replacing the removed `/await`: a fake "LLM job" — a store-backed counter filled by an in-process asyncio task on first send; the polled element is wrapped in `{status == 'running'}...{/status == 'running'}` so completion flips the region AND stops the poll via unmount; `@poll.every-400` renders progress; README section teaching the poll pattern + conditional-render stop + when NOT to use it: per-token streaming → stateful tier or future SSE)

- [ ] **Step 1: e2e RED → app/attribute wiring → GREEN** (both tiers).
- [ ] **Step 2: Demo page + README.**
- [ ] **Step 3: Commit**

```bash
git add packages/pywire examples/demo-edge-stateless
git commit -m "test(pywire): @poll e2e both tiers + stateless demo poll page"
```

---

## Phase 5C — Per-page tier derivation (SPIKE — decision gate, NOT a committed design)

> **Owner directive (2026-09-24):** investigate per-page tier derivation as a spike only. This is NOT a set design decision — findings go to a human gate, and no committed code ships from this phase without an explicit go.

**The idea under test:** invert "app picks a tier" into needs-based derivation — the deployment declares a ceiling (WS available?), pages declare needs (derived: `{$await}` → push; a future `@room` → rooms; nothing → plain), the build validates needs ≤ ceiling, and the runtime swaps transport per page (client opens a WS when SPA-navigating into a stateful page, drops back to snapshot-POST on stateless pages). `stateless=True` survives as the explicit "ceiling: stateless-only" assertion for pure-FaaS deploys (never mount WS; fail the build if any page needs push).

### Task 30: Spike — per-page tier derivation feasibility (decision gate)

**Method:** scratch investigation + throwaway prototype, like T10. No committed code. Follow the scratchpad skill (`review.sh` approval before running scratch scripts).

**Questions to answer (findings → `scratch/adhoc/out/per_page_tier_findings.md`):**

- [ ] **Client transport swap:** can the client open a WS mid-session when SPA-navigating from a stateless page to a stateful page, and drop back to POST on the way out? What breaks: connection lifecycle, reconnect state machine, event queueing during the swap, per-page meta differences, hot-reload, auth re-handshake on WS connect? Prototype in scratch (fixture app with one stateless page + one stateful page, hacked meta).
- [ ] **Needs derivation:** generalize T26's `{$await}` compile-time scan into a page-feature → minimum-tier map. What maps to what (await blocks, server-push hooks, rooms, nothing)? Is derivation purely syntactic, or are there dynamic cases (conditionally-used awaits, components shared across tiers)?
- [ ] **Runtime semantics with both endpoint families mounted:** session state when entering a stateful page (fresh session? resume?), snapshot minting for stateless pages visited after stateful ones, `build_page` paths, auth/middleware parity on both transports (already an invariant — verify), dev-mode reload behavior.
- [ ] **Recommendation:** ship as designed / ship a reduced form (e.g. build-time validation only, no runtime mixing) / don't ship. Include a cost estimate and kill-criteria.

**Human gate:** STOP after findings — report to the orchestrator; do NOT design or write T31/T32 or any committed code.

---

## Phase 6 — Multi-provider deployment targets (gated on Task 20)

### Task 21: AWS Lambda target

**Files:**

- Create: `packages/pywire-templates/src/pywire_templates/deploy/aws/handler.py.j2`, `requirements.txt.j2`, `README.md.j2`
- Modify: `packages/pywire-cli/src/pywire_cli/main.py` (`aws-lambda` platform → `.pywire/deploy/aws/` with rendered handler, `requirements.txt`, vendored deps via `pip install -t .pywire/deploy/aws/package -r requirements.txt`, README with `aws lambda create-function --zip-file` one-liner + API GW HTTP API `$default`-route setup)
- Test: `packages/pywire-cli/tests/test_deploy_aws.py`

**Interfaces:**

- Consumes: `OneShotASGIAdapter` (T19).
- Produces: `handler(event, context) -> dict` (API GW HTTP API v2 payload; tolerates REST v1 `httpMethod`/`path`); `application/x-msgpack` responses returned base64 with `isBase64Encoded: True`.

- [ ] **Step 1: Failing test** — render the template with Jinja2 directly (no AWS deps), exec the generated `handler.py` with the stateless fixture app importable, feed a synthetic API GW v2 GET event for `/` → `statusCode == 200` + `_pywire_snapshot` in body; extract snapshot, feed a synthetic POST event for `/_pywire/stateless` → 200 + `isBase64Encoded` True + decodable msgpack with `regions`.
- [ ] **Step 2: Run → FAIL** (template missing).
- [ ] **Step 3: Implement template:**

```python
import asyncio
import base64

from pywire.adapters.oneshot import OneShotASGIAdapter
from {{ app_module }} import {{ app_attr }}
import _routes  # noqa: F401

_adapter = OneShotASGIAdapter({{ app_attr }})


def handler(event, context):
    http = event.get("requestContext", {}).get("http", {})
    method = http.get("method") or event.get("httpMethod", "GET")
    path = event.get("rawPath") or event.get("path", "/")
    query = event.get("rawQueryString") or ""
    headers = event.get("headers") or {}
    raw_body = event.get("body") or ""
    body = base64.b64decode(raw_body) if event.get("isBase64Encoded") else raw_body.encode()
    status, resp_headers, resp_body = asyncio.run(
        _adapter.fetch(method, path, dict(headers), body, query))
    headers_out = dict(resp_headers)
    binary = headers_out.get("content-type", "").startswith("application/x-msgpack")
    return {
        "statusCode": status,
        "headers": headers_out,
        "body": base64.b64encode(resp_body).decode() if binary else resp_body.decode(),
        "isBase64Encoded": binary,
    }
```

(`asyncio.run` per invocation is deliberate: Lambda freezes between invocations; a fresh loop per warm invoke is the correct-cheap choice.)

- [ ] **Step 4: CLI wiring + generation test; `./scripts/check` in pywire-cli.**
- [ ] **Step 5: Commit**

```bash
git add packages/pywire-templates packages/pywire-cli
git commit -m "feat(pywire-cli): aws-lambda stateless deploy target"
```

### Task 22: Azure Functions target

**Files:**

- Create: `packages/pywire-templates/src/pywire_templates/deploy/azure/function_app.py.j2`, `host.json.j2`, `requirements.txt.j2`, `README.md.j2`
- Modify: `packages/pywire-cli/src/pywire_cli/main.py` (`azure-functions` platform → `.pywire/deploy/azure/`; README: `func start` local, `func azure functionapp publish` deploy)
- Test: `packages/pywire-cli/tests/test_deploy_azure.py`

**Interfaces:**

- Consumes: `OneShotASGIAdapter`.
- Produces: Azure Functions v2 programming-model app, catch-all route `{*path}` (GET/POST), anonymous auth level; `func.HttpRequest` → adapter conversion using only: `request.method`, `request.url`, `request.headers`, `request.get_body()`; returns `func.HttpResponse(body_bytes, status_code, headers=..., mimetype=...)` — binary-safe, no base64 needed.

- [ ] **Step 1: Failing test** — inject a stub `azure.functions` module into `sys.modules` (duck-typed `FunctionApp`, `HttpRequest`, `HttpResponse`, `HttpAuthLevel`, route decorator), exec the rendered template, drive GET `/` → 200 + snapshot; POST stateless event → 200 msgpack bytes.
- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement template** (same shape as T21's handler; conversion via `urlparse(request.url)`).
- [ ] **Step 4: CLI wiring, checks, commit**

```bash
git commit -m "feat(pywire-cli): azure-functions stateless deploy target"
```

### Task 23: GCP targets (Cloud Run + Cloud Functions)

**Files:**

- Create: `packages/pywire-templates/src/pywire_templates/deploy/gcp_functions/main.py.j2`, `requirements.txt.j2`, `README.md.j2`
- Create: `packages/pywire-templates/src/pywire_templates/deploy/gcp_cloudrun/README.md.j2`, `cloudrun.yaml.j2`
- Modify: `packages/pywire-cli/src/pywire_cli/main.py` (`gcp-functions`, `gcp-cloudrun` platforms)
- Test: `packages/pywire-cli/tests/test_deploy_gcp.py`

**Interfaces:**

- `gcp-cloudrun` **reuses the existing docker output** (Cloud Run supports WebSockets → BOTH modes work; README documents `gcloud run deploy` with `--session-affinity` for WS mode, plain for stateless). No new runtime code.
- `gcp-functions`: functions-framework Flask signature `def pywire(request)` — conversion: `request.method`, `request.path`, `dict(request.headers)`, `request.get_data()`, `request.query_string.decode()`; returns `(body_bytes, status, headers)` tuple (binary-safe).

- [ ] **Step 1: Failing tests** — Cloud Run: generation test asserting docker artifacts + README produced by `--platform gcp-cloudrun`. Cloud Functions: duck-typed Flask-request stub through rendered `main.py` → 200 + snapshot; stateless POST → 200 msgpack bytes.
- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement templates + CLI branches.**
- [ ] **Step 4: Checks + commit**

```bash
git commit -m "feat(pywire-cli): gcp-cloudrun and gcp-functions deploy targets"
```

### Task 24: Build-time feature gating + version floors

> **Scope note (Phase 5A amendment):** `{$await}`-on-stateless gating moved to T26. This task keeps the platform-vs-tier check (`_require_stateless` for pure-FaaS platforms), the missing-secret build error, and the version floors.

**Files:**

- Modify: `packages/pywire-cli/src/pywire_cli/main.py` (`_require_stateless(app_instance, platform)` pre-build validation)
- Modify: `packages/pywire-cli/pyproject.toml` + `packages/pywire-cli/src/pywire_cli/_compat.py`; same pair for `pywire-templates` — floors to the next `pywire` minor (AGENTS.md floor rule; single commit)
- Test: `packages/pywire-cli/tests/test_stateless_gating.py`

**Interfaces:**

- Produces: for platforms `cloudflare-edge|aws-lambda|azure-functions|gcp-functions`, build imports the user app and fails fast with actionable messages when `app.state.pywire.stateless` is False (`"add PyWire(stateless=True, secret_key=...) — see docs edge guide"`) or the secret is unset (`"set PYWIRE_SECRET_KEY in your provider environment"`). `gcp-cloudrun` and `cloudflare` (DO) accept either mode.

- [ ] **Step 1: Failing test** — build fixture app WITHOUT `stateless=True` for `aws-lambda` → non-zero exit + message contains `stateless=True`; with it → success.
- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement `_require_stateless` + call it from each stateless-platform branch; bump floors.**
- [ ] **Step 4: Checks + commit**

```bash
git add packages/pywire-cli packages/pywire-templates
git commit -m "feat(pywire-cli): fail-fast stateless config checks + cross-package version floors"
```

### Task 25: Docs

**Files:**

- Modify: `docs/src/content/docs/**` — follow the `update-docs` skill (`.agents/skills/update-docs/SKILL.md`) for placement/nav
- New pages: "Edge & serverless deployment" (model overview; **deployment support matrix**: host × tier table — docker/Fly/Render/Railway/Cloud Run → both tiers, CF DO → stateful at edge, CF plain Worker/Lambda/Azure/GCP Functions → stateless only; ideology column: who owns the timeline), "Stateless mode" (snapshots, `wire.lock()`, security notes, **the O(n)-snapshot design pattern**: bulk data in locked wires + store reads, not page state), "Optimistic UI" (`.optimistic` modifier grammar, reconciliation model, when NOT to use it), "Fast lists" (`key=` + keyed regions, structural-change fallback), "Long-running actions" (`@poll` pattern + cookbook per platform — D1+Queues, Firestore+Tasks; when to use the stateful tier instead; `{$await}` is stateful-only), per-provider quickstarts (CF edge, Lambda, Azure, GCP Run/Functions)

> **Scope note (Phase 5A/5B amendment):** `await_budget` is deleted in T26 — docs must NOT mention it. Add the tier feature matrix page (kernel vs stateless-only vs stateful-only, no-JS floor), the `@poll` directive reference, and the chat/streaming guidance (stateful tier for per-token UX; poll for bounded waits; SSE is roadmap).

- [ ] **Step 1: Load the update-docs skill and follow it.** Must include: the stateful/stateless tier decision rule (push features → stateful), `{$await}` hold-open semantics + budget, locked-attr guidance, secret provisioning per provider, the v1 keyed-region ceiling (structural changes = whole-loop).
- [ ] **Step 2: `cd docs && pnpm build` must pass.**
- [ ] **Step 3: Commit**

```bash
git add docs
git commit -m "docs(pywire-docs): edge stateless mode, optimistic UI, fast lists + provider guides"
```

---

## Self-review notes

- **Spec coverage:** 1→T6; 2→T4; 3→T3,T6; 4→T5; 5→T6,T7; 6→T10–T13 (acceptance in T13/T18/T20); 7→T14–T17; 8→T20–T23; 9→T20 gate. Review Focus: #1,#9→T4; #2→T3,T6; #3→T5; #4→T7; #5→T6; #6→T12; #7→T11; #8→T15,T17.
- **Ordering/dependencies:** T19 (adapter) precedes T20–T23 (all FaaS templates consume it). T10 (spike) gates T11's final scope — findings are pasted into the T11 dispatch briefing. Phase 3 keyed regions benefit every transport (WS mode gets the payload win too) and shrink stateless snapshots' companion payloads — hence before the Phase 5 gate, so the gate measures the finished engine.
- **Type consistency:** `encode_snapshot/decode_snapshot/SnapshotError` (T4) used verbatim in T6–T8, T19; `OneShotASGIAdapter.fetch -> (int, list[tuple[str,str]], bytes)` (T19) used verbatim in T20–T23; `__keyed_region_renderers__: dict[str,str]` + `_pw_item_<site>(key)` (T11) consumed by T12; `__event_handlers__: frozenset[str]` (T5) referenced only there; `data-pw-pending` / `optimistic-class-*` token grammar (T14) consumed verbatim by T15.
- **Known soft spots (flagged, not hidden):** (a) T11's per-item renderer re-derivation for arbitrary (non-index) key expressions is a linear scan — acceptable v1 ceiling, documented in T25; (b) T5's codegen audit may surface dispatch-by-name paths not covered by the allowlist (component `on_*` callbacks route through `_parse_component_event` first — component classes must also emit `__event_handlers__`); (c) T6's `_instantiate_page`/`_resolve_user_for_request` extraction depends on current `app.py` internals — behavior-preserving, pinned by existing app tests; (d) T16 may discover the existing focus-guard already covers bind-echo — that's a pass, not a skip: the test stays as the pin.
